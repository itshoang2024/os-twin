import type { EnterpriseMapProjectionData } from '@/hooks/use-knowledge-explorer';
import type { WorkbenchFacet, WorkbenchModel } from '../model/workbenchModel';

type MapState = 'live' | 'example' | 'empty';

function buckets(values: string[]) {
  const counts = values.reduce<Record<string, number>>((acc, value) => { const key = value || 'unknown'; acc[key] = (acc[key] ?? 0) + 1; return acc; }, {});
  return Object.entries(counts).sort(([a], [b]) => a.localeCompare(b)).map(([id, count]) => ({ id, label: id, count }));
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function issueCount(value: unknown) {
  return Array.isArray(value) ? value.length : 0;
}

export function mapLensAdapter(map: EnterpriseMapProjectionData | null | undefined, modelId = 'enterprise-map', mapState: MapState = 'live'): WorkbenchModel {
  const nodes = (map?.nodes ?? []).map((node) => {
    const metadata = record(node.metadata);
    const properties = { ...record(node.properties), ...metadata };
    const lifecycleState = String(node.lifecycle_state ?? '');
    const reviewState = String(node.review_state ?? '');
    const candidateState = String(node.candidate_state ?? '');
    const qualityState = String(node.quality_state ?? '');
    const validationIssueCount = issueCount(node.validation_issues);
    const eventCount = Number(node.event_count ?? 0);
    const externalRef = record(node.external_ref);
    return {
      id: String(node.id),
      label: String(node.name ?? node.label ?? node.id),
      type: String(node.concept_type ?? 'object'),
      subtitle: [node.layer_label, node.abstraction_label, node.owner ?? metadata.owner].filter(Boolean).slice(0, 3).map(String).join(' · '),
      description: String(node.description ?? metadata.description ?? ''),
      color: String(node.concept_color ?? '#2563eb'),
      layerId: String(node.layer_id ?? 'default'),
      groupId: String(node.map_group ?? node.pack_id ?? node.layer_id ?? 'default'),
      mapGroup: String(node.map_group ?? node.pack_id ?? node.layer_id ?? 'default'),
      lifecycleState,
      reviewState,
      candidateState,
      qualityState,
      eventCount,
      activeEventCount: Number(node.active_event_count ?? 0),
      validationIssueCount,
      externalRef: Object.keys(externalRef).length ? externalRef : null,
      properties: { ...properties, owner: String(node.owner ?? metadata.owner ?? ''), lifecycle_state: lifecycleState, review_state: reviewState, candidate_state: candidateState, quality_state: qualityState, map_group: String(node.map_group ?? '') },
      badges: [lifecycleState, reviewState, candidateState, qualityState, Object.keys(externalRef).length ? 'external' : ''].filter(Boolean),
      sources: Array.isArray(node.provenance_refs) ? node.provenance_refs.map(String) : [],
    };
  });
  const edges = (map?.edges ?? []).map((edge, index) => ({
    id: `${edge.map_source ?? edge.source}->${edge.map_target ?? edge.target}:${edge.relationship_type ?? edge.label ?? index}`,
    source: String(edge.map_source ?? edge.source),
    target: String(edge.map_target ?? edge.target),
    label: String(edge.display_label ?? edge.label ?? edge.relationship_type ?? ''),
    displayLabel: String(edge.display_label ?? edge.label ?? edge.relationship_type ?? ''),
    type: String(edge.relationship_type ?? edge.label ?? 'relationship'),
    family: String(edge.family ?? ''),
    weight: Number(edge.weight ?? 1),
    color: String((edge as { color?: unknown }).color ?? '#64748b'),
    style: String(edge.style ?? 'solid'),
    properties: { review_state: String(edge.review_state ?? ''), candidate_state: String(edge.candidate_state ?? ''), validation_issue_count: issueCount(edge.validation_issues) },
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
    metadata: { source: 'mapLensAdapter', mapState, stats: map?.stats ?? {}, meta: map?.meta ?? {} },
  };
}
