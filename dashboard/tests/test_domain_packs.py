from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from dashboard.knowledge.namespace import NamespaceManager
from dashboard.knowledge.ontology.defaults import create_default_ontology_profile
from dashboard.knowledge.ontology.models import RelationshipType
from dashboard.knowledge.ontology.packs import DomainPackConflictError, DomainPackManifest, DomainPackStore
from dashboard.knowledge.ontology.store import OntologyProfileStore
from dashboard.knowledge.ontology.validator import validate_relationship
from dashboard.knowledge.service import KnowledgeService
from dashboard.routes.knowledge import router
from dashboard.routes.knowledge_models import DomainPackManifestResponse
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError


def _store(tmp_path: Path) -> tuple[NamespaceManager, OntologyProfileStore, DomainPackStore]:
    nm = NamespaceManager(base_dir=tmp_path / "kb")
    nm.create("demo")
    profile_store = OntologyProfileStore(nm)
    return nm, profile_store, DomainPackStore(nm, profile_store)


def test_seed_domain_pack_manifests_exist_and_validate(tmp_path: Path) -> None:
    _, _, store = _store(tmp_path)

    manifests = store.list_available()

    assert {manifest.pack_id for manifest in manifests} >= {
        "financial-services",
        "technology-saas",
        "retail-consumer",
        "public-sector",
        "esg",
        "audit-risk-management",
        "audit-risk",
        "ecommerce-logistics",
    }
    seen_families = set()
    for manifest in manifests:
        assert manifest.compatible_profile_versions
        assert manifest.fixtures
        assert manifest.graph_instruction.default_views
        assert isinstance(manifest.migration_notes, list)
        seen_families.update(rel.family for rel in manifest.relationship_types.values())
    assert {"validation", "assurance", "synchronization"} & seen_families


def test_pack_manifest_requires_acceptance_criteria_fields() -> None:
    payload = {
        "pack_id": "demo-pack",
        "name": "Demo Pack",
        "version": "1.0.0",
        "compatible_profile_versions": ["1.x"],
        "concept_types": {},
        "relationship_types": {},
        "aliases": {},
        "metadata_fields": {},
        "validation_rules": [],
        "fixtures": [],
        "migration_notes": [],
    }

    manifest = DomainPackManifest.model_validate(payload)

    assert manifest.pack_id == "demo-pack"
    with pytest.raises(ValidationError):
        DomainPackManifest.model_validate({k: v for k, v in payload.items() if k != "pack_id"})


def test_install_records_state_and_merges_profile(tmp_path: Path) -> None:
    nm, profile_store, pack_store = _store(tmp_path)
    profile_store.write(create_default_ontology_profile("demo"))
    manifest = pack_store.load_manifest("financial-services")

    result = pack_store.install("demo", manifest, profile_store.get("demo"))
    loaded = profile_store.get("demo")
    state = pack_store.get_state("demo")

    assert result.installed is True
    assert "financial_product" in loaded.concept_types
    assert loaded.aliases["complies_with"] == "regulated_by"
    assert state.installed_packs["financial-services"].version == "1.0.0"
    assert nm.get("demo").ontology_profile_version == loaded.version


def test_conflicting_alias_is_reported_before_saving(tmp_path: Path) -> None:
    _, profile_store, pack_store = _store(tmp_path)
    profile_store.write(create_default_ontology_profile("demo"))
    original = profile_store.get("demo")
    payload = pack_store.load_manifest("financial-services").model_dump(mode="json")
    payload["pack_id"] = "bad-finance"
    payload["aliases"] = {"requires": "regulated_by"}
    manifest = DomainPackManifest.model_validate(payload)

    with pytest.raises(DomainPackConflictError) as excinfo:
        pack_store.install("demo", manifest, original)

    assert any(issue.code == "ALIAS_CONFLICT" for issue in excinfo.value.issues)
    assert profile_store.get("demo") == original


def test_incompatible_profile_version_blocks_install(tmp_path: Path) -> None:
    _, profile_store, pack_store = _store(tmp_path)
    profile_store.write(create_default_ontology_profile("demo", version="2.0.0"))
    manifest = pack_store.load_manifest("financial-services")

    result = pack_store.validate(manifest, profile_store.get("demo"))

    assert result.valid is False
    assert any(issue.code == "INCOMPATIBLE_PROFILE_VERSION" for issue in result.issues)


