from __future__ import annotations

import pytest
from dashboard.knowledge.ontology.defaults import create_default_ontology_profile
from dashboard.knowledge.ontology.graph_instruction import (
    GraphDefaultView,
    GraphInstruction,
    RelationshipGraphInstruction,
)
from dashboard.knowledge.ontology.models import OntologyProfile
from dashboard.knowledge.ontology.projection import project_enterprise_map
from dashboard.routes.knowledge_models import EnterpriseMapProjectionResponse
from pydantic import ValidationError


def test_default_profile_exposes_graph_instruction_defaults() -> None:
    profile = create_default_ontology_profile("demo")

    assert profile.concept_types["feature"].default_layer == "product"
    assert profile.relationship_types["depends_on"].map_direction == "reversed"
    assert profile.graph_instruction.default_views[0].id == "enterprise_map"
    assert profile.graph_instruction.concept_type_defaults["service"].default_layer == "delivery"
    assert profile.graph_instruction.relationship_type_defaults["depends_on"].map_direction == "reversed"


def test_graph_instruction_rejects_mismatched_relationship_keys() -> None:
    with pytest.raises(ValidationError, match="relationship_type_defaults key"):
        GraphInstruction(
            default_views=[GraphDefaultView(id="demo", label="Demo")],
            relationship_type_defaults={
                "depends_on": RelationshipGraphInstruction(
                    relationship_type="consumes",
                    map_direction="forward",
                )
            },
        )


def test_profile_validates_concept_default_layer_reference() -> None:
    payload = create_default_ontology_profile("demo").model_dump(mode="json")
    payload["concept_types"]["feature"]["default_layer"] = "missing_layer"

    with pytest.raises(ValidationError, match="default_layer"):
        OntologyProfile.model_validate(payload)


def test_projection_uses_profile_declared_relationship_direction() -> None:
    profile = create_default_ontology_profile("demo")
    payload = profile.model_dump(mode="json")
    payload["relationship_types"]["depends_on"]["map_direction"] = "forward"
    payload["graph_instruction"]["relationship_type_defaults"]["depends_on"]["map_direction"] = "forward"
    profile = OntologyProfile.model_validate(payload)

    projected = project_enterprise_map(
        nodes=[
            {"id": "feature", "label": "feature", "concept_type": "feature"},
            {"id": "service", "label": "service", "concept_type": "service"},
        ],
        edges=[{"source": "feature", "target": "service", "relationship_type": "depends_on"}],
        profile=profile,
    )

    assert projected["edges"][0]["map_source"] == "feature"
    assert projected["edges"][0]["map_target"] == "service"
    assert projected["edges"][0]["map_direction"] == "forward"


def test_default_profile_required_enterprise_relationships_coexist() -> None:
    profile = create_default_ontology_profile("demo")
    required = {"depends_on", "consumes", "evidences", "mitigates", "implements", "syncs_with"}

    assert required.issubset(profile.relationship_types)
    assert required.issubset(profile.graph_instruction.relationship_type_defaults)

    projected = project_enterprise_map(
        nodes=[
            {"id": "feature", "label": "feature", "concept_type": "feature"},
            {"id": "service", "label": "service", "concept_type": "service"},
            {"id": "evidence", "label": "evidence", "concept_type": "evidence"},
            {"id": "risk", "label": "risk", "concept_type": "risk"},
            {"id": "control", "label": "control", "concept_type": "control"},
        ],
        edges=[
            {"source": "feature", "target": "service", "relationship_type": "depends_on"},
            {"source": "service", "target": "evidence", "relationship_type": "consumes"},
            {"source": "evidence", "target": "feature", "relationship_type": "evidences"},
            {"source": "control", "target": "risk", "relationship_type": "mitigates"},
            {"source": "service", "target": "feature", "relationship_type": "implements"},
            {"source": "service", "target": "evidence", "relationship_type": "syncs_with"},
        ],
        profile=profile,
    )

    assert {edge["relationship_type"] for edge in projected["edges"]} == required
    assert all(edge["display_label"] for edge in projected["edges"])


def test_required_enterprise_map_relationship_types_can_coexist() -> None:
    profile = create_default_ontology_profile("demo")
    required = {"depends_on", "consumes", "evidences", "mitigates", "implements", "syncs_with"}

    assert required.issubset(profile.relationship_types)
    assert required.issubset(profile.graph_instruction.relationship_type_defaults)

    nodes = [
        {"id": "feature", "label": "feature", "concept_type": "feature"},
        {"id": "service", "label": "service", "concept_type": "service"},
        {"id": "data", "label": "data_object", "concept_type": "data_object"},
        {"id": "evidence", "label": "evidence", "concept_type": "evidence"},
        {"id": "risk", "label": "risk", "concept_type": "risk"},
    ]
    edges = [
        {"source": "feature", "target": "service", "relationship_type": "depends_on"},
        {"source": "service", "target": "data", "relationship_type": "consumes"},
        {"source": "evidence", "target": "feature", "relationship_type": "evidences"},
        {"source": "service", "target": "risk", "relationship_type": "mitigates"},
        {"source": "service", "target": "feature", "relationship_type": "implements"},
        {"source": "service", "target": "data", "relationship_type": "syncs_with"},
    ]

    projected = project_enterprise_map(nodes=nodes, edges=edges, profile=profile)

    assert {edge["relationship_type"] for edge in projected["edges"]} == required
    assert projected["relationship_family_counts"]["dependency"] >= 1
    assert projected["relationship_family_counts"]["flow"] >= 1



