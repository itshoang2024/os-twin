import type { OntologyProfile } from '@/hooks/use-ontology';
import { cloneProfile } from './ontology-ui';

export type ProposalStatus = 'suggested' | 'parse_failed' | 'applied' | 'validated' | 'diffed' | 'saved' | 'discarded';

export interface OntologyAssistantProposal {
  answer: string;
  rawBlock?: string;
  proposedChanges: Record<string, unknown> | null;
  rationale?: string;
  evidenceRefs: string[];
  parseError?: string;
  status: ProposalStatus;
}

export interface PatchResult {
  profile: OntologyProfile;
  rejected: string[];
  appliedPaths: string[];
}

const FENCED_JSON_RE = /```json\s*([\s\S]*?)```/i;
const ALLOWED_SECTIONS = new Set([
  'concept_types',
  'relationship_types',
  'aliases',
  'concept_aliases',
  'layers',
  'abstraction_levels',
  'metadata_fields',
  'validation_rules',
  'graph_instruction',
  'fixtures',
  'migration_notes',
  'candidate_actions',
  'fact_actions',
]);
const DRAFT_PROFILE_SECTIONS = new Set([
  'concept_types',
  'relationship_types',
  'aliases',
  'concept_aliases',
  'layers',
  'abstraction_levels',
  'metadata_fields',
  'validation_rules',
  'graph_instruction',
]);
const FIELD_ALLOWLIST: Record<string, Set<string>> = {
  concept_types: new Set(['id', 'label', 'abstraction_level', 'default_layer', 'description', 'metadata_schema', 'metadata_fields', 'color', 'shape', 'source_mappings', 'lifecycle_state']),
  relationship_types: new Set(['id', 'label', 'family', 'inverse', 'description', 'allowed_source_types', 'allowed_target_types', 'weight', 'style', 'display_style', 'map_direction', 'is_directed', 'is_system', 'cardinality', 'source_mappings', 'lifecycle_state']),
  layers: new Set(['id', 'label', 'order', 'description', 'lifecycle_state']),
  abstraction_levels: new Set(['id', 'label', 'order', 'description', 'lifecycle_state']),
  metadata_fields: new Set(['id', 'label', 'field_type', 'allowed_values', 'description', 'required', 'source_mappings', 'lifecycle_state']),
};

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function stripProposalBlock(text: string, rawBlock?: string) {
  if (!rawBlock) return text.trim();
  return text.replace(FENCED_JSON_RE, '').trim();
}

export function parseOntologyAssistantResponse(text: string): OntologyAssistantProposal {
  const match = text.match(FENCED_JSON_RE);
  if (!match) {
    return { answer: text.trim(), proposedChanges: null, evidenceRefs: [], status: 'suggested' };
  }
  const rawBlock = match[1].trim();
  const answer = stripProposalBlock(text, rawBlock);
  try {
    const parsed = JSON.parse(rawBlock) as unknown;
    if (!isObject(parsed)) throw new Error('Proposal JSON must be an object.');
    const proposedChanges = parsed.proposed_changes;
    if (!isObject(proposedChanges)) throw new Error('Proposal JSON must include object field proposed_changes.');
    const unsupported = Object.keys(proposedChanges).filter((key) => !ALLOWED_SECTIONS.has(key));
    if (unsupported.length) throw new Error(`Unsupported proposed_changes sections: ${unsupported.join(', ')}`);
    return {
      answer,
      rawBlock,
      proposedChanges,
      rationale: typeof parsed.rationale === 'string' ? parsed.rationale : undefined,
      evidenceRefs: asStringArray(parsed.evidence_refs),
      status: 'suggested',
    };
  } catch (err) {
    return {
      answer,
      rawBlock,
      proposedChanges: null,
      evidenceRefs: [],
      parseError: err instanceof Error ? err.message : 'Unable to parse proposed changes JSON.',
      status: 'parse_failed',
    };
  }
}

