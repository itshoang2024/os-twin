import type { EnterpriseMapProjectionData } from '@/hooks/use-knowledge-explorer';
import type { WorkbenchFacet, WorkbenchModel } from '../model/workbenchModel';

type MapState = 'live' | 'example' | 'empty';

function buckets(values: string[]) {
  const counts = values.reduce<Record<string, number>>((acc, value) => { const key = value || 'unknown'; acc[key] = (acc[key] ?? 0) + 1; return acc; }, {});
  return Object.entries(counts).sort(([a], [b]) => a.localeCompare(b)).map(([id, count]) => ({ id, label: id, count }));
}

export function mapLensAdapter(map: EnterpriseMapProjectionData | null | undefined, modelId = 'enterprise-map', mapState: MapState = 'live'): WorkbenchModel {
  const nodes = (map?.nodes ?? []).map((node) => ({
    id: String(node.id),
    label: String(node.name ?? node.label ?? node.id),
    type: String(node.concept_type ?? 'object'),
    subtitle: String(node.layer_label ?? node.lifecycle_state ?? ''),
    description: String(node.description ?? ''),
    color: String(node.concept_color ?? '#2563eb'),
    layerId: String(node.layer_id ?? 'default'),
    groupId: String(node.pack_id ?? node.layer_id ?? 'default'),
    properties: { owner: String(node.owner ?? node.metadata?.owner ?? ''), lifecycle_state: String(node.lifecycle_state ?? ''), review_state: String(node.review_state ?? ''), quality_state: String(node.quality_state ?? '') },
    badges: [node.lifecycle_state, node.review_state].filter(Boolean).map(String),
    sources: Array.isArray(node.provenance_refs) ? node.provenance_refs.map(String) : [],
  }));
  const edges = (map?.edges ?? []).map((edge, index) => ({
    id: `${edge.map_source ?? edge.source}->${edge.map_target ?? edge.target}:${edge.relationship_type ?? edge.label ?? index}`,
    source: String(edge.map_source ?? edge.source),
    target: String(edge.map_target ?? edge.target),
    label: String(edge.label ?? edge.relationship_type ?? ''),
    type: String(edge.relationship_type ?? edge.label ?? 'relationship'),
    weight: Number(edge.weight ?? 1),
    style: String(edge.style ?? 'solid'),
  }));
  const facets: WorkbenchFacet[] = [
    { id: 'object_type', label: 'Object type', kind: 'term', buckets: buckets(nodes.map((node) => node.type)) },
    { id: 'layer', label: 'Layer', kind: 'term', buckets: buckets(nodes.map((node) => node.layerId ?? 'default')) },
    { id: 'lifecycle', label: 'Lifecycle', kind: 'term', buckets: buckets(nodes.map((node) => String(node.properties?.lifecycle_state ?? ''))) },
  ];
  return {
    id: modelId,
    title: 'Enterprise Map Lens',
    subtitle: mapState === 'empty' ? 'No graph objects yet' : `${nodes.length} object nodes · ${edges.length} edges`,
    nodes,
    edges,
    facets,
    layers: (map?.layers ?? []).map((layer) => ({ id: String(layer.id), label: String(layer.label ?? layer.id), order: Number(layer.order ?? 0), count: Number(layer.count ?? 0) })),
    metadata: { source: 'mapLensAdapter', mapState, stats: map?.stats ?? {} },
  };
}
