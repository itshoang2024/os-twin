from __future__ import annotations

from dashboard.knowledge.graph.index.kuzudb import KuzuLabelledPropertyGraph
from dashboard.knowledge.ontology.defaults import create_default_ontology_profile
from dashboard.knowledge.ontology.models import OntologyProfile
from dashboard.knowledge.ontology.normalizer import normalize_relation, render_relation_for_ui
from dashboard.knowledge.ontology.validator import validate_relationship


def _profile_with_alias(alias: str, canonical: str) -> OntologyProfile:
    profile = create_default_ontology_profile("demo")
    payload = profile.model_dump(mode="json")
    payload["aliases"][alias] = canonical
    return OntologyProfile.model_validate(payload)


def test_prerequisite_normalizes_to_depends_on() -> None:
    profile = create_default_ontology_profile("demo")

    normalized = normalize_relation("prerequisite", profile)

    assert normalized.normalized == "depends_on"
    assert normalized.classification == "alias"
    assert normalized.canonical is not None
    assert normalized.canonical.id == "depends_on"


def test_namespace_profile_alias_can_normalize_to_consumes() -> None:
    profile = _profile_with_alias("requires_data_from", "consumes")

    normalized = normalize_relation("requires_data_from", profile)

    assert normalized.normalized == "consumes"
    assert normalized.classification == "alias"
    assert normalized.source == "profile_alias"
    assert normalized.canonical is not None
    assert normalized.canonical.id == "consumes"


def test_unknown_relation_label_is_candidate_not_related_to() -> None:
    profile = create_default_ontology_profile("demo")

    normalized = normalize_relation("some unexpected label", profile)

    assert normalized.normalized == "some_unexpected_label"
    assert normalized.classification == "candidate"
    assert normalized.normalized != "related_to"


def test_produces_validation_warns_for_non_artifact_target() -> None:
    profile = create_default_ontology_profile("demo")

    issues = validate_relationship("produces", "service", "service", profile)

    assert len(issues) == 1
    issue = issues[0]
    assert issue.severity == "warning"
    assert issue.code == "INVALID_RELATION_TARGET_TYPE"
    assert issue.path == "edge.target.type"
    assert "data_object" in issue.suggested_fix
    assert issue.model_dump()["suggested_fix"] == issue.suggested_fix


def test_produces_validation_severity_can_be_configured() -> None:
    profile = create_default_ontology_profile("demo")
    payload = profile.model_dump(mode="json")
    for rule in payload["validation_rules"]:
        if rule["id"] == "produces_target_artifact_like":
            rule["severity"] = "error"
    strict_profile = OntologyProfile.model_validate(payload)

    issues = validate_relationship("produces", "service", "service", strict_profile)

    assert issues[0].severity == "error"


def test_depends_on_can_render_inverse_enables_without_storage_duplication() -> None:
    profile = create_default_ontology_profile("demo")

    rendered = render_relation_for_ui("feature-a", "service-b", "depends_on", profile, inverse=True)

    assert rendered.source_id == "service-b"
    assert rendered.target_id == "feature-a"
    assert rendered.relation_type == "enables"
    assert rendered.stored_relation_type == "depends_on"
    assert rendered.is_inverse is True
    assert rendered.should_persist is False


def test_semantic_relationships_are_distinct() -> None:
    profile = create_default_ontology_profile("demo")

    relationships = profile.relationship_types

    assert relationships["depends_on"].family == "dependency"
    assert relationships["depends_on"].inverse == "enables"
    assert relationships["enables"].inverse == "depends_on"
    assert relationships["consumes"].family == "flow"
    assert relationships["produces"].family == "flow"
    assert relationships["consumes"].allowed_target_types != relationships["produces"].allowed_target_types


def test_relationship_weight_lookup_uses_profile_config_with_legacy_fallback() -> None:
    profile = create_default_ontology_profile("demo")
    payload = profile.model_dump(mode="json")
    payload["relationship_types"]["consumes"]["weight"] = 0.25
    weighted_profile = OntologyProfile.model_validate(payload)

    assert KuzuLabelledPropertyGraph.get_relationship_weight("consumes", weighted_profile) == 0.25
    assert (
        KuzuLabelledPropertyGraph.get_relationship_weight(
            "requires_data_from",
            _profile_with_alias("requires_data_from", "consumes"),
        )
        == 0.6
    )
    assert KuzuLabelledPropertyGraph.get_relationship_weight("unknown", weighted_profile) == 0.7
    assert KuzuLabelledPropertyGraph.get_relationship_weight("CONTAINS") == 1.5
