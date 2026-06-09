import type {
  CanvasEdge,
  CanvasNode,
  CanvasViewModel,
  EnterpriseMapProjectionEdge,
  EnterpriseMapProjectionNode,
  EnterpriseMapProjectionResponse,
  ExplorerNodeDetailResponse,
  ExplorerSearchResult,
  GraphLayoutPreset,
  GraphEvent,
} from './types';

const DEFAULT_NODE_COLOR = '#475569';
const DEFAULT_EDGE_COLOR = '#94a3b8';

const LAYOUT_CONFIG: Record<GraphLayoutPreset, { columns: number; xSpacing: number; ySpacing: number; xStart: number; yStart: number }> = {
  grid: { columns: 4, xSpacing: 190, ySpacing: 132, xStart: 96, yStart: 96 },
  layered: { columns: 3, xSpacing: 240, ySpacing: 150, xStart: 110, yStart: 92 },
  compact: { columns: 5, xSpacing: 166, ySpacing: 116, xStart: 76, yStart: 78 },
};

function textBadge(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function sanitizeProperties(redacted: boolean | undefined, properties: Record<string, unknown> | undefined): Record<string, unknown> {
  if (redacted) return {};
  return properties && typeof properties === 'object' ? { ...properties } : {};
}

function activeEvents(events: GraphEvent[] | undefined): GraphEvent[] {
  return (events ?? []).filter((event) => event.status === 'active');
}

function normalizePermissions(permission: EnterpriseMapProjectionNode['permissions']) {
  return {
    level: permission?.level ?? 'read',
    reason: permission?.reason,
    allowedActions: permission?.allowed_actions ?? ['view'],
  };
}

export class EnterpriseMapProjectionAdapter {
  static toCanvasViewModel(projection: EnterpriseMapProjectionResponse, layout: GraphLayoutPreset = 'grid'): CanvasViewModel {
    const nodes = projection.nodes.map((node, index) => this.nodeToCanvas(node, index, layout));
    const nodeIds = new Set(nodes.map((node) => node.id));
    const edges = projection.edges
      .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
      .map((edge) => this.edgeToCanvas(edge));

    const filterCounts = new Map<string, number>();
    nodes.forEach((node) => {
      node.badges.forEach((badge) => filterCounts.set(badge, (filterCounts.get(badge) ?? 0) + 1));
    });

    return {
      nodes,
      edges,
      stats: projection.stats,
      meta: { ...projection.meta, source: 'adapter' },
      filters: Array.from(filterCounts.entries()).map(([label, count]) => ({
        id: label.toLowerCase().replace(/[^a-z0-9]+/g, '-'),
        label,
        count,
      })),
      permissions: projection.permissions,
    };
  }

  static searchResultToNode(result: ExplorerSearchResult, index: number, existingCount: number, layout: GraphLayoutPreset = 'grid'): CanvasNode {
    const position = this.positionFor(existingCount + index, layout);
    return {
      id: result.id,
      label: result.label,
      typeLabel: result.object_type,
      badges: [result.object_type, result.redacted ? 'Redacted' : 'Search result'].filter(Boolean),
      x: position.x,
      y: position.y,
      redacted: Boolean(result.redacted),
      properties: sanitizeProperties(result.redacted, result.properties),
      permissions: normalizePermissions(result.permissions),
      validation: { count: result.validation_issues?.length ?? 0, issues: result.validation_issues ?? [] },
      provenance: { refs: result.provenance_refs ?? [] },
      style: {
        color: result.redacted ? '#991b1b' : '#0f766e',
        shape: result.redacted ? 'shield' : 'rounded',
        opacity: result.redacted ? 0.72 : 1,
        stroke: result.redacted ? '#fecaca' : '#99f6e4',
      },
      source: 'search',
      events: [],
      activeEventCount: 0,
      totalEventCount: 0,
      timeSeries: [],
    };
  }

  static mergeViewModels(base: CanvasViewModel, incoming: CanvasViewModel): CanvasViewModel {
    const nodesById = new Map<string, CanvasNode>();
    [...base.nodes, ...incoming.nodes].forEach((node) => nodesById.set(node.id, node));
    const edgesById = new Map<string, CanvasEdge>();
    [...base.edges, ...incoming.edges].forEach((edge) => edgesById.set(edge.id, edge));
    const nodeIds = new Set(nodesById.keys());
    const nodes = Array.from(nodesById.values());
    const edges = Array.from(edgesById.values()).filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target));
    const filterCounts = new Map<string, number>();
    nodes.forEach((node) => node.badges.forEach((badge) => filterCounts.set(badge, (filterCounts.get(badge) ?? 0) + 1)));
    return {
      ...base,
      nodes,
      edges,
      stats: {
        ...base.stats,
        ...incoming.stats,
        node_count: nodes.length,
        edge_count: edges.length,
        truncated: Boolean(base.stats.truncated || incoming.stats.truncated),
      },
      meta: { ...base.meta, ...incoming.meta, truncated: Boolean(base.meta.truncated || incoming.meta.truncated), source: 'adapter' },
      filters: Array.from(filterCounts.entries()).map(([label, count]) => ({ id: label.toLowerCase().replace(/[^a-z0-9]+/g, '-'), label, count })),
      permissions: incoming.permissions ?? base.permissions,
    };
  }

  static applyLayout(viewModel: CanvasViewModel, layout: GraphLayoutPreset): CanvasViewModel {
    return {
      ...viewModel,
      nodes: viewModel.nodes.map((node, index) => ({ ...node, ...this.positionFor(index, layout) })),
    };
  }

  static detailToNodePatch(detail: ExplorerNodeDetailResponse): Pick<CanvasNode, 'properties' | 'permissions' | 'validation' | 'provenance' | 'redacted'> {
    return {
      redacted: Boolean(detail.redacted || detail.permissions?.level === 'limited'),
      properties: sanitizeProperties(detail.redacted || detail.permissions?.level === 'limited', detail.properties),
      permissions: normalizePermissions(detail.permissions),
      validation: { count: detail.validation_issues?.length ?? 0, issues: detail.validation_issues ?? [] },
      provenance: { refs: detail.provenance_refs ?? [] },
    };
  }

  private static positionFor(index: number, layout: GraphLayoutPreset): { x: number; y: number } {
    const config = LAYOUT_CONFIG[layout];
    return {
      x: config.xStart + (index % config.columns) * config.xSpacing,
      y: config.yStart + Math.floor(index / config.columns) * config.ySpacing,
    };
  }

  private static nodeToCanvas(node: EnterpriseMapProjectionNode, index: number, layout: GraphLayoutPreset): CanvasNode {
    const position = this.positionFor(index, layout);
    const badges = [
      textBadge(node.concept_label),
      textBadge(node.layer),
      textBadge(node.lifecycle_state),
      node.redacted ? 'Redacted' : null,
      node.validation_issues?.length ? 'Needs validation' : null,
    ].filter((badge): badge is string => Boolean(badge));

    return {
      id: node.id,
      label: node.label || node.name || node.id,
      typeLabel: node.concept_label ?? node.concept_type ?? 'Object',
      badges,
      x: position.x,
      y: position.y,
      redacted: Boolean(node.redacted),
      properties: sanitizeProperties(node.redacted, node.properties),
      permissions: normalizePermissions(node.permissions),
      validation: { count: node.validation_issues?.length ?? 0, issues: node.validation_issues ?? [] },
      provenance: { refs: node.provenance_refs ?? [] },
      style: {
        color: node.color ?? (node.redacted ? '#991b1b' : DEFAULT_NODE_COLOR),
        shape: node.shape ?? (node.redacted ? 'shield' : 'rounded'),
        opacity: node.redacted ? 0.68 : 1,
        stroke: node.redacted ? '#fecaca' : node.review_state === 'needs_review' ? '#fbbf24' : '#cbd5e1',
      },
      source: 'projection',
      events: node.events ?? [],
      activeEventCount: activeEvents(node.events).length,
      totalEventCount: node.events?.length ?? 0,
      timeSeries: node.time_series ?? [],
    };
  }

  private static edgeToCanvas(edge: EnterpriseMapProjectionEdge): CanvasEdge {
    return {
      id: edge.id ?? `${edge.source}->${edge.target}:${edge.label}`,
      source: edge.source,
      target: edge.target,
      label: edge.label,
      badges: [textBadge(edge.relationship_type), textBadge(edge.relationship_family), edge.redacted ? 'Redacted' : null]
        .filter((badge): badge is string => Boolean(badge)),
      redacted: Boolean(edge.redacted),
      properties: sanitizeProperties(edge.redacted, edge.properties),
      permissions: normalizePermissions(edge.permissions),
      validation: { count: edge.validation_issues?.length ?? 0, issues: edge.validation_issues ?? [] },
      provenance: { refs: edge.provenance_refs ?? [] },
      style: {
        color: edge.color ?? DEFAULT_EDGE_COLOR,
        weight: edge.weight ?? 1,
        opacity: edge.redacted ? 0.5 : 1,
      },
      events: edge.events ?? [],
      activeEventCount: activeEvents(edge.events).length,
      totalEventCount: edge.events?.length ?? 0,
      timeSeries: edge.time_series ?? [],
      groupedEdge: edge.grouped_edge,
    };
  }
}
