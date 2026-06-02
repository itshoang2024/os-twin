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
