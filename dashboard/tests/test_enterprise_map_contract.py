from __future__ import annotations

from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from dashboard.knowledge.graph.explorer import KnowledgeExplorer
from dashboard.knowledge.ontology.defaults import create_default_ontology_profile
from dashboard.knowledge.ontology.projection import project_enterprise_map
from dashboard.routes.knowledge_models import (
    EnterpriseMapEdgeResponse,
    EnterpriseMapMetaResponse,
    EnterpriseMapNodeResponse,
    EnterpriseMapProjectionResponse,
    EnterpriseMapQueryRequest,
    EnterpriseMapStatsResponse,
    ExplorerOntologyFilters,
    TimeRangeResponse,
)
from test_knowledge_explorer import FakeEntityNode, FakeKuzuGraph, FakeRelation


def _annotation_has_any(annotation) -> bool:
    if annotation is Any:
        return True
    return any(_annotation_has_any(arg) for arg in get_args(annotation))


def test_enterprise_map_optional_visual_fields_are_precisely_typed_and_omittable() -> None:
    visual_fields = {
        "event_count", "active_event_count", "time_range", "series_refs", "flow_refs", "state",
        "simulation_state", "simulation_refs", "state_machine_ref", "state_color", "phase", "track",
        "priority", "effort", "prerequisites", "acceptance",
    }
    for model in (EnterpriseMapNodeResponse, EnterpriseMapEdgeResponse):
        for field in visual_fields:
            assert field in model.model_fields
            assert not _annotation_has_any(model.model_fields[field].annotation), field

    minimal_node = EnterpriseMapNodeResponse(id="n1")
    minimal_edge = EnterpriseMapEdgeResponse(source="n1", target="n2")
    assert minimal_node.series_refs == []
    assert minimal_node.flow_refs == []
    assert minimal_edge.prerequisites == []

    all_present = EnterpriseMapNodeResponse(
        id="n2", event_count=1, active_event_count=1, time_range={"start": None, "end": "2026"},
        series_refs=["s1"], flow_refs=["f1"], state="open", simulation_state="ready", simulation_refs=["sim"],
        state_machine_ref="sm", state_color="#fff000", phase="build", track="core", priority=1, effort="M",
        prerequisites=["n1"], acceptance=["done"],
    )
    assert all_present.time_range == TimeRangeResponse(start=None, end="2026")


def test_strict_enterprise_map_query_models_reject_unknown_keys() -> None:
    assert ExplorerOntologyFilters(concept_type=["feature"]).to_filter_dict() == {"concept_type": ["feature"]}
    assert ExplorerOntologyFilters(concept_type={"values": ["airport"], "mode": "exclude"}).to_filter_dict()["concept_type"]["mode"] == "exclude"
    with pytest.raises(ValidationError):
        ExplorerOntologyFilters(unknown=["x"])  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        TimeRangeResponse(start="2026", extra="nope")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        EnterpriseMapQueryRequest(filters={"bad": ["x"]})


def test_project_enterprise_map_group_by_is_per_read_and_non_mutating() -> None:
    profile = create_default_ontology_profile("demo")
    nodes = [{"id": "f1", "label": "feature", "concept_type": "feature"}]
    by_default = project_enterprise_map(nodes, [], profile)
    by_concept = project_enterprise_map(nodes, [], profile, group_by=["concept_type"], color_by="lifecycle_state")

    assert by_default["applied_group_by"] == ["default_layer", "concept_type"]
    assert by_concept["applied_group_by"] == ["concept_type"]
    assert by_concept["applied_color_by"] == "lifecycle_state"
    assert by_default["nodes"][0]["id"] == by_concept["nodes"][0]["id"]
    assert by_default["nodes"][0]["map_group"] != by_concept["nodes"][0]["map_group"]


def test_explorer_filters_support_include_exclude_and_keep_edges_consistent() -> None:
    profile = create_default_ontology_profile("demo")
    feature = FakeEntityNode(id="feature-1", label="feature", properties={"concept_type": "feature"})
    service = FakeEntityNode(id="service-1", label="service", properties={"concept_type": "service"})
    rel = FakeRelation(source_id="feature-1", target_id="service-1", label="depends_on", properties={})
    explorer = KnowledgeExplorer(FakeKuzuGraph([feature, service], [rel], [(feature, rel, service)], profile))

    included = explorer.enterprise_map(filters={"concept_type": ["feature"]})
    assert [node["id"] for node in included["nodes"]] == ["feature-1"]
    assert included["edges"] == []

    excluded = explorer.enterprise_map(filters={"concept_type": {"values": ["service"], "mode": "exclude"}})
    assert [node["id"] for node in excluded["nodes"]] == ["feature-1"]
    node_ids = {node["id"] for node in excluded["nodes"]}
    assert all(edge["source"] in node_ids and edge["target"] in node_ids for edge in excluded["edges"])


def test_explorer_expand_returns_projected_contract_and_cap_metadata() -> None:
    profile = create_default_ontology_profile("demo")
    nodes = [FakeEntityNode(id=f"n{i}", label="feature", properties={"concept_type": "feature"}) for i in range(5)]
    triplets = []
    for idx in range(1, 5):
        rel = FakeRelation(source_id="n0", target_id=f"n{idx}", label="depends_on", properties={})
        triplets.append((nodes[0], rel, nodes[idx]))
    explorer = KnowledgeExplorer(FakeKuzuGraph(nodes, [], triplets, profile))

    result = explorer.expand(["n0"], depth=5, node_cap=3)

    assert result["stats"]["depth_requested"] == 5
    assert result["stats"]["depth_effective"] == 3
    assert result["stats"]["node_cap"] == 3
    assert result["stats"]["truncated"] is True
    assert len(result["nodes"]) <= 3
    assert "concept_label" in result["nodes"][0]
    assert "map_source" in result["edges"][0]


def test_generated_frontend_type_contains_full_backend_projection_contract() -> None:
    generated = Path("fe/src/types/ontology-map.generated.ts").read_text()
    hook = Path("fe/src/hooks/use-knowledge-explorer.ts").read_text()

    expected_type_names = {
        "EnterpriseMapNodeResponse",
        "EnterpriseMapEdgeResponse",
        "EnterpriseMapStatsResponse",
        "EnterpriseMapMetaResponse",
        "EnterpriseMapProjectionResponse",
        "EnterpriseMapProjectionData",
        "OntologyVisualExtensions",
    }
    for type_name in expected_type_names:
        assert f"export type {type_name}" in generated

    for model in (
        EnterpriseMapNodeResponse,
        EnterpriseMapEdgeResponse,
        EnterpriseMapStatsResponse,
        EnterpriseMapMetaResponse,
        EnterpriseMapProjectionResponse,
    ):
        for field in model.model_fields:
            assert field in generated, f"{model.__name__}.{field} missing from generated type"

    visual_fields = {
        "event_count", "active_event_count", "time_range", "series_refs", "flow_refs", "state",
        "simulation_state", "simulation_refs", "state_machine_ref", "state_color", "phase", "track",
        "priority", "effort", "prerequisites", "acceptance",
    }
    for field in visual_fields:
        assert f"'" + field + "'" in generated

    assert "GeneratedEnterpriseMapProjectionResponse" in hook
    assert "export type EnterpriseMapProjectionData = Omit<GeneratedEnterpriseMapProjectionResponse" in hook
    assert "export type OntologyVisualExtensions = Partial<GeneratedOntologyVisualExtensions>" in hook
