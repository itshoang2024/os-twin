from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dashboard.knowledge.namespace import NamespaceManager
from dashboard.knowledge.ontology.defaults import create_default_ontology_profile
from dashboard.knowledge.ontology.models import (
    OntologyProfile,
    OntologyUnit,
    OntologyUnitLifecycle,
    RelationshipType,
    is_ontology_lifecycle_state,
)
from dashboard.knowledge.ontology.store import OntologyProfileStore
from dashboard.knowledge.service import KnowledgeService
from pydantic import ValidationError


def test_default_profile_is_valid_and_deterministic() -> None:
    first = create_default_ontology_profile("demo")
    second = create_default_ontology_profile("demo")

    assert first == second
    assert first.profile_id == "enterprise_feature_map"
    assert first.namespace == "demo"
    assert "feature" in first.concept_types
    assert "depends_on" in first.relationship_types
    assert first.aliases["requires"] == "depends_on"


def test_relationship_type_rejects_invalid_enum() -> None:
    with pytest.raises(ValidationError):
        RelationshipType(
            id="bad_rel",
            label="Bad Relationship",
            family="not_a_family",
        )


def test_relationship_alias_cannot_shadow_canonical_id() -> None:
    profile = create_default_ontology_profile("demo")
    payload = profile.model_dump(mode="json")
    payload["aliases"]["depends_on"] = "contains"

    with pytest.raises(ValidationError, match="cannot shadow"):
        OntologyProfile.model_validate(payload)


def test_missing_required_fields_are_rejected() -> None:
    payload = create_default_ontology_profile("demo").model_dump(mode="json")
    del payload["relationship_types"]["contains"]["label"]

    with pytest.raises(ValidationError):
        OntologyProfile.model_validate(payload)


def test_profile_store_writes_profile_atomically_and_updates_manifest(tmp_path: Path) -> None:
    nm = NamespaceManager(base_dir=tmp_path / "kb")
    nm.create("demo")
    store = OntologyProfileStore(nm)
    profile = create_default_ontology_profile("demo")

    written = store.write(profile)

    assert written == profile
    profile_path = tmp_path / "kb" / "demo" / "ontology" / "profile.json"
    assert profile_path.exists()
    assert not list(profile_path.parent.glob(".profile.*.tmp"))
    assert json.loads(profile_path.read_text())["version"] == "1.0.0"
    assert nm.get("demo").ontology_profile_version == "1.0.0"


def test_profile_store_publish_sets_active_unit_pointer_from_null(tmp_path: Path) -> None:
    nm = NamespaceManager(base_dir=tmp_path / "kb")
    nm.create("demo")
    store = OntologyProfileStore(nm)
    draft_unit = store.write_unit(OntologyUnit(namespace="demo", active_profile_id=None, name="Flight Delay Template"))
    profile = create_default_ontology_profile("demo").model_copy(update={"status": "active"})

    store.write(profile, set_active=True)

    active_unit = store.get_unit("demo")
    assert draft_unit.active_profile_id is None
    assert active_unit is not None
    assert active_unit.active_profile_id == profile.profile_id
    assert active_unit.name == "Flight Delay Template"
    assert json.loads(store.unit_path("demo").read_text())["active_profile_id"] == profile.profile_id


def test_legacy_manifest_without_ontology_field_still_loads(tmp_path: Path) -> None:
    ns_dir = tmp_path / "kb" / "legacy"
    ns_dir.mkdir(parents=True)
    now = datetime.now(UTC).isoformat()
    (ns_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "name": "legacy",
                "created_at": now,
                "updated_at": now,
                "language": "English",
                "description": None,
                "embedding_model": "test-model",
                "embedding_dimension": 8,
                "stats": {},
                "imports": [],
                "retention": {},
            }
        )
    )

    nm = NamespaceManager(base_dir=tmp_path / "kb")
    meta = nm.get("legacy")

    assert meta is not None
    assert meta.ontology_profile_version is None
    assert meta.schema_version == 3


def test_profile_persistence_survives_new_knowledge_service_instance(tmp_path: Path) -> None:
    nm = NamespaceManager(base_dir=tmp_path / "kb")
    nm.create("demo")
    svc = KnowledgeService(namespace_manager=nm)
    profile = svc.create_default_ontology_profile("demo")

    restarted = KnowledgeService(namespace_manager=NamespaceManager(base_dir=tmp_path / "kb"))
    loaded = restarted.get_ontology_profile("demo")

    assert loaded == profile
    assert restarted.get_namespace("demo").ontology_profile_version == profile.version


def test_legacy_namespace_without_profile_returns_none(tmp_path: Path) -> None:
    nm = NamespaceManager(base_dir=tmp_path / "kb")
    nm.create("legacy")
    svc = KnowledgeService(namespace_manager=nm)

    assert svc.get_ontology_profile("legacy") is None



def test_ontology_unit_creation_serialization_and_strict_fields() -> None:
    unit = OntologyUnit(
        namespace="demo",
        active_profile_id=None,
        name="Audit Process Unit",
        purpose="Govern audit workflow vocabulary",
        domain="audit",
        expected_users=["auditor", "manager"],
        source_material=["policy.pdf"],
        governance_mode="strict",
    )

    payload = unit.model_dump(mode="json")

    assert unit.id == "demo"
    assert payload["active_profile_id"] is None
    assert payload["name"] == "Audit Process Unit"
    assert payload["purpose"] == "Govern audit workflow vocabulary"
    assert payload["domain"] == "audit"
    assert payload["expected_users"] == ["auditor", "manager"]
    assert payload["source_material"] == ["policy.pdf"]
    assert payload["governance_mode"] == "strict"
    assert payload["lifecycle"] == "active"
    assert payload["installed_packs"] == []
    assert payload["auto_confirm_threshold"] == 1.0
    assert payload["created_at"]
    with pytest.raises(ValidationError):
        OntologyUnit.model_validate({**payload, "unexpected": True})


