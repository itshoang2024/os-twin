import { CANONICAL_ERROR_CODES, REQUIRED_ONTOLOGY_GRAPH_FEATURE_FLAGS } from './types';
import type {
  ApiErrorResponse,
  EnterpriseMapProjectionResponse,
  ExplorerNodeDetailResponse,
  ExplorerSearchResponse,
  ExplorerSearchResult,
  GraphFixtureKey,
  ObjectSetRef,
  RelationshipTypeRef,
  SearchAroundPreviewRequest,
  SearchAroundPreviewResponse,
  SearchAroundRunResponse,
  GovernanceStateResponse,
  GovernanceRole,
  ChangeSetResponse,
  ApprovalDecisionRequest,
  PublishedVersionRef,
  GraphEvent,
  GraphTimeRange,
} from './types';


const DEFAULT_FEATURE_FLAGS = Object.fromEntries(
  REQUIRED_ONTOLOGY_GRAPH_FEATURE_FLAGS.map((flag) => [flag, true]),
) as Record<(typeof REQUIRED_ONTOLOGY_GRAPH_FEATURE_FLAGS)[number], boolean>;

function permissionSummary(nodes: EnterpriseMapProjectionResponse['nodes'], edges: EnterpriseMapProjectionResponse['edges']): EnterpriseMapProjectionResponse['permissions'] {
  const redactedNodes = nodes.filter((node) => node.redacted || node.permissions?.level === 'limited' || node.permissions?.level === 'blocked').length;
  const redactedEdges = edges.filter((edge) => edge.redacted || edge.permissions?.level === 'limited' || edge.permissions?.level === 'blocked').length;
  return {
    level: redactedNodes || redactedEdges ? 'limited' : 'read',
    redacted_nodes: redactedNodes,
    redacted_edges: redactedEdges,
    notice: redactedNodes || redactedEdges
      ? 'Permission policy redacted sensitive graph details before serialization.'
      : 'Read access granted for visible graph topology.',
  };
}

function withPermissionSummary(projection: EnterpriseMapProjectionResponse): EnterpriseMapProjectionResponse {
  return { ...projection, permissions: permissionSummary(projection.nodes, projection.edges) };
}

const statsFor = (nodes: number, edges: number, truncated = false, events = 0, activeEvents = 0): EnterpriseMapProjectionResponse['stats'] => ({
  source_node_count: nodes,
  source_edge_count: edges,
  node_count: nodes,
  edge_count: edges,
  ontology_candidate_count: 3,
  validation_issue_count: nodes === 0 ? 0 : 1,
  event_count: events,
  active_event_count: activeEvents,
  truncated,
  node_cap: truncated ? nodes : null,
  limit: truncated ? nodes : null,
  warnings: truncated ? ['Response capped at node limit'] : [],
});

const metaFor = (namespace: string, fixture: GraphFixtureKey, truncated = false, timeRange: GraphTimeRange = DEFAULT_TIME_RANGE): EnterpriseMapProjectionResponse['meta'] => ({
  profile_id: `profile-${namespace}`,
  namespace,
  map_state: fixture === 'empty' ? 'empty' : 'live',
  map_source_kind: fixture === 'empty' ? 'none' : 'knowledge_graph',
  source_node_count: 0,
  source_edge_count: 0,
  applied_filters: {},
  applied_group_by: [],
  applied_color_by: 'concept_type',
  generated_at: '2026-06-09T10:00:00.000Z',
  truncated,
  node_cap: truncated ? 18 : null,
  node_limit: truncated ? 18 : null,
  edge_limit: truncated ? 17 : null,
  event_limit: 3,
  next_cursor: truncated ? 'mock-next-cursor' : null,
  limit: truncated ? 18 : null,
  warnings: truncated ? ['Response capped at node limit'] : [],
  fixture,
  active_time_range: timeRange,
  event_truncation_warnings: [],
  feature_flags: DEFAULT_FEATURE_FLAGS,
});


const DEFAULT_TIME_RANGE: GraphTimeRange = { start: '2026-06-09T08:00:00.000Z', end: '2026-06-09T12:00:00.000Z' };

const scenarioEvents: GraphEvent[] = [
  { id: 'event-claim-spike', entity_refs: [{ kind: 'node', id: 'object.claim' }, { kind: 'edge', id: 'rel.policy-claim' }], severity: 'critical', status: 'active', starts_at: '2026-06-09T09:10:00.000Z', ends_at: '2026-06-09T11:30:00.000Z', summary: 'Claim volume breach active in selected operating window.' },
  { id: 'event-policy-review', entity_refs: [{ kind: 'node', id: 'object.policy' }], severity: 'warning', status: 'active', starts_at: '2026-06-09T10:00:00.000Z', summary: 'Policy source mapping review SLA is open.' },
  { id: 'event-customer-resolved', entity_refs: [{ kind: 'node', id: 'object.customer' }], severity: 'info', status: 'resolved', starts_at: '2026-06-08T10:00:00.000Z', ends_at: '2026-06-08T11:00:00.000Z', summary: 'Customer enrichment job resolved before current window.' },
  { id: 'event-boundary-cross', entity_refs: [{ kind: 'edge', id: 'rel.customer-policy' }], severity: 'warning', status: 'active', starts_at: '2026-06-09T07:30:00.000Z', ends_at: '2026-06-09T08:30:00.000Z', summary: 'Ownership sync crossed the window boundary.' },
  { id: 'event-late-outside-window', entity_refs: [{ kind: 'node', id: 'object.agent-session' }], severity: 'info', status: 'active', starts_at: '2026-06-09T14:00:00.000Z', summary: 'Late agent activity outside the default time range.' },
];

