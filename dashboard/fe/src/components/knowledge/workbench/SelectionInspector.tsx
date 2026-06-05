import React from 'react';
import type { OntologyProfile, OntologySourceMapping } from '@/hooks/use-ontology';
import type { WorkbenchModel, WorkbenchSelection } from './model/workbenchModel';

function patchRecord<T extends Record<string, unknown>>(record: T | undefined, id: string, patch: Record<string, unknown>): Record<string, unknown> {
  return { ...(record ?? {}), [id]: { ...((record?.[id] as Record<string, unknown>) ?? { id }), ...patch } };
}

function mappingAt(items: OntologySourceMapping[] | undefined, index = 0): OntologySourceMapping {
  return items?.[index] ?? { source_id: '', source_type: 'other', source_label: '', field_path: '', transform: '', confidence: null, notes: '' };
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="rounded-lg border p-3" style={{ borderColor: 'var(--color-border, #cbd5e1)' }}><h4 className="mb-2 text-xs font-bold uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-muted, #64748b)' }}>{title}</h4>{children}</section>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block text-xs" style={{ color: 'var(--color-text-muted, #64748b)' }}>{label}<div className="mt-1">{children}</div></label>;
}

function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className="w-full rounded border px-2 py-1 text-sm" style={{ borderColor: 'var(--color-border, #cbd5e1)', color: 'var(--color-text-main, #0f172a)' }} />;
}

const cardinalities = ['', 'one_to_one', 'one_to_many', 'many_to_one', 'many_to_many'];
const families = ['composition', 'dependency', 'flow', 'semantic', 'ownership', 'classification', 'causality', 'temporal', 'validation', 'traceability', 'assurance', 'synchronization'];

