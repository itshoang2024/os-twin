/**
 * SWR hooks for Knowledge Explorer API — the graph visualization layer.
 *
 * Endpoints:
 * - GET  /api/knowledge/namespaces/{namespace}/explorer/summary  -> ExplorerSummary
 * - GET  /api/knowledge/namespaces/{namespace}/explorer/seed     -> ExplorerGraphData
 * - POST /api/knowledge/namespaces/{namespace}/explorer/expand   -> ExplorerGraphData
 * - POST /api/knowledge/namespaces/{namespace}/explorer/search   -> ExplorerGraphData
 * - POST /api/knowledge/namespaces/{namespace}/explorer/path     -> ExplorerPathData
 * - GET  /api/knowledge/namespaces/{namespace}/explorer/node/{id} -> ExplorerNodeDetail
 * - GET  /api/knowledge/namespaces/{namespace}/ontology/enterprise-map -> EnterpriseMapProjectionData
 *
 * The explorer hook maintains an **accumulated** graph state — each expand/search
 * merges new nodes/edges into the existing set so the visualisation grows
 * progressively without losing previously loaded data.
 */

import { useState, useCallback, useRef } from 'react';
import useSWR from 'swr';
import { apiGet, apiPost } from '@/lib/api-client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Enhanced node with optional degree/centrality/community data from the explorer. */
export interface ExplorerNode {
  id: string;
  label: string;
  name: string;
  score: number;
  properties: Record<string, unknown>;
  /** Degree computed by node_detail; 0 when not available. */
  degree?: number;
  in_degree?: number;
  out_degree?: number;
  /** Louvain community ID from the explorer seed/communities endpoint. */
  community_id?: number;
  /** Ontology-aware concept metadata (present when a namespace profile exists, safe defaults otherwise). */
  concept_type?: string | null;
  abstraction_level?: string | null;
  layer?: string | null;
  pack_id?: string | null;
  lifecycle_state?: string | null;
  metadata?: Record<string, unknown>;
  validation_issues?: Array<Record<string, unknown>>;
  quality_state?: string | null;
  candidate_state?: string | null;
  review_state?: string | null;
  confidence?: number | null;
  provenance_refs?: string[];
  external_ref?: EnterpriseMapExternalRef | Record<string, unknown> | null;
}

/** Enhanced edge with label, weight, and direction. */
export interface ExplorerEdge {
  source: string;
  target: string;
  /** Relationship label (e.g. 'MENTIONS', 'KNOWS', 'RELATES'). */
  label: string;
  /** Edge weight from PageRank / relationship-type weighting. */
  weight: number;
  /** Optional properties from the relationship. */
  properties?: Record<string, unknown>;
  /** Set during node_detail: 'incoming' | 'outgoing'. */
  direction?: 'incoming' | 'outgoing';
  /** Ontology-aware relation metadata for enterprise concept maps. */
  relationship_type?: string | null;
  family?: string | null;
  display_label?: string | null;
  inverse_label?: string | null;
  style?: 'solid' | 'dashed' | 'dotted' | 'bold' | string | null;
  is_candidate?: boolean;
  review_state?: string | null;
  candidate_state?: string | null;
  confidence?: number | null;
  provenance_refs?: string[];
  external_ref?: EnterpriseMapExternalRef | Record<string, unknown> | null;
  map_direction?: 'forward' | 'reversed' | string | null;
  validation_issues?: Array<Record<string, unknown>>;
}

/** Common graph data shape returned by seed/expand/search endpoints. */
export interface ExplorerGraphData {
  nodes: ExplorerNode[];
  edges: ExplorerEdge[];
  stats: {
    node_count: number;
    edge_count: number;
    seed_count?: number;
    query?: string;
    path_length?: number;
    error?: string;
  };
  meta?: {
    ontology_profile?: Record<string, unknown> | null;
    profile_exists?: boolean;
    [key: string]: unknown;
  };
}

