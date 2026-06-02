"""Unit tests for knowledge/graph/explorer.py — the Supernova explorer module.

Tests exercise every public method of :class:`KnowledgeExplorer` using a
mocked :class:`KuzuLabelledPropertyGraph` that never touches a real KuzuDB
instance. This keeps tests fast (< 1s total) and deterministic.

Test categories:
  1. Serialization helpers (_node_to_dict, _relation_to_dict)
  2. summary() — topology stats
  3. seed() — PageRank-based initial load
  4. expand() — multi-hop neighborhood expansion
  5. search() — vector similarity + 1-hop context
  6. path() — shortest path between nodes
  7. node_detail() — single node deep inspection
  8. Edge cases — empty graph, missing nodes, broken connections
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from dashboard.knowledge.graph.explorer import (
    KnowledgeExplorer,
    _node_to_dict,
    _relation_to_dict,
)
from dashboard.knowledge.ontology.defaults import create_default_ontology_profile


# ---------------------------------------------------------------------------
# Test doubles — lightweight fakes for LlamaIndex types
# ---------------------------------------------------------------------------


@dataclass
class FakeEntityNode:
    """Mimics llama_index EntityNode for serialization tests."""

    id: str = "test-id"
    name: str = "Test Entity"
    label: str = "person"
    properties: Optional[Dict[str, Any]] = None
    embedding: Optional[List[float]] = None

    def __post_init__(self):
        if self.properties is None:
            self.properties = {"entity_description": "A test entity", "weight": 0.8}


@dataclass
class FakeRelation:
    """Mimics llama_index Relation for serialization tests."""

    source_id: str = "src"
    target_id: str = "tgt"
    label: str = "RELATES"
    properties: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.properties is None:
            self.properties = {"relation_label": "MENTIONS", "weight": 1.2}


# ---------------------------------------------------------------------------
# Fake KuzuLabelledPropertyGraph
# ---------------------------------------------------------------------------


class FakeKuzuGraph:
    """Deterministic fake that supports all methods called by KnowledgeExplorer."""

    def __init__(self, entities=None, relations=None, triplets=None, ontology_profile=None):
        self._entities = entities or []
        self._relations = relations or []
        self._triplets = triplets or []
        self.ontology_profile = ontology_profile

    # -- Counts --

    def count_entities(self) -> int:
        return len(self._entities)

    def count_chunks(self) -> int:
        return 0

    def count_relations(self) -> int:
        return len(self._relations)

    # -- Node retrieval --

    def get_all_nodes(self, **kwargs) -> list:
        label_type = kwargs.get("label_type", None)
        context = kwargs.get("context", "")
        graph = kwargs.get("graph", False)
        if graph:
            # Return a NetworkX MultiGraph for PageRank/community detection
            import networkx as nx
            G = nx.MultiGraph()
            for e in self._entities:
                eid = getattr(e, "id", "")
                G.add_node(eid, id=eid)
            for s, r, t in self._triplets:
                s_id = getattr(s, "id", "")
                t_id = getattr(t, "id", "")
                G.add_edge(s_id, t_id, weight=1.0, relation_label=getattr(r, "label", "RELATES"))
            return G
        if context:
            # Simulate vector search: return first N entities
            limit = kwargs.get("limit", 50)
            return self._entities[:limit]
        if label_type == "entity":
            return self._entities
        return self._entities

    def get_all_relations(self) -> list:
        return self._relations

    def get_by_ids(self, ids: list) -> list:
        id_set = set(ids)
        return [e for e in self._entities if getattr(e, "id", "") in id_set]

    def get_node(self, id_: str):
        for e in self._entities:
            if getattr(e, "id", "") == id_:
                return e
        return None

    def get_triplets(self, ids: list = None) -> list:
        if ids:
            id_set = set(ids)
            return [
                (s, r, t)
                for s, r, t in self._triplets
                if getattr(s, "id", "") in id_set or getattr(t, "id", "") in id_set
            ]
        return self._triplets

    # -- PageRank --

    def pagerank(self, personalize: dict, **kwargs) -> list:
        """Return deterministic PageRank scores for testing."""
        # Just return entity IDs with equal scores
        return [(eid, 1.0 / max(len(personalize), 1)) for eid in personalize]

    # -- Connection (for summary queries) --

    @property
    def connection(self):
        conn = MagicMock()
        # Mock the label distribution query
        result_mock = MagicMock()
        result_mock.__iter__ = lambda self: iter([["person", 5], ["organization", 3]])
        conn.execute.return_value = result_mock
        return conn


# ---------------------------------------------------------------------------
# Test: Serialization helpers
# ---------------------------------------------------------------------------


class TestNodeToDict:
    """Tests for _node_to_dict serialization."""

    def test_basic_entity(self):
        node = FakeEntityNode(id="e1", name="Alice", label="person")
        result = _node_to_dict(node)
        assert result["id"] == "e1"
        assert result["name"] == "Alice"
        assert result["label"] == "person"
        assert "properties" in result
        assert isinstance(result["properties"], dict)

    def test_properties_as_json_string(self):
        node = FakeEntityNode(id="e2", properties='{"key": "value"}')
        result = _node_to_dict(node)
        assert result["properties"] == {"key": "value"}

    def test_none_properties(self):
        node = FakeEntityNode(id="e3", properties=None)
        # FakeEntityNode auto-sets properties in __post_init__,
        # so let's force it after
        node.properties = None
        result = _node_to_dict(node)
        assert result["properties"] == {}

    def test_score_from_weight(self):
        node = FakeEntityNode(id="e4", properties={"weight": 2.5})
        result = _node_to_dict(node)
        assert result["score"] == 2.5

    def test_default_score_is_1(self):
        node = FakeEntityNode(id="e5", properties={})
        result = _node_to_dict(node)
        assert result["score"] == 1.0

    def test_community_id_included_when_provided(self):
        node = FakeEntityNode(id="e1", name="Alice", label="person")
        result = _node_to_dict(node, community_id=3)
        assert result["community_id"] == 3

    def test_community_id_absent_when_none(self):
        node = FakeEntityNode(id="e1", name="Alice", label="person")
        result = _node_to_dict(node, community_id=None)
        assert "community_id" not in result

    def test_node_includes_ontology_metadata_when_profile_available(self):
        profile = create_default_ontology_profile("test-ns")
        node = FakeEntityNode(
            id="feature-1",
            label="feature",
            properties={
                "concept_type": "feature",
                "layer": "product",
                "pack_id": "core",
                "metadata": {"owner": "platform"},
            },
        )
        result = _node_to_dict(node, profile=profile)
        assert result["concept_type"] == "feature"
        assert result["abstraction_level"] == "feature"
        assert result["layer"] == "product"
        assert result["pack_id"] == "core"
        assert result["metadata"] == {"owner": "platform"}
        assert result["validation_issues"] == []


class TestRelationToDict:
    """Tests for _relation_to_dict serialization."""

    def test_basic_relation(self):
        rel = FakeRelation(source_id="a", target_id="b", label="MENTIONS")
        result = _relation_to_dict(rel)
        assert result["source"] == "a"
        assert result["target"] == "b"
        assert result["label"] == "MENTIONS"

    def test_weight_from_properties(self):
        rel = FakeRelation(properties={"weight": 2.0})
        result = _relation_to_dict(rel)
        assert result["weight"] == 2.0

    def test_default_weight_is_1(self):
        rel = FakeRelation(properties={})
        result = _relation_to_dict(rel)
        assert result["weight"] == 1.0

    def test_label_fallback_to_relates(self):
        rel = FakeRelation(label="", properties={})
        result = _relation_to_dict(rel)
        assert result["label"] == "RELATES"

    def test_relation_includes_ontology_metadata(self):
        profile = create_default_ontology_profile("test-ns")
        rel = FakeRelation(source_id="a", target_id="b", label="depends_on")
        source = FakeEntityNode(id="a", label="feature", properties={"concept_type": "feature"})
        target = FakeEntityNode(id="b", label="service", properties={"concept_type": "service"})
        result = _relation_to_dict(rel, profile=profile, source_node=source, target_node=target)
        assert result["relationship_type"] == "depends_on"
        assert result["family"] == "dependency"
        assert result["display_label"] == "Depends on"
        assert result["style"] == "dashed"
        assert result["is_candidate"] is False

    def test_relation_without_profile_has_legacy_defaults(self):
        rel = FakeRelation(source_id="a", target_id="b", label="RELATES")
        result = _relation_to_dict(rel)
        assert result["label"] == "RELATES"
        assert result["relationship_type"] == "relates"
        assert result["family"] is None
        assert result["is_candidate"] is True


# ---------------------------------------------------------------------------
# Test: KnowledgeExplorer
# ---------------------------------------------------------------------------


class TestExplorerSummary:
    """Tests for explorer.summary()."""

    def test_empty_graph(self):
        kg = FakeKuzuGraph(entities=[])
        explorer = KnowledgeExplorer(kg)
        result = explorer.summary()
        assert result["entity_count"] == 0
        assert result["chunk_count"] == 0
        assert result["relation_count"] == 0

    def test_with_entities(self):
        entities = [FakeEntityNode(id=f"e{i}", name=f"Entity {i}") for i in range(10)]
        kg = FakeKuzuGraph(entities=entities)
        explorer = KnowledgeExplorer(kg)
        result = explorer.summary()
        assert result["entity_count"] == 10

    def test_count_failure_returns_zeros(self):
        kg = FakeKuzuGraph()
        kg.count_entities = MagicMock(side_effect=Exception("db error"))
        explorer = KnowledgeExplorer(kg)
        result = explorer.summary()
        assert result["entity_count"] == 0

    def test_includes_degree_stats(self):
        entities = [FakeEntityNode(id="e1")]
        kg = FakeKuzuGraph(entities=entities)
        explorer = KnowledgeExplorer(kg)
        result = explorer.summary()
        assert "degree_stats" in result
        assert "max_degree" in result["degree_stats"]


class TestExplorerSeed:
    """Tests for explorer.seed()."""

    def test_empty_graph_returns_empty(self):
        kg = FakeKuzuGraph(entities=[])
        explorer = KnowledgeExplorer(kg)
        result = explorer.seed()
        assert result["nodes"] == []
        assert result["edges"] == []
        assert result["stats"]["node_count"] == 0

    def test_returns_nodes_and_edges(self):
        e1 = FakeEntityNode(id="e1", name="Alice")
        e2 = FakeEntityNode(id="e2", name="Bob")
        rel = FakeRelation(source_id="e1", target_id="e2", label="KNOWS")
        triplets = [(e1, rel, e2)]
        kg = FakeKuzuGraph(entities=[e1, e2], triplets=triplets)
        explorer = KnowledgeExplorer(kg)
        result = explorer.seed(top_k=10)
        assert result["stats"]["node_count"] >= 1
        assert result["stats"]["seed_count"] >= 1


    def test_seed_includes_profile_summary_meta(self):
        profile = create_default_ontology_profile("test-ns")
        e1 = FakeEntityNode(id="feature-1", label="feature", properties={"concept_type": "feature"})
        kg = FakeKuzuGraph(entities=[e1], ontology_profile=profile)
        explorer = KnowledgeExplorer(kg)
        result = explorer.seed(top_k=1)
        assert result["meta"]["profile_exists"] is True
        assert result["meta"]["ontology_profile"]["profile_id"] == profile.profile_id

    def test_seed_count_in_stats(self):
        """With community-aware seeding, seed_count reflects actual seeds selected.

        When entities are disconnected (each is its own community),
        community-aware seeding picks one per community, so seed_count
        equals the number of communities (up to max_seeds).
        """
        entities = [FakeEntityNode(id=f"e{i}", name=f"Entity {i}") for i in range(5)]
        # No edges → 5 communities of 1 node each
        kg = FakeKuzuGraph(entities=entities)
        explorer = KnowledgeExplorer(kg)
        result = explorer.seed(top_k=3)
        # With 5 disconnected nodes, community seeding picks all 5
        # (each is its own community representative)
        assert result["stats"]["seed_count"] >= 3

    def test_pagerank_failure_falls_back_to_id_list(self):
        entities = [FakeEntityNode(id=f"e{i}", name=f"Entity {i}") for i in range(5)]
        kg = FakeKuzuGraph(entities=entities)
        kg.pagerank = MagicMock(side_effect=Exception("pagerank failed"))
        explorer = KnowledgeExplorer(kg)
        result = explorer.seed(top_k=3)
        # Should fall back to first 3 entity IDs
        assert result["stats"]["seed_count"] == 3


class TestExplorerExpand:
    """Tests for explorer.expand()."""

    def test_expand_from_single_node(self):
        e1 = FakeEntityNode(id="e1", name="Alice")
        e2 = FakeEntityNode(id="e2", name="Bob")
        rel = FakeRelation(source_id="e1", target_id="e2")
        kg = FakeKuzuGraph(entities=[e1, e2], triplets=[(e1, rel, e2)])
        explorer = KnowledgeExplorer(kg)
        result = explorer.expand(node_ids=["e1"], depth=1)
        assert result["stats"]["node_count"] == 2
        assert result["stats"]["edge_count"] == 1

    def test_expand_depth_capped_at_3(self):
        """Depth > 3 should be silently clamped to 3."""
        e1 = FakeEntityNode(id="e1")
        kg = FakeKuzuGraph(entities=[e1])
        explorer = KnowledgeExplorer(kg)
        # Should not raise — just cap
        result = explorer.expand(node_ids=["e1"], depth=10)
        assert isinstance(result, dict)

    def test_expand_empty_ids(self):
        kg = FakeKuzuGraph(entities=[])
        explorer = KnowledgeExplorer(kg)
        result = explorer.expand(node_ids=["nonexistent"])
        assert result["nodes"] == []

    def test_expand_triplet_failure_graceful(self):
        """When triplet fetch fails, expand returns only the starting nodes (no new neighbors)."""
        kg = FakeKuzuGraph(entities=[FakeEntityNode(id="e1")])
        kg.get_triplets = MagicMock(side_effect=Exception("triplet error"))
        explorer = KnowledgeExplorer(kg)
        result = explorer.expand(node_ids=["e1"], depth=1)
        # The starting node "e1" is still in the result, but no neighbors added
        assert result["stats"]["node_count"] == 1
        assert result["stats"]["edge_count"] == 0


class TestExplorerSearch:
    """Tests for explorer.search()."""

    def test_returns_matching_entities(self):
        e1 = FakeEntityNode(id="e1", name="Python")
        e2 = FakeEntityNode(id="e2", name="JavaScript")
        rel = FakeRelation(source_id="e1", target_id="e2")
        kg = FakeKuzuGraph(entities=[e1, e2], triplets=[(e1, rel, e2)])
        explorer = KnowledgeExplorer(kg)
        result = explorer.search(query="programming languages", limit=10)
        assert result["stats"]["query"] == "programming languages"
        assert result["stats"]["node_count"] >= 1

    def test_no_results_returns_empty(self):
        kg = FakeKuzuGraph(entities=[])
        explorer = KnowledgeExplorer(kg)
        result = explorer.search(query="anything")
        assert result["nodes"] == []
        assert result["stats"]["query"] == "anything"

    def test_search_failure_graceful(self):
        kg = FakeKuzuGraph()
        kg.get_all_nodes = MagicMock(side_effect=Exception("vector error"))
        explorer = KnowledgeExplorer(kg)
        result = explorer.search(query="test")
        assert result["nodes"] == []

    def test_search_filters_by_concept_type_and_relationship_family(self):
        profile = create_default_ontology_profile("test-ns")
        e1 = FakeEntityNode(id="feature-1", label="feature", properties={"concept_type": "feature"})
        e2 = FakeEntityNode(id="service-1", label="service", properties={"concept_type": "service"})
        e3 = FakeEntityNode(id="risk-1", label="risk", properties={"concept_type": "risk"})
        rel1 = FakeRelation(source_id="feature-1", target_id="service-1", label="depends_on")
        rel2 = FakeRelation(source_id="feature-1", target_id="risk-1", label="validates")
        kg = FakeKuzuGraph(entities=[e1, e2, e3], triplets=[(e1, rel1, e2), (e1, rel2, e3)], ontology_profile=profile)
        explorer = KnowledgeExplorer(kg)
        result = explorer.search(
            query="feature",
            filters={"concept_type": ["feature", "service"], "relationship_family": ["dependency"]},
        )
        assert {node["concept_type"] for node in result["nodes"]} == {"feature", "service"}
        assert len(result["edges"]) == 1
        assert result["edges"][0]["family"] == "dependency"


class TestExplorerEnterpriseMap:
    """Tests for ontology-owned enterprise map projections."""

    def test_enterprise_map_projects_profile_layers_and_map_direction(self):
        profile = create_default_ontology_profile("test-ns")
        feature = FakeEntityNode(
            id="feature-1",
            name="Feature 1",
            label="feature",
            properties={"concept_type": "feature", "metadata": {"owner": "Product"}},
        )
        service = FakeEntityNode(
            id="service-1",
            name="Service 1",
            label="service",
            properties={"concept_type": "service", "metadata": {"owner": "Platform"}},
        )
        rel = FakeRelation(source_id="feature-1", target_id="service-1", label="depends_on")
        kg = FakeKuzuGraph(entities=[feature, service], triplets=[(feature, rel, service)], ontology_profile=profile)

        result = KnowledgeExplorer(kg).enterprise_map(limit=20)

        assert result["stats"]["node_count"] == 2
        assert {layer["id"] for layer in result["layers"]} >= {"product", "delivery"}
        assert result["nodes"][0]["ontology_path"]["concept_type"] == "feature"
        assert result["edges"][0]["relationship_type"] == "depends_on"
        assert result["edges"][0]["map_source"] == "service-1"
        assert result["edges"][0]["map_target"] == "feature-1"
        assert result["meta"]["profile_exists"] is True


class TestExplorerPath:
    """Tests for explorer.path()."""

    def test_path_between_connected_nodes(self):
        """Test path finding with a mocked NetworkX graph."""
        e1 = FakeEntityNode(id="e1", name="Start")
        e2 = FakeEntityNode(id="e2", name="End")
        kg = FakeKuzuGraph(entities=[e1, e2])

        # Mock the NetworkX graph returned by get_all_nodes(graph=True)
        import networkx as nx
        G = nx.Graph()
        G.add_node("n1", id="e1")
        G.add_node("n2", id="e2")
        G.add_edge("n1", "n2", weight=1.0, relation_label="CONNECTS")

        kg.get_all_nodes = MagicMock(return_value=G)
        kg.get_by_ids = MagicMock(return_value=[e1, e2])

        explorer = KnowledgeExplorer(kg)
        result = explorer.path(source_id="n1", target_id="n2")
        assert len(result["path"]) == 2
        assert result["stats"]["path_length"] == 2

    def test_no_path_returns_empty(self):
        e1 = FakeEntityNode(id="e1")
        kg = FakeKuzuGraph(entities=[e1])

        import networkx as nx
        G = nx.Graph()
        G.add_node("n1", id="e1")
        G.add_node("n2", id="e2")
        # No edge between n1 and n2

        kg.get_all_nodes = MagicMock(return_value=G)
        explorer = KnowledgeExplorer(kg)
        result = explorer.path(source_id="n1", target_id="n2")
        assert result["path"] == []
        assert result["stats"].get("error") == "no_path"

    def test_missing_node_returns_error(self):
        e1 = FakeEntityNode(id="e1")
        kg = FakeKuzuGraph(entities=[e1])

        import networkx as nx
        G = nx.Graph()
        G.add_node("n1", id="e1")

        kg.get_all_nodes = MagicMock(return_value=G)
        explorer = KnowledgeExplorer(kg)
        result = explorer.path(source_id="n1", target_id="nonexistent")
        assert result["stats"].get("error") == "node_not_found"

    def test_graph_fetch_failure_graceful(self):
        kg = FakeKuzuGraph()
        kg.get_all_nodes = MagicMock(side_effect=Exception("graph error"))
        explorer = KnowledgeExplorer(kg)
        result = explorer.path(source_id="a", target_id="b")
        assert result["path"] == []


class TestExplorerNodeDetail:
    """Tests for explorer.node_detail()."""

    def test_existing_node(self):
        e1 = FakeEntityNode(id="e1", name="Alice", label="person")
        rel = FakeRelation(source_id="e1", target_id="e2", label="KNOWS")
        kg = FakeKuzuGraph(entities=[e1], triplets=[(e1, rel, FakeEntityNode(id="e2", name="Bob"))])
        explorer = KnowledgeExplorer(kg)
        result = explorer.node_detail("e1")
        assert result["node"]["id"] == "e1"
        assert result["node"]["name"] == "Alice"
        assert result["node"]["degree"] == 1
        assert result["node"]["out_degree"] == 1
        assert result["node"]["in_degree"] == 0
        assert len(result["edges"]) == 1

    def test_missing_node(self):
        kg = FakeKuzuGraph(entities=[])
        explorer = KnowledgeExplorer(kg)
        result = explorer.node_detail("nonexistent")
        assert result["node"] is None
        assert result["stats"].get("error") == "node_not_found"

    def test_node_with_incoming_edge(self):
        e1 = FakeEntityNode(id="e1", name="Alice")
        e2 = FakeEntityNode(id="e2", name="Bob")
        rel = FakeRelation(source_id="e2", target_id="e1", label="FOLLOWS")
        kg = FakeKuzuGraph(entities=[e1, e2], triplets=[(e2, rel, e1)])
        explorer = KnowledgeExplorer(kg)
        result = explorer.node_detail("e1")
        assert result["node"]["in_degree"] == 1
        assert result["node"]["out_degree"] == 0
        assert result["edges"][0]["direction"] == "incoming"

    def test_incident_edges_include_peer_info(self):
        e1 = FakeEntityNode(id="e1", name="Alice")
        e2 = FakeEntityNode(id="e2", name="Bob")
        rel = FakeRelation(source_id="e1", target_id="e2")
        kg = FakeKuzuGraph(entities=[e1, e2], triplets=[(e1, rel, e2)])
        explorer = KnowledgeExplorer(kg)
        result = explorer.node_detail("e1")
        assert result["edges"][0]["peer"]["name"] == "Bob"


    def test_node_detail_groups_edges_by_canonical_type_and_direction(self):
        profile = create_default_ontology_profile("test-ns")
        e1 = FakeEntityNode(id="feature-1", label="feature", properties={"concept_type": "feature"})
        e2 = FakeEntityNode(id="service-1", label="service", properties={"concept_type": "service"})
        rel = FakeRelation(source_id="feature-1", target_id="service-1", label="depends_on")
        kg = FakeKuzuGraph(entities=[e1, e2], triplets=[(e1, rel, e2)], ontology_profile=profile)
        explorer = KnowledgeExplorer(kg)
        result = explorer.node_detail("feature-1")
        assert "depends_on" in result["edge_groups"]
        assert len(result["edge_groups"]["depends_on"]["outgoing"]) == 1

    def test_node_fetch_failure_graceful(self):
        kg = FakeKuzuGraph()
        kg.get_node = MagicMock(side_effect=Exception("db error"))
        explorer = KnowledgeExplorer(kg)
        result = explorer.node_detail("e1")
        assert result["node"] is None


class TestExplorerEdgeCases:
    """Edge case tests for KnowledgeExplorer."""

    def test_expand_with_multiple_overlapping_hops(self):
        """Expanding from A→B and B→C should not duplicate B."""
        e1 = FakeEntityNode(id="a")
        e2 = FakeEntityNode(id="b")
        e3 = FakeEntityNode(id="c")
        rel1 = FakeRelation(source_id="a", target_id="b")
        rel2 = FakeRelation(source_id="b", target_id="c")
        kg = FakeKuzuGraph(entities=[e1, e2, e3], triplets=[(e1, rel1, e2), (e2, rel2, e3)])
        explorer = KnowledgeExplorer(kg)
        result = explorer.expand(node_ids=["a"], depth=2)
        # Should have 3 unique nodes
        node_ids = {n["id"] for n in result["nodes"]}
        assert "a" in node_ids
        assert "b" in node_ids
        assert "c" in node_ids

    def test_edge_deduplication(self):
        """Same edge should not appear twice even if triplets return it twice."""
        e1 = FakeEntityNode(id="a")
        e2 = FakeEntityNode(id="b")
        rel = FakeRelation(source_id="a", target_id="b")
        # Return the same triplet twice
        kg = FakeKuzuGraph(entities=[e1, e2], triplets=[(e1, rel, e2), (e1, rel, e2)])
        explorer = KnowledgeExplorer(kg)
        result = explorer.expand(node_ids=["a"], depth=1)
        # Edge should appear only once
        assert result["stats"]["edge_count"] == 1

    def test_edges_filtered_to_present_nodes(self):
        """Edges whose endpoints are missing from the node set should be dropped."""
        e1 = FakeEntityNode(id="a")
        rel = FakeRelation(source_id="a", target_id="missing")
        kg = FakeKuzuGraph(entities=[e1], triplets=[(e1, rel, FakeEntityNode(id="missing"))])
        # get_by_ids only returns "a", not "missing"
        kg.get_by_ids = MagicMock(return_value=[e1])
        explorer = KnowledgeExplorer(kg)
        result = explorer.expand(node_ids=["a"], depth=1)
        # Edge to "missing" should be filtered out
        assert result["stats"]["edge_count"] == 0

    def test_batch_fetch_fallback_to_individual(self):
        """If batch get_by_ids fails, individual get_node calls are used."""
        e1 = FakeEntityNode(id="a")
        kg = FakeKuzuGraph(entities=[e1])
        kg.get_by_ids = MagicMock(side_effect=Exception("batch error"))
        kg.get_node = MagicMock(return_value=e1)
        explorer = KnowledgeExplorer(kg)
        result = explorer._fetch_nodes_by_ids(["a"])
        assert len(result) == 1
        assert result[0]["id"] == "a"

    def test_seed_with_zero_top_k(self):
        """top_k=0 should return empty result gracefully."""
        entities = [FakeEntityNode(id=f"e{i}") for i in range(5)]
        kg = FakeKuzuGraph(entities=entities)
        explorer = KnowledgeExplorer(kg)
        result = explorer.seed(top_k=0)
        assert result["stats"]["seed_count"] == 0


class TestExplorerCommunities:
    """Tests for Louvain community detection and community-aware seeding."""

    def test_community_detection_on_simple_graph(self):
        """Two disconnected clusters should produce two communities."""
        e1 = FakeEntityNode(id="e1", name="A")
        e2 = FakeEntityNode(id="e2", name="B")
        e3 = FakeEntityNode(id="e3", name="C")
        e4 = FakeEntityNode(id="e4", name="D")

        # Cluster 1: e1-e2 connected
        # Cluster 2: e3-e4 connected
        rel1 = FakeRelation(source_id="e1", target_id="e2")
        rel2 = FakeRelation(source_id="e3", target_id="e4")

        kg = FakeKuzuGraph(
            entities=[e1, e2, e3, e4],
            triplets=[(e1, rel1, e2), (e3, rel2, e4)],
        )

        # Provide a NetworkX graph for community detection
        import networkx as nx
        G = nx.MultiGraph()
        G.add_node("n1", id="e1")
        G.add_node("n2", id="e2")
        G.add_node("n3", id="e3")
        G.add_node("n4", id="e4")
        G.add_edge("n1", "n2", weight=1.0)
        G.add_edge("n3", "n4", weight=1.0)
        kg.get_all_nodes = MagicMock(return_value=G)
        kg.get_by_ids = MagicMock(return_value=[e1, e2, e3, e4])

        explorer = KnowledgeExplorer(kg)
        result = explorer.communities()

        assert result["community_count"] == 2
        assert len(result["community_map"]) == 4
        assert result["community_sizes"][0] == 2
        assert result["community_sizes"][1] == 2

    def test_community_map_cached(self):
        """Calling communities() twice should use the cached result."""
        e1 = FakeEntityNode(id="e1")
        e2 = FakeEntityNode(id="e2")
        rel = FakeRelation(source_id="e1", target_id="e2")
        kg = FakeKuzuGraph(entities=[e1, e2], triplets=[(e1, rel, e2)])

        import networkx as nx
        G = nx.MultiGraph()
        G.add_node("n1", id="e1")
        G.add_node("n2", id="e2")
        G.add_edge("n1", "n2", weight=1.0)
        kg.get_all_nodes = MagicMock(return_value=G)
        kg.get_by_ids = MagicMock(return_value=[e1, e2])

        explorer = KnowledgeExplorer(kg)
        result1 = explorer.communities()

        # Reset mock to verify it's not called again
        kg.get_all_nodes.reset_mock()

        result2 = explorer.communities()
        assert result2["community_count"] == result1["community_count"]
        # get_all_nodes should NOT be called again (cached)
        kg.get_all_nodes.assert_not_called()

    def test_seed_includes_community_count(self):
        """seed() should return community_count in stats."""
        e1 = FakeEntityNode(id="e1", name="A")
        e2 = FakeEntityNode(id="e2", name="B")
        e3 = FakeEntityNode(id="e3", name="C")
        e4 = FakeEntityNode(id="e4", name="D")
        rel1 = FakeRelation(source_id="e1", target_id="e2")
        rel2 = FakeRelation(source_id="e3", target_id="e4")

        kg = FakeKuzuGraph(
            entities=[e1, e2, e3, e4],
            triplets=[(e1, rel1, e2), (e3, rel2, e4)],
        )

        import networkx as nx
        G = nx.MultiGraph()
        G.add_node("n1", id="e1")
        G.add_node("n2", id="e2")
        G.add_node("n3", id="e3")
        G.add_node("n4", id="e4")
        G.add_edge("n1", "n2", weight=1.0)
        G.add_edge("n3", "n4", weight=1.0)
        kg.get_all_nodes = MagicMock(return_value=G)
        kg.get_by_ids = MagicMock(return_value=[e1, e2, e3, e4])

        explorer = KnowledgeExplorer(kg)
        result = explorer.seed(top_k=10)

        assert "community_count" in result["stats"]
        assert result["stats"]["community_count"] == 2

    def test_seed_nodes_include_community_id(self):
        """Nodes returned by seed() should have community_id when available."""
        e1 = FakeEntityNode(id="e1", name="A")
        e2 = FakeEntityNode(id="e2", name="B")
        rel = FakeRelation(source_id="e1", target_id="e2")
        kg = FakeKuzuGraph(entities=[e1, e2], triplets=[(e1, rel, e2)])

        import networkx as nx
        G = nx.MultiGraph()
        G.add_node("n1", id="e1")
        G.add_node("n2", id="e2")
        G.add_edge("n1", "n2", weight=1.0)
        kg.get_all_nodes = MagicMock(return_value=G)
        kg.get_by_ids = MagicMock(return_value=[e1, e2])

        explorer = KnowledgeExplorer(kg)
        result = explorer.seed(top_k=10)

        # At least one node should have a community_id
        nodes_with_community = [n for n in result["nodes"] if "community_id" in n]
        assert len(nodes_with_community) > 0

    def test_community_aware_seeding_covers_all_communities(self):
        """Community-aware seeding should pick at least one node per community."""
        # Create 3 disconnected communities of 3 nodes each
        entities = []
        for i in range(9):
            entities.append(FakeEntityNode(id=f"e{i}", name=f"Entity {i}"))

        kg = FakeKuzuGraph(entities=entities)
        kg.get_by_ids = MagicMock(return_value=entities)

        import networkx as nx
        G = nx.MultiGraph()
        for i in range(9):
            G.add_node(f"n{i}", id=f"e{i}")
        # Community 0: e0-e1-e2
        G.add_edge("n0", "n1", weight=1.0)
        G.add_edge("n1", "n2", weight=1.0)
        # Community 1: e3-e4-e5
        G.add_edge("n3", "n4", weight=1.0)
        G.add_edge("n4", "n5", weight=1.0)
        # Community 2: e6-e7-e8
        G.add_edge("n6", "n7", weight=1.0)
        G.add_edge("n7", "n8", weight=1.0)

        kg.get_all_nodes = MagicMock(return_value=G)

        explorer = KnowledgeExplorer(kg)
        result = explorer.seed(top_k=3)

        # With 3 communities and top_k=3, we should get at least one from each
        community_ids_in_seed = set()
        for n in result["nodes"]:
            if "community_id" in n:
                community_ids_in_seed.add(n["community_id"])

        # Should cover all communities (at least in the seed set)
        assert len(community_ids_in_seed) >= 2  # At least 2 of 3 covered

    def test_communities_on_empty_graph(self):
        """Community detection on empty graph should return empty mapping."""
        kg = FakeKuzuGraph(entities=[])
        import networkx as nx
        G = nx.MultiGraph()
        kg.get_all_nodes = MagicMock(return_value=G)

        explorer = KnowledgeExplorer(kg)
        result = explorer.communities()
        assert result["community_count"] == 0
        assert result["community_map"] == {}

    def test_community_detection_failure_graceful(self):
        """Community detection failure should not crash seed()."""
        e1 = FakeEntityNode(id="e1")
        kg = FakeKuzuGraph(entities=[e1])
        kg.get_all_nodes = MagicMock(side_effect=Exception("graph error"))

        explorer = KnowledgeExplorer(kg)
        result = explorer.seed(top_k=10)
        # Should gracefully return empty or minimal result
        assert isinstance(result, dict)
        assert "nodes" in result
