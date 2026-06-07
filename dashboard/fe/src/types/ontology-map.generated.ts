// Generated from dashboard.routes.knowledge_models EnterpriseMapProjectionResponse.
// Regenerate/check via tests/test_enterprise_map_contract.py. Do not hand-edit field names.

export type JsonObject = Record<string, unknown>;
export type TimeRangeResponse = { start?: string | null; end?: string | null };
export type EnterpriseMapOntologyPathResponse = { layer?: string | null; abstraction_level?: string | null; concept_type?: string | null; pack_id?: string | null; lifecycle_state?: string | null };

export type EnterpriseMapNodeResponse = {
  id: string;
  label?: string | null;
  name?: string | null;
  score: number;
  properties: JsonObject;
  metadata: JsonObject;
  concept_type?: string | null;
  concept_label?: string | null;
  concept_color?: string | null;
  concept_shape?: string | null;
  abstraction_level?: string | null;
  abstraction_label?: string | null;
  layer_id?: string | null;
  layer_label?: string | null;
  layer_order?: number | null;
  pack_id?: string | null;
  lifecycle_state?: string | null;
  review_state?: string | null;
  confidence?: number | null;
  provenance_refs: string[];
  external_ref?: JsonObject | null;
  owner?: string | null;
  description?: string | null;
  map_group?: string | null;
  data_store?: string | null;
  sync_mode?: string | null;
  quality_state?: string | null;
  candidate_state?: string | null;
  event_count?: number | null;
  active_event_count?: number | null;
  time_range?: TimeRangeResponse | null;
  series_refs: string[];
  flow_refs: string[];
  state?: string | null;
  simulation_state?: string | null;
  simulation_refs: string[];
  state_machine_ref?: string | null;
  state_color?: string | null;
  phase?: string | null;
  track?: string | null;
  priority?: string | number | null;
  effort?: string | number | null;
  prerequisites: string[];
  acceptance?: string[] | string | null;
  ontology_path: EnterpriseMapOntologyPathResponse;
  validation_issues: JsonObject[];
};

export type EnterpriseMapEdgeResponse = {
  id?: string | null;
  source: string;
  target: string;
  label?: string | null;
  weight: number;
  properties: JsonObject;
  relationship_type?: string | null;
  family?: string | null;
  display_label?: string | null;
  inverse_label?: string | null;
  style?: string | null;
  color?: string | null;
  dash?: string | null;
  map_source?: string | null;
  map_target?: string | null;
  map_direction?: string | null;
  map_group?: string | null;
  review_state?: string | null;
  confidence?: number | null;
  provenance_refs: string[];
  external_ref?: JsonObject | null;
  candidate_state?: string | null;
  event_count?: number | null;
  active_event_count?: number | null;
  time_range?: TimeRangeResponse | null;
  series_refs: string[];
  flow_refs: string[];
  state?: string | null;
  simulation_state?: string | null;
  simulation_refs: string[];
  state_machine_ref?: string | null;
  state_color?: string | null;
  phase?: string | null;
  track?: string | null;
  priority?: string | number | null;
  effort?: string | number | null;
  prerequisites: string[];
  acceptance?: string[] | string | null;
  is_candidate: boolean;
  validation_issues: JsonObject[];
};

export type EnterpriseMapLayerResponse = {
  id: string;
  label: string;
  order: number;
  description: string;
  lifecycle_state: string;
  count: number;
};

export type EnterpriseMapAbstractionLevelResponse = {
  id: string;
  label: string;
  order?: number | null;
  description: string;
};

export type EnterpriseMapStatsResponse = {
  node_count: number;
  edge_count: number;
  layer_count: number;
  concept_type_count: number;
  relationship_type_count: number;
  candidate_edge_count: number;
  validation_issue_count: number;
  source_node_count: number;
  source_edge_count: number;
  ontology_candidate_count: number;
  event_count: number;
  active_event_count: number;
  flow_count: number;
  state_machine_count: number;
  simulation_scenario_count: number;
  limit?: number | null;
  filtered: boolean;
  truncated: boolean;
  node_cap?: number | null;
  depth_requested?: number | null;
  depth_effective?: number | null;
};

export type EnterpriseMapMetaResponse = {
  ontology_profile?: JsonObject | null;
  profile_exists: boolean;
  ontology_candidate_count: number;
  graph_instruction: JsonObject;
  time_window: JsonObject;
  observation_series_backend: string;
  analysis: JsonObject;
  map_state: 'live' | 'empty';
  map_source_kind: 'knowledge_graph' | 'none';
  source_node_count: number;
  source_edge_count: number;
  applied_filters: JsonObject;
  applied_group_by: string[];
  applied_color_by: string;
};

export type EnterpriseMapProjectionResponse = {
  nodes: EnterpriseMapNodeResponse[];
  edges: EnterpriseMapEdgeResponse[];
  layers: EnterpriseMapLayerResponse[];
  abstraction_levels: EnterpriseMapAbstractionLevelResponse[];
  concept_type_counts: Record<string, number>;
  relationship_type_counts: Record<string, number>;
  relationship_family_counts: Record<string, number>;
  stats: EnterpriseMapStatsResponse;
  meta: EnterpriseMapMetaResponse;
};

export type OntologyVisualExtensions = Pick<EnterpriseMapNodeResponse,
  | 'event_count'
  | 'active_event_count'
  | 'time_range'
  | 'series_refs'
  | 'flow_refs'
  | 'state'
  | 'simulation_state'
  | 'simulation_refs'
  | 'state_machine_ref'
  | 'state_color'
  | 'phase'
  | 'track'
  | 'priority'
  | 'effort'
  | 'prerequisites'
  | 'acceptance'
>;
export type EnterpriseMapProjectionData = EnterpriseMapProjectionResponse;

export type ExplorerFilterClause = { values: string[]; mode?: 'include' | 'exclude' };
export type ExplorerFilterValue = string[] | ExplorerFilterClause;
export type ExplorerOntologyFilters = {
  layer?: ExplorerFilterValue | null;
  abstraction_level?: ExplorerFilterValue | null;
  concept_type?: ExplorerFilterValue | null;
  relationship_family?: ExplorerFilterValue | null;
  relationship_type?: ExplorerFilterValue | null;
  pack_id?: ExplorerFilterValue | null;
  lifecycle_state?: ExplorerFilterValue | null;
  owner?: ExplorerFilterValue | null;
  metadata?: Record<string, string | number | boolean | null> | null;
};