function intersectsTimeRange(event: GraphEvent, range: GraphTimeRange): boolean {
  const start = Date.parse(event.starts_at);
  const end = event.ends_at ? Date.parse(event.ends_at) : start;
  return start <= Date.parse(range.end) && end >= Date.parse(range.start);
}

function eventsFor(kind: 'node' | 'edge', id: string, range: GraphTimeRange): GraphEvent[] {
  return scenarioEvents.filter((event) => event.entity_refs.some((ref) => ref.kind === kind && ref.id === id) && intersectsTimeRange(event, range));
}

function withScenario08Data(projection: EnterpriseMapProjectionResponse, range: GraphTimeRange): EnterpriseMapProjectionResponse {
  const nodes = projection.nodes.map((node) => ({
    ...node,
    events: eventsFor('node', node.id, range),
    time_series: node.id.includes('policy') || node.id.includes('claim') ? [{ metric: node.id.includes('claim') ? 'claim_count' : 'policy_updates', unit: 'count', time_range: range, points: [{ timestamp: range.start, value: node.id.includes('claim') ? 42 : 12 }, { timestamp: range.end, value: node.id.includes('claim') ? 71 : 18 }], aggregates: { min: node.id.includes('claim') ? 42 : 12, max: node.id.includes('claim') ? 71 : 18, avg: node.id.includes('claim') ? 56.5 : 15, latest: node.id.includes('claim') ? 71 : 18 } }] : [],
  }));
  const edges = projection.edges.map((edge) => ({
    ...edge,
    events: eventsFor('edge', edge.id ?? `${edge.source}->${edge.target}:${edge.label}`, range),
    time_series: edge.relationship_type === 'generates' ? [{ metric: 'edge_throughput', unit: 'events', time_range: range, points: [{ timestamp: range.start, value: 8 }, { timestamp: range.end, value: 21 }], aggregates: { min: 8, max: 21, avg: 14.5, latest: 21 } }] : [],
  }));
  const eventCount = nodes.reduce((sum, node) => sum + (node.events?.length ?? 0), 0) + edges.reduce((sum, edge) => sum + (edge.events?.length ?? 0), 0);
  const activeCount = nodes.reduce((sum, node) => sum + (node.events?.filter((event) => event.status === 'active').length ?? 0), 0) + edges.reduce((sum, edge) => sum + (edge.events?.filter((event) => event.status === 'active').length ?? 0), 0);
  const warnings = eventCount > 3 ? ['Event list capped at 3 active items for the graph view.'] : [];
  return { ...projection, nodes, edges, stats: { ...projection.stats, event_count: eventCount, active_event_count: activeCount, warnings: [...(projection.stats.warnings ?? []), ...warnings] }, meta: { ...projection.meta, active_time_range: range, event_truncation_warnings: warnings } };
}

