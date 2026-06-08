import type { Cardinality, MetadataField, OntologyConceptType, OntologyProfile, OntologyRelationshipType, SourceMapping } from './types';

const palette = ['#2563eb', '#7c3aed', '#0f766e', '#b45309', '#be123c', '#475569'];

export function slugifyLabel(label: string, fallback = 'object_type'): string {
  const slug = label.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  return slug || fallback;
}

function uniqueId(base: string, existing: Record<string, unknown>): string {
  let id = base;
  let idx = 2;
  while (existing[id]) id = `${base}_${idx++}`;
  return id;
}

export function cloneProfile(profile: OntologyProfile): OntologyProfile {
  return JSON.parse(JSON.stringify(profile));
}

export function makeBlankOntologyProfile(namespace = 'local'): OntologyProfile {
  return {
    id: `${namespace}-draft`,
    namespace,
    label: 'Active ontology profile',
    status: 'draft',
    conceptTypes: {},
    relationshipTypes: {},
    graphInstruction: { conceptTypeDefaults: {}, relationshipTypeDefaults: {} },
    candidates: [
      { id: 'candidate_policy', kind: 'object', label: 'Policy', evidenceRefs: ['doc://policy-handbook#p4'], source: 'Candidate extractor' },
      { id: 'candidate_proves', kind: 'relationship', label: 'proves', evidenceRefs: ['doc://evidence-log#r12'], source: 'Candidate extractor' },
    ],
    updatedAt: new Date().toISOString(),
  };
}

export function createObjectType(profile: OntologyProfile, label: string, options: Partial<OntologyConceptType> = {}) {
  const next = cloneProfile(profile);
  const id = uniqueId(slugifyLabel(label, 'object_type'), next.conceptTypes);
  const concept: OntologyConceptType = {
    id,
    label: label.trim() || 'Object Type',
    description: options.description ?? '',
    layer: options.layer ?? 'semantic',
    abstractionLevel: options.abstractionLevel ?? 'unit',
    lifecycle: options.lifecycle ?? 'draft',
    metadataFields: options.metadataFields ? [...options.metadataFields] : [],
    sourceMappings: options.sourceMappings ? [...options.sourceMappings] : [],
  };
  next.conceptTypes[id] = concept;
  next.graphInstruction.conceptTypeDefaults[id] = {
    color: palette[Object.keys(next.conceptTypes).length % palette.length],
    shape: 'rounded',
  };
  next.updatedAt = new Date().toISOString();
  return { profile: next, concept };
}

export function renameObjectType(profile: OntologyProfile, id: string, label: string) {
  const next = cloneProfile(profile);
  if (!next.conceptTypes[id]) return next;
  next.conceptTypes[id].label = label;
  next.updatedAt = new Date().toISOString();
  return next;
}

export function patchObjectType(profile: OntologyProfile, id: string, patch: Partial<OntologyConceptType>) {
  const next = cloneProfile(profile);
  if (!next.conceptTypes[id]) return next;
  next.conceptTypes[id] = { ...next.conceptTypes[id], ...patch, id };
  next.updatedAt = new Date().toISOString();
  return next;
}

export function addMetadataFieldToObjectType(profile: OntologyProfile, conceptId: string, field: Partial<MetadataField>) {
  const next = cloneProfile(profile);
  const concept = next.conceptTypes[conceptId];
  if (!concept) return next;
  const id = uniqueId(slugifyLabel(field.label ?? 'property', 'property'), Object.fromEntries(concept.metadataFields.map((f) => [f.id, f])));
  concept.metadataFields.push({ id, label: field.label ?? 'Property', type: field.type ?? 'text', required: field.required ?? false, source: field.source ?? '' });
  next.updatedAt = new Date().toISOString();
  return next;
}

export function attachSourceMapping(profile: OntologyProfile, conceptId: string, mapping: Partial<SourceMapping>) {
  const next = cloneProfile(profile);
  const concept = next.conceptTypes[conceptId];
  if (!concept) return next;
  concept.sourceMappings.push({
    id: uniqueId('source_mapping', Object.fromEntries(concept.sourceMappings.map((m) => [m.id, m]))),
    source: mapping.source ?? 'knowledge graph',
    selector: mapping.selector ?? concept.label,
    evidenceRefs: mapping.evidenceRefs ?? [],
  });
  next.updatedAt = new Date().toISOString();
  return next;
}

