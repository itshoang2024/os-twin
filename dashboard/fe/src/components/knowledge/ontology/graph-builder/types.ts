import type {
  EnterpriseMapApiErrorResponse,
  EnterpriseMapEdge,
  EnterpriseMapNode,
  EnterpriseMapPermission,
  EnterpriseMapProjectionResponse as GeneratedEnterpriseMapProjectionResponse,
  ExplorerNodeDetailResponse as GeneratedExplorerNodeDetailResponse,
  ExplorerSearchResponse as GeneratedExplorerSearchResponse,
  ExplorerSearchResult as GeneratedExplorerSearchResult,
} from '@/types/ontology-map.generated';

export type ApiErrorResponse = EnterpriseMapApiErrorResponse;

export const CANONICAL_ERROR_CODES = [
  'NOT_FOUND',
  'UNAUTHORIZED',
  'FORBIDDEN',
  'VALIDATION_FAILED',
  'CONFLICT',
  'GRAPH_TOO_LARGE',
  'TIMEOUT',
  'REDACTED',
  'CAP_EXCEEDED',
  'INVALID_TRAVERSAL',
  'SCHEMA_INCOMPATIBLE',
  'FEATURE_DISABLED',
] as const;

export type CanonicalErrorCode = typeof CANONICAL_ERROR_CODES[number];

export const REQUIRED_ONTOLOGY_GRAPH_FEATURE_FLAGS = [
  'ontologyGraphBuilder',
  'ontologyGraphSearchAround',
  'ontologyGraphInstanceAuthoring',
  'ontologyGraphGovernance',
  'ontologyGraphTemplates',
  'ontologyGraphEvents',
  'ontologyGraphSharing',
] as const;

export type RequiredOntologyGraphFeatureFlag = typeof REQUIRED_ONTOLOGY_GRAPH_FEATURE_FLAGS[number];

export interface PermissionSummary {
  level: PermissionLevel;
  redacted_nodes: number;
  redacted_edges: number;
  notice: string;
}

export type GraphMode = 'explore' | 'validate' | 'provenance';
export type GraphLayoutPreset = 'grid' | 'layered' | 'compact';
export type GraphFixtureKey = 'empty' | 'basic' | 'redacted' | 'large' | 'error';
export type PermissionLevel = EnterpriseMapPermission['level'];

export type GraphEventSeverity = 'info' | 'warning' | 'critical';
export type GraphEventStatus = 'active' | 'resolved' | 'acknowledged';

export interface GraphTimeRange {
  start: string;
  end: string;
}

export interface GraphEvent {
  id: string;
  entity_refs: { kind: 'node' | 'edge'; id: string }[];
  severity: GraphEventSeverity;
  status: GraphEventStatus;
  starts_at: string;
  ends_at?: string;
  summary: string;
}

export interface TimeSeriesSummary {
  metric: string;
  time_range: GraphTimeRange;
  points?: { timestamp: string; value: number }[];
  aggregates?: { min?: number; max?: number; avg?: number; latest?: number };
  unit?: string;
  truncated?: boolean;
}

export interface GraphGroup {
  id: string;
  label: string;
  rule: { kind: 'selected' | 'type' | 'property'; property?: string; value?: string };
  member_ids: string[];
  aggregate_stats: { member_count: number; redacted_count: number; event_count: number; active_event_count: number };
  warnings?: string[];
}

export interface GroupedEdge {
  id: string;
  label: string;
  source: string;
  target: string;
  contained_edge_ids: string[];
  contained_object_ids: string[];
  aggregate_labels: string[];
  redacted_count?: number;
  warnings?: string[];
}

export interface EnterpriseMapProjectionNode extends Omit<EnterpriseMapNode, 'name' | 'score' | 'properties' | 'validation_issues' | 'provenance_refs' | 'series_refs' | 'flow_refs' | 'simulation_refs' | 'prerequisites'> {
  /** UI-only redaction marker for mock/adapter view-models; not part of generated backend EnterpriseMapNode. */
  redacted?: boolean;
  /** UI-only permission summary consumed by the canvas adapter; not part of generated backend EnterpriseMapNode. */
  permissions?: EnterpriseMapPermission;
  /** UI-only style hints consumed after projection adaptation; not part of generated backend EnterpriseMapNode. */
  style?: Record<string, unknown>;
  name?: string;
  score?: number;
  properties?: Record<string, unknown>;
  validation_issues?: string[];
  provenance_refs?: string[];
  series_refs?: string[];
  flow_refs?: string[];
  simulation_refs?: string[];
  prerequisites?: string[];
  events?: GraphEvent[];
  time_series?: TimeSeriesSummary[];
}