def test_projection_prefers_graph_instruction_visual_defaults_over_legacy_type_fields() -> None:
    profile = create_default_ontology_profile("demo")
    payload = profile.model_dump(mode="json")
    payload["concept_types"]["feature"]["color"] = "#111111"
    payload["concept_types"]["feature"]["shape"] = "legacy-shape"
    payload["graph_instruction"]["concept_type_defaults"]["feature"]["color"] = "#abcdef"
    payload["graph_instruction"]["concept_type_defaults"]["feature"]["shape"] = "hexagon"
    payload["relationship_types"]["depends_on"]["style"] = "bold"
    payload["relationship_types"]["depends_on"]["weight"] = 0.2
    payload["graph_instruction"]["relationship_type_defaults"]["depends_on"]["dash"] = "2 4"
    payload["graph_instruction"]["relationship_type_defaults"]["depends_on"]["color"] = "#fedcba"
    payload["graph_instruction"]["relationship_type_defaults"]["depends_on"]["weight"] = 0.8
    profile = OntologyProfile.model_validate(payload)

    projected = project_enterprise_map(
        nodes=[
            {"id": "feature", "label": "feature", "concept_type": "feature"},
            {"id": "service", "label": "service", "concept_type": "service"},
        ],
        edges=[{"source": "feature", "target": "service", "relationship_type": "depends_on"}],
        profile=profile,
    )

    assert projected["nodes"][0]["concept_color"] == "#abcdef"
    assert projected["nodes"][0]["concept_shape"] == "hexagon"
    assert projected["edges"][0]["style"] == "dotted"
    assert projected["edges"][0]["color"] == "#fedcba"
    assert projected["edges"][0]["weight"] == 0.8


def test_projection_remains_legacy_safe_and_names_optional_extension_fields() -> None:
    projected = project_enterprise_map(
        nodes=[
            {
                "id": "legacy-node",
                "label": "legacy concept",
                "properties": {"owner": "Ops", "event_count": 3, "flow_refs": ["flow:a"], "phase": "build"},
                "metadata": {"quality_state": "needs_review"},
                "validation_issues": [{"message": "Needs label review"}],
            }
        ],
        edges=[
            {
                "source": "legacy-node",
                "target": "legacy-node",
                "label": "relates_to",
                "is_candidate": True,
                "properties": {"series_refs": ["series:a"], "priority": "p1"},
            }
        ],
        profile=None,
    )

    node = projected["nodes"][0]
    edge = projected["edges"][0]
    assert node["layer_id"] == "unassigned"
    assert node["quality_state"] == "needs_review"
    assert node["event_count"] == 3
    assert node["flow_refs"] == ["flow:a"]
    assert node["phase"] == "build"
    assert node["validation_issues"] == [{"message": "Needs label review"}]
    assert edge["id"] == "legacy-node:relates_to:legacy-node"
    assert edge["candidate_state"] == "pending"
    assert edge["series_refs"] == ["series:a"]
    assert edge["priority"] == "p1"
    assert projected["stats"]["validation_issue_count"] == 1



def test_enterprise_map_response_model_preserves_visual_projection_extensions() -> None:
    node_extensions = {
        "candidate_state": "proposed",
        "quality_state": "needs_review",
        "event_count": 7,
        "active_event_count": 3,
        "time_range": {"start": "2026-01-01", "end": "2026-02-01"},
        "series_refs": ["series:node"],
        "flow_refs": ["flow:node"],
        "state": "active",
        "simulation_state": "simulated",
        "phase": "build",
        "track": "platform",
        "priority": "p1",
        "effort": "m",
        "prerequisites": ["dep:node"],
        "acceptance": ["node accepted"],
    }
    edge_extensions = {
        "id": "feature:depends_on:service",
        "review_state": "approved",
        "candidate_state": "pending",
        "map_group": "dependency",
        "event_count": 5,
        "active_event_count": 2,
        "time_range": {"start": "2026-03-01", "end": "2026-04-01"},
        "series_refs": ["series:edge"],
        "flow_refs": ["flow:edge"],
        "state": "queued",
        "simulation_state": "forecast",
        "phase": "validate",
        "track": "product",
        "priority": "p0",
        "effort": "s",
        "prerequisites": ["dep:edge"],
        "acceptance": ["edge accepted"],
    }
    payload = {
        "nodes": [
            {
                "id": "feature",
                "label": "Feature",
                **node_extensions,
            }
        ],
        "edges": [
            {
                "source": "feature",
                "target": "service",
                "label": "depends_on",
                **edge_extensions,
            }
        ],
    }

    dumped = EnterpriseMapProjectionResponse.model_validate(payload).model_dump()

    for field, value in node_extensions.items():
        assert dumped["nodes"][0][field] == value
    for field, value in edge_extensions.items():
        assert dumped["edges"][0][field] == value