export interface EnterpriseMapLayer {
  id: string;
  label: string;
  order: number;
  description?: string;
  lifecycle_state?: string;
  count: number;
}

export interface EnterpriseMapAbstractionLevel {
  id: string;
  label: string;
  order?: number;
  description?: string;
}

export type OntologyVisualTimeRange = { start?: string | null; end?: string | null; [key: string]: unknown } | string | null;

export interface EnterpriseMapExternalRef {
  system: string;
  id: string;
  uri?: string | null;
}

export interface OntologyExternalRef {
  system?: string | null;
  id?: string | null;
  uri?: string | null;
  [key: string]: unknown;
}

export interface OntologyVisualExtensions {
  event_count?: number | null;
  active_event_count?: number | null;
  time_range?: OntologyVisualTimeRange;
  series_refs?: string[];
  flow_refs?: string[];
  state?: string | null;
  simulation_state?: string | null;
  simulation_refs?: string[];
  state_machine_ref?: string | null;
  state_color?: string | null;
  phase?: string | null;
  track?: string | null;
  priority?: string | number | null;
  effort?: string | number | null;
  prerequisites?: string[];
  acceptance?: string[] | string | null;
}

export interface EnterpriseMapNode extends ExplorerNode, OntologyVisualExtensions {
  concept_label?: string | null;
  concept_color?: string | null;
  concept_shape?: string | null;
  abstraction_label?: string | null;
  layer_id?: string | null;
  layer_label?: string | null;
  layer_order?: number | null;
  owner?: string | null;
  description?: string | null;
  map_group?: string | null;
  data_store?: string | null;
  sync_mode?: string | null;
  quality_state?: string | null;
  candidate_state?: string | null;
  review_state?: string | null;
  confidence?: number | null;
  provenance_refs?: string[];
  external_ref?: EnterpriseMapExternalRef | Record<string, unknown> | null;
  ontology_path?: {
    layer?: string | null;
    abstraction_level?: string | null;
    concept_type?: string | null;
    pack_id?: string | null;
    lifecycle_state?: string | null;
  };
}

export interface EnterpriseMapEdge extends ExplorerEdge, OntologyVisualExtensions {
  id?: string | null;
  color?: string | null;
  review_state?: string | null;
  candidate_state?: string | null;
  confidence?: number | null;
  provenance_refs?: string[];
  external_ref?: EnterpriseMapExternalRef | Record<string, unknown> | null;
  validation_issues?: Array<Record<string, unknown>>;
  map_source?: string | null;
  map_target?: string | null;
  map_direction?: 'forward' | 'reversed' | string | null;
}

export interface EnterpriseMapProjectionData {
  nodes: EnterpriseMapNode[];
  edges: EnterpriseMapEdge[];
  layers: EnterpriseMapLayer[];
  abstraction_levels: EnterpriseMapAbstractionLevel[];
  concept_type_counts: Record<string, number>;
  relationship_type_counts: Record<string, number>;
  relationship_family_counts: Record<string, number>;
  stats: {
    node_count: number;
    edge_count: number;
    layer_count: number;
    concept_type_count: number;
    relationship_type_count: number;
    candidate_edge_count: number;
    validation_issue_count: number;
    source_node_count?: number;
    source_edge_count?: number;
    ontology_candidate_count?: number;
    limit?: number;
    filtered?: boolean;
    [key: string]: unknown;
  };
  meta?: {
    ontology_profile?: Record<string, unknown> | null;
    profile_exists?: boolean;
    ontology_candidate_count?: number;
    [key: string]: unknown;
  };
}

/** Summary — lightweight topology stats. */
export interface ExplorerSummary {
  entity_count: number;
  chunk_count: number;
  relation_count: number;
  label_distribution: Record<string, number>;
  degree_stats: {
    max_degree: number;
  };
}

/** Path result from explorer/path endpoint. */
export interface ExplorerPathData extends ExplorerGraphData {
  /** Ordered list of node IDs along the path. */
  path: string[];
}

