import type { OntologyProfile } from '@/hooks/use-ontology';
import type { WorkbenchEdge, WorkbenchFacet, WorkbenchLayer, WorkbenchModel, WorkbenchNode, WorkbenchSelection } from '../model/workbenchModel';

export type PackOwnership = Record<string, { packId: string; name?: string; status?: string }>;

function labelFor(id: string, label?: string): string {
  if (label) return label;
  return id.replaceAll('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

function ownershipBadges(id: string, packOwnership?: PackOwnership): string[] {
  const owner = packOwnership?.[id];
  if (!owner) return [];
  return [owner.name ? `Pack: ${owner.name}` : `Pack: ${owner.packId}`, owner.status ?? 'installed'];
}

function facetBuckets(counts: Record<string, number>) {
  return Object.entries(counts).sort(([a], [b]) => a.localeCompare(b)).map(([id, count]) => ({ id, label: labelFor(id), count }));
}

export function specLensAdapter(
  profile: OntologyProfile,
  selection?: WorkbenchSelection,
  packOwnership?: PackOwnership,
): WorkbenchModel {
  const conceptEntries = Object.entries(profile.concept_types ?? {});
  const relationshipEntries = Object.entries(profile.relationship_types ?? {});
  const nodes: WorkbenchNode[] = conceptEntries.map(([id, concept]) => {
    const graphDefaults = (profile.graph_instruction?.concept_type_defaults?.[id] ?? {}) as Record<string, unknown>;
    const layerId = String(graphDefaults.default_layer ?? concept.default_layer ?? concept.layer ?? 'unassigned');
    const sourceMappings = Array.isArray(concept.source_mappings) ? concept.source_mappings : [];
    return {
      id,
      label: labelFor(id, concept.label),
      type: 'schema_type',
      kind: 'concept',
      subtitle: labelFor(String(concept.abstraction_level ?? 'type')),
      description: concept.description,
      color: String(graphDefaults.color ?? concept.color ?? '#64748b'),
      icon: String(graphDefaults.shape ?? concept.shape ?? 'rounded_rectangle'),
      layerId,
      badges: [...ownershipBadges(`concept_types:${id}`, packOwnership), String(concept.lifecycle_state ?? 'active')],
      sources: sourceMappings.map((item) => String(item.source_label || item.source_id)),
      properties: {
        concept_type: id,
        abstraction_level: concept.abstraction_level,
        default_layer: layerId,
        property_count: Object.keys(concept.metadata_schema ?? {}).length,
        source_mappings: sourceMappings,
        legacy_color: concept.color,
        legacy_shape: concept.shape,
      },
    };
  });

  const edges: WorkbenchEdge[] = relationshipEntries.flatMap(([id, relationship]) => {
    const sources = relationship.allowed_source_types?.length ? relationship.allowed_source_types : [];
    const targets = relationship.allowed_target_types?.length ? relationship.allowed_target_types : [];
    return sources.flatMap((source) => targets.map((target) => ({
      id: `${id}:${source}:${target}`,
      source,
      target,
      label: relationship.cardinality ? `${relationship.label ?? labelFor(id)} · ${labelFor(String(relationship.cardinality))}` : labelFor(id, relationship.label),
      type: id,
      family: relationship.family,
      weight: relationship.weight,
      style: relationship.style,
      properties: {
        relationship_type: id,
        cardinality: relationship.cardinality ?? null,
        map_direction: relationship.map_direction,
        is_directed: relationship.is_directed ?? true,
        source_mappings: relationship.source_mappings ?? [],
      },
    } satisfies WorkbenchEdge)));
  });

  const layerCounts = nodes.reduce<Record<string, number>>((acc, node) => {
    const id = node.layerId ?? 'unassigned';
    acc[id] = (acc[id] ?? 0) + 1;
    return acc;
  }, {});
  const layers: WorkbenchLayer[] = Object.entries(profile.layers ?? {}).map(([id, layer]) => ({
    id,
    label: labelFor(id, layer.label),
    order: Number(layer.order ?? 999),
    count: layerCounts[id] ?? 0,
  }));
  if (layerCounts.unassigned && !layers.some((layer) => layer.id === 'unassigned')) {
    layers.push({ id: 'unassigned', label: 'Unassigned', count: layerCounts.unassigned, order: 999 });
  }

  const familyCounts = relationshipEntries.reduce<Record<string, number>>((acc, [, relationship]) => {
    const id = String(relationship.family ?? 'semantic');
    acc[id] = (acc[id] ?? 0) + 1;
    return acc;
  }, {});
  const lifecycleCounts = conceptEntries.reduce<Record<string, number>>((acc, [, concept]) => {
    const id = String(concept.lifecycle_state ?? 'active');
    acc[id] = (acc[id] ?? 0) + 1;
    return acc;
  }, {});
  const facets: WorkbenchFacet[] = [
    { id: 'object_types', label: 'Object Types', buckets: facetBuckets(Object.fromEntries(conceptEntries.map(([id]) => [id, 1]))) },
    { id: 'relationship_family', label: 'Relationship Families', buckets: facetBuckets(familyCounts) },
    { id: 'lifecycle', label: 'Lifecycle', buckets: facetBuckets(lifecycleCounts) },
  ];

  return {
    id: `spec-lens:${profile.namespace}:${profile.profile_id}`,
    title: 'Spec Lens',
    subtitle: `${conceptEntries.length} object types · ${relationshipEntries.length} relationship types`,
    nodes,
    edges,
    selection,
    facets,
    layers,
    metadata: {
      lens: 'spec',
      profile_id: profile.profile_id,
      namespace: profile.namespace,
      version: profile.version,
      layout: 'hierarchy',
      sections: ['Sources', 'Candidates', 'Object Types', 'Properties', 'Relationships', 'Validation', 'Templates'],
      validation_rule_count: profile.validation_rules?.length ?? 0,
      metadata_field_count: Object.keys(profile.metadata_fields ?? {}).length,
    },
  };
}