export function SelectionInspector({
  model,
  selection,
  profile,
  onProfileChange,
  onValidate,
}: {
  model: WorkbenchModel;
  selection?: WorkbenchSelection;
  profile?: OntologyProfile;
  onProfileChange?: (profile: OntologyProfile) => void;
  onValidate?: (profile: OntologyProfile) => void | Promise<void>;
}) {
  const fallbackConceptId = profile ? Object.keys(profile.concept_types ?? {})[0] : undefined;
  const effectiveSelection = selection ?? (fallbackConceptId ? { kind: 'concept', id: fallbackConceptId, title: profile?.concept_types?.[fallbackConceptId]?.label ?? fallbackConceptId, source: 'profile' } : null);
  const node = effectiveSelection ? model.nodes.find((item) => item.id === effectiveSelection.id) : null;
  const relationshipId = effectiveSelection?.kind === 'relationship' ? effectiveSelection.id : String(effectiveSelection?.properties?.relationship_type ?? '');
  const concept = profile && effectiveSelection?.kind === 'concept' ? profile.concept_types?.[effectiveSelection.id] : null;
  const relationship = profile && relationshipId ? profile.relationship_types?.[relationshipId] : null;

  const updateConcept = (patch: Record<string, unknown>) => {
    if (!profile || !effectiveSelection || effectiveSelection.kind !== 'concept') return;
    onProfileChange?.({ ...profile, concept_types: patchRecord(profile.concept_types, effectiveSelection.id, patch) as OntologyProfile['concept_types'] });
  };
  const updateConceptGraphDefaults = (patch: Record<string, unknown>) => {
    if (!profile || !effectiveSelection || effectiveSelection.kind !== 'concept') return;
    const current = profile.graph_instruction?.concept_type_defaults?.[effectiveSelection.id] ?? { concept_type: effectiveSelection.id };
    onProfileChange?.({
      ...profile,
      graph_instruction: {
        ...(profile.graph_instruction ?? {}),
        concept_type_defaults: { ...(profile.graph_instruction?.concept_type_defaults ?? {}), [effectiveSelection.id]: { ...current, ...patch, concept_type: effectiveSelection.id } },
      },
    });
  };
  const updateRelationship = (patch: Record<string, unknown>) => {
    if (!profile || !relationshipId) return;
    onProfileChange?.({ ...profile, relationship_types: patchRecord(profile.relationship_types, relationshipId, patch) as OntologyProfile['relationship_types'] });
  };
  const updateRelationshipById = (id: string, patch: Record<string, unknown>) => {
    if (!profile || !id) return;
    onProfileChange?.({ ...profile, relationship_types: patchRecord(profile.relationship_types, id, patch) as OntologyProfile['relationship_types'] });
  };
  const updateMetadataField = (id: string, patch: Record<string, unknown>) => {
    if (!profile) return;
    onProfileChange?.({ ...profile, metadata_fields: patchRecord(profile.metadata_fields, id, patch) as OntologyProfile['metadata_fields'] });
  };
  const updateConceptAlias = (alias: string, target: string) => {
    if (!profile) return;
    const aliases = { ...(profile.concept_aliases ?? {}) };
    Object.entries(aliases).forEach(([key, value]) => { if (value === target) delete aliases[key]; });
    if (alias.trim()) aliases[alias.trim()] = target;
    onProfileChange?.({ ...profile, concept_aliases: aliases });
  };
  const addScopedRule = () => {
    if (!profile || !effectiveSelection || effectiveSelection.kind !== 'concept') return;
    const nextRules = [...(profile.validation_rules ?? []), { id: `${effectiveSelection.id}_draft_rule_${(profile.validation_rules ?? []).length + 1}`, subject: 'concept_type', concept_type: effectiveSelection.id, rule_type: 'metadata_schema', severity: 'warning' }];
    onProfileChange?.({ ...profile, validation_rules: nextRules });
  };

  if (concept && effectiveSelection?.kind === 'concept') {
    const source = mappingAt(concept.source_mappings);
    const graphDefaults = (profile?.graph_instruction?.concept_type_defaults?.[effectiveSelection.id] ?? {}) as Record<string, unknown>;
    const ownerField = profile?.metadata_fields?.owner ?? { id: 'owner', label: 'Owner', field_type: 'string' };
    const ownerAllowedValues = Array.isArray(ownerField.allowed_values) ? ownerField.allowed_values.join(', ') : '';
    const firstAlias = Object.entries(profile?.concept_aliases ?? {}).find(([, value]) => value === effectiveSelection.id)?.[0] ?? '';
    const firstRelationshipId = Object.keys(profile?.relationship_types ?? {})[0] ?? '';
    const firstRelationship = firstRelationshipId ? profile?.relationship_types?.[firstRelationshipId] : undefined;
    const targetTypes = firstRelationship?.allowed_target_types ?? [];
    const packBadge = node?.badges?.find((badge) => String(badge).startsWith('Pack:'));
    const labelTemplate = String(graphDefaults.label_template ?? '{label}');
    const preview = labelTemplate.replaceAll('{label}', concept.label ?? effectiveSelection.title ?? effectiveSelection.id);
    return (
      <section data-testid="selection-inspector" className="space-y-3">
        <div data-testid="object-workbench" className="space-y-3">
          <div><h3 className="text-sm font-semibold">SelectionInspector · Object Type</h3><p className="text-[11px]" style={{ color: 'var(--color-text-muted, #64748b)' }}>Complete draft workspace for the selected schema object. Edits stay local until validation, diff, and save.</p>{packBadge ? <span data-testid="schema-pack-origin" className="mt-2 inline-flex rounded-full border px-2 py-0.5 text-[11px]">{packBadge}</span> : null}</div>
          <Section title="Identity"><div className="grid gap-2"><Field label="Label"><TextInput aria-label="Object label" value={concept.label ?? ''} onChange={(event) => updateConcept({ label: event.target.value })} /></Field><Field label="Description"><TextInput aria-label="Object type description" value={concept.description ?? ''} onChange={(event) => updateConcept({ description: event.target.value })} /></Field></div></Section>
          <Section title="View styling (GraphInstruction defaults)"><div className="grid gap-2"><Field label="Rendering shape"><TextInput aria-label="Rendering shape" value={String(graphDefaults.shape ?? concept.shape ?? '')} onChange={(event) => updateConceptGraphDefaults({ shape: event.target.value })} /></Field><Field label="Color"><TextInput aria-label="Object type color" type="color" value={String(graphDefaults.color ?? concept.color ?? '#64748b')} onChange={(event) => updateConceptGraphDefaults({ color: event.target.value })} /></Field><Field label="Rendering label template"><TextInput aria-label="Rendering label template" value={labelTemplate} onChange={(event) => updateConceptGraphDefaults({ label_template: event.target.value })} /></Field><p data-testid="object-workbench-preview" className="rounded border px-2 py-1 text-xs">{preview}</p><p className="text-[11px]" style={{ color: 'var(--color-text-muted, #64748b)' }}>Legacy ConceptType color/shape fallback: {concept.color} · {concept.shape}</p></div></Section>
          <Section title="Properties"><div className="grid gap-2"><Field label="Property owner label"><TextInput aria-label="Property owner label" value={ownerField.label ?? ''} onChange={(event) => updateMetadataField('owner', { label: event.target.value })} /></Field><Field label="Property owner type"><select aria-label="Property owner type" value={ownerField.field_type ?? 'string'} onChange={(event) => updateMetadataField('owner', { field_type: event.target.value })}><option value="string">string</option><option value="enum">enum</option><option value="number">number</option><option value="boolean">boolean</option><option value="date">date</option></select></Field><Field label="Property owner allowed values"><TextInput aria-label="Property owner allowed values" value={ownerAllowedValues} onChange={(event) => updateMetadataField('owner', { allowed_values: event.target.value.split(',').map((item) => item.trim()).filter(Boolean) })} /></Field></div></Section>
          {firstRelationship ? <Section title="Relationship constraints"><label className="flex items-center gap-2 text-xs"><input aria-label={`${firstRelationshipId} allows target ${effectiveSelection.id}`} type="checkbox" checked={targetTypes.includes(effectiveSelection.id)} onChange={(event) => updateRelationshipById(firstRelationshipId, { allowed_target_types: event.target.checked ? Array.from(new Set([...targetTypes, effectiveSelection.id])) : targetTypes.filter((item) => item !== effectiveSelection.id) })} />{firstRelationshipId} allows target {effectiveSelection.id}</label></Section> : null}
          <Section title="Aliases and scoped rules"><div className="grid gap-2"><Field label="Concept alias capability"><TextInput aria-label="Concept alias capability" value={firstAlias} onChange={(event) => updateConceptAlias(event.target.value, effectiveSelection.id)} /></Field><button type="button" onClick={addScopedRule} className="rounded border px-2 py-1 text-xs">Add rule</button></div></Section>
          <Section title="Source mappings"><div className="grid gap-2"><Field label="Source id"><TextInput aria-label="Object source id" value={source.source_id} onChange={(event) => updateConcept({ source_mappings: [{ ...source, source_id: event.target.value }] })} /></Field><Field label="Field path"><TextInput aria-label="Object source field path" value={source.field_path ?? ''} onChange={(event) => updateConcept({ source_mappings: [{ ...source, field_path: event.target.value }] })} /></Field></div></Section>
          <Section title="Validation"><button type="button" onClick={() => profile && void onValidate?.(profile)} className="rounded border px-2 py-1 text-xs">Validate draft</button></Section>
          <Section title="Lifecycle"><select aria-label="Object lifecycle state" value={String(concept.lifecycle_state ?? 'active')} onChange={(event) => updateConcept({ lifecycle_state: event.target.value })}><option value="draft">draft</option><option value="active">active</option><option value="deprecated">deprecated</option><option value="retired">retired</option></select></Section>
        </div>
      </section>
    );
  }

  if (relationship) {
    const source = mappingAt(relationship.source_mappings);
    return (
      <section data-testid="selection-inspector" className="space-y-3">
        <h3 className="text-sm font-semibold">SelectionInspector · Relationship Type</h3>
        <Section title="Identity"><div className="grid gap-2"><Field label="Label"><TextInput aria-label="Relationship label" value={relationship.label ?? ''} onChange={(event) => updateRelationship({ label: event.target.value })} /></Field><Field label="Description"><TextInput aria-label="Relationship description" value={relationship.description ?? ''} onChange={(event) => updateRelationship({ description: event.target.value })} /></Field></div></Section>
        <Section title="Endpoints and direction"><div className="grid gap-2"><Field label="Source types"><TextInput aria-label="Relationship source types" value={(relationship.allowed_source_types ?? []).join(', ')} onChange={(event) => updateRelationship({ allowed_source_types: event.target.value.split(',').map((item) => item.trim()).filter(Boolean) })} /></Field><Field label="Target types"><TextInput aria-label="Relationship target types" value={(relationship.allowed_target_types ?? []).join(', ')} onChange={(event) => updateRelationship({ allowed_target_types: event.target.value.split(',').map((item) => item.trim()).filter(Boolean) })} /></Field><Field label="Direction"><select aria-label="Relationship direction" value={relationship.map_direction ?? 'forward'} onChange={(event) => updateRelationship({ map_direction: event.target.value })}><option value="forward">forward</option><option value="reversed">reversed</option><option value="bidirectional">bidirectional</option><option value="none">none</option></select></Field></div></Section>
        <Section title="Cardinality and style"><div className="grid gap-2"><Field label="Cardinality"><select aria-label="Relationship cardinality" value={relationship.cardinality ?? ''} onChange={(event) => updateRelationship({ cardinality: event.target.value || null })}>{cardinalities.map((item) => <option key={item || 'none'} value={item}>{item || 'not specified'}</option>)}</select></Field><Field label="Family"><select aria-label="Relationship family" value={relationship.family ?? 'semantic'} onChange={(event) => updateRelationship({ family: event.target.value })}>{families.map((item) => <option key={item} value={item}>{item}</option>)}</select></Field><Field label="Style"><select aria-label="Relationship style" value={relationship.style ?? 'solid'} onChange={(event) => updateRelationship({ style: event.target.value })}><option value="solid">solid</option><option value="dashed">dashed</option><option value="dotted">dotted</option><option value="bold">bold</option></select></Field></div></Section>
        <Section title="Source mappings"><div className="grid gap-2"><Field label="Source id"><TextInput aria-label="Relationship source id" value={source.source_id} onChange={(event) => updateRelationship({ source_mappings: [{ ...source, source_id: event.target.value }] })} /></Field><Field label="Field path"><TextInput aria-label="Relationship source field path" value={source.field_path ?? ''} onChange={(event) => updateRelationship({ source_mappings: [{ ...source, field_path: event.target.value }] })} /></Field></div></Section>
        <Section title="Validation"><button type="button" onClick={() => profile && void onValidate?.(profile)} className="rounded border px-2 py-1 text-xs">Validate draft</button></Section>
      </section>
    );
  }

  return <section data-testid="selection-inspector"><h3>Selection</h3><pre>{JSON.stringify(node ?? effectiveSelection ?? { model: model.id }, null, 2)}</pre></section>;
}

export default SelectionInspector;
