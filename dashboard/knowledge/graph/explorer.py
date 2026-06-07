"""Knowledge Explorer — tiled graph loading for the Supernova visualization layer.

Provides progressive, on-demand graph exploration APIs that compose existing
:class:`KuzuLabelledPropertyGraph` methods. The existing flat ``get_graph``
endpoint remains untouched — this module adds *new* capabilities:

- **seed**: Load the "brightest" nodes (top PageRank per Louvain community)
  + their 1-hop neighborhood.
- **expand**: Expand from a set of node IDs outward by N hops.
- **search**: Vector-similarity search over node embeddings + 1-hop context.
- **path**: Shortest weighted path between two nodes.
- **node_detail**: Full detail for a single node including incident edges + scores.
- **summary**: Lightweight topology stats without any node data.
- **communities**: Detect Louvain communities and return the mapping.

All methods return plain dicts that are JSON-serialisable — no LlamaIndex types
leak into the API layer.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from dashboard.knowledge.ontology.normalizer import normalize_concept_type, normalize_relation
from dashboard.knowledge.ontology.projection import project_enterprise_map
from dashboard.knowledge.ontology.validator import validate_node, validate_relationship

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Node / edge serialization helpers
# ---------------------------------------------------------------------------


def _coerce_properties(value: Any) -> Dict[str, Any]:
    """Return a defensive dict for node/edge property payloads."""
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _profile_summary(profile: Any) -> Optional[Dict[str, Any]]:
    """Small, stable profile payload for explorer response metadata."""
    if profile is None:
        return None
    return {
        "profile_id": getattr(profile, "profile_id", ""),
        "namespace": getattr(profile, "namespace", ""),
        "version": getattr(profile, "version", ""),
        "status": getattr(profile, "status", "active"),
        "concept_type_count": len(getattr(profile, "concept_types", {}) or {}),
        "relationship_type_count": len(getattr(profile, "relationship_types", {}) or {}),
        "layer_count": len(getattr(profile, "layers", {}) or {}),
        "abstraction_level_count": len(getattr(profile, "abstraction_levels", {}) or {}),
    }


def _node_to_dict(node: Any, community_id: Optional[int] = None, profile: Any = None) -> Dict[str, Any]:
    """Serialize a LlamaIndex LabelledNode to a JSON-friendly dict.

    The legacy shape is preserved while ontology-aware fields are added when
    profile/node metadata is available. Legacy graphs without profiles receive
    safe defaults (``validation_issues=[]`` and metadata from properties only).
    """
    props = _coerce_properties(getattr(node, "properties", None))
    node_label = getattr(node, "label", "") or ""
    raw_type = props.get("concept_type") or props.get("type") or node_label
    concept_type = normalize_concept_type(str(raw_type), profile) if raw_type else ""
    concept = None
    if profile is not None and concept_type:
        concept = (getattr(profile, "concept_types", {}) or {}).get(concept_type)

    metadata = props.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {
            key: value
            for key, value in props.items()
            if key not in {
                "weight", "concept_type", "type", "abstraction_level", "layer",
                "pack_id", "lifecycle_state", "validation_issues", "metadata",
            }
        }

    validation_issues: List[Dict[str, Any]] = []
    if isinstance(props.get("validation_issues"), list):
        validation_issues.extend(props["validation_issues"])
    if profile is not None and concept_type:
        try:
            validation_issues.extend(issue.model_dump() for issue in validate_node(concept_type, profile))
        except Exception as exc:  # noqa: BLE001 - validation must not break explorer reads
            logger.debug("Explorer node validation failed for %s: %s", concept_type, exc)

    result = {
        "id": getattr(node, "id", ""),
        "label": node_label,
        "name": getattr(node, "name", "") or getattr(node, "id", ""),
        "score": float(props.get("weight", 1.0)),
        "properties": props,
        "concept_type": concept_type or None,
        "abstraction_level": props.get("abstraction_level") or getattr(concept, "abstraction_level", None),
        "layer": props.get("layer"),
        "pack_id": props.get("pack_id"),
        "lifecycle_state": props.get("lifecycle_state") or getattr(concept, "lifecycle_state", None),
        "metadata": metadata,
        "validation_issues": validation_issues,
    }
    if community_id is not None:
        result["community_id"] = community_id
    return result


def _relation_to_dict(rel: Any, profile: Any = None, source_node: Any = None, target_node: Any = None) -> Dict[str, Any]:
    """Serialize a LlamaIndex Relation to a JSON-friendly dict.

    Adds canonical relation metadata used by enterprise concept maps while
    preserving the existing ``label``/``weight``/``properties`` contract.
    """
    rel_props = _coerce_properties(getattr(rel, "properties", None))
    rel_label = getattr(rel, "label", "") or rel_props.get("relation_label", "RELATES")
    rel_weight = float(rel_props.get("weight", 1.0))
    normalized = normalize_relation(str(rel_label), profile)
    relationship = normalized.canonical
    relationship_type = normalized.normalized

    validation_issues: List[Dict[str, Any]] = []
    if isinstance(rel_props.get("validation_issues"), list):
        validation_issues.extend(rel_props["validation_issues"])
    if profile is not None:
        try:
            source_props = _coerce_properties(getattr(source_node, "properties", None)) if source_node is not None else {}
            target_props = _coerce_properties(getattr(target_node, "properties", None)) if target_node is not None else {}
            source_type = source_props.get("concept_type") or source_props.get("type") or getattr(source_node, "label", "")
            target_type = target_props.get("concept_type") or target_props.get("type") or getattr(target_node, "label", "")
            if source_type and target_type:
                validation_issues.extend(
                    issue.model_dump()
                    for issue in validate_relationship(str(rel_label), str(source_type), str(target_type), profile)
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Explorer relation validation failed for %s: %s", rel_label, exc)

    inverse_label = None
    if relationship is not None and relationship.inverse:
        inverse = (getattr(profile, "relationship_types", {}) or {}).get(relationship.inverse) if profile else None
        inverse_label = getattr(inverse, "label", None) or relationship.inverse

    return {
        "source": getattr(rel, "source_id", ""),
        "target": getattr(rel, "target_id", ""),
        "label": rel_label,
        "weight": rel_weight,
        "properties": rel_props,
        "relationship_type": relationship_type,
        "family": getattr(relationship, "family", None),
        "display_label": getattr(relationship, "label", None) or rel_label,
        "inverse_label": inverse_label,
        "style": getattr(relationship, "style", "solid"),
        "is_candidate": normalized.classification == "candidate",
        "validation_issues": validation_issues,
    }


def _triplet_to_edge_dicts(source: Any, rel: Any, target: Any, profile: Any = None) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Convert a (source, relation, target) triplet into node/edge dicts."""
    s_dict = _node_to_dict(source, profile=profile)
    t_dict = _node_to_dict(target, profile=profile)
    e_dict = _relation_to_dict(rel, profile=profile, source_node=source, target_node=target)
    return s_dict, t_dict, e_dict, [s_dict, t_dict]