export const mockProjectionFixtures: Record<Exclude<GraphFixtureKey, 'error'>, EnterpriseMapProjectionResponse> = {
  empty: {
    nodes: [],
    edges: [],
    stats: statsFor(0, 0),
    meta: metaFor('mock-namespace', 'empty'),
  },
  basic: {
    nodes: [
      {
        id: 'object.customer',
        label: 'Customer Account',
        concept_type: 'object_type',
        concept_label: 'Customer',
        abstraction_level: 'Business Object',
        layer: 'Semantic',
        lifecycle_state: 'active',
        review_state: 'approved',
        family: 'Commercial',
        properties: { owner: 'Data Stewardship', recordCount: 1240, pii: 'masked-by-policy' },
        validation_issues: [],
        provenance_refs: ['doc://crm/schema#customer'],
        color: '#2563eb',
        shape: 'rounded',
        permissions: { level: 'read', allowed_actions: ['view', 'search'] },
      },
      {
        id: 'object.policy',
        label: 'Policy Contract',
        concept_type: 'object_type',
        concept_label: 'Policy',
        abstraction_level: 'Business Object',
        layer: 'Semantic',
        lifecycle_state: 'draft',
        review_state: 'needs_review',
        family: 'Insurance',
        properties: { owner: 'Policy Ops', recordCount: 842, system: 'PAS' },
        validation_issues: ['Missing canonical source mapping'],
        provenance_refs: ['doc://pas/model#policy'],
        color: '#7c3aed',
        shape: 'diamond',
        permissions: { level: 'read', allowed_actions: ['view', 'search'] },
      },
      {
        id: 'object.claim',
        label: 'Claim Event',
        concept_type: 'event_type',
        concept_label: 'Claim',
        abstraction_level: 'Event',
        layer: 'Activation',
        lifecycle_state: 'active',
        review_state: 'approved',
        family: 'Claims',
        properties: { owner: 'Claims Analytics', recordCount: 2310, system: 'Claims Hub' },
        validation_issues: [],
        provenance_refs: ['doc://claims/events#claim'],
        color: '#059669',
        shape: 'circle',
        permissions: { level: 'read', allowed_actions: ['view', 'search'] },
      },
    ],
    edges: [
      {
        id: 'rel.customer-policy',
        source: 'object.customer',
        target: 'object.policy',
        label: 'owns policy',
        relationship_type: 'owns',
        relationship_family: 'ownership',
        weight: 2,
        properties: { cardinality: 'one_to_many' },
        validation_issues: [],
        provenance_refs: ['doc://crm/schema#customer_policy'],
        color: '#64748b',
        permissions: { level: 'read', allowed_actions: ['view'] },
      },
      {
        id: 'rel.policy-claim',
        source: 'object.policy',
        target: 'object.claim',
        label: 'generates claim',
        relationship_type: 'generates',
        relationship_family: 'event',
        weight: 1,
        properties: { cardinality: 'one_to_many' },
        validation_issues: [],
        provenance_refs: ['doc://claims/events#policy_claim'],
        color: '#64748b',
        permissions: { level: 'read', allowed_actions: ['view'] },
      },
    ],
    stats: statsFor(3, 2),
    meta: metaFor('mock-namespace', 'basic'),
  },
  redacted: {
    nodes: [
      {
        id: 'object.customer',
        label: 'Customer Account',
        concept_label: 'Customer',
        layer: 'Semantic',
        properties: { owner: 'Data Stewardship' },
        validation_issues: [],
        provenance_refs: ['doc://crm/schema#customer'],
        permissions: { level: 'read', allowed_actions: ['view'] },
      },
      {
        id: 'object.restricted-person',
        label: 'Restricted Person',
        concept_label: 'Person',
        layer: 'Semantic',
        properties: {},
        redacted: true,
        validation_issues: [],
        provenance_refs: ['redacted://source/hidden'],
        color: '#991b1b',
        permissions: { level: 'limited', reason: 'Sensitive identity data is hidden in mock mode.', allowed_actions: ['view_topology'] },
      },
    ],
    edges: [
      {
        id: 'rel.customer-person',
        source: 'object.customer',
        target: 'object.restricted-person',
        label: 'linked to',
        relationship_type: 'identity_link',
        properties: {},
        redacted: true,
        validation_issues: [],
        provenance_refs: ['redacted://edge/hidden'],
        permissions: { level: 'limited', reason: 'Relationship details hidden.', allowed_actions: ['view_topology'] },
      },
    ],
    stats: statsFor(2, 1),
    meta: metaFor('mock-namespace', 'redacted'),
  },
  large: {
    nodes: Array.from({ length: 18 }, (_, index) => ({
      id: `object.large-${index + 1}`,
      label: `Enterprise Object ${index + 1}`,
      concept_label: index % 2 ? 'Domain Object' : 'Event Object',
      layer: index % 3 === 0 ? 'Activation' : 'Semantic',
      family: index % 2 ? 'Operations' : 'Commercial',
      properties: { owner: `Team ${index + 1}`, recordCount: 100 + index },
      validation_issues: index === 4 ? ['Orphaned relationship candidate'] : [],
      provenance_refs: [`doc://large/${index + 1}`],
      permissions: { level: 'read' as const, allowed_actions: ['view'] },
    })),
    edges: Array.from({ length: 17 }, (_, index) => ({
      id: `rel.large-${index + 1}`,
      source: `object.large-${index + 1}`,
      target: `object.large-${index + 2}`,
      label: 'depends on',
      relationship_type: 'depends_on',
      properties: { weight: index + 1 },
      validation_issues: [],
      provenance_refs: [`doc://large-edge/${index + 1}`],
      permissions: { level: 'read' as const, allowed_actions: ['view'] },
    })),
    stats: statsFor(18, 17, true),
    meta: metaFor('mock-namespace', 'large', true),
  },
};