def test_pack_cannot_mutate_core_system_relationship(tmp_path: Path) -> None:
    _, profile_store, pack_store = _store(tmp_path)
    profile = create_default_ontology_profile("demo")
    profile_store.write(profile)
    payload = pack_store.load_manifest("technology-saas").model_dump(mode="json")
    payload["pack_id"] = "bad-core"
    payload["relationship_types"] = {
        "enables": RelationshipType(
            id="enables",
            label="Mutated Enables",
            family="dependency",
            allowed_source_types=["service"],
            allowed_target_types=["feature"],
            is_system=False,
        ).model_dump(mode="json")
    }
    payload["aliases"] = {}
    manifest = DomainPackManifest.model_validate(payload)

    result = pack_store.validate(manifest, profile)

    assert result.valid is False
    assert any(issue.code == "CORE_RELATIONSHIP_CONFLICT" for issue in result.issues)


def test_uninstall_disables_pack_additions_without_corrupting_core_profile(tmp_path: Path) -> None:
    _, profile_store, pack_store = _store(tmp_path)
    profile_store.write(create_default_ontology_profile("demo"))
    manifest = pack_store.load_manifest("financial-services")
    pack_store.install("demo", manifest, profile_store.get("demo"))

    result = pack_store.uninstall("demo", "financial-services", profile_store.get("demo"))
    loaded = profile_store.get("demo")
    state = pack_store.get_state("demo")

    assert result.installed is False
    assert state.installed_packs["financial-services"].status == "disabled"
    assert "financial_product" not in loaded.concept_types
    assert "regulated_by" not in loaded.relationship_types
    assert "depends_on" in loaded.relationship_types
    assert loaded.aliases["requires"] == "depends_on"


def test_upgrade_reinstalls_same_pack_id_with_new_version_and_additions(tmp_path: Path) -> None:
    _, profile_store, pack_store = _store(tmp_path)
    profile_store.write(create_default_ontology_profile("demo"))
    v1_manifest = pack_store.load_manifest("financial-services")
    pack_store.install("demo", v1_manifest, profile_store.get("demo"))

    payload = v1_manifest.model_dump(mode="json")
    payload["version"] = "1.1.0"
    payload["metadata_fields"]["risk_tier"] = {
        "id": "risk_tier",
        "label": "Risk Tier",
        "field_type": "enum",
        "allowed_values": ["low", "medium", "high"],
        "description": "Risk classification used by upgraded financial packs.",
    }
    payload["aliases"]["banking_compliance"] = "regulated_by"
    v2_manifest = DomainPackManifest.model_validate(payload)

    result = pack_store.install("demo", v2_manifest, profile_store.get("demo"))
    loaded = profile_store.get("demo")
    state = pack_store.get_state("demo")

    assert result.action == "install"
    assert state.installed_packs["financial-services"].version == "1.1.0"
    assert "financial_product" in loaded.concept_types
    assert loaded.aliases["banking_compliance"] == "regulated_by"
    assert loaded.metadata_fields["risk_tier"].allowed_values == ["low", "medium", "high"]


def test_invalid_upgrade_conflict_rolls_back_profile_and_state(tmp_path: Path) -> None:
    _, profile_store, pack_store = _store(tmp_path)
    profile_store.write(create_default_ontology_profile("demo"))
    v1_manifest = pack_store.load_manifest("financial-services")
    pack_store.install("demo", v1_manifest, profile_store.get("demo"))
    original_profile = profile_store.get("demo")
    original_state = pack_store.get_state("demo")

    payload = v1_manifest.model_dump(mode="json")
    payload["version"] = "1.2.0"
    payload["aliases"]["complies_with"] = "depends_on"
    invalid_upgrade = DomainPackManifest.model_validate(payload)

    with pytest.raises(DomainPackConflictError) as excinfo:
        pack_store.install("demo", invalid_upgrade, profile_store.get("demo"))

    assert any(issue.code == "ALIAS_CONFLICT" for issue in excinfo.value.issues)
    assert profile_store.get("demo") == original_profile
    assert pack_store.get_state("demo") == original_state


