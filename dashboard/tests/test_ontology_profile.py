from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dashboard.knowledge.namespace import NamespaceManager
from dashboard.knowledge.ontology.defaults import create_default_ontology_profile
from dashboard.knowledge.ontology.models import OntologyProfile, RelationshipType
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