export function removeObjectTypeSafely(profile: OntologyProfile, id: string) {
  const blockers = Object.values(profile.relationshipTypes).filter((rel) => rel.allowedSourceTypes.includes(id) || rel.allowedTargetTypes.includes(id));
  if (blockers.length) return { profile, removed: false, blockers };
  const next = cloneProfile(profile);
  delete next.conceptTypes[id];
  delete next.graphInstruction.conceptTypeDefaults[id];
  next.updatedAt = new Date().toISOString();
  return { profile: next, removed: true, blockers: [] };
}

export function createRelationshipType(profile: OntologyProfile, label: string, options: Partial<OntologyRelationshipType>) {
  const next = cloneProfile(profile);
  const id = uniqueId(slugifyLabel(label, 'relationship_type'), next.relationshipTypes);
  const relationship: OntologyRelationshipType = {
    id,
    label: label.trim() || 'relates to',
    description: options.description ?? '',
    family: options.family ?? 'dependency',
    allowedSourceTypes: options.allowedSourceTypes ?? [],
    allowedTargetTypes: options.allowedTargetTypes ?? [],
    cardinality: options.cardinality ?? 'many_to_many',
    mapDirection: options.mapDirection ?? 'forward',
    inverse: options.inverse ?? '',
    style: options.style ?? 'solid',
    weight: options.weight ?? 1,
    sourceMappings: options.sourceMappings ?? [],
  };
  next.relationshipTypes[id] = relationship;
  next.graphInstruction.relationshipTypeDefaults[id] = { color: '#64748b', style: relationship.style, weight: relationship.weight };
  next.updatedAt = new Date().toISOString();
  return { profile: next, relationship };
}

export function patchRelationshipType(profile: OntologyProfile, id: string, patch: Partial<OntologyRelationshipType>) {
  const next = cloneProfile(profile);
  if (!next.relationshipTypes[id]) return next;
  next.relationshipTypes[id] = { ...next.relationshipTypes[id], ...patch, id };
  if (patch.style || patch.weight) {
    next.graphInstruction.relationshipTypeDefaults[id] = {
      ...next.graphInstruction.relationshipTypeDefaults[id],
      style: next.relationshipTypes[id].style,
      weight: next.relationshipTypes[id].weight,
    };
  }
  next.updatedAt = new Date().toISOString();
  return next;
}

export function toggleRelationshipEndpoint(profile: OntologyProfile, relationshipId: string, sourceId: string, targetId: string) {
  const rel = profile.relationshipTypes[relationshipId];
  if (!rel) return profile;
  const hasSource = rel.allowedSourceTypes.includes(sourceId);
  const hasTarget = rel.allowedTargetTypes.includes(targetId);
  if (hasSource && hasTarget) {
    return patchRelationshipType(profile, relationshipId, {
      allowedSourceTypes: rel.allowedSourceTypes.filter((id) => id !== sourceId),
      allowedTargetTypes: rel.allowedTargetTypes.filter((id) => id !== targetId),
    });
  }
  return patchRelationshipType(profile, relationshipId, {
    allowedSourceTypes: Array.from(new Set([...rel.allowedSourceTypes, sourceId])),
    allowedTargetTypes: Array.from(new Set([...rel.allowedTargetTypes, targetId])),
  });
}

export function validateOntologyProfile(profile: OntologyProfile) {
  const issues = [] as import('./types').ValidationIssue[];
  Object.values(profile.conceptTypes).forEach((concept) => {
    if (!concept.label.trim()) issues.push({ id: `concept-${concept.id}-label`, severity: 'error', message: 'Object Type needs a label.', path: `conceptTypes.${concept.id}.label`, focus: 'identity' });
  });
  Object.values(profile.relationshipTypes).forEach((rel) => {
    if (!rel.allowedSourceTypes.length) issues.push({ id: `rel-${rel.id}-source`, severity: 'error', message: `${rel.label} needs at least one source Object Type.`, path: `relationshipTypes.${rel.id}.allowedSourceTypes`, focus: 'endpoint' });
    if (!rel.allowedTargetTypes.length) issues.push({ id: `rel-${rel.id}-target`, severity: 'error', message: `${rel.label} needs at least one target Object Type.`, path: `relationshipTypes.${rel.id}.allowedTargetTypes`, focus: 'endpoint' });
    if (!(['one_to_one','one_to_many','many_to_one','many_to_many'] as Cardinality[]).includes(rel.cardinality)) issues.push({ id: `rel-${rel.id}-cardinality`, severity: 'error', message: `${rel.label} has invalid cardinality.`, path: `relationshipTypes.${rel.id}.cardinality`, focus: 'cardinality' });
  });
  return issues;
}