/** Node detail from explorer/node/{id} endpoint. */
export interface ExplorerNodeDetail {
  node: ExplorerNode | null;
  edges: ExplorerEdge[];
  edge_groups?: Record<string, { incoming: ExplorerEdge[]; outgoing: ExplorerEdge[] }>;
  stats: {
    degree?: number;
    in_degree?: number;
    out_degree?: number;
    error?: string;
  };
}

export interface ExplorerOntologyFilters {
  layer?: string[];
  abstraction_level?: string[];
  concept_type?: string[];
  relationship_family?: string[];
  relationship_type?: string[];
  pack_id?: string[];
  lifecycle_state?: string[];
  owner?: string[];
  metadata?: Record<string, unknown>;
}

/** Expand request body. */
interface ExpandRequest {
  node_ids: string[];
  depth: number;
  filters?: ExplorerOntologyFilters;
}

/** Search request body. */
interface SearchRequest {
  query: string;
  limit: number;
  filters?: ExplorerOntologyFilters;
}

/** Path request body. */
interface PathRequest {
  source_id: string;
  target_id: string;
}

/** Visual brightness computed for a node (0 = dim, 1 = full glow). */
export type LensMode = 'structural' | 'semantic' | 'category' | 'community';

// ---------------------------------------------------------------------------
// Hook: useKnowledgeExplorerSummary
// ---------------------------------------------------------------------------

const KNOWLEDGE_BASE = '/knowledge';

/**
 * Hook to fetch lightweight topology summary for a namespace.
 */
export function useKnowledgeExplorerSummary(namespace: string | null) {
  const { data, error, isLoading } = useSWR<ExplorerSummary>(
    namespace ? `${KNOWLEDGE_BASE}/namespaces/${namespace}/explorer/summary` : null,
    { revalidateOnFocus: false }
  );

  return {
    summary: data ?? null,
    isLoading,
    error: error ? String(error) : null,
  };
}

export function useEnterpriseMap(namespace: string | null, limit: number = 200) {
  const key = namespace
    ? `${KNOWLEDGE_BASE}/namespaces/${encodeURIComponent(namespace)}/ontology/enterprise-map?limit=${limit}`
    : null;
  const { data, error, isLoading, mutate } = useSWR<EnterpriseMapProjectionData>(
    key,
    (url: string) => apiGet<EnterpriseMapProjectionData>(url),
    { revalidateOnFocus: false },
  );

  return {
    map: data ?? null,
    isLoading,
    error: error ? String(error) : null,
    mutate,
  };
}

// ---------------------------------------------------------------------------
// Hook: useKnowledgeExplorer
// ---------------------------------------------------------------------------

/**
 * The main Knowledge Explorer hook. Manages accumulated graph state
 * and provides actions for progressive exploration.
 *
 * Usage:
 * ```tsx
 * const { nodes, edges, ignite, expand, search, findPath } = useKnowledgeExplorer(namespace);
 * ```
 */