export const mockSearchResults: ExplorerSearchResponse = {
  results: [
    {
      id: 'object.agent-session',
      label: 'Agent Session',
      object_type: 'Operational Event',
      description: 'A captured execution session with prompts, tools, and outcomes.',
      properties: { owner: 'Agent Platform', retention: '30 days' },
      provenance_refs: ['doc://agent/session'],
      validation_issues: [],
      permissions: { level: 'read', allowed_actions: ['view', 'add_to_graph'] },
    },
    {
      id: 'object.knowledge-namespace',
      label: 'Knowledge Namespace',
      object_type: 'Knowledge Object',
      description: 'A curated knowledge container with import, query, and ontology metadata.',
      properties: { owner: 'Knowledge Ops', profileVersion: '1.0.0' },
      provenance_refs: ['doc://knowledge/namespace'],
      validation_issues: ['Needs relationship coverage review'],
      permissions: { level: 'read', allowed_actions: ['view', 'add_to_graph'] },
    },
    {
      id: 'object.restricted-person',
      label: 'Restricted Person',
      object_type: 'Sensitive Object',
      description: 'Topology-only object. Properties are redacted.',
      redacted: true,
      properties: {},
      provenance_refs: ['redacted://search/result'],
      validation_issues: [],
      permissions: { level: 'limited', reason: 'Sensitive data hidden.', allowed_actions: ['view_topology', 'add_to_graph'] },
    },
  ],
  meta: { query: 'mock', truncated: false, limit: 20, filters: {}, warnings: [], fixture: 'search-results' },
};

export const mockSearchNoResults: ExplorerSearchResponse = {
  results: [],
  meta: { query: 'no-match', truncated: false, limit: 20, filters: {}, warnings: [], fixture: 'search-no-results' },
};

export const mockFilteredSearchResults: ExplorerSearchResponse = {
  results: mockSearchResults.results.filter((result) => result.object_type === 'Knowledge Object'),
  meta: { query: 'namespace', truncated: false, limit: 20, filters: { object_type: ['Knowledge Object'] }, warnings: [], fixture: 'search-filtered-results' },
};

export const mockExpandResponse: EnterpriseMapProjectionResponse = {
  nodes: [
    mockProjectionFixtures.basic.nodes[0],
    {
      id: 'object.agent-session',
      label: 'Agent Session',
      concept_type: 'event_type',
      concept_label: 'Agent Session',
      abstraction_level: 'Event',
      layer: 'Activation',
      lifecycle_state: 'active',
      review_state: 'approved',
      family: 'Agent Platform',
      properties: { owner: 'Agent Platform', retention: '30 days' },
      validation_issues: [],
      provenance_refs: ['doc://agent/session'],
      color: '#0f766e',
      permissions: { level: 'read', allowed_actions: ['view'] },
    },
  ],
  edges: [{ id: 'rel.customer-agent-session', source: 'object.customer', target: 'object.agent-session', label: 'observed in', relationship_type: 'observed_in', relationship_family: 'provenance', weight: 1, properties: {}, validation_issues: [], provenance_refs: ['doc://agent/session'], permissions: { level: 'read', allowed_actions: ['view'] } }],
  stats: statsFor(2, 1),
  meta: metaFor('mock-namespace', 'basic'),
};

export const mockNodeDetails: Record<string, ExplorerNodeDetailResponse> = {
  'object.customer': {
    id: 'object.customer',
    label: 'Customer Account',
    properties: { owner: 'Data Stewardship', recordCount: 1240, pii: 'masked-by-policy' },
    relationships: [{ id: 'rel.customer-policy', label: 'owns policy', target: 'object.policy', direction: 'out' }],
    validation_issues: [],
    provenance_refs: ['doc://crm/schema#customer'],
    permissions: { level: 'read', allowed_actions: ['view', 'search'] },
  },
  'object.restricted-person': {
    id: 'object.restricted-person',
    label: 'Restricted Person',
    properties: {},
    relationships: [],
    validation_issues: [],
    provenance_refs: ['redacted://source/hidden'],
    permissions: { level: 'limited', reason: 'Sensitive identity data is hidden in mock mode.', allowed_actions: ['view_topology'] },
  },
};

export const canonicalErrorFixtures: Record<(typeof CANONICAL_ERROR_CODES)[number], ApiErrorResponse> = Object.fromEntries(
  CANONICAL_ERROR_CODES.map((code) => [
    code,
    {
      error: {
        code,
        message: {
          NOT_FOUND: 'Requested graph resource was not found.',
          UNAUTHORIZED: 'Sign in before opening this ontology graph.',
          FORBIDDEN: 'You do not have permission to perform this graph action.',
          VALIDATION_FAILED: 'Graph request validation failed.',
          CONFLICT: 'Graph state changed while applying this action.',
          GRAPH_TOO_LARGE: 'Graph result exceeds the configured canvas cap.',
          TIMEOUT: 'Graph query timed out before completion.',
          REDACTED: 'Sensitive graph fields were redacted by policy.',
          CAP_EXCEEDED: 'Requested traversal cap was exceeded.',
          INVALID_TRAVERSAL: 'Traversal definition is invalid for this object set.',
          SCHEMA_INCOMPATIBLE: 'Projection schema is incompatible with the active ontology profile.',
          FEATURE_DISABLED: 'Ontology Graph Builder backend is not enabled yet.',
        }[code],
        validation_issues: code === 'VALIDATION_FAILED' ? ['filters.badges must be an array'] : undefined,
      },
      request_id: `mock-${code.toLowerCase().replace(/_/g, '-')}`,
    },
  ]),
) as Record<(typeof CANONICAL_ERROR_CODES)[number], ApiErrorResponse>;