# ---------------------------------------------------------------------------
# KnowledgeExplorer
# ---------------------------------------------------------------------------


class KnowledgeExplorer:
    """Progressive graph exploration engine for the Supernova visualisation.

    Composes existing :class:`KuzuLabelledPropertyGraph` methods — no new
    Cypher queries are introduced. This class is a thin orchestration layer.

    Community detection uses NetworkX Louvain (``community.louvain_communities``)
    on the entity subgraph already loaded for PageRank. Community assignments
    are cached on the instance so subsequent calls are free.

    Usage::

        kg = service.get_kuzu_graph(namespace)
        explorer = KnowledgeExplorer(kg)
        seed = explorer.seed(top_k=50)
        expanded = explorer.expand(node_ids=["id1", "id2"], depth=1)
    """

    def __init__(self, graph: Any) -> None:
        self.graph = graph
        self.profile = getattr(graph, "ontology_profile", None)
        # Cached community mapping: {entity_id: community_id}
        self._community_map: Dict[str, int] = {}
        # Cached NetworkX graph (shared between seed / communities)
        self._nx_graph: Optional[Any] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        """Return lightweight topology stats without node data.

        Includes node/edge counts, label distribution, and degree stats.
        All via cheap Cypher COUNT queries.
        """
        kg = self.graph
        try:
            entity_count = kg.count_entities()
            chunk_count = kg.count_chunks()
            relation_count = kg.count_relations()
        except Exception as exc:
            logger.error("Explorer summary count failed: %s", exc)
            entity_count, chunk_count, relation_count = 0, 0, 0

        # Label distribution (cheap aggregation)
        label_distribution: Dict[str, int] = {}
        try:
            conn = kg.connection
            result = conn.execute(
                "MATCH (n:Node) WHERE n.label <> 'text_chunk' "
                "RETURN n.label AS label, count(n) AS cnt ORDER BY cnt DESC LIMIT 20"
            )
            for row in result:
                label_distribution[row[0]] = row[1]
        except Exception as exc:
            logger.debug("Label distribution query failed: %s", exc)

        # Degree stats
        degree_stats: Dict[str, Any] = {}
        try:
            conn = kg.connection
            result = conn.execute(
                "MATCH (n:Node)-[r:RELATES]->(m:Node) "
                "WHERE n.label <> 'text_chunk' AND m.label <> 'text_chunk' "
                "RETURN n.id AS nid, count(r) AS deg "
                "ORDER BY deg DESC LIMIT 1"
            )
            max_deg = 0
            for row in result:
                max_deg = row[1]
            degree_stats["max_degree"] = max_deg
        except Exception as exc:
            logger.debug("Degree stats query failed: %s", exc)
            degree_stats["max_degree"] = 0

        return {
            "entity_count": entity_count,
            "chunk_count": chunk_count,
            "relation_count": relation_count,
            "label_distribution": label_distribution,
            "degree_stats": degree_stats,
        }

    def seed(self, top_k: int = 50) -> Dict[str, Any]:
        """Load the initial "sky" — top-K nodes by PageRank per community + 1-hop neighborhood.

        Community-aware seeding strategy:
        1. Load the entity subgraph into NetworkX.
        2. Run Louvain community detection.
        3. Run PageRank with uniform personalization.
        4. For each community, pick the top-PageRank node (representative).
        5. Fill remaining slots from the global PageRank ranking.
        6. Expand 1-hop via ``get_triplets(ids=...)``.

        This ensures every community in the graph gets at least one seed
        node, giving much better visual coverage than uniform PageRank top-K
        (which tends to cluster all seeds in the densest community).

        The PageRank computation is cached by the graph store so repeated
        calls are fast. Community assignments are cached on this explorer
        instance.
        """
        kg = self.graph

        # Step 1: Get entity graph into NetworkX (shared with community detection)
        try:
            G = self._get_nx_graph()
        except Exception as exc:
            logger.error("Explorer seed graph fetch failed: %s", exc)
            return self._with_meta({"nodes": [], "edges": [], "stats": {"node_count": 0, "edge_count": 0, "seed_count": 0, "community_count": 0}})

        if G is None or len(G.nodes()) == 0:
            return self._with_meta({"nodes": [], "edges": [], "stats": {"node_count": 0, "edge_count": 0, "seed_count": 0, "community_count": 0}})

        # Step 2: Run community detection (caches result)
        try:
            self._detect_communities(G)
        except Exception as exc:
            logger.warning("Explorer seed community detection failed: %s", exc)

        # Step 3: PageRank with uniform personalization
        try:
            # Map NX node IDs to original entity IDs for personalization
            entity_ids = []
            for nx_id in G.nodes():
                orig_id = G.nodes[nx_id].get("id", nx_id)
                entity_ids.append(orig_id)

            if not entity_ids:
                return self._with_meta({"nodes": [], "edges": [], "stats": {"node_count": 0, "edge_count": 0, "seed_count": 0, "community_count": 0}})

            uniform_weight = 1.0 / len(entity_ids)
            personalize = {eid: uniform_weight for eid in entity_ids}
            pagerank_results = kg.pagerank(personalize, score_threshold=0.0)

            # Build a lookup: entity_id -> pagerank_score
            pr_scores = {pid: score for pid, score in pagerank_results}
        except Exception as exc:
            logger.error("Explorer seed PageRank failed: %s", exc)
            pr_scores = {}

        # Step 4: Community-aware seed selection
        top_ids = self._select_community_seeds(pr_scores, top_k)

        if not top_ids:
            # Fallback: just use first top_k entity IDs
            top_ids = entity_ids[:top_k]

        # Step 5: Expand 1-hop from top nodes
        return self._with_meta(self._expand_from_ids(top_ids, include_seed_info=True))

    def expand(self, node_ids: List[str], depth: int = 1, filters: Optional[Dict[str, Any]] = None, node_cap: int = 300) -> Dict[str, Any]:
        """Expand from a set of node IDs outward by N hops.

        Each hop fetches the neighborhood of the frontier nodes via
        ``get_triplets(ids=...)``. Depth is capped at 3 for performance.

        Args:
            node_ids: Starting node IDs to expand from.
            depth: Number of hops (1-3, default 1).

        Returns:
            Dict with nodes, edges, and stats.
        """
        requested_depth = int(depth or 1)
        depth = max(1, min(3, requested_depth))
        kg = self.graph

        all_node_ids = set(node_ids)
        discovered_order = list(node_ids)
        frontier = list(node_ids)
        all_edges: List[Dict[str, Any]] = []
        seen_edges: set = set()

        for hop in range(depth):
            if not frontier:
                break
            try:
                triplets = kg.get_triplets(ids=frontier)
            except Exception as exc:
                logger.error("Explorer expand hop %d failed: %s", hop, exc)
                break

            next_frontier: List[str] = []
            for source, rel, target in triplets:
                s_id = getattr(source, "id", "")
                t_id = getattr(target, "id", "")
                r_key = (s_id, t_id, getattr(rel, "label", ""))
                if r_key not in seen_edges:
                    seen_edges.add(r_key)
                    all_edges.append(_relation_to_dict(rel, profile=self.profile, source_node=source, target_node=target))
                if s_id not in all_node_ids:
                    all_node_ids.add(s_id)
                    discovered_order.append(s_id)
                    next_frontier.append(s_id)
                if t_id not in all_node_ids:
                    all_node_ids.add(t_id)
                    discovered_order.append(t_id)
                    next_frontier.append(t_id)
            frontier = next_frontier

        # Fetch full node data for all discovered IDs and cap the response to keep
        # search-around bounded even for dense hubs. Edges are re-derived against
        # the capped node set so no dangling references leak to the UI.
        all_ids = discovered_order
        node_cap = max(1, int(node_cap or 300))
        truncated = len(all_ids) > node_cap
        nodes = self._fetch_nodes_by_ids(all_ids[:node_cap])
        node_id_set = {n["id"] for n in nodes}
        filtered_edges = [
            e for e in all_edges
            if e["source"] in node_id_set and e["target"] in node_id_set
        ]

        projection = project_enterprise_map(nodes, filtered_edges, self.profile)
        projection["stats"].update({
            "node_count": len(projection.get("nodes") or []),
            "edge_count": len(projection.get("edges") or []),
            "depth_requested": requested_depth,
            "depth_effective": depth,
            "node_cap": node_cap,
            "truncated": truncated,
        })
        projection = self._apply_filters(projection, filters)
        projection.setdefault("meta", {})["truncated"] = truncated
        projection["meta"]["node_cap"] = node_cap
        projection["meta"]["depth_requested"] = requested_depth
        projection["meta"]["depth_effective"] = depth
        return self._with_meta(projection)

    def search(self, query: str, limit: int = 20, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Vector-similarity search over node embeddings + 1-hop context.

        Uses ``get_all_nodes(context=query)`` which leverages KuzuDB's
        vector index, then expands 1-hop for context.

        Args:
            query: Natural language search query.
            limit: Max number of seed results from vector search.

        Returns:
            Dict with nodes, edges, and stats.
        """
        kg = self.graph
        try:
            results = kg.get_all_nodes(label_type="entity", context=query, limit=limit)
        except Exception as exc:
            logger.error("Explorer search failed: %s", exc)
            return {"nodes": [], "edges": [], "stats": {"node_count": 0, "edge_count": 0, "query": query}}

        seed_ids = [getattr(n, "id", "") for n in results if getattr(n, "id", "")]
        if not seed_ids:
            return {"nodes": [], "edges": [], "stats": {"node_count": 0, "edge_count": 0, "query": query}}

        result = self._expand_from_ids(seed_ids)
        result["stats"]["query"] = query
        return self._apply_filters(result, filters)

    def enterprise_map(self, limit: int = 200, filters: Optional[Dict[str, Any]] = None, group_by: Optional[List[str]] = None, color_by: Optional[str] = None) -> Dict[str, Any]:
        """Return an ontology-owned projection suitable for enterprise map surfaces.

        Unlike ``seed`` and ``expand`` this does not model an interaction state.
        It returns a bounded, stable read model of graph nodes and relationships
        enriched with ontology layer/concept metadata. The projection is built
        in ``knowledge.ontology`` so builder surfaces and map surfaces share the
        same interpretation of raw graph facts.
        """
        kg = self.graph
        limit = max(1, min(500, int(limit or 200)))

        try:
            kg_nodes = kg.get_all_nodes(label_type="entity", limit=limit)
        except Exception as exc:
            logger.error("Explorer enterprise_map node fetch failed: %s", exc)
            kg_nodes = []

        kg_nodes = kg_nodes[:limit]
        nodes = [_node_to_dict(node, profile=self.profile) for node in kg_nodes]
        node_ids = [node["id"] for node in nodes if node.get("id")]
        node_id_set = set(node_ids)
        edges: List[Dict[str, Any]] = []
        seen_edges: set = set()

        if node_ids:
            try:
                triplets = kg.get_triplets(ids=node_ids)
            except Exception as exc:
                logger.error("Explorer enterprise_map triplet fetch failed: %s", exc)
                triplets = []

            for source, rel, target in triplets:
                s_id = getattr(source, "id", "")
                t_id = getattr(target, "id", "")
                if s_id not in node_id_set or t_id not in node_id_set:
                    continue
                r_key = (s_id, t_id, getattr(rel, "label", ""))
                if r_key in seen_edges:
                    continue
                seen_edges.add(r_key)
                edges.append(_relation_to_dict(rel, profile=self.profile, source_node=source, target_node=target))

        graph_result = self._apply_filters(
            {
                "nodes": nodes,
                "edges": edges,
                "stats": {
                    "source_node_count": len(nodes),
                    "source_edge_count": len(edges),
                    "limit": limit,
                    "filtered": bool(filters),
                },
            },
            filters,
        )
        projection = project_enterprise_map(graph_result["nodes"], graph_result["edges"], self.profile, group_by=group_by, color_by=color_by)
        projection["stats"].update(graph_result.get("stats") or {})
        projection["applied_group_by"] = projection.pop("applied_group_by", [])
        projection["applied_color_by"] = projection.pop("applied_color_by", "type")
        return self._with_meta(projection)

    def path(self, source_id: str, target_id: str) -> Dict[str, Any]:
        """Find the shortest weighted path between two nodes.

        Uses NetworkX shortest_path on the entity subgraph with
        relationship-type weighting.

        Args:
            source_id: Starting node ID.
            target_id: Ending node ID.

        Returns:
            Dict with path node IDs, path edges, nodes, and stats.
        """
        import networkx as nx  # noqa: WPS433

        kg = self.graph
        try:
            G = kg.get_all_nodes(label_type="entity", graph=True)
        except Exception as exc:
            logger.error("Explorer path graph fetch failed: %s", exc)
            return {"path": [], "nodes": [], "edges": [], "stats": {"path_length": 0}}

        if source_id not in G or target_id not in G:
            return {"path": [], "nodes": [], "edges": [], "stats": {"path_length": 0, "error": "node_not_found"}}

        try:
            path_nodes = nx.shortest_path(G, source_id, target_id, weight="weight")
        except nx.NetworkXNoPath:
            return {"path": [], "nodes": [], "edges": [], "stats": {"path_length": 0, "error": "no_path"}}
        except Exception as exc:
            logger.error("Explorer path computation failed: %s", exc)
            return {"path": [], "nodes": [], "edges": [], "stats": {"path_length": 0, "error": str(exc)}}

        # Fetch full node data for path nodes
        # Map NX node IDs to original entity IDs
        original_ids = []
        for nx_id in path_nodes:
            orig_id = G.nodes[nx_id].get("id", nx_id)
            original_ids.append(orig_id)

        nodes = self._fetch_nodes_by_ids(original_ids)

        # Get edges along the path
        path_edges = []
        for i in range(len(path_nodes) - 1):
            nx_s = path_nodes[i]
            nx_t = path_nodes[i + 1]
            orig_s = G.nodes[nx_s].get("id", nx_s)
            orig_t = G.nodes[nx_t].get("id", nx_t)
            edge_data = G.edges[nx_s, nx_t] if G.has_edge(nx_s, nx_t) else {}
            rel_label = edge_data.get("relation_label", edge_data.get("label", "RELATES"))
            rel_weight = edge_data.get("weight", 1.0)
            rel_obj = type("ExplorerPathRelation", (), {
                "source_id": orig_s,
                "target_id": orig_t,
                "label": rel_label,
                "properties": {"weight": rel_weight},
            })()
            path_edges.append(_relation_to_dict(rel_obj, profile=self.profile))

        return {
            "path": original_ids,
            "nodes": nodes,
            "edges": path_edges,
            "stats": {"path_length": len(original_ids)},
        }

    def node_detail(self, node_id: str) -> Dict[str, Any]:
        """Full detail for a single node: properties, incident edges, scores.

        Args:
            node_id: The node ID to inspect.

        Returns:
            Dict with node data, incident edges, and scores.
        """
        kg = self.graph
        try:
            node = kg.get_node(node_id)
        except Exception as exc:
            logger.error("Explorer node_detail fetch failed: %s", exc)
            return {"node": None, "edges": [], "stats": {}}

        if node is None:
            return {"node": None, "edges": [], "stats": {"error": "node_not_found"}}

        node_dict = _node_to_dict(node, profile=self.profile)

        # Get incident edges
        incident_edges = []
        try:
            triplets = kg.get_triplets(ids=[node_id])
            for source, rel, target in triplets:
                edge = _relation_to_dict(rel, profile=self.profile, source_node=source, target_node=target)
                # Annotate with whether this is incoming or outgoing
                s_id = getattr(source, "id", "")
                if s_id == node_id:
                    edge["direction"] = "outgoing"
                else:
                    edge["direction"] = "incoming"
                # Include peer node info
                peer = target if s_id == node_id else source
                edge["peer"] = _node_to_dict(peer, profile=self.profile)
                incident_edges.append(edge)
        except Exception as exc:
            logger.error("Explorer node_detail edges failed: %s", exc)

        # Compute degree
        out_degree = sum(1 for e in incident_edges if e.get("direction") == "outgoing")
        in_degree = sum(1 for e in incident_edges if e.get("direction") == "incoming")

        node_dict["degree"] = in_degree + out_degree
        node_dict["in_degree"] = in_degree
        node_dict["out_degree"] = out_degree

        edge_groups: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        for edge in incident_edges:
            rel_type = edge.get("relationship_type") or edge.get("label") or "RELATES"
            direction = edge.get("direction") or "outgoing"
            group = edge_groups.setdefault(str(rel_type), {"incoming": [], "outgoing": []})
            group.setdefault(str(direction), []).append(edge)

        return {
            "node": node_dict,
            "edges": incident_edges,
            "edge_groups": edge_groups,
            "stats": {
                "degree": in_degree + out_degree,
                "in_degree": in_degree,
                "out_degree": out_degree,
            },
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _with_meta(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Attach ontology profile summary without changing graph data shape."""
        meta = result.setdefault("meta", {})
        summary = _profile_summary(self.profile)
        meta["ontology_profile"] = summary
        meta["profile_exists"] = summary is not None
        graph_instruction = getattr(self.profile, "graph_instruction", None)
        meta["graph_instruction"] = graph_instruction.model_dump(mode="json") if graph_instruction is not None else {}
        meta["safe_defaults"] = summary is None
        return result

    def _apply_filters(self, result: Dict[str, Any], filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Apply ontology-driven include/exclude filters to a graph response."""
        if not filters:
            return result

        filters = {k: v for k, v in filters.items() if v not in (None, [], {})}
        if not filters:
            return result

        def clause(expected: Any) -> tuple[list[Any], str]:
            if isinstance(expected, dict) and "values" in expected:
                values = expected.get("values") or []
                mode = expected.get("mode") or "include"
            else:
                values = expected if isinstance(expected, list) else [expected]
                mode = "include"
            return list(values), "exclude" if mode == "exclude" else "include"

        def match_clause(value: Any, expected: Any) -> bool:
            if expected is None:
                return True
            values, mode = clause(expected)
            if not values:
                return True
            matched = value in values
            return not matched if mode == "exclude" else matched

        metadata_filters = filters.get("metadata") or {}
        nodes = []
        for node in result.get("nodes", []):
            layer_value = node.get("layer") or node.get("layer_id") or (node.get("ontology_path") or {}).get("layer")
            if not match_clause(node.get("concept_type"), filters.get("concept_type")):
                continue
            if not match_clause(node.get("abstraction_level"), filters.get("abstraction_level")):
                continue
            if not match_clause(layer_value, filters.get("layer")):
                continue
            if not match_clause(node.get("pack_id"), filters.get("pack_id")):
                continue
            if not match_clause(node.get("lifecycle_state"), filters.get("lifecycle_state")):
                continue
            props = node.get("properties") or {}
            metadata = node.get("metadata") or {}
            if filters.get("owner") is not None and not match_clause(node.get("owner") or props.get("owner") or metadata.get("owner"), filters.get("owner")):
                continue
            if any(metadata.get(key) != value and props.get(key) != value for key, value in metadata_filters.items()):
                continue
            nodes.append(node)

        node_ids = {node.get("id") for node in nodes}
        edges = []
        for edge in result.get("edges", []):
            if edge.get("source") not in node_ids or edge.get("target") not in node_ids:
                continue
            if not match_clause(edge.get("family"), filters.get("relationship_family")):
                continue
            if not match_clause(edge.get("relationship_type"), filters.get("relationship_type")):
                continue
            edges.append(edge)

        result = dict(result)
        result["nodes"] = nodes
        result["edges"] = edges
        stats = dict(result.get("stats") or {})
        stats["node_count"] = len(nodes)
        stats["edge_count"] = len(edges)
        stats["filtered"] = True
        result["stats"] = stats
        return result

    def _get_nx_graph(self) -> Any:
        """Get-or-compute the cached NetworkX entity subgraph.

        This is the same graph used by ``pagerank()`` — we cache it so
        community detection doesn't need to reload it.
        """
        import networkx as nx  # noqa: WPS433

        if self._nx_graph is not None:
            return self._nx_graph

        kg = self.graph
        G = kg.get_all_nodes(label_type="entity", graph=True)
        self._nx_graph = G
        return G

    def _detect_communities(self, G: Any = None) -> Dict[str, int]:
        """Run Louvain community detection on the entity subgraph.

        Uses NetworkX's ``community.louvain_communities`` which is a
        well-tested implementation that works on the same graph we already
        load for PageRank. Results are cached on the explorer instance.

        Returns:
            Dict mapping entity_id -> community_id (0-indexed).
        """
        import networkx as nx  # noqa: WPS433
        from networkx.algorithms.community import louvain_communities  # noqa: WPS433

        if self._community_map:
            return self._community_map

        if G is None:
            G = self._get_nx_graph()

        if G is None or len(G.nodes()) == 0:
            return {}

        try:
            # Convert MultiGraph to simple Graph for Louvain
            if isinstance(G, nx.MultiGraph):
                simple_G = nx.Graph()
                simple_G.add_nodes_from(G.nodes(data=True))
                for u, v, key, data in G.edges(data=True, keys=True):
                    weight = data.get("weight", 1.0)
                    if simple_G.has_edge(u, v):
                        simple_G.edges[u, v]["weight"] = simple_G.edges[u, v].get("weight", 0.0) + weight
                    else:
                        simple_G.add_edge(u, v, weight=weight)
            else:
                simple_G = G

            # Run Louvain community detection
            communities = louvain_communities(simple_G, weight="weight", seed=42)

            # Build mapping: entity_id -> community_id
            community_map: Dict[str, int] = {}
            for community_idx, community_set in enumerate(communities):
                for nx_node_id in community_set:
                    # Map NX node ID back to original entity ID
                    orig_id = G.nodes[nx_node_id].get("id", nx_node_id) if nx_node_id in G.nodes else nx_node_id
                    community_map[orig_id] = community_idx

            self._community_map = community_map
            logger.debug(
                "Louvain detected %d communities across %d nodes",
                len(communities), len(community_map),
            )
            return community_map

        except Exception as exc:
            logger.warning("Louvain community detection failed: %s", exc)
            return {}

    def _select_community_seeds(self, pr_scores: Dict[str, float], top_k: int) -> List[str]:
        """Select seed nodes using community-aware strategy.

        For each community, pick the node with the highest PageRank score
        as its representative. Fill remaining slots from the global
        PageRank ranking.

        This guarantees every community gets at least one seed, preventing
        the "all seeds in the densest cluster" problem.
        """
        if not pr_scores or not self._community_map:
            # No community data — fall back to pure PageRank top-K
            sorted_pr = sorted(pr_scores.items(), key=lambda x: x[1], reverse=True)
            return [pid for pid, _ in sorted_pr[:top_k]]

        # Group entity IDs by community
        communities: Dict[int, List[str]] = {}
        for eid, cid in self._community_map.items():
            communities.setdefault(cid, []).append(eid)

        # For each community, find the highest-PageRank node
        community_representatives: List[str] = []
        for cid in sorted(communities.keys()):
            members = communities[cid]
            # Sort members by PageRank score (default to 0 if not in pr_scores)
            members_sorted = sorted(members, key=lambda eid: pr_scores.get(eid, 0.0), reverse=True)
            if members_sorted:
                community_representatives.append(members_sorted[0])

        # If we have more communities than top_k, we still include one per community
        # (up to 2x top_k to avoid explosion on extremely fragmented graphs)
        max_seeds = max(top_k, min(len(community_representatives), top_k * 2))

        # Start with community representatives (guaranteed coverage)
        selected = set(community_representatives[:max_seeds])

        # Fill remaining slots from global PageRank ranking
        remaining = max_seeds - len(selected)
        if remaining > 0:
            sorted_pr = sorted(pr_scores.items(), key=lambda x: x[1], reverse=True)
            for pid, _ in sorted_pr:
                if pid not in selected:
                    selected.add(pid)
                    remaining -= 1
                    if remaining <= 0:
                        break

        return list(selected)

    def communities(self) -> Dict[str, Any]:
        """Return the Louvain community mapping for the entity subgraph.

        Runs community detection if not already cached. Returns:
        - ``community_map``: {entity_id: community_id}
        - ``community_count``: number of communities detected
        - ``community_sizes``: {community_id: member_count}
        """
        G = self._get_nx_graph()
        community_map = self._detect_communities(G)

        # Compute community sizes
        community_sizes: Dict[int, int] = {}
        for _, cid in community_map.items():
            community_sizes[cid] = community_sizes.get(cid, 0) + 1

        return {
            "community_map": community_map,
            "community_count": len(community_sizes),
            "community_sizes": community_sizes,
        }

    def _expand_from_ids(self, seed_ids: List[str], include_seed_info: bool = False) -> Dict[str, Any]:
        """Expand 1-hop from seed IDs and return the subgraph.

        This is the shared core for ``seed()`` and ``search()``.
        Includes ``community_id`` in node data when community detection
        has been run.
        """
        kg = self.graph
        all_node_ids = set(seed_ids)
        all_edges: List[Dict[str, Any]] = []
        seen_edges: set = set()

        try:
            triplets = kg.get_triplets(ids=seed_ids)
        except Exception as exc:
            logger.error("Explorer _expand_from_ids triplet fetch failed: %s", exc)
            triplets = []

        for source, rel, target in triplets:
            s_id = getattr(source, "id", "")
            t_id = getattr(target, "id", "")
            r_key = (s_id, t_id, getattr(rel, "label", ""))
            if r_key not in seen_edges:
                seen_edges.add(r_key)
                all_edges.append(_relation_to_dict(rel, profile=self.profile, source_node=source, target_node=target))
            all_node_ids.add(s_id)
            all_node_ids.add(t_id)

        nodes = self._fetch_nodes_by_ids(list(all_node_ids))

        # Filter edges to only those with both endpoints present
        node_id_set = {n["id"] for n in nodes}
        filtered_edges = [
            e for e in all_edges
            if e["source"] in node_id_set and e["target"] in node_id_set
        ]

        stats: Dict[str, Any] = {
            "node_count": len(nodes),
            "edge_count": len(filtered_edges),
        }
        if include_seed_info:
            stats["seed_count"] = len(seed_ids)
            stats["community_count"] = len(set(
                self._community_map.get(n["id"], -1)
                for n in nodes
                if n.get("community_id") is not None
            )) or 0

        return {
            "nodes": nodes,
            "edges": filtered_edges,
            "stats": stats,
        }

    def _fetch_nodes_by_ids(self, node_ids: List[str]) -> List[Dict[str, Any]]:
        """Fetch full node data for a list of IDs.

        Uses ``kg.get_by_ids()`` which is efficient for batch lookups.
        Falls back to individual ``get_node()`` calls if batch fails.

        Annotates each node with ``community_id`` when the Louvain
        community mapping is available on this explorer instance.
        """
        if not node_ids:
            return []

        kg = self.graph
        nodes: List[Dict[str, Any]] = []
        try:
            kg_nodes = kg.get_by_ids(node_ids)
            for n in kg_nodes:
                eid = getattr(n, "id", "")
                cid = self._community_map.get(eid) if self._community_map else None
                nodes.append(_node_to_dict(n, community_id=cid, profile=self.profile))
            return nodes
        except Exception as exc:
            logger.warning("Batch node fetch failed, falling back: %s", exc)

        # Fallback: individual fetches
        for nid in node_ids:
            try:
                n = kg.get_node(nid)
                if n is not None:
                    eid = getattr(n, "id", "")
                    cid = self._community_map.get(eid) if self._community_map else None
                    nodes.append(_node_to_dict(n, community_id=cid, profile=self.profile))
            except Exception:
                pass
        return nodes