def test_install_state_write_failure_rolls_back_profile_upgrade(tmp_path: Path) -> None:
    _, profile_store, pack_store = _store(tmp_path)
    profile_store.write(create_default_ontology_profile("demo"))
    manifest = pack_store.load_manifest("financial-services")
    original = profile_store.get("demo")

    original_write_state = pack_store.write_state
    calls = {"count": 0}

    def flaky_write_state(state):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated state write failure")
        return original_write_state(state)

    with patch.object(pack_store, "write_state", side_effect=flaky_write_state):
        with pytest.raises(RuntimeError, match="simulated state write failure"):
            pack_store.install("demo", manifest, original)

    assert profile_store.get("demo") == original
    assert pack_store.get_state("demo").installed_packs == {}


def test_uninstall_keeps_pack_additions_used_by_dependent_pack_and_graph_relation(tmp_path: Path) -> None:
    _, profile_store, pack_store = _store(tmp_path)
    profile_store.write(create_default_ontology_profile("demo"))
    base_payload = {
        "pack_id": "shared-pack",
        "name": "Shared Pack",
        "version": "1.0.0",
        "compatible_profile_versions": ["1.x"],
        "concept_types": {
            "shared_concept": {
                "id": "shared_concept",
                "label": "Shared Concept",
                "abstraction_level": "implementation",
                "description": "Concept provided by one pack and consumed by another.",
                "metadata_schema": {},
                "color": "#64748b",
                "shape": "rounded_rectangle",
            }
        },
        "relationship_types": {
            "shared_rel": {
                "id": "shared_rel",
                "label": "Shared relation",
                "family": "semantic",
                "description": "Relationship provided by the shared pack.",
                "allowed_source_types": ["feature"],
                "allowed_target_types": ["shared_concept"],
                "weight": 0.5,
            }
        },
        "aliases": {"shared_alias": "shared_rel"},
        "metadata_fields": {},
        "validation_rules": [],
        "fixtures": [
            {
                "id": "shared_graph_fixture",
                "edges": [
                    {
                        "relation_type": "shared_rel",
                        "source_type": "feature",
                        "target_type": "shared_concept",
                    }
                ],
            }
        ],
        "migration_notes": ["Provides shared ontology additions."],
    }
    dependent_payload = {
        "pack_id": "dependent-pack",
        "name": "Dependent Pack",
        "version": "1.0.0",
        "compatible_profile_versions": ["1.x"],
        "concept_types": {},
        "relationship_types": {
            "dependent_rel": {
                "id": "dependent_rel",
                "label": "Dependent relation",
                "family": "semantic",
                "description": "Relationship that depends on shared_concept from shared-pack.",
                "allowed_source_types": ["feature"],
                "allowed_target_types": ["shared_concept"],
                "weight": 0.5,
            }
        },
        "aliases": {"dependent_shared_alias": "shared_rel"},
        "metadata_fields": {},
        "validation_rules": [],
        "fixtures": [
            {
                "id": "dependent_graph_fixture",
                "edges": [
                    {
                        "relation_type": "dependent_rel",
                        "source_type": "feature",
                        "target_type": "shared_concept",
                    }
                ],
            }
        ],
        "migration_notes": ["Depends on shared-pack concept and relationship."],
    }
    shared_manifest = DomainPackManifest.model_validate(base_payload)
    dependent_manifest = DomainPackManifest.model_validate(dependent_payload)
    pack_store.install("demo", shared_manifest, profile_store.get("demo"))
    pack_store.install("demo", dependent_manifest, profile_store.get("demo"))

    def load_manifest(pack_id: str) -> DomainPackManifest:
        return {"shared-pack": shared_manifest, "dependent-pack": dependent_manifest}[pack_id]

    with patch.object(pack_store, "load_manifest", side_effect=load_manifest):
        pack_store.uninstall("demo", "shared-pack", profile_store.get("demo"))

    loaded = profile_store.get("demo")
    state = pack_store.get_state("demo")

    assert state.installed_packs["shared-pack"].status == "disabled"
    assert state.installed_packs["dependent-pack"].status == "installed"
    assert "shared_concept" in loaded.concept_types
    assert "shared_rel" in loaded.relationship_types
    assert loaded.aliases["dependent_shared_alias"] == "shared_rel"
    assert not validate_relationship("dependent_rel", "feature", "shared_concept", loaded)
    assert not validate_relationship("shared_rel", "feature", "shared_concept", loaded)


def test_service_install_from_clean_namespace_bootstraps_default_profile(tmp_path: Path) -> None:
    nm = NamespaceManager(base_dir=tmp_path / "kb")
    nm.create("demo")
    service = KnowledgeService(namespace_manager=nm)

    result = service.install_domain_pack("demo", "financial-services")

    assert result["installed"] is True
    assert result["profile"]["concept_types"]["financial_product"]
    assert service.get_ontology_profile("demo") is not None


