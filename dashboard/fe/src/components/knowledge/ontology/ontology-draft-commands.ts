import type { OntologyConceptType, OntologyMetadataField, OntologyProfile, OntologyRelationshipType, OntologySourceMapping } from '@/hooks/use-ontology';
import { cloneProfile } from './ontology-ui';

export type ObjectTypeDraftInput = {
  label: string;
  description?: string;
  abstractionLevel?: string;
  layer?: string;
  color?: string;
  shape?: string;
  sourceMapping?: Partial<OntologySourceMapping>;
};

export type RelationshipTypeDraftInput = {
  label: string;
  description?: string;
  sourceTypes: string[];
  targetTypes: string[];
  family?: string;
  cardinality?: string | null;
  mapDirection?: string;
  inverse?: string;
  style?: string;
  weight?: number;
  sourceMapping?: Partial<OntologySourceMapping>;
};

export function slugifyOntologyId(label: string, existing: Record<string, unknown> = {}, fallback = 'object_type'): string {
  const base = (label || fallback).trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || fallback;
  if (!existing[base]) return base;
  let suffix = 2;
  while (existing[`${base}_${suffix}`]) suffix += 1;
  return `${base}_${suffix}`;
}

function ensureLayer(profile: OntologyProfile, id: string, label = id): void {
  if (!profile.layers[id]) profile.layers[id] = { id, label: label.replaceAll('_', ' ').replace(/\b\w/g, (m) => m.toUpperCase()) };
}

function ensureAbstractionLevel(profile: OntologyProfile, id: string, label = id): void {
  if (!profile.abstraction_levels[id]) profile.abstraction_levels[id] = { id, label: label.replaceAll('_', ' ').replace(/\b\w/g, (m) => m.toUpperCase()) };
}

function sourceMappingFrom(partial?: Partial<OntologySourceMapping>): OntologySourceMapping[] {
  if (!partial || (!partial.source_id && !partial.field_path && !partial.source_label)) return [];
  return [{ source_id: partial.source_id ?? '', source_type: partial.source_type ?? 'other', source_label: partial.source_label ?? partial.source_id ?? '', field_path: partial.field_path ?? '', transform: partial.transform ?? '', confidence: partial.confidence ?? null, notes: partial.notes ?? '' }];
}

export function createObjectType(profile: OntologyProfile, input: ObjectTypeDraftInput): { profile: OntologyProfile; id: string } {
  const next = cloneProfile(profile);
  const id = slugifyOntologyId(input.label, next.concept_types, 'object_type');
  const layer = input.layer || Object.keys(next.layers ?? {})[0] || 'default';
  const abstractionLevel = input.abstractionLevel || Object.keys(next.abstraction_levels ?? {})[0] || 'entity';
  ensureLayer(next, layer);
  ensureAbstractionLevel(next, abstractionLevel);
  const concept: OntologyConceptType = {
    id,
    label: input.label.trim() || 'Object Type',
    description: input.description || `Draft object type ${input.label || id}.`,
    abstraction_level: abstractionLevel,
    default_layer: layer,
    layer,
    metadata_schema: {},
    metadata_fields: [],
    source_mappings: sourceMappingFrom(input.sourceMapping),
  };
  next.concept_types = { ...(next.concept_types ?? {}), [id]: concept };
  next.graph_instruction = {
    ...(next.graph_instruction ?? {}),
    concept_type_defaults: {
      ...(next.graph_instruction?.concept_type_defaults ?? {}),
      [id]: { concept_type: id, default_layer: layer, color: input.color ?? '#64748b', shape: input.shape ?? 'rounded_rectangle', group: layer, label_template: '{label}' },
    },
  };
  return { profile: next, id };
}

export function renameObjectType(profile: OntologyProfile, id: string, label: string): OntologyProfile {
  const next = cloneProfile(profile);
  if (!next.concept_types[id]) return next;
  next.concept_types[id] = { ...next.concept_types[id], label };
  return next;
}

export function patchObjectType(profile: OntologyProfile, id: string, patch: Partial<OntologyConceptType>): OntologyProfile {
  const next = cloneProfile(profile);
  if (!next.concept_types[id]) return next;
  next.concept_types[id] = { ...next.concept_types[id], ...patch };
  return next;
}