export const mockErrorFixtures: Record<'projection' | 'search' | 'detail' | 'timeout' | 'invalidExpand', ApiErrorResponse> = {
  projection: canonicalErrorFixtures.FEATURE_DISABLED,
  search: canonicalErrorFixtures.VALIDATION_FAILED,
  detail: canonicalErrorFixtures.NOT_FOUND,
  timeout: canonicalErrorFixtures.TIMEOUT,
  invalidExpand: { error: { ...canonicalErrorFixtures.NOT_FOUND.error, message: 'Requested node was not found.', validation_issues: ['node_id does not exist'] }, request_id: 'mock-expand-invalid' },
};

export function getProjectionFixture(key: GraphFixtureKey, namespace: string, timeRange: GraphTimeRange = DEFAULT_TIME_RANGE): EnterpriseMapProjectionResponse {
  if (key === 'error') {
    throw Object.assign(new Error(mockErrorFixtures.projection.error.message), { data: mockErrorFixtures.projection });
  }
  const fixture = mockProjectionFixtures[key];
  return withPermissionSummary(withScenario08Data({
    ...fixture,
    nodes: fixture.nodes.map((node) => ({ ...node })),
    edges: fixture.edges.map((edge) => ({ ...edge })),
    stats: { ...fixture.stats },
    meta: {
      ...fixture.meta,
      namespace,
      source_node_count: fixture.stats.source_node_count,
      source_edge_count: fixture.stats.source_edge_count,
      fixture: key,
      active_time_range: timeRange,
    },
  }, timeRange));
}

export function searchMockObjects(query: string): ExplorerSearchResponse {
  const term = query.trim().toLowerCase();
  const results: ExplorerSearchResult[] = term
    ? mockSearchResults.results.filter((result) => `${result.label} ${result.object_type} ${result.description}`.toLowerCase().includes(term))
    : mockSearchResults.results;
  return { results, meta: { ...mockSearchResults.meta, query, truncated: false, limit: 20, filters: {}, warnings: [] } };
}


export const mockRelationshipTypes: RelationshipTypeRef[] = [
  { id: 'owns', label: 'owns policy', source_types: ['Customer', 'Customer Account'], target_types: ['Policy', 'Policy Contract'] },
  { id: 'generates', label: 'generates claim', source_types: ['Policy', 'Policy Contract'], target_types: ['Claim', 'Claim Event'] },
  { id: 'observed_in', label: 'observed in', source_types: ['Customer', 'Customer Account'], target_types: ['Agent Session', 'Operational Event'] },
  { id: 'retired_identity_link', label: 'retired identity link', source_types: ['Restricted Person'], target_types: ['Customer'], retired: true },
];

export const mockSavedObjectSets: ObjectSetRef[] = [
  {
    id: 'set-key-accounts',
    name: 'Key account objects',
    description: 'Saved mock object set with Customer and Policy nodes.',
    object_ids: ['object.customer', 'object.policy'],
    object_type_counts: { Customer: 1, Policy: 1 },
    source: 'saved',
    created_at: '2026-06-09T00:00:00.000Z',
  },
  {
    id: 'set-claims-review',
    name: 'Claims review set',
    description: 'Saved mock object set for compare and inbound traversal tests.',
    object_ids: ['object.policy', 'object.claim'],
    object_type_counts: { Policy: 1, Claim: 1 },
    source: 'saved',
    created_at: '2026-06-09T00:00:00.000Z',
    warnings: ['object.deleted-demo was omitted because it no longer exists'],
  },
];

const basicNodeById = new Map(mockProjectionFixtures.basic.nodes.map((node) => [node.id, node]));
const searchNodeById = new Map(mockSearchResults.results.map((result) => [result.id, result]));

export function makeMockObjectSet(name: string, objectIds: string[], source: ObjectSetRef['source']): ObjectSetRef {
  const uniqueIds = Array.from(new Set(objectIds));
  const counts: Record<string, number> = {};
  uniqueIds.forEach((id) => {
    const projectionNode = basicNodeById.get(id);
    const searchNode = searchNodeById.get(id);
    const label = projectionNode?.concept_label ?? searchNode?.object_type ?? 'Object';
    counts[label] = (counts[label] ?? 0) + 1;
  });
  return {
    id: `set-${source}-${uniqueIds.join('-').replace(/[^a-z0-9]+/gi, '-').toLowerCase() || 'empty'}`,
    name,
    object_ids: uniqueIds,
    object_type_counts: counts,
    source,
    created_at: new Date(0).toISOString(),
    warnings: uniqueIds.length > 6 ? ['Object set creation capped to the first 6 objects in mock mode'] : [],
  };
}