@pytest.fixture(autouse=True)
def _set_test_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OSTWIN_API_KEY", "test-api-key")


def test_domain_pack_api_endpoints() -> None:
    service = MagicMock()
    manifest_payload = {
        "pack_id": "financial-services",
        "name": "Financial Services",
        "version": "1.0.0",
        "compatible_profile_versions": ["1.x"],
        "concept_types": {"financial_product": {"id": "financial_product", "default_layer": "product"}},
        "relationship_types": {"regulated_by": {"id": "regulated_by", "map_direction": "forward"}},
        "layers": {"product": {"id": "product", "label": "Product", "order": 1}},
        "abstraction_levels": {"feature": {"id": "feature", "label": "Feature", "order": 2}},
        "graph_instruction": {
            "default_views": [{"id": "finance_map", "label": "Finance Map"}],
            "relationship_type_defaults": {
                "regulated_by": {"relationship_type": "regulated_by", "map_direction": "forward"}
            },
        },
    }
    service.list_available_domain_packs.return_value = [manifest_payload]
    service.list_installed_domain_packs.return_value = {"namespace": "demo", "schema_version": 1, "installed_packs": {}}
    service.validate_domain_pack_install.return_value = {
        "namespace": "demo",
        "pack_id": "financial-services",
        "valid": True,
        "issues": [],
        "profile": None,
        "manifest": manifest_payload,
    }
    service.install_domain_pack.return_value = {
        "namespace": "demo",
        "pack_id": "financial-services",
        "action": "install",
        "installed": True,
        "profile": {"profile_id": "enterprise_feature_map"},
        "state": {"namespace": "demo", "schema_version": 1, "installed_packs": {}},
        "issues": [],
    }

    app = FastAPI()
    app.include_router(router)
    headers = {"X-API-Key": "test-api-key"}
    with patch("dashboard.routes.knowledge._get_service", return_value=service):
        client = TestClient(app)
        packs_response = client.get("/api/knowledge/ontology/packs", headers=headers)
        assert packs_response.status_code == 200
        pack_json = packs_response.json()["packs"][0]
        assert pack_json["layers"]["product"]["id"] == "product"
        assert pack_json["abstraction_levels"]["feature"]["id"] == "feature"
        assert pack_json["graph_instruction"]["default_views"][0]["id"] == "finance_map"
        assert pack_json["graph_instruction"]["relationship_type_defaults"]["regulated_by"]["map_direction"] == "forward"
        assert client.get("/api/knowledge/namespaces/demo/ontology/packs", headers=headers).status_code == 200
        validate_json = client.post(
            "/api/knowledge/namespaces/demo/ontology/packs/validate",
            headers=headers,
            json={"pack_id": "financial-services"},
        ).json()
        assert validate_json["valid"] is True
        assert validate_json["manifest"]["graph_instruction"]["default_views"][0]["id"] == "finance_map"
        assert client.post(
            "/api/knowledge/namespaces/demo/ontology/packs/install",
            headers=headers,
            json={"pack_id": "financial-services"},
        ).json()["installed"] is True


def test_epic008_domain_pack_response_preserves_graph_instruction_contract(tmp_path: Path) -> None:
    _, _, pack_store = _store(tmp_path)
    manifest = pack_store.load_manifest("ecommerce-logistics")

    response = DomainPackManifestResponse.model_validate(manifest.model_dump(mode="json")).model_dump()

    assert response["layers"]["commerce"]["label"] == "Commerce"
    assert response["abstraction_levels"] == {}
    assert response["graph_instruction"]["default_views"][0]["id"] == "domain_map"
    assert response["graph_instruction"]["concept_type_defaults"]["order"]["default_layer"] == "commerce"
    assert response["graph_instruction"]["relationship_type_defaults"]["reserves"]["map_direction"] == "reversed"
    assert response["relationship_types"]["reserves"]["map_direction"] == "reversed"


