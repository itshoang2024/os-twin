"""EPIC-001 — Knowledge REST API tests.

Covers:
- TestNamespacesAPI: CRUD on namespaces
- TestImportAPI: folder import submission
- TestJobsAPI: job listing and status polling
- TestQueryAPI: all three query modes
- TestErrorMapping: error code responses
- TestAuth: authentication enforcement
- TestLazyImport: import-time audit
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure dashboard is importable
_root = Path(__file__).resolve().parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_service() -> MagicMock:
    """Create a mock KnowledgeService for testing."""
    from dashboard.knowledge.namespace import NamespaceStats, ImportRecord
    from dashboard.knowledge.jobs import JobState
    
    service = MagicMock()

    # Create proper NamespaceStats
    stats = NamespaceStats(
        files_indexed=0,
        chunks=0,
        entities=0,
        relations=0,
        vectors=0,
        bytes_on_disk=0,
    )
    
    # Namespace methods - create proper NamespaceMeta-like objects
    class MockNamespaceMeta:
        def __init__(self, name="test-ns", description="Test namespace", language="English"):
            self.schema_version = 1
            self.name = name
            self.created_at = datetime.now(timezone.utc)
            self.updated_at = datetime.now(timezone.utc)
            self.language = language
            self.description = description
            self.embedding_model = "qwen3-embedding:0.6b"
            self.embedding_dimension = 1024
            self.stats = stats
            self.imports = []
        
        def model_dump(self, mode=None):
            return {
                "schema_version": self.schema_version,
                "name": self.name,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "language": self.language,
                "description": self.description,
                "embedding_model": self.embedding_model,
                "embedding_dimension": self.embedding_dimension,
                "stats": {
                    "files_indexed": self.stats.files_indexed,
                    "chunks": self.stats.chunks,
                    "entities": self.stats.entities,
                    "relations": self.stats.relations,
                    "vectors": self.stats.vectors,
                    "bytes_on_disk": self.stats.bytes_on_disk,
                },
                "imports": [],
            }
    
    service._mock_meta_class = MockNamespaceMeta
    service.list_namespaces.return_value = []
    service.get_namespace.return_value = None
    service.create_namespace.return_value = MockNamespaceMeta()
    service.delete_namespace.return_value = True

    # Import/job methods
    service.import_folder.return_value = "test-job-id-123"
    service.list_jobs.return_value = []
    service.get_job.return_value = None

    # Query/graph methods
    class MockQueryResult:
        def __init__(self):
            self.query = "test query"
            self.mode = "raw"
            self.namespace = "test-ns"
            self.chunks = []
            self.entities = []
            self.answer = None
            self.citations = []
            self.latency_ms = 50
            self.warnings = []
    
    service.query.return_value = MockQueryResult()

    return service


@pytest.fixture
def client(mock_service: MagicMock) -> Iterator[TestClient]:
    """Create a test client with mocked service."""
    # Clear the service singleton
    import dashboard.routes.knowledge as knowledge_routes

    knowledge_routes._service_instance = None  # type: ignore[attr-defined]

    with patch("dashboard.routes.knowledge._get_service", return_value=mock_service):
        from dashboard.api import app

        with TestClient(app) as test_client:
            yield test_client

    # Clean up
    knowledge_routes._service_instance = None  # type: ignore[attr-defined]


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Return auth headers for API key authentication."""
    # Use a test API key
    api_key = os.environ.get("OSTWIN_API_KEY", "test-api-key")
    return {"X-API-Key": api_key}


