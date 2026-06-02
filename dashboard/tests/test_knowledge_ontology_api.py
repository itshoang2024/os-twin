"""EPIC-003 — Ontology profile Knowledge REST API tests."""

from __future__ import annotations

from collections.abc import Iterator
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
