"""EPIC-003 — Ontology profile Knowledge REST API tests."""

from __future__ import annotations

from collections.abc import Iterator
import json
from unittest.mock import MagicMock, patch

import pytest
from dashboard.routes.knowledge import router
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _set_test_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OSTWIN_API_KEY", "test-api-key")


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"X-API-Key": "test-api-key"}


@pytest.fixture
def mock_service() -> MagicMock:
    service = MagicMock()
    return service


@pytest.fixture
def client(mock_service: MagicMock) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router)
    with patch("dashboard.routes.knowledge._get_service", return_value=mock_service):
        with TestClient(app) as test_client:
            yield test_client


class TestOntologyProfileAPI:
    """Tests for /api/knowledge/namespaces/{namespace}/ontology endpoints."""


    def test_get_unit_returns_draft_identity(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        mock_service.get_ontology_unit_response.return_value = {
            "namespace": "demo",
            "unit_exists": True,
            "unit": {
                "id": "demo",
                "namespace": "demo",
                "active_profile_id": None,
                "name": "Audit Process Unit",
                "purpose": "Govern audit process vocabulary",
                "domain": "audit",
                "expected_users": ["auditor"],
                "source_material": ["policy.pdf"],
                "governance_mode": "strict",
            },
        }

        response = client.get("/api/knowledge/namespaces/demo/ontology/unit", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["unit_exists"] is True
        assert data["unit"]["active_profile_id"] is None
        assert data["unit"]["name"] == "Audit Process Unit"
        mock_service.get_ontology_unit_response.assert_called_once_with("demo")

    def test_put_unit_saves_identity_without_profile_publication(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        unit = MagicMock()
        unit.model_dump.return_value = {
            "id": "demo",
            "namespace": "demo",
            "active_profile_id": None,
            "name": "Build Software Unit",
            "purpose": "Model software delivery",
            "domain": "software",
            "expected_users": ["engineer"],
            "source_material": ["repo"],
            "governance_mode": "manual",
        }
        mock_service.save_ontology_unit_payload.return_value = unit

        response = client.put(
            "/api/knowledge/namespaces/demo/ontology/unit",
            headers=auth_headers,
            json={"unit": unit.model_dump.return_value},
        )

        assert response.status_code == 200
        assert response.json()["unit"]["active_profile_id"] is None
        mock_service.save_ontology_unit_payload.assert_called_once()
        mock_service.save_ontology_profile_payload.assert_not_called()

    def test_get_profile_returns_default_suggestion_for_legacy_namespace(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        from dashboard.knowledge.ontology.defaults import create_default_ontology_profile

        profile = create_default_ontology_profile("legacy")
        mock_service.get_ontology_profile_with_default.return_value = {
            "namespace": "legacy",
            "profile": None,
            "profile_exists": False,
            "default_suggested": True,
            "default_profile": profile.model_dump(mode="json"),
            "validation_issues": [],
        }

        response = client.get("/api/knowledge/namespaces/legacy/ontology/profile", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["profile_exists"] is False
        assert data["default_suggested"] is True
        assert data["default_profile"]["profile_id"] == "enterprise_feature_map"

    def test_put_profile_saves_validated_payload(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        from dashboard.knowledge.ontology.defaults import create_default_ontology_profile

        profile = create_default_ontology_profile("demo")
        mock_service.save_ontology_profile_payload.return_value = profile

        response = client.put(
            "/api/knowledge/namespaces/demo/ontology/profile",
            headers=auth_headers,
            json={"profile": profile.model_dump(mode="json")},
        )

        assert response.status_code == 200
        assert response.json()["profile_exists"] is True
        mock_service.save_ontology_profile_payload.assert_called_once()

    def test_validate_edge_is_side_effect_free(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        mock_service.validate_ontology_payload.return_value = {
            "namespace": "demo",
            "subject": "edge",
            "valid": False,
            "issues": [
                {
                    "severity": "error",
                    "code": "INVALID_RELATION_SOURCE_TYPE",
                    "path": "edge.source.type",
                    "message": "Invalid source type",
                    "suggested_fix": "Use an allowed source type.",
                    "subject": "edge",
                    "metadata": {},
                }
            ],
        }

        response = client.post(
            "/api/knowledge/namespaces/demo/ontology/validate",
            headers=auth_headers,
            json={
                "subject": "edge",
                "edge": {"relation_type": "contains", "source_type": "service", "target_type": "feature"},
            },
        )

        assert response.status_code == 200
        assert response.json()["valid"] is False
        mock_service.validate_ontology_payload.assert_called_once()
        mock_service.save_ontology_profile_payload.assert_not_called()

    def test_reset_default_creates_or_replaces_profile(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        from dashboard.knowledge.ontology.defaults import create_default_ontology_profile

        profile = create_default_ontology_profile("demo")
        mock_service.reset_default_ontology_profile.return_value = (profile, True)

        response = client.post("/api/knowledge/namespaces/demo/ontology/reset-default", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["replaced_existing"] is True
        assert response.json()["profile"]["namespace"] == "demo"

    def test_summary_returns_ontology_counts(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        mock_service.get_ontology_summary.return_value = {
            "namespace": "demo",
            "profile_exists": True,
            "profile_id": "enterprise_feature_map",
            "version": "1.0.0",
            "concept_type_count": 8,
            "relation_type_count": 9,
            "alias_count": 4,
            "candidate_count": 0,
            "validation_issue_count": 0,
            "validation_issues": [],
        }

        response = client.get("/api/knowledge/namespaces/demo/ontology/summary", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["concept_type_count"] == 8
        assert data["relation_type_count"] == 9
        assert data["alias_count"] == 4


    def test_ontology_assistant_uses_bounded_context_and_stable_conversation(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        async def fake_master_chat(messages, conversation_id):
            fake_master_chat.messages = messages
            fake_master_chat.conversation_id = conversation_id
            return type("Response", (), {"content": "Proposed only."})()

        mock_service._require_namespace.return_value = None
        profile = {
            "profile_id": "enterprise_feature_map",
            "version": "1.0.0",
            "concept_types": {"feature": {"id": "feature", "label": "Feature", "description": "x" * 10000}},
            "relationship_types": {},
            "layers": {},
            "abstraction_levels": {},
            "metadata_fields": {},
            "validation_rules": [],
        }
        with patch("dashboard.master_agent.master_chat", side_effect=fake_master_chat):
            response = client.post(
                "/api/knowledge/namespaces/demo/ontology/assistant",
                headers=auth_headers,
                json={
                    "message": "Review selected",
                    "profile": profile,
                    "selected": {"kind": "concept", "id": "feature", "object": profile["concept_types"]["feature"]},
                    "context": {"evidence_refs": ["anchor-1"], "candidate_refs": [{"id": "cand-1"}]},
                },
            )

        assert response.status_code == 200
        assert response.json()["conversation_id"] == "ontology-schema:demo:api-key-user"
        assert fake_master_chat.conversation_id == "ontology-schema:demo:api-key-user"
        prompt = fake_master_chat.messages[0].content
        user_context = fake_master_chat.messages[-1].content
        assert "advisory conversational co-builder" in prompt
        assert "apply_to_draft" in user_context
        assert "anchor-1" in user_context
        assert "x" * 5000 not in user_context
        assert '"profile"' not in user_context
        mock_service.save_ontology_profile_payload.assert_not_called()

    def test_ontology_assistant_preserves_recent_history_roles(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        async def fake_master_chat(messages, conversation_id):
            fake_master_chat.messages = messages
            return type("Response", (), {"content": "ok"})()

        mock_service._require_namespace.return_value = None
        with patch("dashboard.master_agent.master_chat", side_effect=fake_master_chat):
            response = client.post(
                "/api/knowledge/namespaces/demo/ontology/assistant",
                headers=auth_headers,
                json={
                    "message": "Map candidate",
                    "profile": {"profile_id": "p", "version": "1", "concept_types": {}, "relationship_types": {}, "layers": {}, "abstraction_levels": {}, "metadata_fields": {}},
                    "history": [{"role": "assistant", "content": "Prior advisory answer"}],
                },
            )

        assert response.status_code == 200
        assert any(msg.role == "assistant" and msg.content == "Prior advisory answer" for msg in fake_master_chat.messages)



    def test_ontology_assistant_returns_fallback_pack_draft_when_master_fails(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        async def failing_master_chat(messages, conversation_id):
            raise RuntimeError("Internal Server Error")

        mock_service._require_namespace.return_value = None
        profile = {
            "profile_id": "enterprise_feature_map",
            "version": "1.0.0",
            "concept_types": {"feature": {"id": "feature", "label": "Feature"}},
            "relationship_types": {},
            "layers": {},
            "abstraction_levels": {},
            "metadata_fields": {},
            "validation_rules": [],
        }
        with patch("dashboard.master_agent.master_chat", side_effect=failing_master_chat):
            response = client.post(
                "/api/knowledge/namespaces/demo/ontology/assistant",
                headers=auth_headers,
                json={
                    "message": "Draft a small vocabulary bundle proposal with concept_types, relationship_types, layers, metadata_fields, graph_instruction, fixtures, and migration_notes.",
                    "profile": profile,
                },
            )

        assert response.status_code == 200
        text = response.json()["text"]
        assert "```json" in text
        raw = text.split("```json", 1)[1].split("```", 1)[0].strip()
        proposed = json.loads(raw)["proposed_changes"]
        for section in [
            "concept_types",
            "relationship_types",
            "layers",
            "metadata_fields",
            "graph_instruction",
            "fixtures",
            "migration_notes",
        ]:
            assert section in proposed
        mock_service.save_ontology_profile_payload.assert_not_called()

    def test_ontology_assistant_falls_back_for_nonconforming_pack_draft_success(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        async def nonconforming_master_chat(messages, conversation_id):
            return type(
                "Response",
                (),
                {
                    "content": (
                        "Here is a bundle draft.\n"
                        "```json\n"
                        '{"bundle_id":"audit-risk","namespace":"demo","status":"draft","concepts":[]}\n'
                        "```"
                    )
                },
            )()

        mock_service._require_namespace.return_value = None
        profile = {
            "profile_id": "enterprise_feature_map",
            "version": "1.0.0",
            "concept_types": {},
            "relationship_types": {},
            "layers": {},
            "abstraction_levels": {},
            "metadata_fields": {},
            "validation_rules": [],
        }
        with patch("dashboard.master_agent.master_chat", side_effect=nonconforming_master_chat):
            response = client.post(
                "/api/knowledge/namespaces/demo/ontology/assistant",
                headers=auth_headers,
                json={
                    "message": "Draft pack from these docs as a reviewable vocabulary bundle proposal.",
                    "profile": profile,
                },
            )

        assert response.status_code == 200
        text = response.json()["text"]
        raw = text.split("```json", 1)[1].split("```", 1)[0].strip()
        parsed = json.loads(raw)
        assert "proposed_changes" in parsed
        assert "bundle_id" not in parsed
        proposed = parsed["proposed_changes"]
        for section in [
            "concept_types",
            "relationship_types",
            "layers",
            "metadata_fields",
            "graph_instruction",
            "fixtures",
            "migration_notes",
        ]:
            assert section in proposed
        mock_service.save_ontology_profile_payload.assert_not_called()

    def test_ontology_endpoint_maps_invalid_namespace_to_404(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        from dashboard.knowledge.namespace import NamespaceNotFoundError

        mock_service.get_ontology_summary.side_effect = NamespaceNotFoundError("missing")

        response = client.get("/api/knowledge/namespaces/missing/ontology/summary", headers=auth_headers)

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "NAMESPACE_NOT_FOUND"

    def test_put_profile_invalid_payload_uses_knowledge_error_mapping(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        mock_service.save_ontology_profile_payload.side_effect = ValueError(
            "Ontology profile namespace must match path namespace"
        )

        response = client.put(
            "/api/knowledge/namespaces/demo/ontology/profile",
            headers=auth_headers,
            json={"profile": {"profile_id": "enterprise_feature_map", "namespace": "other", "version": "1.0.0"}},
        )

        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "INVALID_REQUEST"

    def test_validate_malformed_subject_is_rejected_by_pydantic(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        response = client.post(
            "/api/knowledge/namespaces/demo/ontology/validate",
            headers=auth_headers,
            json={"subject": "unknown"},
        )

        assert response.status_code == 422
        mock_service.validate_ontology_payload.assert_not_called()

    def test_ontology_endpoints_require_authentication(self, client: TestClient, mock_service: MagicMock) -> None:
        response = client.get("/api/knowledge/namespaces/demo/ontology/profile")

        assert response.status_code == 401
        mock_service.get_ontology_profile_with_default.assert_not_called()


class TestEnterpriseMapAPI:
    def test_enterprise_map_endpoint_uses_typed_response_model(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        mock_service.ontology_enterprise_map.return_value = {
            "nodes": [
                {
                    "id": "svc-1",
                    "label": "service",
                    "name": "Sync Service",
                    "concept_type": "service",
                    "layer_id": "delivery",
                    "layer_label": "Delivery",
                    "layer_order": 3,
                    "owner": "Platform",
                    "metadata": {"owner": "Platform"},
                    "properties": {},
                    "ontology_path": {"layer": "delivery", "concept_type": "service"},
                }
            ],
            "edges": [
                {
                    "source": "svc-1",
                    "target": "order-1",
                    "label": "syncs_with",
                    "relationship_type": "syncs_with",
                    "family": "integration",
                    "style": "dashed",
                    "map_source": "svc-1",
                    "map_target": "order-1",
                    "map_direction": "forward",
                }
            ],
            "layers": [{"id": "delivery", "label": "Delivery", "order": 3, "count": 1}],
            "abstraction_levels": [],
            "concept_type_counts": {"service": 1},
            "relationship_type_counts": {"syncs_with": 1},
            "relationship_family_counts": {"integration": 1},
            "stats": {"node_count": 1, "edge_count": 1, "layer_count": 1, "concept_type_count": 1, "relationship_type_count": 1, "candidate_edge_count": 0, "validation_issue_count": 0, "limit": 200},
            "meta": {"profile_exists": True, "ontology_candidate_count": 0, "graph_instruction": {"schema_version": 1}},
        }

        response = client.get("/api/knowledge/namespaces/demo/ontology/enterprise-map", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["nodes"][0]["ontology_path"]["layer"] == "delivery"
        assert data["edges"][0]["relationship_type"] == "syncs_with"
        assert data["meta"]["graph_instruction"]["schema_version"] == 1
