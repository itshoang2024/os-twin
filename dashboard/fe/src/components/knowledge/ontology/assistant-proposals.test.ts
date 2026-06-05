import { describe, expect, it } from 'vitest';
import type { OntologyProfile } from '@/hooks/use-ontology';
import { applyOntologyProposalToDraft, parseOntologyAssistantResponse } from './assistant-proposals';

function profile(): OntologyProfile {
  return {
    profile_id: 'demo_profile',
    namespace: 'demo',
    version: '1.0.0',
    concept_types: { feature: { id: 'feature', label: 'Feature' } },
    relationship_types: {},
    aliases: {},
    layers: {},
    abstraction_levels: {},
    metadata_fields: {},
  };
}

describe('assistant proposal parsing', () => {
  it('parses strict fenced proposed_changes JSON while preserving natural-language answer', () => {
    const parsed = parseOntologyAssistantResponse('Add a risk object.\n```json\n{"proposed_changes":{"concept_types":{"risk":{"id":"risk","label":"Risk"}}},"rationale":"Doc mentions risk.","evidence_refs":["anchor-1"]}\n```');
    expect(parsed.answer).toBe('Add a risk object.');
    expect(parsed.status).toBe('suggested');
    expect(parsed.rationale).toBe('Doc mentions risk.');
    expect(parsed.evidenceRefs).toEqual(['anchor-1']);
    expect(parsed.proposedChanges).toEqual({ concept_types: { risk: { id: 'risk', label: 'Risk' } } });
  });

  it('keeps natural-language-only answers advisory with no patch', () => {
    const parsed = parseOntologyAssistantResponse('The current ontology is valid.');
    expect(parsed.answer).toBe('The current ontology is valid.');
    expect(parsed.proposedChanges).toBeNull();
    expect(parsed.parseError).toBeUndefined();
  });

  it('marks invalid JSON as parse_failed and applies nothing', () => {
    const parsed = parseOntologyAssistantResponse('Here is a proposal.\n```json\n{"proposed_changes": { bad json }\n```');
    expect(parsed.status).toBe('parse_failed');
    expect(parsed.answer).toBe('Here is a proposal.');
    expect(parsed.proposedChanges).toBeNull();
    expect(parsed.parseError).toBeTruthy();
  });

  it('rejects unsupported proposed_changes sections', () => {
    const parsed = parseOntologyAssistantResponse('Unsafe.\n```json\n{"proposed_changes":{"saved_profile":{"status":"approved"}},"rationale":"bad","evidence_refs":[]}\n```');
    expect(parsed.status).toBe('parse_failed');
    expect(parsed.parseError).toMatch(/Unsupported/);
  });
});

describe('assistant proposal draft patching', () => {
  it('patches allowed profile sections without mutating the saved profile object', () => {
    const base = profile();
    const result = applyOntologyProposalToDraft(base, {
      concept_types: { risk: { id: 'risk', label: 'Risk', lifecycle_state: 'draft' } },
      relationship_types: { mitigates: { id: 'mitigates', label: 'Mitigates', allowed_source_types: ['feature'], allowed_target_types: ['risk'] } },
      aliases: { hazard: 'risk' },
      graph_instruction: { concept_type_defaults: { risk: { concept_type: 'risk', color: '#dc2626' } } },
    });
    expect(base.concept_types.risk).toBeUndefined();
    expect(result.profile.concept_types.risk.label).toBe('Risk');
    expect(result.profile.relationship_types.mitigates.allowed_target_types).toEqual(['risk']);
    expect(result.profile.aliases.hazard).toBe('risk');
    expect(result.rejected).toEqual([]);
  });

  it('rejects unsupported fields and advisory-only candidate/fact actions', () => {
    const result = applyOntologyProposalToDraft(profile(), {
      concept_types: { risk: { id: 'risk', label: 'Risk', save_now: true } },
      candidate_actions: [{ action: 'approve', id: 'cand-1' }],
      fact_actions: [{ action: 'promote', id: 'fact-1' }],
    });
    expect(result.profile.concept_types.risk).toBeUndefined();
    expect(result.rejected.join('\n')).toMatch(/unsupported fields/);
    expect(result.rejected.join('\n')).toMatch(/candidate_actions is advisory-only/);
    expect(result.rejected.join('\n')).toMatch(/fact_actions is advisory-only/);
  });
});


  it('allows governed cardinality and source mapping fields in staged proposals', () => {
    const result = applyOntologyProposalToDraft(profile(), {
      concept_types: { feature: { id: 'feature', label: 'Feature', source_mappings: [{ source_id: 'doc-1', field_path: 'features[]' }] } },
      relationship_types: { owns: { id: 'owns', label: 'Owns', family: 'ownership', cardinality: 'one_to_many', source_mappings: [{ source_id: 'crm', field_path: 'owner_id' }] } },
      metadata_fields: { owner: { id: 'owner', label: 'Owner', field_type: 'string', source_mappings: [{ source_id: 'hr', field_path: 'email' }] } },
    });

    expect(result.rejected).toEqual([]);
    expect(result.profile.relationship_types.owns.cardinality).toBe('one_to_many');
    expect(result.profile.concept_types.feature.source_mappings?.[0]).toMatchObject({ source_id: 'doc-1' });
    expect(result.profile.metadata_fields.owner.source_mappings?.[0]).toMatchObject({ field_path: 'email' });
  });
