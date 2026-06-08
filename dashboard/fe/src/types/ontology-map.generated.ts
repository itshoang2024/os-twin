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
}

export interface ProjectionData {
  nodes: EnterpriseMapNode[];
  edges: EnterpriseMapEdge[];
  layers: { id: string; label: string; order: number }[];
  abstraction_levels: { id: string; label: string; order: number }[];
  stats: EnterpriseMapStats;
  meta: EnterpriseMapMeta;
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