export function addMetadataFieldToObjectType(profile: OntologyProfile, conceptId: string, field: Partial<OntologyMetadataField> & { label: string }): { profile: OntologyProfile; id: string } {
  const next = cloneProfile(profile);
  const id = slugifyOntologyId(field.id || field.label, next.metadata_fields, 'property');
  next.metadata_fields = { ...(next.metadata_fields ?? {}), [id]: { id, label: field.label, field_type: field.field_type ?? 'string', description: field.description, required: field.required ?? false, allowed_values: field.allowed_values ?? [] } };
  const concept = next.concept_types[conceptId];
  if (concept) {
    const fields = Array.from(new Set([...(concept.metadata_fields ?? []), id]));
    next.concept_types[conceptId] = { ...concept, metadata_fields: fields, metadata_schema: { ...(concept.metadata_schema ?? {}), [id]: next.metadata_fields[id] } };
  }
  return { profile: next, id };
}

export function attachSourceMapping(profile: OntologyProfile, conceptId: string, mapping: Partial<OntologySourceMapping>): OntologyProfile {
  const next = cloneProfile(profile);
  const concept = next.concept_types[conceptId];
  if (!concept) return next;
  next.concept_types[conceptId] = { ...concept, source_mappings: [...(concept.source_mappings ?? []), ...sourceMappingFrom(mapping)] };
  return next;
}

export function removeObjectTypeSafely(profile: OntologyProfile, id: string): { profile: OntologyProfile; blockedBy: string[] } {
  const blockers = Object.entries(profile.relationship_types ?? {}).filter(([, rel]) => [...(rel.allowed_source_types ?? []), ...(rel.allowed_target_types ?? [])].includes(id)).map(([relId]) => relId);
  if (blockers.length) return { profile, blockedBy: blockers };
  const next = cloneProfile(profile);
  delete next.concept_types[id];
  if (next.graph_instruction?.concept_type_defaults) delete next.graph_instruction.concept_type_defaults[id];
  return { profile: next, blockedBy: [] };
}

export function createRelationshipType(profile: OntologyProfile, input: RelationshipTypeDraftInput): { profile: OntologyProfile; id: string } {
  const next = cloneProfile(profile);
  const id = slugifyOntologyId(input.label, next.relationship_types, 'relationship_type');
  const relationship: OntologyRelationshipType = {
    id,
    label: input.label.trim() || 'Relationship Type',
    description: input.description || `Draft relationship type ${input.label || id}.`,
    family: input.family || 'semantic',
    allowed_source_types: Array.from(new Set(input.sourceTypes)).filter((item) => Boolean(next.concept_types[item])),
    allowed_target_types: Array.from(new Set(input.targetTypes)).filter((item) => Boolean(next.concept_types[item])),
    cardinality: (input.cardinality || null) as OntologyRelationshipType['cardinality'],
    map_direction: input.mapDirection || 'forward',
    inverse: input.inverse || undefined,
    style: input.style || 'solid',
    weight: input.weight ?? 0.5,
    is_directed: (input.mapDirection || 'forward') !== 'none',
    source_mappings: sourceMappingFrom(input.sourceMapping),
  };
  next.relationship_types = { ...(next.relationship_types ?? {}), [id]: relationship };
  next.graph_instruction = {
    ...(next.graph_instruction ?? {}),
    relationship_type_defaults: {
      ...(next.graph_instruction?.relationship_type_defaults ?? {}),
      [id]: { relationship_type: id, map_direction: relationship.map_direction, group: String(relationship.family ?? 'semantic'), weight: relationship.weight, dash: relationship.style === 'dashed' || relationship.style === 'dotted' ? relationship.style : null, label_template: '{label}' },
    },
  };
  return { profile: next, id };
}

export function patchRelationshipEndpoints(profile: OntologyProfile, relationshipId: string, sourceTypes: string[], targetTypes: string[]): OntologyProfile {
  const next = cloneProfile(profile);
  const relationship = next.relationship_types[relationshipId];
  if (!relationship) return next;
  next.relationship_types[relationshipId] = { ...relationship, allowed_source_types: Array.from(new Set(sourceTypes)).filter((id) => Boolean(next.concept_types[id])), allowed_target_types: Array.from(new Set(targetTypes)).filter((id) => Boolean(next.concept_types[id])) };
  return next;
}