function mergeRecordSection(next: OntologyProfile, section: keyof OntologyProfile, value: unknown, rejected: string[], appliedPaths: string[]) {
  if (!isObject(value)) {
    rejected.push(`${String(section)} must be an object.`);
    return;
  }
  const current = isObject(next[section]) ? { ...(next[section] as Record<string, unknown>) } : {};
  const fieldAllowlist = FIELD_ALLOWLIST[String(section)];
  Object.entries(value).forEach(([id, patch]) => {
    if (!isObject(patch)) {
      rejected.push(`${String(section)}.${id} must be an object.`);
      return;
    }
    const illegalFields = fieldAllowlist ? Object.keys(patch).filter((field) => !fieldAllowlist.has(field)) : [];
    if (illegalFields.length) {
      rejected.push(`${String(section)}.${id} has unsupported fields: ${illegalFields.join(', ')}`);
      return;
    }
    current[id] = { ...(isObject(current[id]) ? current[id] as Record<string, unknown> : { id }), ...patch, id: String(patch.id ?? id) };
    appliedPaths.push(`${String(section)}.${id}`);
  });
  (next as unknown as Record<string, unknown>)[section as string] = current;
}

function mergeStringMap(next: OntologyProfile, section: 'aliases' | 'concept_aliases', value: unknown, rejected: string[], appliedPaths: string[]) {
  if (!isObject(value)) {
    rejected.push(`${section} must be an object.`);
    return;
  }
  const current = { ...((next[section] ?? {}) as Record<string, string>) };
  Object.entries(value).forEach(([alias, target]) => {
    if (typeof target !== 'string') {
      rejected.push(`${section}.${alias} must map to a string target.`);
      return;
    }
    current[alias] = target;
    appliedPaths.push(`${section}.${alias}`);
  });
  next[section] = current;
}

function deepMerge(base: unknown, patch: unknown): unknown {
  if (!isObject(base) || !isObject(patch)) return patch;
  return Object.entries(patch).reduce<Record<string, unknown>>((acc, [key, value]) => {
    acc[key] = isObject(value) && isObject(acc[key]) ? deepMerge(acc[key], value) : value;
    return acc;
  }, { ...base });
}

export function applyOntologyProposalToDraft(profile: OntologyProfile, proposedChanges: Record<string, unknown>): PatchResult {
  const next = cloneProfile(profile);
  const rejected: string[] = [];
  const appliedPaths: string[] = [];
  Object.entries(proposedChanges).forEach(([section, value]) => {
    if (!DRAFT_PROFILE_SECTIONS.has(section)) {
      rejected.push(`${section} is advisory-only and is not applied to the ontology draft.`);
      return;
    }
    if (['concept_types', 'relationship_types', 'layers', 'abstraction_levels', 'metadata_fields'].includes(section)) {
      mergeRecordSection(next, section as keyof OntologyProfile, value, rejected, appliedPaths);
    } else if (section === 'aliases' || section === 'concept_aliases') {
      mergeStringMap(next, section, value, rejected, appliedPaths);
    } else if (section === 'validation_rules') {
      if (!Array.isArray(value)) rejected.push('validation_rules must be an array.');
      else {
        next.validation_rules = [...(next.validation_rules ?? []), ...value.filter(isObject)];
        appliedPaths.push('validation_rules');
      }
    } else if (section === 'graph_instruction') {
      if (!isObject(value)) rejected.push('graph_instruction must be an object.');
      else {
        next.graph_instruction = deepMerge(next.graph_instruction ?? {}, value) as OntologyProfile['graph_instruction'];
        appliedPaths.push('graph_instruction');
      }
    }
  });
  return { profile: next, rejected, appliedPaths };
}

export function proposalSectionCounts(proposedChanges: Record<string, unknown> | null): Array<{ section: string; count: number }> {
  if (!proposedChanges) return [];
  return Object.entries(proposedChanges).map(([section, value]) => ({
    section,
    count: Array.isArray(value) ? value.length : isObject(value) ? Object.keys(value).length : 1,
  }));
}