export function compareMockObjectSets(base: ObjectSetRef, candidate: ObjectSetRef) {
  const baseIds = new Set(base.object_ids);
  const candidateIds = new Set(candidate.object_ids);
  const added_ids = candidate.object_ids.filter((id) => !baseIds.has(id));
  const removed_ids = base.object_ids.filter((id) => !candidateIds.has(id));
  const overlap_ids = candidate.object_ids.filter((id) => baseIds.has(id));
  return { base_id: base.id, candidate_id: candidate.id, added_count: added_ids.length, removed_count: removed_ids.length, overlap_count: overlap_ids.length, added_ids, removed_ids, overlap_ids };
}

function traversalIssues(request: SearchAroundPreviewRequest): SearchAroundPreviewResponse['validation_issues'] {
  const issues: SearchAroundPreviewResponse['validation_issues'] = [];
  request.steps.forEach((step, index) => {
    const relationship = mockRelationshipTypes.find((item) => item.id === step.relationship_type_id);
    if (!relationship) issues.push({ code: 'RELATIONSHIP_TYPE_NOT_FOUND', message: 'Select a valid relationship type.', step_index: index, severity: 'error' });
    if (relationship?.retired) issues.push({ code: 'RELATIONSHIP_TYPE_RETIRED', message: `${relationship.label} is retired and cannot be traversed.`, step_index: index, severity: 'error' });
    if (relationship?.id === 'generates' && step.direction === 'inbound') issues.push({ code: 'INCOMPATIBLE_DIRECTION', message: 'Inbound generates traversal is incompatible with this starting object set in mock mode.', step_index: index, severity: 'error' });
  });
  if (request.steps.length === 0) issues.push({ code: 'NO_TRAVERSAL_STEPS', message: 'Add at least one traversal step.', severity: 'error' });
  return issues;
}

export function previewMockSearchAround(request: SearchAroundPreviewRequest): SearchAroundPreviewResponse {
  const issues = traversalIssues(request);
  if (issues.some((issue) => issue.severity === 'error')) {
    return { counts_by_object_type: {}, total_count: 0, edge_count: 0, truncated: false, limit: request.limit ?? 50, warnings: [], validation_issues: issues };
  }
  const multiStep = request.steps.length > 1;
  const total = multiStep ? 3 : 2;
  const limit = request.limit ?? 50;
  const truncated = total > limit || request.steps.some((step) => step.relationship_type_id === 'observed_in');
  return {
    counts_by_object_type: multiStep ? { Policy: 1, Claim: 1, 'Agent Session': 1 } : { Policy: 1, Claim: 1 },
    total_count: truncated ? Math.min(total, limit) : total,
    edge_count: multiStep ? 2 : 1,
    truncated,
    timeout_ms: truncated ? 900 : undefined,
    limit,
    warnings: truncated ? ['Preview capped before full traversal materialization. Refine filters or lower depth.'] : [],
    validation_issues: [],
  };
}

export function runMockSearchAround(request: SearchAroundPreviewRequest, namespace: string): SearchAroundRunResponse {
  const preview = previewMockSearchAround(request);
  if (preview.validation_issues.some((issue) => issue.severity === 'error')) {
    throw Object.assign(new Error('Traversal validation failed'), { data: { error: { code: 'VALIDATION_FAILED', message: preview.validation_issues[0]?.message ?? 'Traversal validation failed' }, validation_issues: preview.validation_issues, request_id: 'mock-search-around-invalid' } });
  }
  const nodes = [mockProjectionFixtures.basic.nodes[0], mockProjectionFixtures.basic.nodes[1], mockProjectionFixtures.basic.nodes[2], mockExpandResponse.nodes[1]];
  const edges = [...mockProjectionFixtures.basic.edges, mockExpandResponse.edges[0]];
  const truncated = preview.truncated;
  const resultSet = makeMockObjectSet('Traversal result', nodes.map((node) => node.id), 'traversal');
  return {
    nodes,
    edges,
    stats: { ...statsFor(nodes.length, edges.length, truncated), warnings: preview.warnings },
    meta: { ...metaFor(namespace, truncated ? 'large' : 'basic', truncated), warnings: preview.warnings },
    traversal: { object_set_id: request.object_set_id, step_count: request.steps.length, result_object_set: resultSet, truncated, warnings: preview.warnings, validation_issues: [] },
  };
}


const governanceTimestamps = {
  created: '2026-06-09T08:00:00.000Z',
  submitted: '2026-06-09T08:15:00.000Z',
  approved: '2026-06-09T08:30:00.000Z',
  published: '2026-06-09T08:45:00.000Z',
};

const baseIssues = [
  { id: 'issue-source-mapping', severity: 'error' as const, category: 'evidence' as const, code: 'SOURCE_MAPPING_REQUIRED', message: 'Policy Contract is missing a canonical source mapping evidence link.', target: { kind: 'node' as const, id: 'object.policy', property: 'sourceMapping' }, blocking: true, suggested_fix: 'Attach evidence://pas/policy-source-map before submit.' },
  { id: 'issue-lineage-review', severity: 'warning' as const, category: 'lineage' as const, code: 'LINEAGE_REVIEW', message: 'Claim Event downstream lineage changed and needs approver review.', target: { kind: 'edge' as const, id: 'rel.policy-claim' }, blocking: false, suggested_fix: 'Review downstream consumers before publish.' },
];

