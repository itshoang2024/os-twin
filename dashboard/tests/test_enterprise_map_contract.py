from __future__ import annotations

import re
from pathlib import Path

import pytest
from dashboard.knowledge.graph.explorer import KnowledgeExplorer
from dashboard.knowledge.service import KnowledgeService
from dashboard.routes.knowledge_models import (
    EnterpriseMapEdgeResponse,
    EnterpriseMapNodeResponse,
    EnterpriseMapProjectionResponse,
    ExplorerOntologyFilters,
    TimeRangeResponse,
)
from pydantic import ValidationError


class FakeNode:
    def __init__(self, node_id: str, label: str = "entity", **properties):
        self.id = node_id
        self.label = label
        self.name = properties.get("name", node_id)
        self.properties = properties


class FakeRel:
    def __init__(self, source_id: str, target_id: str, label: str = "RELATES", **properties):
        self.source_id = source_id
        self.target_id = target_id
        self.label = label
        self.properties = properties


class FakeGraph:
    def __init__(self):
        self.nodes = {
            "flight-1": FakeNode("flight-1", concept_type="flight", layer="ops", owner="ops"),
            "airport-1": FakeNode("airport-1", concept_type="airport", layer="ops", owner="ops"),
            "policy-1": FakeNode("policy-1", concept_type="policy", layer="governance", owner="legal"),
        }
        self.rels = [
            FakeRel("flight-1", "airport-1", "USES", relationship_type="uses", relationship_family="dependency"),
            FakeRel("policy-1", "flight-1", "GOVERNS", relationship_type="governs", relationship_family="governance"),
        ]

    def get_graph(self, limit=200):
        nodes = []
        for node in self.nodes.values():
            nodes.append({
                "id": node.id,
                "label": node.label,
                "name": node.name,
                "score": 1.0,
                "properties": node.properties,
            })
        edges = [
            {
                "source": rel.source_id,
                "target": rel.target_id,
                "label": rel.label,
                "weight": 1.0,
                "properties": rel.properties,
            }
            for rel in self.rels
        ]
        return {"nodes": nodes[:limit], "edges": edges, "stats": {"ontology_candidate_count": 3}}

    def get_triplets(self, ids):
        ids = set(ids)
        return [
            (self.nodes[rel.source_id], rel, self.nodes[rel.target_id])
            for rel in self.rels
            if rel.source_id in ids or rel.target_id in ids
        ]

    def get_by_ids(self, ids):
        return [self.nodes[node_id] for node_id in ids if node_id in self.nodes]


def test_enterprise_map_response_models_are_precise_and_additive():
    absent = EnterpriseMapNodeResponse(id="n1", name="Node")
    assert absent.model_dump()["series_refs"] == []
    assert absent.time_range is None

    present = EnterpriseMapNodeResponse.model_validate({
        "id": "n1",
        "name": "Node",
        "event_count": 2,
        "active_event_count": 1,
        "time_range": {"start": "2026-01-01", "end": None},
        "series_refs": ["s1"],
        "flow_refs": ["f1"],
        "simulation_refs": ["sim1"],
        "state": "ready",
        "simulation_state": "idle",
        "state_machine_ref": "sm",
        "state_color": "#fff",
        "phase": "alpha",
        "track": "main",
        "priority": 1,
        "effort": "m",
        "prerequisites": ["p1"],
        "acceptance": ["done"],
    })
    assert present.time_range == TimeRangeResponse(start="2026-01-01", end=None)
    assert present.event_count == 2

    node_schema = EnterpriseMapNodeResponse.model_json_schema()["properties"]
    edge_schema = EnterpriseMapEdgeResponse.model_json_schema()["properties"]
    for schema, fields in (
        (node_schema, ("event_count", "time_range", "series_refs", "priority", "acceptance")),
        (edge_schema, ("active_event_count", "time_range", "flow_refs", "effort", "acceptance")),
    ):
        for field in fields:
            assert schema[field] != {}, f"{field} must not be Any in OpenAPI schema"


def test_strict_filter_and_time_range_models_reject_unknown_fields():
    with pytest.raises(ValidationError) as filter_error:
        ExplorerOntologyFilters.model_validate({"concept_type": ["flight"], "bad_key": ["x"]})
    assert "bad_key" in str(filter_error.value)

    with pytest.raises(ValidationError) as time_error:
        TimeRangeResponse.model_validate({"start": None, "timezone": "UTC"})
    assert "timezone" in str(time_error.value)