@pytest.fixture(autouse=True)
def _set_test_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set a test API key for all tests."""
    monkeypatch.setenv("OSTWIN_API_KEY", "test-api-key")


# ---------------------------------------------------------------------------
# Test Namespaces API
# ---------------------------------------------------------------------------


class TestNamespacesAPI:
    """Tests for /api/knowledge/namespaces endpoints."""

    def test_list_namespaces_empty(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """GET /namespaces returns empty list when no namespaces exist."""
        mock_service.list_namespaces.return_value = []
        response = client.get("/api/knowledge/namespaces", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []

    def test_list_namespaces_returns_list(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """GET /namespaces returns list of namespaces."""
        MockNamespaceMeta = mock_service._mock_meta_class
        mock_service.list_namespaces.return_value = [
            MockNamespaceMeta(name="ns1", description="First namespace")
        ]
        response = client.get("/api/knowledge/namespaces", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "ns1"


    def test_create_namespace_invalid_name(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """POST /namespaces returns 400 for invalid namespace name."""
        # The Pydantic model validates the pattern first, so we get 422
        response = client.post(
            "/api/knowledge/namespaces",
            headers=auth_headers,
            json={"name": "Invalid-Name!"},
        )
        # FastAPI validates the pattern before calling our code
        assert response.status_code == 422

    def test_create_namespace_already_exists(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """POST /namespaces returns 409 when namespace already exists."""
        from dashboard.knowledge.namespace import NamespaceExistsError

        mock_service.create_namespace.side_effect = NamespaceExistsError("Exists!")

        response = client.post(
            "/api/knowledge/namespaces",
            headers=auth_headers,
            json={"name": "existing-ns"},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "NAMESPACE_EXISTS"

    def test_get_namespace_success(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """GET /namespaces/{namespace} returns namespace metadata."""
        MockNamespaceMeta = mock_service._mock_meta_class
        mock_service.get_namespace.return_value = MockNamespaceMeta(name="test-ns")
        response = client.get("/api/knowledge/namespaces/test-ns", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["name"] == "test-ns"

    def test_get_namespace_not_found(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """GET /namespaces/{namespace} returns 404 when namespace doesn't exist."""
        mock_service.get_namespace.return_value = None
        response = client.get("/api/knowledge/namespaces/nonexistent", headers=auth_headers)
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "NAMESPACE_NOT_FOUND"

    def test_delete_namespace_success(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """DELETE /namespaces/{namespace} deletes a namespace."""
        response = client.delete("/api/knowledge/namespaces/test-ns", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] is True
        assert data["namespace"] == "test-ns"

    def test_delete_namespace_not_found_returns_false(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """DELETE /namespaces/{namespace} returns {deleted: false} for non-existent."""
        mock_service.delete_namespace.return_value = False
        response = client.delete("/api/knowledge/namespaces/nonexistent", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["deleted"] is False


# ---------------------------------------------------------------------------
# Test Import API
# ---------------------------------------------------------------------------


class TestImportAPI:
    """Tests for /api/knowledge/namespaces/{namespace}/import endpoint."""

    def test_import_folder_success(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock, tmp_path: Path
    ) -> None:
        """POST /namespaces/{namespace}/import starts an import job."""
        folder = tmp_path / "test-docs"
        folder.mkdir()

        response = client.post(
            "/api/knowledge/namespaces/test-ns/import",
            headers=auth_headers,
            json={"folder_path": str(folder)},
        )
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["namespace"] == "test-ns"

    def test_import_folder_relative_path_rejected(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """POST /import returns 400 for relative paths."""
        response = client.post(
            "/api/knowledge/namespaces/test-ns/import",
            headers=auth_headers,
            json={"folder_path": "relative/path"},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "INVALID_FOLDER_PATH"

    def test_import_folder_empty_path_rejected(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """POST /import returns 400 for empty path."""
        response = client.post(
            "/api/knowledge/namespaces/test-ns/import",
            headers=auth_headers,
            json={"folder_path": ""},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "INVALID_FOLDER_PATH"

    def test_import_folder_system_directory_rejected(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """POST /import returns 400 for system directories."""
        # Note: On macOS, /etc is a symlink to /private/etc, so we test with /dev
        # which is a real system directory that exists and matches the deny-list
        response = client.post(
            "/api/knowledge/namespaces/test-ns/import",
            headers=auth_headers,
            json={"folder_path": "/dev"},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "INVALID_FOLDER_PATH"

    def test_import_folder_nonexistent_rejected(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """POST /import returns 404 for non-existent folder."""
        response = client.post(
            "/api/knowledge/namespaces/test-ns/import",
            headers=auth_headers,
            json={"folder_path": "/nonexistent/path"},
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "FOLDER_NOT_FOUND"

    def test_import_folder_file_not_directory(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock, tmp_path: Path
    ) -> None:
        """POST /import returns 400 when path is a file, not a directory."""
        file = tmp_path / "test.txt"
        file.write_text("content")

        response = client.post(
            "/api/knowledge/namespaces/test-ns/import",
            headers=auth_headers,
            json={"folder_path": str(file)},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "NOT_A_DIRECTORY"


# ---------------------------------------------------------------------------
# Test Jobs API
# ---------------------------------------------------------------------------


class TestJobsAPI:
    """Tests for /api/knowledge/namespaces/{namespace}/jobs endpoints."""

    def test_list_jobs_empty(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """GET /namespaces/{namespace}/jobs returns empty list."""
        mock_service.list_jobs.return_value = []
        response = client.get("/api/knowledge/namespaces/test-ns/jobs", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []

    def test_list_jobs_returns_jobs(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """GET /namespaces/{namespace}/jobs returns list of jobs."""
        from dashboard.knowledge.jobs import JobState

        mock_service.list_jobs.return_value = [
            MagicMock(
                job_id="job-1",
                namespace="test-ns",
                operation="import_folder",
                state=JobState.COMPLETED,
                submitted_at=datetime.now(timezone.utc),
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
                progress_current=100,
                progress_total=100,
                message="Done",
                errors=[],
                result={"files_processed": 5},
            )
        ]
        response = client.get("/api/knowledge/namespaces/test-ns/jobs", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["job_id"] == "job-1"

    def test_get_job_success(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """GET /namespaces/{namespace}/jobs/{job_id} returns job status."""
        from dashboard.knowledge.jobs import JobState

        mock_service.get_job.return_value = MagicMock(
            job_id="job-123",
            namespace="test-ns",
            operation="import_folder",
            state=JobState.RUNNING,
            submitted_at=datetime.now(timezone.utc),
            started_at=datetime.now(timezone.utc),
            finished_at=None,
            progress_current=50,
            progress_total=100,
            message="Processing...",
            errors=[],
            result=None,
        )
        response = client.get("/api/knowledge/namespaces/test-ns/jobs/job-123", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "job-123"
        assert data["state"] == "running"

    def test_get_job_not_found(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """GET /namespaces/{namespace}/jobs/{job_id} returns 404 for unknown job."""
        mock_service.get_job.return_value = None
        response = client.get("/api/knowledge/namespaces/test-ns/jobs/nonexistent", headers=auth_headers)
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "JOB_NOT_FOUND"


# ---------------------------------------------------------------------------
# Test Query API
# ---------------------------------------------------------------------------


class TestQueryAPI:
    """Tests for /api/knowledge/namespaces/{namespace}/query endpoint."""

    def test_query_raw_mode(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """POST /query with mode=raw returns vector search results."""
        mock_service.query.return_value = MagicMock(
            query="test query",
            mode="raw",
            namespace="test-ns",
            chunks=[
                MagicMock(
                    text="Result text",
                    score=0.85,
                    file_path="/docs/file.md",
                    filename="file.md",
                    chunk_index=0,
                    total_chunks=1,
                    file_hash="abc123",
                    mime_type="text/markdown",
                    category_id=None,
                    model_dump=lambda: {
                        "text": "Result text",
                        "score": 0.85,
                        "file_path": "/docs/file.md",
                        "filename": "file.md",
                        "chunk_index": 0,
                        "total_chunks": 1,
                        "file_hash": "abc123",
                        "mime_type": "text/markdown",
                        "category_id": None,
                    },
                )
            ],
            entities=[],
            answer=None,
            citations=[],
            latency_ms=42,
            warnings=[],
        )

        response = client.post(
            "/api/knowledge/namespaces/test-ns/query",
            headers=auth_headers,
            json={"query": "test query", "mode": "raw"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["mode"] == "raw"
        assert len(data["chunks"]) == 1
        assert data["chunks"][0]["score"] == 0.85

    def test_query_graph_mode(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """POST /query with mode=graph returns chunks + entities."""
        mock_service.query.return_value = MagicMock(
            query="test query",
            mode="graph",
            namespace="test-ns",
            chunks=[],
            entities=[
                MagicMock(
                    id="ent-1",
                    name="Entity One",
                    label="concept",
                    score=0.9,
                    description="A concept",
                    category_id=None,
                    model_dump=lambda: {
                        "id": "ent-1",
                        "name": "Entity One",
                        "label": "concept",
                        "score": 0.9,
                        "description": "A concept",
                        "category_id": None,
                    },
                )
            ],
            answer=None,
            citations=[],
            latency_ms=120,
            warnings=[],
        )

        response = client.post(
            "/api/knowledge/namespaces/test-ns/query",
            headers=auth_headers,
            json={"query": "test query", "mode": "graph"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["mode"] == "graph"
        assert len(data["entities"]) == 1

    def test_query_summarized_mode(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """POST /query with mode=summarized returns LLM answer."""
        mock_service.query.return_value = MagicMock(
            query="test query",
            mode="summarized",
            namespace="test-ns",
            chunks=[],
            entities=[],
            answer="This is the LLM-generated answer.",
            citations=[],
            latency_ms=250,
            warnings=[],
        )

        response = client.post(
            "/api/knowledge/namespaces/test-ns/query",
            headers=auth_headers,
            json={"query": "test query", "mode": "summarized"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "This is the LLM-generated answer."

    def test_query_namespace_not_found(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """POST /query returns 404 when namespace doesn't exist."""
        from dashboard.knowledge.namespace import NamespaceNotFoundError

        mock_service.query.side_effect = NamespaceNotFoundError("test-ns")
        response = client.post(
            "/api/knowledge/namespaces/nonexistent/query",
            headers=auth_headers,
            json={"query": "test"},
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "NAMESPACE_NOT_FOUND"




# ---------------------------------------------------------------------------
# Test Error Mapping
# ---------------------------------------------------------------------------


class TestErrorMapping:
    """Tests for error code responses."""

    def test_invalid_namespace_id_error(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """Invalid namespace ID returns 400 with INVALID_NAMESPACE_ID code."""
        from dashboard.knowledge.namespace import InvalidNamespaceIdError

        # Use a valid name format in request, but have service raise the error
        mock_service.create_namespace.side_effect = InvalidNamespaceIdError("Bad ID")
        response = client.post(
            "/api/knowledge/namespaces",
            headers=auth_headers,
            json={"name": "valid-name"},  # Valid format, but service raises error
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "INVALID_NAMESPACE_ID"

    def test_namespace_not_found_error(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """Namespace not found returns 404 with NAMESPACE_NOT_FOUND code."""
        from dashboard.knowledge.namespace import NamespaceNotFoundError

        mock_service.get_namespace.side_effect = NamespaceNotFoundError("test-ns")
        response = client.get("/api/knowledge/namespaces/test-ns", headers=auth_headers)
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "NAMESPACE_NOT_FOUND"

    def test_namespace_exists_error(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """Namespace exists returns 409 with NAMESPACE_EXISTS code."""
        from dashboard.knowledge.namespace import NamespaceExistsError

        mock_service.create_namespace.side_effect = NamespaceExistsError("Exists")
        response = client.post(
            "/api/knowledge/namespaces",
            headers=auth_headers,
            json={"name": "existing"},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "NAMESPACE_EXISTS"

    def test_value_error_returns_400(
        self, client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock
    ) -> None:
        """Generic ValueError returns 400 with INVALID_REQUEST code."""
        mock_service.query.side_effect = ValueError("Bad query")
        response = client.post(
            "/api/knowledge/namespaces/test-ns/query",
            headers=auth_headers,
            json={"query": "test"},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "INVALID_REQUEST"


# ---------------------------------------------------------------------------
# Test Auth
# ---------------------------------------------------------------------------


class TestAuth:
    """Tests for authentication enforcement."""



    def test_bearer_token_auth_works(self, client: TestClient, mock_service: MagicMock) -> None:
        """Authorization: Bearer <key> is accepted."""
        response = client.get(
            "/api/knowledge/namespaces",
            headers={"Authorization": "Bearer test-api-key"},
        )
        assert response.status_code == 200



# ---------------------------------------------------------------------------
# Test Lazy Import
# ---------------------------------------------------------------------------


class TestLazyImport:
    """Tests for lazy import behavior."""

    def test_import_does_not_load_heavy_deps(self) -> None:
        """Importing the routes module does not load kuzu/zvec/transformers."""
        # Clear any cached imports
        heavy_modules = ["kuzu", "zvec", "anthropic"]
        for mod in heavy_modules:
            if mod in sys.modules:
                del sys.modules[mod]

        # Import the routes module
        import dashboard.routes.knowledge as knowledge_routes  # noqa: F401

        # Check that heavy modules are NOT loaded
        for mod in heavy_modules:
            assert mod not in sys.modules, f"{mod} should not be imported at module load time"

    def test_import_does_not_load_knowledge_service(self) -> None:
        """Importing routes does not immediately construct KnowledgeService."""
        # The service should be None before any endpoint is called
        import dashboard.routes.knowledge as knowledge_routes

        # After import, the singleton should still be None
        assert knowledge_routes._service_instance is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Test OpenAPI
# ---------------------------------------------------------------------------


class TestOpenAPI:
    """Tests for OpenAPI schema generation."""

    def test_openapi_includes_all_endpoints(self, client: TestClient) -> None:
        """OpenAPI schema includes all 8 knowledge endpoints."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()

        paths = schema.get("paths", {})

        # Check for all endpoints
        assert "/api/knowledge/namespaces" in paths
        assert "/api/knowledge/namespaces/{namespace}" in paths
        assert "/api/knowledge/namespaces/{namespace}/import" in paths
        assert "/api/knowledge/namespaces/{namespace}/jobs" in paths
        assert "/api/knowledge/namespaces/{namespace}/jobs/{job_id}" in paths
        assert "/api/knowledge/namespaces/{namespace}/query" in paths

    def test_openapi_has_examples(self, client: TestClient) -> None:
        """OpenAPI schemas include examples."""
        response = client.get("/openapi.json")
        schema = response.json()

        # Check CreateNamespaceRequest has examples
        components = schema.get("components", {}).get("schemas", {})
        if "CreateNamespaceRequest" in components:
            props = components["CreateNamespaceRequest"].get("properties", {})
            assert "name" in props
            # Examples should be present
            assert "examples" in props.get("name", {}) or "example" in props.get("name", {})