const baseDiff = [
  { id: 'diff-policy-owner', kind: 'property' as const, action: 'update' as const, label: 'Policy Contract.owner', before: 'Policy Ops', after: 'Policy Governance' },
  { id: 'diff-source-map', kind: 'evidence' as const, action: 'create' as const, label: 'Canonical source evidence', before: 'missing', after: 'evidence://pas/policy-source-map' },
  { id: 'diff-claim-edge', kind: 'edge' as const, action: 'update' as const, label: 'Policy Contract → Claim Event lineage', before: 'unreviewed', after: 'governed downstream lineage' },
];

function initialChangeset(namespace: string): ChangeSetResponse {
  return {
    id: `cs-${namespace}-governance-06`,
    state: 'draft',
    author: { id: 'steward-1', name: 'Dana Steward' },
    summary: 'Govern Policy Contract ownership, source mapping, and downstream Claim lineage.',
    validation_issues: baseIssues,
    affected_objects: ['object.policy', 'object.claim'],
    affected_types: ['Policy', 'Claim'],
    diff: baseDiff,
    created_at: governanceTimestamps.created,
    updated_at: governanceTimestamps.created,
    base_version_id: 'version-3',
    stale: false,
    required_evidence_missing: true,
  };
}

const governanceByNamespace = new Map<string, GovernanceStateResponse>();

function cloneGovernance<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

export function getMockGovernanceState(namespace: string): GovernanceStateResponse {
  if (!governanceByNamespace.has(namespace)) {
    const changeset = initialChangeset(namespace);
    governanceByNamespace.set(namespace, {
      changeset,
      approval_queue: [],
      audit_events: [
        { id: 'audit-draft-created', actor: 'Dana Steward', action: 'changeset.created', entity: changeset.id, timestamp: governanceTimestamps.created, diff: changeset.diff.slice(0, 1), evidence_refs: ['evidence://pas/policy-source-map'] },
        { id: 'audit-validation-started', actor: 'Validator', action: 'validation.failed', entity: 'object.policy', timestamp: '2026-06-09T08:02:00.000Z', diff: [], evidence_refs: [] },
      ],
      lineage: [
        { entity_id: 'object.policy', upstream: ['source://pas/policies', 'doc://pas/model#policy'], downstream: ['object.claim', 'report://loss-ratio'], source_refs: ['evidence://pas/policy-source-map'] },
        { entity_id: 'object.claim', upstream: ['object.policy'], downstream: ['workflow://claims-triage'], source_refs: ['doc://claims/events#claim'] },
      ],
      versions: [
        { id: 'version-3', label: 'v3 current published', created_at: '2026-06-08T12:00:00.000Z', changeset_id: 'cs-previous-3', immutable: true },
        { id: 'version-2', label: 'v2 historical', created_at: '2026-06-07T12:00:00.000Z', changeset_id: 'cs-previous-2', immutable: true },
      ],
      current_version_id: 'version-3',
    });
  }
  return cloneGovernance(governanceByNamespace.get(namespace)!);
}

function mutateGovernance(namespace: string, updater: (state: GovernanceStateResponse) => void): GovernanceStateResponse {
  const state = getMockGovernanceState(namespace);
  updater(state);
  governanceByNamespace.set(namespace, state);
  return cloneGovernance(state);
}

export function validateMockChangeset(namespace: string): GovernanceStateResponse {
  return mutateGovernance(namespace, (state) => {
    state.changeset.validation_issues = state.changeset.validation_issues.filter((issue) => issue.severity !== 'error');
    state.changeset.required_evidence_missing = false;
    state.changeset.updated_at = governanceTimestamps.submitted;
    state.audit_events.unshift({ id: 'audit-validation-passed', actor: 'Validator', action: 'validation.passed', entity: state.changeset.id, timestamp: governanceTimestamps.submitted, diff: [], evidence_refs: ['evidence://pas/policy-source-map'] });
  });
}

export function submitMockChangeset(namespace: string, role: GovernanceRole): GovernanceStateResponse {
  return mutateGovernance(namespace, (state) => {
    if (role !== 'steward') throw Object.assign(new Error('Only stewards can submit changesets'), { data: { error: { code: 'PERMISSION_DENIED', message: 'Only stewards can submit changesets' } } });
    if (state.changeset.state !== 'draft' && state.changeset.state !== 'rejected') throw Object.assign(new Error('Invalid transition'), { data: { error: { code: 'INVALID_STATE_TRANSITION', message: 'Only draft or rejected changesets can be submitted' } } });
    if (state.changeset.validation_issues.some((issue) => issue.blocking)) throw Object.assign(new Error('Validation failed'), { data: { error: { code: 'VALIDATION_FAILED', message: 'Resolve blocking validation issues before submit' } } });
    state.changeset.state = 'submitted';
    state.changeset.submitted_at = governanceTimestamps.submitted;
    state.changeset.updated_at = governanceTimestamps.submitted;
    state.approval_queue = [state.changeset];
    state.audit_events.unshift({ id: 'audit-submitted', actor: 'Dana Steward', action: 'changeset.submitted', entity: state.changeset.id, timestamp: governanceTimestamps.submitted, diff: state.changeset.diff, evidence_refs: ['evidence://pas/policy-source-map'] });
  });
}