def test_epic008_audit_and_ecommerce_packs_declare_graph_instructions(tmp_path: Path) -> None:
    _, profile_store, pack_store = _store(tmp_path)
    profile_store.write(create_default_ontology_profile("demo"))

    audit = pack_store.load_manifest("audit-risk-management")
    ecommerce = pack_store.load_manifest("ecommerce-logistics")

    audit_preview = pack_store.validate(audit, profile_store.get("demo")).profile
    assert audit_preview is not None
    assert set(audit_preview.concept_types) >= {"risk", "control", "obligation", "evidence", "finding", "remediation"}
    assert set(ecommerce.concept_types) >= {
        "order",
        "shipment",
        "carrier",
        "inventory",
        "crm_touchpoint",
        "sla",
        "integration",
    }
    assert audit.graph_instruction.relationship_type_defaults["mitigates"].map_direction == "forward"
    assert ecommerce.graph_instruction.relationship_type_defaults["reserves"].map_direction == "reversed"
    assert audit.fixtures and ecommerce.fixtures
    assert pack_store.validate(audit, profile_store.get("demo")).valid is True
    assert pack_store.validate(ecommerce, profile_store.get("demo")).valid is True


def test_epic008_pack_install_merges_layers_and_graph_instruction(tmp_path: Path) -> None:
    _, profile_store, pack_store = _store(tmp_path)
    profile_store.write(create_default_ontology_profile("demo"))

    result = pack_store.install("demo", pack_store.load_manifest("audit-risk"), profile_store.get("demo"))

    assert result.profile.concept_types["risk"].default_layer == "risk"
    assert "risk" in result.profile.layers
    assert "mitigates" in result.profile.graph_instruction.relationship_type_defaults
    assert result.profile.graph_instruction.relationship_type_defaults["mitigates"].map_direction == "forward"


def test_epic008_unknown_concepts_and_relations_become_review_candidates() -> None:
    profile = create_default_ontology_profile("demo")

    node_issues = validate_relationship("mystery_relation", "unknown_source", "unknown_target", profile)

    assert any(issue.code == "CANDIDATE_RELATION_TYPE" for issue in node_issues)
    assert node_issues[0].metadata["candidate"] == "mystery_relation"



def test_default_packs_and_dm03_relationship_families_validate(tmp_path: Path) -> None:
    _, profile_store, pack_store = _store(tmp_path)
    profile = create_default_ontology_profile("demo")
    profile_store.write(profile)

    loaded_pack_ids = {manifest.pack_id for manifest in pack_store.list_available()}
    assert loaded_pack_ids >= {
        "financial-services",
        "technology-saas",
        "retail-consumer",
        "public-sector",
        "esg",
        "audit-risk-management",
        "audit-risk",
        "ecommerce-logistics",
    }
    for family in ["classification", "causality", "temporal"]:
        payload = {
            "pack_id": f"{family}-pack",
            "name": f"{family.title()} Pack",
            "version": "1.0.0",
            "compatible_profile_versions": ["1.x"],
            "relationship_types": {
                f"{family}_rel": {
                    "id": f"{family}_rel",
                    "label": f"{family.title()} Relation",
                    "family": family,
                }
            },
            "fixtures": [{"id": f"{family}-fixture"}],
            "migration_notes": ["DM-03 proposed family coverage."],
        }
        manifest = DomainPackManifest.model_validate(payload)
        result = pack_store.validate(manifest, profile)
        assert result.valid is True


def test_pack_install_and_uninstall_append_profile_history_without_mixing_observation_events(tmp_path: Path) -> None:
    nm = NamespaceManager(base_dir=tmp_path / "kb")
    nm.create("demo")
    service = KnowledgeService(namespace_manager=nm)
    service.save_ontology_profile(create_default_ontology_profile("demo"), actor="alice", reason="Seed")

    service.install_domain_pack("demo", "financial-services", actor="po", reason="Install finance vocabulary")
    latest = service.list_ontology_profile_history("demo")[0]
    assert latest["actor"] == "po"
    assert latest["reason"] == "Install finance vocabulary"
    assert any(entry["kind"] == "domain_pack_install" for entry in latest["migration_entries"])
    assert "financial_product" in latest["diff"]["added"]["concept_types"]

    service.uninstall_domain_pack("demo", "financial-services", actor="po", reason="Disable finance vocabulary")
    latest = service.list_ontology_profile_history("demo")[0]
    assert any(entry["kind"] == "domain_pack_uninstall" for entry in latest["migration_entries"])
    assert "financial_product" in latest["diff"]["removed"]["concept_types"]
    assert service.list_observation_events("demo", event_type="DomainPackInstalled")
    assert all("event_type" not in record for record in service.list_ontology_profile_history("demo"))