def test_profile_store_persists_draft_unit_without_profile(tmp_path: Path) -> None:
    nm = NamespaceManager(base_dir=tmp_path / "kb")
    nm.create("draftns")
    store = OntologyProfileStore(nm)

    unit = store.write_unit(OntologyUnit(namespace="draftns", active_profile_id=None, name="Draft Unit"))

    assert unit.active_profile_id is None
    assert store.get_unit("draftns") == unit
    assert store.get("draftns") is None
    payload = json.loads(store.unit_path("draftns").read_text())
    assert payload["name"] == "Draft Unit"
    assert payload["active_profile_id"] is None


def test_ontology_unit_rejects_external_or_mismatched_active_profile(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="outside namespace"):
        OntologyUnit(namespace="demo", active_profile_id="other:enterprise_feature_map")

    nm = NamespaceManager(base_dir=tmp_path / "kb")
    nm.create("demo")
    store = OntologyProfileStore(nm)
    store.write(create_default_ontology_profile("demo"))

    with pytest.raises(ValueError, match="existing profile"):
        store.write_unit(OntologyUnit(namespace="demo", active_profile_id="missing_profile"))


def test_service_preserves_active_profile_on_metadata_only_unit_update(tmp_path: Path) -> None:
    nm = NamespaceManager(base_dir=tmp_path / "kb")
    nm.create("demo")
    store = OntologyProfileStore(nm)
    profile = create_default_ontology_profile("demo")
    store.write(profile)
    svc = KnowledgeService(namespace_manager=nm)

    saved = svc.save_ontology_unit_payload(
        "demo",
        {
            "namespace": "demo",
            "name": "Renamed Ontology Unit",
            "purpose": "Update identity metadata only",
            "expected_users": ["ontology owner"],
        },
    )

    assert saved.active_profile_id == profile.profile_id
    assert saved.name == "Renamed Ontology Unit"
    assert saved.expected_users == ["ontology owner"]
    assert svc.get_ontology_profile("demo") == profile
    assert svc.get_ontology_unit("demo") is not None
    assert svc.get_ontology_unit("demo").active_profile_id == profile.profile_id


def test_profile_store_synthesizes_unit_for_legacy_profile_without_unit_json(tmp_path: Path) -> None:
    nm = NamespaceManager(base_dir=tmp_path / "kb")
    nm.create("legacy")
    store = OntologyProfileStore(nm)
    profile = create_default_ontology_profile("legacy")
    profile_path = store.profile_path("legacy")
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(profile.model_dump(mode="json")))

    unit = store.get_unit("legacy")
    loaded = store.get("legacy")

    assert unit is not None
    assert unit.id == "legacy"
    assert unit.namespace == "legacy"
    assert unit.active_profile_id == profile.profile_id
    assert unit.auto_confirm_threshold == 1.0
    assert unit.name == ""
    assert unit.purpose == ""
    assert unit.domain == ""
    assert unit.expected_users == []
    assert unit.source_material == []
    assert unit.governance_mode == "manual"
    assert loaded == profile
    assert not store.unit_path("legacy").exists()


def test_unit_lifecycle_is_separate_from_candidate_status() -> None:
    unit = OntologyUnit(namespace="demo", active_profile_id="enterprise_feature_map", lifecycle="active")

    assert unit.lifecycle == OntologyUnitLifecycle.ACTIVE
    assert unit.model_dump(mode="json")["lifecycle"] == "active"
    # Ontology review candidates use pending/approved/mapped/rejected status; ontology
    # units and schema instances use draft/active/deprecated/retired lifecycle_state.
    assert is_ontology_lifecycle_state("active")
    assert not is_ontology_lifecycle_state("pending")
    assert {item.value for item in OntologyUnitLifecycle}.isdisjoint({"pending", "approved", "mapped", "rejected"})


def test_relationship_family_includes_dm03_core_families() -> None:
    for family in ["classification", "causality", "temporal", "validation", "assurance", "synchronization"]:
        rel = RelationshipType(id=f"{family}_rel", label=family.title(), family=family)
        assert rel.family == family


def test_source_mapping_and_cardinality_round_trip_are_strict() -> None:
    profile = create_default_ontology_profile("demo")
    payload = profile.model_dump(mode="json")
    payload["concept_types"]["feature"]["source_mappings"] = [
        {"source_id": "roadmap_db", "source_type": "database", "source_label": "Roadmap DB", "field_path": "features.id"}
    ]
    payload["relationship_types"]["depends_on"]["cardinality"] = "many_to_many"
    payload["relationship_types"]["depends_on"]["source_mappings"] = [
        {"source_id": "dependency_api", "source_type": "api", "field_path": "dependencies[].target"}
    ]
    payload["metadata_fields"]["owner"]["source_mappings"] = [
        {"source_id": "hr_file", "source_type": "file", "field_path": "owner_email", "confidence": 0.9}
    ]

    parsed = OntologyProfile.model_validate(payload)

    assert parsed.relationship_types["depends_on"].cardinality == "many_to_many"
    assert parsed.concept_types["feature"].source_mappings[0].source_id == "roadmap_db"
    assert parsed.metadata_fields["owner"].source_mappings[0].confidence == 0.9
    with pytest.raises(ValidationError):
        OntologyProfile.model_validate({**payload, "concept_types": {"feature": {**payload["concept_types"]["feature"], "unexpected": True}}})
    with pytest.raises(ValidationError):
        OntologyProfile.model_validate({**payload, "relationship_types": {"depends_on": {**payload["relationship_types"]["depends_on"], "cardinality": "sometimes"}}})
