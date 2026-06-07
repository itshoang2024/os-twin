import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { OntologyProfile } from '@/hooks/use-ontology';
import { createObjectType, createRelationshipType, addMetadataFieldToObjectType, removeObjectTypeSafely, patchRelationshipEndpoints } from '@/components/knowledge/ontology/ontology-draft-commands';
import { useOntologyDraftController } from '@/components/knowledge/ontology/useOntologyDraftController';
import { specLensAdapter } from '@/components/knowledge/workbench';

function blankProfile(): OntologyProfile {
  return {
    profile_id: 'draft',
    namespace: 'demo',
    version: '0.1.0',
    status: 'draft',
    concept_types: {},
    relationship_types: {},
    aliases: {},
    concept_aliases: {},
    layers: {},
    abstraction_levels: {},
    metadata_fields: {},
    validation_rules: [],
    graph_instruction: { schema_version: 1, concept_type_defaults: {}, relationship_type_defaults: {} },
  };
}

describe('ontology authoring draft commands', () => {
  it('creates Object Types with GraphInstruction defaults and visible Spec Lens nodes', () => {
    const result = createObjectType(blankProfile(), { label: 'Feature', layer: 'product', abstractionLevel: 'capability', color: '#2563eb', shape: 'rounded_rectangle' });

    expect(result.id).toBe('feature');
    expect(result.profile.concept_types.feature).toMatchObject({ id: 'feature', label: 'Feature', default_layer: 'product', abstraction_level: 'capability' });
    expect(result.profile.graph_instruction?.concept_type_defaults?.feature).toMatchObject({ concept_type: 'feature', color: '#2563eb', shape: 'rounded_rectangle', default_layer: 'product' });
    expect(specLensAdapter(result.profile).nodes.map((node) => node.id)).toContain('feature');
  });

  it('creates Relationship Types from endpoint chips and emits a Spec Lens edge', () => {
    let profile = createObjectType(blankProfile(), { label: 'Feature' }).profile;
    profile = createObjectType(profile, { label: 'Control' }).profile;
    const result = createRelationshipType(profile, { label: 'Mitigates', sourceTypes: ['control'], targetTypes: ['feature'], family: 'assurance', cardinality: 'many_to_many', mapDirection: 'forward', style: 'dashed', weight: 0.8 });

    expect(result.id).toBe('mitigates');
    expect(result.profile.relationship_types.mitigates).toMatchObject({ allowed_source_types: ['control'], allowed_target_types: ['feature'], family: 'assurance', cardinality: 'many_to_many', style: 'dashed', weight: 0.8 });
    expect(result.profile.graph_instruction?.relationship_type_defaults?.mitigates).toMatchObject({ relationship_type: 'mitigates', group: 'assurance', weight: 0.8 });
    expect(specLensAdapter(result.profile).edges).toEqual(expect.arrayContaining([expect.objectContaining({ source: 'control', target: 'feature', type: 'mitigates' })]));
  });

  it('adds properties and blocks unsafe Object Type removal while relationships reference it', () => {
    let profile = createObjectType(blankProfile(), { label: 'Feature' }).profile;
    profile = addMetadataFieldToObjectType(profile, 'feature', { label: 'Owner', field_type: 'string' }).profile;
    expect(profile.concept_types.feature.metadata_fields).toContain('owner');
    profile = createRelationshipType(profile, { label: 'Depends on', sourceTypes: ['feature'], targetTypes: ['feature'] }).profile;

    const blocked = removeObjectTypeSafely(profile, 'feature');
    expect(blocked.blockedBy).toEqual(['depends_on']);
    expect(blocked.profile.concept_types.feature).toBeTruthy();
  });



  it('keeps draft controller commits undoable and redoable outside the panel shell', () => {
    const initial = createObjectType(blankProfile(), { label: 'Feature' }).profile;
    const { result } = renderHook(({ profile }) => useOntologyDraftController(profile), { initialProps: { profile: initial } });

    act(() => {
      result.current.commitDraft(createRelationshipType(result.current.draft!, { label: 'Depends on', sourceTypes: ['feature'], targetTypes: ['feature'] }).profile, 'Add relationship');
    });
    expect(result.current.draft?.relationship_types.depends_on).toBeTruthy();
    expect(result.current.undoStack).toHaveLength(1);

    act(() => result.current.handleUndoDraft());
    expect(result.current.draft?.relationship_types.depends_on).toBeUndefined();
    expect(result.current.redoStack).toHaveLength(1);

    act(() => result.current.handleRedoDraft());
    expect(result.current.draft?.relationship_types.depends_on).toBeTruthy();
  });

  it('updates relationship matrix endpoint coverage without raw CSV parsing', () => {
    let profile = createObjectType(blankProfile(), { label: 'Feature' }).profile;
    profile = createObjectType(profile, { label: 'Control' }).profile;
    profile = createRelationshipType(profile, { label: 'Proves', sourceTypes: ['control'], targetTypes: ['feature'] }).profile;
    const updated = patchRelationshipEndpoints(profile, 'proves', ['control', 'feature'], ['feature']);

    expect(updated.relationship_types.proves.allowed_source_types).toEqual(['control', 'feature']);
    expect(updated.relationship_types.proves.allowed_target_types).toEqual(['feature']);
  });
});