export interface EnterpriseMapProjectionEdge extends Omit<EnterpriseMapEdge, 'weight' | 'properties' | 'validation_issues' | 'provenance_refs' | 'series_refs' | 'flow_refs' | 'simulation_refs' | 'prerequisites'> {
  /** UI-only redaction marker for mock/adapter view-models; not part of generated backend EnterpriseMapEdge. */
  redacted?: boolean;
  /** UI-only permission summary consumed by the canvas adapter; not part of generated backend EnterpriseMapEdge. */
  permissions?: EnterpriseMapPermission;
  id?: string;
  weight?: number;
  properties?: Record<string, unknown>;
  validation_issues?: string[];
  provenance_refs?: string[];
  series_refs?: string[];
  flow_refs?: string[];
  simulation_refs?: string[];
  prerequisites?: string[];
  events?: GraphEvent[];
  time_series?: TimeSeriesSummary[];
  grouped_edge?: GroupedEdge;
}

export interface EnterpriseMapProjectionResponse extends Omit<GeneratedEnterpriseMapProjectionResponse, 'nodes' | 'edges' | 'stats' | 'meta' | 'layers' | 'abstraction_levels'> {
  nodes: EnterpriseMapProjectionNode[];
  edges: EnterpriseMapProjectionEdge[];
  stats: GeneratedEnterpriseMapProjectionResponse['stats'] & {
    limit?: number | null;
    warnings?: string[];
  };
  layers?: GeneratedEnterpriseMapProjectionResponse['layers'];
  abstraction_levels?: GeneratedEnterpriseMapProjectionResponse['abstraction_levels'];
  meta: GeneratedEnterpriseMapProjectionResponse['meta'] & {
    namespace: string;
    generated_at: string;
    node_limit?: number | null;
    edge_limit?: number | null;
    event_limit?: number | null;
    next_cursor?: string | null;
    map_state: 'live' | 'empty';
    map_source_kind: 'knowledge_graph' | 'none';
    limit?: number | null;
    warnings?: string[];
    feature_flags?: Record<RequiredOntologyGraphFeatureFlag, boolean>;
    fixture?: GraphFixtureKey;
    active_time_range?: GraphTimeRange;
    event_truncation_warnings?: string[];
    groups?: GraphGroup[];
    grouped_edges?: GroupedEdge[];
  };
  permissions?: PermissionSummary;
}

export type ExplorerSearchResult = GeneratedExplorerSearchResult;
export type ExplorerSearchResponse = GeneratedExplorerSearchResponse;
export type ExplorerNodeDetailResponse = GeneratedExplorerNodeDetailResponse;

export interface CanvasNode {
  id: string;
  label: string;
  typeLabel: string;
  badges: string[];
  x: number;
  y: number;
  redacted: boolean;
  properties: Record<string, unknown>;
  permissions: { level: PermissionLevel; reason?: string; allowedActions: string[] };
  validation: { count: number; issues: string[] };
  provenance: { refs: string[] };
  style: { color: string; shape: string; opacity: number; stroke: string };
  source: 'projection' | 'search';
  events: GraphEvent[];
  activeEventCount: number;
  totalEventCount: number;
  timeSeries: TimeSeriesSummary[];
  group?: GraphGroup;
}

export interface CanvasEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  badges: string[];
  redacted: boolean;
  properties: Record<string, unknown>;
  permissions: { level: PermissionLevel; reason?: string; allowedActions: string[] };
  validation: { count: number; issues: string[] };
  provenance: { refs: string[] };
  style: { color: string; weight: number; opacity: number };
  events: GraphEvent[];
  activeEventCount: number;
  totalEventCount: number;
  timeSeries: TimeSeriesSummary[];
  groupedEdge?: GroupedEdge;
}

export interface CanvasViewModel {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  stats: EnterpriseMapProjectionResponse['stats'];
  meta: EnterpriseMapProjectionResponse['meta'] & { source: 'adapter' };
  filters: { id: string; label: string; count: number }[];
  permissions?: PermissionSummary;
}

export interface GraphBuilderFilterState {
  badges: string[];
  timeRange?: GraphTimeRange;
}


export type GraphSelection =
  | { kind: 'node'; id: string }
  | { kind: 'edge'; id: string }
  | null;


export type ObjectSetSource = 'selected' | 'search' | 'saved' | 'traversal';
export type TraversalDirection = 'outbound' | 'inbound' | 'either';

export interface ObjectSetRef {
  id: string;
  name: string;
  description?: string;
  object_ids: string[];
  object_type_counts: Record<string, number>;
  source: ObjectSetSource;
  created_at: string;
  warnings?: string[];
}

export interface ObjectSetCreateRequest {
  name: string;
  object_ids: string[];
  source: ObjectSetSource;
}

export interface ObjectSetCreateResponse {
  object_set: ObjectSetRef;
}

export interface ObjectSetCompareSummary {
  base_id: string;
  candidate_id: string;
  added_count: number;
  removed_count: number;
  overlap_count: number;
  added_ids: string[];
  removed_ids: string[];
  overlap_ids: string[];
}

export interface RelationshipTypeRef {
  id: string;
  label: string;
  source_types: string[];
  target_types: string[];
  retired?: boolean;
}

export interface SearchAroundStepRequest {
  relationship_type_id: string;
  direction: TraversalDirection;
  filters?: Record<string, unknown>;
}

export interface SearchAroundPreviewRequest {
  object_set_id: string;
  steps: SearchAroundStepRequest[];
  limit?: number;
}