def test_explorer_filters_include_exclude_and_edge_consistency():
    explorer = KnowledgeExplorer(FakeGraph())

    included = explorer.enterprise_map(filters={"concept_type": ["flight"]})
    assert [node["id"] for node in included["nodes"]] == ["flight-1"]
    assert included["edges"] == []

    excluded = explorer.enterprise_map(filters={"concept_type": {"values": ["airport"], "mode": "exclude"}})
    node_ids = {node["id"] for node in excluded["nodes"]}
    assert "airport-1" not in node_ids
    assert all(edge["source"] in node_ids and edge["target"] in node_ids for edge in excluded["edges"])

    mixed = explorer.enterprise_map(filters={"layer": ["ops"], "owner": {"values": ["legal"], "mode": "exclude"}})
    assert {node["id"] for node in mixed["nodes"]} == {"flight-1", "airport-1"}


def test_service_enterprise_map_map_state_rollups_and_group_by(monkeypatch):
    service = object.__new__(KnowledgeService)
    monkeypatch.setattr(service, "_get_explorer", lambda namespace: KnowledgeExplorer(FakeGraph()))

    result = service.ontology_enterprise_map(
        "ns",
        filters={"concept_type": ["flight"]},
        group_by=["concept_type"],
        color_by="state",
    )
    response = EnterpriseMapProjectionResponse.model_validate(result)
    assert response.meta.map_state == "live"
    assert response.meta.map_source_kind == "knowledge_graph"
    assert response.meta.applied_filters == {"concept_type": ["flight"]}
    assert response.meta.applied_group_by == ["concept_type"]
    assert response.meta.applied_color_by == "state"
    assert response.stats.ontology_candidate_count == 3
    assert response.stats.validation_issue_count == 0
    assert response.stats.event_count == 0
    assert response.stats.active_event_count == 0
    assert response.nodes[0].map_group == "flight"

    empty = service.ontology_enterprise_map("ns", filters={"concept_type": ["missing"]})
    empty_response = EnterpriseMapProjectionResponse.model_validate(empty)
    assert empty_response.nodes == []
    assert empty_response.meta.map_state == "empty"
    assert empty_response.meta.map_source_kind == "none"


def test_explorer_expand_returns_projected_contract_and_cap_metadata(monkeypatch):
    service = object.__new__(KnowledgeService)
    monkeypatch.setattr(service, "_get_explorer", lambda namespace: KnowledgeExplorer(FakeGraph()))

    result = service.explorer_expand("ns", node_ids=["flight-1"], depth=5, node_cap=2)
    response = EnterpriseMapProjectionResponse.model_validate(result)
    assert response.stats.depth_requested == 5
    assert response.stats.depth_effective == 3
    assert response.stats.node_cap == 2
    assert len(response.nodes) <= 2
    assert response.meta.depth_requested == 5
    assert response.meta.depth_effective == 3
    node_ids = {node.id for node in response.nodes}
    assert all(edge.source in node_ids and edge.target in node_ids for edge in response.edges)
    assert {"id", "concept_type", "map_group", "validation_issues"}.issubset(response.nodes[0].model_dump().keys())


def test_generated_frontend_types_match_backend_field_sets():
    generated = Path(__file__).parents[1] / "fe" / "src" / "types" / "ontology-map.generated.ts"
    source = generated.read_text()

    def interface_fields(name: str) -> set[str]:
        match = re.search(rf"export interface {name} \{{(?P<body>.*?)\n\}}", source, re.S)
        assert match, f"missing generated interface {name}"
        fields = set()
        for line in match.group("body").splitlines():
            field_match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\??:", line)
            if field_match:
                fields.add(field_match.group(1))
        return fields

    expectations = (
        (EnterpriseMapNodeResponse, "EnterpriseMapNode"),
        (EnterpriseMapEdgeResponse, "EnterpriseMapEdge"),
        ("stats", "EnterpriseMapStats"),
        ("meta", "EnterpriseMapMeta"),
    )
    for backend, frontend in expectations:
        backend_fields = (
            set(backend.model_fields)
            if not isinstance(backend, str)
            else set(EnterpriseMapProjectionResponse.model_fields[backend].annotation.model_fields)
        )
        assert interface_fields(frontend) == backend_fields