export function useKnowledgeExplorer(namespace: string | null) {
  // ---- Accumulated graph state ----
  const [nodesMap, setNodesMap] = useState<Map<string, ExplorerNode>>(new Map());
  const [edgesMap, setEdgesMap] = useState<Map<string, ExplorerEdge>>(new Map());

  // ---- Exploration state ----
  const [activeIgnitionPoints, setActiveIgnitionPoints] = useState<string[]>([]);
  const [selectedPath, setSelectedPath] = useState<{ source: string; target: string; path: string[] } | null>(null);
  const [activeLens, setActiveLens] = useState<LensMode>('structural');
  const [expansionDepth, setExpansionDepth] = useState(1);

  // ---- Loading flags ----
  const [isSeeding, setIsSeeding] = useState(false);
  const [isExpanding, setIsExpanding] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [isFindingPath, setIsFindingPath] = useState(false);

  // ---- Node brightness computed from ignition points ----
  const [nodeBrightness, setNodeBrightness] = useState<Map<string, number>>(new Map());

  // ---- Ref to track if seed was loaded ----
  const seedLoadedRef = useRef(false);

  // ---- Helper: merge new graph data into accumulated state ----
  const mergeGraphData = useCallback((data: ExplorerGraphData) => {
    setNodesMap(prev => {
      const next = new Map(prev);
      for (const node of data.nodes) {
        next.set(node.id, node);
      }
      return next;
    });

    setEdgesMap(prev => {
      const next = new Map(prev);
      for (const edge of data.edges) {
        const key = `${edge.source}->${edge.target}`;
        next.set(key, edge);
      }
      return next;
    });
  }, []);

  // ---- Helper: compute brightness from ignition points ----
  const computeBrightness = useCallback(
    (ignitionPoints: string[], allNodes: Map<string, ExplorerNode>, allEdges: Map<string, ExplorerEdge>) => {
      const brightness = new Map<string, number>();

      // All nodes start at base brightness 0.3
      for (const [id] of allNodes) {
        brightness.set(id, 0.3);
      }

      // Ignition points are full brightness
      for (const id of ignitionPoints) {
        brightness.set(id, 1.0);
      }

      // 1-hop neighbors of ignition points are brighter
      for (const [, edge] of allEdges) {
        if (ignitionPoints.includes(edge.source)) {
          brightness.set(edge.target, Math.max(brightness.get(edge.target) ?? 0.3, 0.7));
        }
        if (ignitionPoints.includes(edge.target)) {
          brightness.set(edge.source, Math.max(brightness.get(edge.source) ?? 0.3, 0.7));
        }
      }

      setNodeBrightness(brightness);
    },
    []
  );

  // ---- Action: seed the initial graph ----
  const seed = useCallback(async (topK: number = 50) => {
    if (!namespace) return;
    setIsSeeding(true);
    try {
      const data = await apiGet<ExplorerGraphData>(
        `${KNOWLEDGE_BASE}/namespaces/${namespace}/explorer/seed?top_k=${topK}`
      );
      mergeGraphData(data);

      // Set seed nodes as initial ignition points
      const seedNodeIds = data.nodes.slice(0, data.stats.seed_count ?? topK).map(n => n.id);
      setActiveIgnitionPoints(seedNodeIds);

      // Compute brightness
      const tempNodes = new Map<string, ExplorerNode>();
      for (const node of data.nodes) {
        tempNodes.set(node.id, node);
      }
      const tempEdges = new Map<string, ExplorerEdge>();
      for (const edge of data.edges) {
        tempEdges.set(`${edge.source}->${edge.target}`, edge);
      }
      computeBrightness(seedNodeIds, tempNodes, tempEdges);

      seedLoadedRef.current = true;
    } catch (err) {
      console.error('Explorer seed failed:', err);
    } finally {
      setIsSeeding(false);
    }
  }, [namespace, mergeGraphData, computeBrightness]);

  // ---- Action: ignite a node (expand from it) ----
  const ignite = useCallback(async (nodeId: string, depth?: number) => {
    if (!namespace) return;
    setIsExpanding(true);
    try {
      const data = await apiPost<ExplorerGraphData>(
        `${KNOWLEDGE_BASE}/namespaces/${namespace}/explorer/expand`,
        { node_ids: [nodeId], depth: depth ?? expansionDepth } satisfies ExpandRequest
      );
      mergeGraphData(data);

      // Add to ignition points
      const newIgnition = [...new Set([...activeIgnitionPoints, nodeId])];
      setActiveIgnitionPoints(newIgnition);

      // Recompute brightness with updated graph state
      // We need to read current state, so use functional updates
      setNodesMap(currentNodes => {
        setEdgesMap(currentEdges => {
          computeBrightness(newIgnition, currentNodes, currentEdges);
          return currentEdges;
        });
        return currentNodes;
      });
    } catch (err) {
      console.error('Explorer ignite failed:', err);
    } finally {
      setIsExpanding(false);
    }
  }, [namespace, expansionDepth, activeIgnitionPoints, mergeGraphData, computeBrightness]);

  // ---- Action: expand from multiple nodes ----
  const expand = useCallback(async (nodeIds: string[], depth?: number, filters?: ExplorerOntologyFilters) => {
    if (!namespace || nodeIds.length === 0) return;
    setIsExpanding(true);
    try {
      const data = await apiPost<ExplorerGraphData>(
        `${KNOWLEDGE_BASE}/namespaces/${namespace}/explorer/expand`,
        { node_ids: nodeIds, depth: depth ?? expansionDepth, ...(filters ? { filters } : {}) } satisfies ExpandRequest
      );
      mergeGraphData(data);
    } catch (err) {
      console.error('Explorer expand failed:', err);
    } finally {
      setIsExpanding(false);
    }
  }, [namespace, expansionDepth, mergeGraphData]);

  // ---- Action: search and ignite results ----
  const search = useCallback(async (query: string, limit?: number, filters?: ExplorerOntologyFilters) => {
    if (!namespace || !query.trim()) return;
    setIsSearching(true);
    try {
      const data = await apiPost<ExplorerGraphData>(
        `${KNOWLEDGE_BASE}/namespaces/${namespace}/explorer/search`,
        { query: query.trim(), limit: limit ?? 20, ...(filters ? { filters } : {}) } satisfies SearchRequest
      );
      mergeGraphData(data);
    } catch (err) {
      console.error('Explorer search failed:', err);
    } finally {
      setIsSearching(false);
    }
  }, [namespace, mergeGraphData]);

  // ---- Action: find path between two nodes ----
  const findPath = useCallback(async (sourceId: string, targetId: string) => {
    if (!namespace) return;
    setIsFindingPath(true);
    try {
      const data = await apiPost<ExplorerPathData>(
        `${KNOWLEDGE_BASE}/namespaces/${namespace}/explorer/path`,
        { source_id: sourceId, target_id: targetId } satisfies PathRequest
      );
      mergeGraphData(data);
      setSelectedPath({
        source: sourceId,
        target: targetId,
        path: data.path,
      });
    } catch (err) {
      console.error('Explorer path failed:', err);
      setSelectedPath(null);
    } finally {
      setIsFindingPath(false);
    }
  }, [namespace, mergeGraphData]);

  // ---- Action: get node detail ----
  const getNodeDetail = useCallback(async (nodeId: string): Promise<ExplorerNodeDetail | null> => {
    if (!namespace) return null;
    try {
      return await apiGet<ExplorerNodeDetail>(
        `${KNOWLEDGE_BASE}/namespaces/${namespace}/explorer/node/${encodeURIComponent(nodeId)}`
      );
    } catch (err) {
      console.error('Explorer node detail failed:', err);
      return null;
    }
  }, [namespace]);

  // ---- Action: clear path selection ----
  const clearPath = useCallback(() => {
    setSelectedPath(null);
  }, []);

  // ---- Action: reset all state ----
  const reset = useCallback(() => {
    setNodesMap(new Map());
    setEdgesMap(new Map());
    setActiveIgnitionPoints([]);
    setSelectedPath(null);
    setNodeBrightness(new Map());
    seedLoadedRef.current = false;
  }, []);

  // ---- Derived: arrays from maps ----
  const nodes = Array.from(nodesMap.values());
  const edges = Array.from(edgesMap.values());

  return {
    // Graph data
    nodes,
    edges,
    stats: {
      node_count: nodes.length,
      edge_count: edges.length,
    },

    // Exploration state
    activeIgnitionPoints,
    selectedPath,
    activeLens,
    expansionDepth,
    nodeBrightness,
    isSeeded: seedLoadedRef.current,

    // Loading flags
    isSeeding,
    isExpanding,
    isSearching,
    isFindingPath,
    isLoading: isSeeding || isExpanding || isSearching || isFindingPath,

    // Actions
    seed,
    ignite,
    expand,
    search,
    findPath,
    getNodeDetail,
    clearPath,
    reset,
    setLens: setActiveLens,
    setExpansionDepth,
  };
}