export function decideMockApproval(namespace: string, role: GovernanceRole, request: ApprovalDecisionRequest): GovernanceStateResponse {
  return mutateGovernance(namespace, (state) => {
    if (role !== 'approver') throw Object.assign(new Error('Approver role required'), { data: { error: { code: 'PERMISSION_DENIED', message: 'Approver role required' } } });
    if (state.changeset.author.id === 'approver-1') throw Object.assign(new Error('Self approval blocked'), { data: { error: { code: 'SELF_APPROVAL_FORBIDDEN', message: 'Approvers cannot approve their own changeset' } } });
    if (state.changeset.state !== 'submitted') throw Object.assign(new Error('Invalid transition'), { data: { error: { code: 'INVALID_STATE_TRANSITION', message: 'Only submitted changesets can be approved or rejected' } } });
    if (request.decision === 'reject' && !request.comment.trim()) throw Object.assign(new Error('Reject comment required'), { data: { error: { code: 'COMMENT_REQUIRED', message: 'Reject decisions require a comment' } } });
    state.changeset.state = request.decision === 'approve' ? 'approved' : 'rejected';
    state.changeset.updated_at = request.decision === 'approve' ? governanceTimestamps.approved : '2026-06-09T08:31:00.000Z';
    if (request.decision === 'approve') state.changeset.approved_at = governanceTimestamps.approved;
    if (request.decision === 'reject') { state.changeset.rejected_at = '2026-06-09T08:31:00.000Z'; state.changeset.rejection_comment = request.comment; }
    state.approval_queue = [];
    state.audit_events.unshift({ id: `audit-${request.decision}`, actor: 'Alex Approver', action: `changeset.${request.decision}d`, entity: state.changeset.id, timestamp: state.changeset.updated_at, diff: state.changeset.diff, evidence_refs: request.comment ? [`comment://${request.comment}`] : ['approval://comment-recorded'] });
  });
}

export function publishMockChangeset(namespace: string, role: GovernanceRole, simulateConflict = false): GovernanceStateResponse {
  return mutateGovernance(namespace, (state) => {
    if (role !== 'steward') throw Object.assign(new Error('Only stewards can publish'), { data: { error: { code: 'PERMISSION_DENIED', message: 'Only stewards can publish approved changesets' } } });
    if (state.changeset.state !== 'approved') throw Object.assign(new Error('Invalid transition'), { data: { error: { code: 'INVALID_STATE_TRANSITION', message: 'Only approved changesets can be published' } } });
    if (state.changeset.stale || simulateConflict) throw Object.assign(new Error('Concurrent publish conflict'), { data: { error: { code: 'STALE_CHANGESET_CONFLICT', message: 'This changeset is stale because another version was published. Rebase before publishing.' } } });
    const version: PublishedVersionRef = { id: `version-${state.versions.length + 2}`, label: `v${state.versions.length + 2} published from Scenario 06`, created_at: governanceTimestamps.published, changeset_id: state.changeset.id, immutable: true };
    state.changeset.state = 'published';
    state.changeset.published_at = governanceTimestamps.published;
    state.changeset.version_id = version.id;
    state.changeset.updated_at = governanceTimestamps.published;
    state.versions = [version, ...state.versions];
    state.current_version_id = version.id;
    state.audit_events.unshift({ id: 'audit-published', actor: 'Dana Steward', action: 'version.published', entity: version.id, timestamp: governanceTimestamps.published, diff: state.changeset.diff, evidence_refs: ['evidence://pas/policy-source-map'] });
  });
}

export function revertMockVersion(namespace: string, role: GovernanceRole, targetVersionId: string): GovernanceStateResponse {
  return mutateGovernance(namespace, (state) => {
    if (role !== 'steward') throw Object.assign(new Error('Only stewards can revert'), { data: { error: { code: 'PERMISSION_DENIED', message: 'Only stewards can create revert versions' } } });
    const version: PublishedVersionRef = { id: `version-revert-${state.versions.length + 1}`, label: `Revert to ${targetVersionId}`, created_at: '2026-06-09T09:00:00.000Z', changeset_id: `revert-${targetVersionId}`, immutable: true };
    state.versions = [version, ...state.versions];
    state.current_version_id = version.id;
    state.audit_events.unshift({ id: 'audit-revert-created', actor: 'Dana Steward', action: 'version.revert_created', entity: version.id, timestamp: version.created_at, diff: [{ id: 'diff-revert', kind: 'property', action: 'update', label: `Revert created from ${targetVersionId}`, before: state.current_version_id, after: version.id }], evidence_refs: [`version://${targetVersionId}`] });
  });
}