export interface TraversalValidationIssue {
  code: string;
  message: string;
  step_index?: number;
  severity: 'error' | 'warning';
}

export interface SearchAroundPreviewResponse {
  counts_by_object_type: Record<string, number>;
  total_count: number;
  edge_count: number;
  truncated: boolean;
  timeout_ms?: number;
  limit?: number;
  warnings: string[];
  validation_issues: TraversalValidationIssue[];
}

export interface SearchAroundRunResponse extends EnterpriseMapProjectionResponse {
  traversal: {
    object_set_id: string;
    step_count: number;
    result_object_set: ObjectSetRef;
    truncated: boolean;
    warnings: string[];
    validation_issues: TraversalValidationIssue[];
  };
}


export interface SavedSelectionResponse {
  id: string;
  name: string;
  color: string;
  members: string[];
  overlay: boolean;
  warnings?: string[];
}

export interface GraphStyleResponse {
  id: string;
  name: string;
  node_rules: { match: string; color: string; stroke?: string }[];
  edge_rules: { match: string; color: string; weight?: number }[];
  legend: { label: string; color: string; description?: string }[];
  warnings?: string[];
}

export interface SavedGraphResponse {
  id: string;
  name: string;
  description?: string;
  view_state: CanvasViewModel;
  filters: GraphBuilderFilterState;
  layout: GraphLayoutPreset;
  pinned_positions: Record<string, { x: number; y: number }>;
  style_refs: string[];
  selection_refs: string[];
  version: number;
  updated_at: string;
  warnings?: string[];
  permission?: 'owner' | 'editor' | 'viewer' | 'limited_viewer';
}

export interface SavedGraphVersionResponse {
  id: string;
  graph_id: string;
  version: number;
  label: string;
  created_at: string;
  immutable: boolean;
  snapshot: SavedGraphResponse;
  diff: { id: string; label: string; before?: string; after?: string }[];
  warnings?: string[];
}

export interface ShareGraphPolicy {
  id: string;
  principal: string;
  permission: 'editor' | 'viewer' | 'limited_viewer';
  redacted: boolean;
}

export interface GraphTemplateResponse {
  id: string;
  name: string;
  description?: string;
  parameters: { id: string; label: string; type: 'object' | 'object_set' | 'string'; required: boolean; value?: string }[];
  traversal_definitions: SearchAroundStepRequest[];
  filters: GraphBuilderFilterState;
  styles: string[];
  layout: GraphLayoutPreset;
}

export interface TemplateRunResponse {
  projection: EnterpriseMapProjectionResponse;
  run_metadata: { template_id: string; run_id: string; parameter_values: Record<string, string>; generated_at: string; warnings: string[] };
}

export type GovernanceRole = 'steward' | 'approver' | 'auditor';
export type ChangeSetState = 'draft' | 'submitted' | 'approved' | 'rejected' | 'published';
export type GovernanceIssueSeverity = 'error' | 'warning' | 'info';

export interface GovernanceValidationIssue {
  id: string;
  severity: GovernanceIssueSeverity;
  category: 'schema' | 'instance' | 'evidence' | 'permission' | 'lineage';
  code: string;
  message: string;
  target: { kind: 'node' | 'edge' | 'property'; id: string; property?: string };
  blocking: boolean;
  suggested_fix?: string;
}

export interface ChangeSetDiffItem {
  id: string;
  kind: 'node' | 'edge' | 'property' | 'evidence';
  action: 'create' | 'update' | 'delete';
  label: string;
  before?: string;
  after?: string;
}

export interface ChangeSetResponse {
  id: string;
  state: ChangeSetState;
  author: { id: string; name: string };
  summary: string;
  validation_issues: GovernanceValidationIssue[];
  affected_objects: string[];
  affected_types: string[];
  diff: ChangeSetDiffItem[];
  created_at: string;
  updated_at: string;
  submitted_at?: string;
  approved_at?: string;
  published_at?: string;
  rejected_at?: string;
  base_version_id: string;
  version_id?: string;
  stale: boolean;
  required_evidence_missing: boolean;
  rejection_comment?: string;
}

export interface ApprovalDecisionRequest {
  decision: 'approve' | 'reject';
  comment: string;
  reassignee?: string;
}

export interface AuditEventResponse {
  id: string;
  actor: string;
  action: string;
  entity: string;
  timestamp: string;
  diff: ChangeSetDiffItem[];
  evidence_refs: string[];
}

export interface LineageResponse {
  entity_id: string;
  upstream: string[];
  downstream: string[];
  source_refs: string[];
}

export interface PublishedVersionRef {
  id: string;
  label: string;
  created_at: string;
  changeset_id: string;
  immutable: boolean;
}

export interface GovernanceStateResponse {
  changeset: ChangeSetResponse;
  approval_queue: ChangeSetResponse[];
  audit_events: AuditEventResponse[];
  lineage: LineageResponse[];
  versions: PublishedVersionRef[];
  current_version_id: string;
  conflict?: { code: string; message: string };
}
