/**
 * Generated EnterpriseMap projection contract types.
 * Source: routes/knowledge_models.py Pydantic response models.
 * Regenerate when the backend schema changes.
 */

export interface TimeRangeResponse {
  start?: string | null;
  end?: string | null;
}

export interface EnterpriseMapOntologyPathResponse {
  concept_type?: string | null;
  abstraction_level?: string | null;
  layer?: string | null;
  pack_id?: string | null;
}

export type PermissionLevel = 'read' | 'limited' | 'blocked';

export interface EnterpriseMapPermission {
  level: PermissionLevel;
  reason?: string;
  allowed_actions?: string[];
}

export type EnterpriseMapCanonicalErrorCode =
  | 'NOT_FOUND'
  | 'UNAUTHORIZED'
  | 'FORBIDDEN'
  | 'VALIDATION_FAILED'
  | 'CONFLICT'
  | 'GRAPH_TOO_LARGE'
  | 'TIMEOUT'
  | 'REDACTED'
  | 'CAP_EXCEEDED'
  | 'INVALID_TRAVERSAL'
  | 'SCHEMA_INCOMPATIBLE'
  | 'FEATURE_DISABLED';

export interface EnterpriseMapCanonicalError {
  code: EnterpriseMapCanonicalErrorCode;
  message: string;
  details?: Record<string, unknown>;
  validation_issues?: string[];
}

export interface EnterpriseMapApiErrorResponse {
  error: EnterpriseMapCanonicalError;
  request_id?: string;
}

export interface EnterpriseMapNode {
  id: string;
  label: string;
  name: string;
  score: number;
  properties: Record<string, unknown>;
  concept_type?: string | null;
  concept_label?: string | null;
  abstraction_level?: string | null;
  layer?: string | null;
  pack_id?: string | null;
  family?: string | null;
  review_state?: string | null;
  lifecycle_state?: string | null;
  validation_issues: string[];
  external_ref?: string | null;
  provenance_refs: string[];
  ontology_path?: EnterpriseMapOntologyPathResponse | null;
  map_group?: string | null;
  color?: string | null;
  shape?: string | null;
  event_count?: number | null;
  active_event_count?: number | null;
  time_range?: TimeRangeResponse | null;
  series_refs: string[];
  flow_refs: string[];
  simulation_refs: string[];
  state?: string | null;
  simulation_state?: string | null;
  state_machine_ref?: string | null;
  state_color?: string | null;
  phase?: string | null;
  track?: string | null;
  priority?: string | number | null;
  effort?: string | number | null;
  prerequisites: string[];
  acceptance?: string[] | string | null;
}

export interface EnterpriseMapEdge {
  source: string;
  target: string;
  label: string;
  weight: number;
  properties: Record<string, unknown>;
  relationship_type?: string | null;
  relationship_family?: string | null;
  family?: string | null;
  review_state?: string | null;
  validation_issues: string[];
  external_ref?: string | null;
  provenance_refs: string[];
  color?: string | null;
  event_count?: number | null;
  active_event_count?: number | null;
  time_range?: TimeRangeResponse | null;
  series_refs: string[];
  flow_refs: string[];
  simulation_refs: string[];
  state?: string | null;
  simulation_state?: string | null;
  state_machine_ref?: string | null;
  state_color?: string | null;
  phase?: string | null;
  track?: string | null;
  priority?: string | number | null;
  effort?: string | number | null;
  prerequisites: string[];
  acceptance?: string[] | string | null;
}

export interface EnterpriseMapStats {
  source_node_count: number;
  source_edge_count: number;
  node_count: number;
  edge_count: number;
  ontology_candidate_count: number;
  validation_issue_count: number;
  event_count: number;
  active_event_count: number;
  truncated: boolean;
  depth_requested?: number | null;
  depth_effective?: number | null;
  node_cap?: number | null;
}

export interface EnterpriseMapMeta {
  profile_id?: string | null;
  namespace: string;
  generated_at: string;
  map_state: 'live' | 'empty';
  map_source_kind: 'knowledge_graph' | 'none';
  source_node_count: number;
  source_edge_count: number;
  applied_filters: Record<string, unknown>;
  applied_group_by: string[];
  applied_color_by: string;
  truncated: boolean;
  depth_requested?: number | null;
  depth_effective?: number | null;
  node_cap?: number | null;
  node_limit?: number | null;
  edge_limit?: number | null;
  event_limit?: number | null;
  next_cursor?: string | null;
  warnings?: string[];
  feature_flags?: Record<string, boolean>;
}

export interface EnterpriseMapPermissionSummary {
  level: PermissionLevel;
  redacted_nodes: number;
  redacted_edges: number;
  notice: string;
}

export interface EnterpriseMapProjectionResponse {
  nodes: EnterpriseMapNode[];
  edges: EnterpriseMapEdge[];
  layers: { id: string; label: string; order: number }[];
  abstraction_levels: { id: string; label: string; order: number }[];
  stats: EnterpriseMapStats;
  meta: EnterpriseMapMeta;
  groups?: unknown[];
  object_sets?: unknown[];
  facets?: unknown[];
  events?: unknown[];
  permissions?: EnterpriseMapPermissionSummary;
}

export type ProjectionData = EnterpriseMapProjectionResponse;

export interface ExplorerSearchResult {
  id: string;
  label: string;
  object_type: string;
  description: string;
  properties?: Record<string, unknown>;
  provenance_refs?: string[];
  validation_issues?: string[];
  permissions?: EnterpriseMapPermission;
  redacted?: boolean;
}

export interface ExplorerSearchResponse {
  results: ExplorerSearchResult[];
  meta: {
    query: string;
    truncated: boolean;
    limit?: number | null;
    filters?: Record<string, unknown>;
    warnings?: string[];
    fixture?: string;
  };
}

export interface ExplorerNodeDetailResponse {
  id: string;
  label: string;
  properties: Record<string, unknown>;
  relationships: { id: string; label: string; target: string; direction: 'in' | 'out' }[];
  validation_issues: string[];
  provenance_refs: string[];
  permissions: EnterpriseMapPermission & { allowed_actions: string[] };
  redacted?: boolean;
}

export type OntologyVisualExtensions = Pick<EnterpriseMapNode,
  | 'concept_type'
  | 'concept_label'
  | 'abstraction_level'
  | 'layer'
  | 'pack_id'
  | 'family'
  | 'review_state'
  | 'lifecycle_state'
  | 'validation_issues'
  | 'map_group'
  | 'color'
  | 'shape'
>;
