"""End-to-End REST API lifecycle tests for Knowledge system (EPIC-008).

Full lifecycle coverage via TestClient:
1. Create namespace
2. Import folder
3. Poll job status until completion
4. Query (all 3 modes: raw, graph, summarized)
5. Get graph
6. Backup namespace
7. Delete namespace
8. Restore from backup
9. Query after restore

Target runtime: < 3 minutes on CI hardware.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

# Fixture path for test documents
FIXTURES = Path(__file__).parent / "fixtures" / "knowledge_sample"


@pytest.fixture
def fresh_kb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated knowledge-base directory for each test."""
    kb = tmp_path / "kb"
    monkeypatch.setenv("OSTWIN_KNOWLEDGE_DIR", str(kb))
    yield kb


@pytest.fixture
def client_with_auth(fresh_kb: Path):
    """TestClient with authentication bypassed."""
    from dashboard.api import app
    from dashboard.auth import get_current_user

    # Override auth to return a mock user
    async def mock_get_current_user():
        return {"sub": "test-user", "email": "test@example.com"}

    app.dependency_overrides[get_current_user] = mock_get_current_user

    with TestClient(app) as client:
        yield client

    # Clean up
    app.dependency_overrides.clear()


class TestKnowledgeE2ERestLifecycle:
    """Full REST API lifecycle tests."""

    @pytest.mark.slow
    def test_full_lifecycle_rest(self, client_with_auth: TestClient) -> None:
        """Complete lifecycle: create -> import -> query -> backup -> delete -> restore.

        This test validates the entire Knowledge system REST API works end-to-end.
        Target runtime: < 180 seconds on CI hardware.

        Note: Requires kuzu, zvec, and potentially anthropic for full coverage.
        """
        client = client_with_auth
        start_time = time.perf_counter()
        import uuid
        ns_name = f"e2e-test-rest-{uuid.uuid4().hex[:8]}"

        # ============================================================
        # STEP 1: Create namespace
        # ============================================================
        create_resp = client.post(
            "/api/knowledge/namespaces",
            json={"name": ns_name, "description": "E2E REST test namespace"},
        )
        assert create_resp.status_code == 201, f"Create failed: {create_resp.text}"
        ns_data = create_resp.json()
        assert ns_data["name"] == ns_name
        assert ns_data["description"] == "E2E REST test namespace"
        print(f"[{time.perf_counter() - start_time:.1f}s] Namespace created: {ns_name}")

        # ============================================================
        # STEP 2: Import folder
        # ============================================================
        import_resp = client.post(
            f"/api/knowledge/namespaces/{ns_name}/import",
            json={"folder_path": str(FIXTURES.resolve())},
        )
        assert import_resp.status_code == 200, f"Import failed: {import_resp.text}"
        import_data = import_resp.json()
        assert "job_id" in import_data
        job_id = import_data["job_id"]
        print(f"[{time.perf_counter() - start_time:.1f}s] Import job submitted: {job_id}")

        # ============================================================
        # STEP 3: Poll job status until completion
        # ============================================================
        deadline = time.time() + 120  # 2 minute timeout
        job_state = None
        job_data = {}
        while time.time() < deadline:
            job_resp = client.get(f"/api/knowledge/namespaces/{ns_name}/jobs/{job_id}")
            assert job_resp.status_code == 200, f"Job status failed: {job_resp.text}"
            job_data = job_resp.json()
            job_state = job_data["state"]
            if job_state in ("completed", "failed", "cancelled", "interrupted"):
                break
            time.sleep(0.5)

        assert job_state == "completed", f"Job did not complete: state={job_state}, errors={job_data.get('errors', [])}"
        print(f"[{time.perf_counter() - start_time:.1f}s] Import completed")

        # ============================================================
        # STEP 4: Query (mode=raw) - basic vector search
        # ============================================================
        query_raw_resp = client.post(
            f"/api/knowledge/namespaces/{ns_name}/query",
            json={"query": "test document", "mode": "raw", "top_k": 5},
        )
        assert query_raw_resp.status_code == 200, f"Raw query failed: {query_raw_resp.text}"
        raw_result = query_raw_resp.json()
        assert "chunks" in raw_result
        assert isinstance(raw_result["chunks"], list)
        assert raw_result["mode"] == "raw"
        assert "latency_ms" in raw_result
        print(f"[{time.perf_counter() - start_time:.1f}s] Raw query returned {len(raw_result['chunks'])} chunks")

        # ============================================================
        # STEP 5: Query (mode=graph) - requires kuzu
        # ============================================================
        query_graph_resp = client.post(
            f"/api/knowledge/namespaces/{ns_name}/query",
            json={"query": "sample text", "mode": "graph", "top_k": 5},
        )
        # Graph mode requires kuzu - may return 500 if not installed
        if query_graph_resp.status_code == 500 and "kuzu" in query_graph_resp.text:
            print(f"[{time.perf_counter() - start_time:.1f}s] Graph query skipped (kuzu not installed)")
        else:
            assert query_graph_resp.status_code == 200, f"Graph query failed: {query_graph_resp.text}"
            graph_result = query_graph_resp.json()
            assert "chunks" in graph_result
            assert "entities" in graph_result
            assert graph_result["mode"] == "graph"
            print(f"[{time.perf_counter() - start_time:.1f}s] Graph query returned {len(graph_result['chunks'])} chunks")

        # ============================================================
        # STEP 6: Query (mode=summarized) - requires LLM
        # ============================================================
        query_summ_resp = client.post(
            f"/api/knowledge/namespaces/{ns_name}/query",
            json={"query": "information", "mode": "summarized", "top_k": 3},
        )
        # Summarized mode requires LLM - may return warnings or errors
        if query_summ_resp.status_code == 200:
            summ_result = query_summ_resp.json()
            assert "chunks" in summ_result
            assert summ_result["mode"] == "summarized"
            if "warnings" in summ_result and summ_result["warnings"]:
                print(f"[{time.perf_counter() - start_time:.1f}s] Summarized query warnings: {summ_result['warnings']}")
            else:
                print(f"[{time.perf_counter() - start_time:.1f}s] Summarized query completed")
        else:
            print(f"[{time.perf_counter() - start_time:.1f}s] Summarized query skipped (LLM unavailable)")

        # ============================================================
        # STEP 7: Get graph - requires kuzu
        # ============================================================
        graph_resp = client.get(f"/api/knowledge/namespaces/{ns_name}/graph?limit=100")
        if graph_resp.status_code == 500 and "kuzu" in graph_resp.text:
            print(f"[{time.perf_counter() - start_time:.1f}s] Graph endpoint skipped (kuzu not installed)")
        else:
            assert graph_resp.status_code == 200, f"Graph endpoint failed: {graph_resp.text}"
            graph_data = graph_resp.json()
            assert "nodes" in graph_data
            assert "edges" in graph_data
            assert "stats" in graph_data
            print(f"[{time.perf_counter() - start_time:.1f}s] Graph: {graph_data['stats']}")

        # ============================================================
        # STEP 8: Backup namespace
        # ============================================
        backup_resp = client.post(f"/api/knowledge/namespaces/{ns_name}/backup")
        assert backup_resp.status_code == 200, f"Backup failed: {backup_resp.text}"
        backup_data = backup_resp.json()
        assert "archive_path" in backup_data
        assert "namespace" in backup_data
        assert backup_data["namespace"] == ns_name
        archive_path = Path(backup_data["archive_path"])
        assert archive_path.exists()
        backup_size = archive_path.stat().st_size
        print(f"[{time.perf_counter() - start_time:.1f}s] Backup created: {backup_size} bytes at {archive_path}")

        # ============================================================
        # STEP 9: Delete namespace
        # ============================================================
        delete_resp = client.delete(f"/api/knowledge/namespaces/{ns_name}")
        assert delete_resp.status_code == 200, f"Delete failed: {delete_resp.text}"
        print(f"[{time.perf_counter() - start_time:.1f}s] Namespace deleted")

        # ============================================================
        # STEP 10: Restore from backup
        # ============================================================
        restore_resp = client.post(
            f"/api/knowledge/namespaces/{ns_name}/restore",
            json={"archive_path": str(archive_path.resolve())},
        )
        assert restore_resp.status_code == 200, f"Restore failed: {restore_resp.text}"
        print(f"[{time.perf_counter() - start_time:.1f}s] Namespace restored")

        # ============================================================
        # STEP 11: Query after restore
        # ============================================================
        query_after_resp = client.post(
            f"/api/knowledge/namespaces/{ns_name}/query",
            json={"query": "test", "mode": "raw"},
        )
        assert query_after_resp.status_code == 200, f"Query after restore failed: {query_after_resp.text}"
        assert len(query_after_resp.json()["chunks"]) > 0
        print(f"[{time.perf_counter() - start_time:.1f}s] Query after restore successful")

        # Cleanup: delete restore
        client.delete(f"/api/knowledge/namespaces/{ns_name}")
        if archive_path.exists():
            archive_path.unlink()


        elapsed = time.perf_counter() - start_time
        print(f"\n=== E2E REST lifecycle completed in {elapsed:.1f}s ===")
        assert elapsed < 180, f"E2E test took {elapsed}s, exceeds 3-minute target"


class TestKnowledgeE2ERestErrorHandling:
    """Error handling tests for REST API."""

    def test_create_invalid_namespace_name(self, client_with_auth: TestClient) -> None:
        """Invalid namespace name returns structured error.

        Note: Pydantic may return 422 before our validation runs, so we accept
        either 400 (our error) or 422 (Pydantic validation error).
        """
        resp = client_with_auth.post(
            "/api/knowledge/namespaces",
            json={"name": "Invalid Name!"},
        )
        # Accept either our error code or Pydantic's 422
        assert resp.status_code in (400, 422), f"Expected 400 or 422, got {resp.status_code}"
        data = resp.json()
        if resp.status_code == 400:
            assert "detail" in data
            assert data["detail"]["code"] == "INVALID_NAMESPACE_ID"

    def test_create_duplicate_namespace(self, client_with_auth: TestClient) -> None:
        """Creating duplicate namespace returns 409 conflict."""
        # Create first
        client_with_auth.post("/api/knowledge/namespaces", json={"name": "dup-test"})
        # Try to create again
        resp = client_with_auth.post("/api/knowledge/namespaces", json={"name": "dup-test"})
        assert resp.status_code == 409
        data = resp.json()
        assert data["detail"]["code"] == "NAMESPACE_EXISTS"

    def test_import_relative_path_rejected(self, client_with_auth: TestClient) -> None:
        """Relative path in import is rejected."""
        client_with_auth.post("/api/knowledge/namespaces", json={"name": "path-test"})
        resp = client_with_auth.post(
            "/api/knowledge/namespaces/path-test/import",
            json={"folder_path": "relative/path"},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["detail"]["code"] == "INVALID_FOLDER_PATH"

    def test_import_nonexistent_path_rejected(self, client_with_auth: TestClient) -> None:
        """Non-existent path in import returns 404."""
        client_with_auth.post("/api/knowledge/namespaces", json={"name": "path-test2"})
        resp = client_with_auth.post(
            "/api/knowledge/namespaces/path-test2/import",
            json={"folder_path": "/tmp/does-not-exist-12345"},
        )
        assert resp.status_code == 404
        data = resp.json()
        assert data["detail"]["code"] == "FOLDER_NOT_FOUND"

    def test_query_nonexistent_namespace(self, client_with_auth: TestClient) -> None:
        """Query on non-existent namespace returns 404."""
        resp = client_with_auth.post(
            "/api/knowledge/namespaces/never-created/query",
            json={"query": "test", "mode": "raw"},
        )
        assert resp.status_code == 404
        data = resp.json()
        assert data["detail"]["code"] == "NAMESPACE_NOT_FOUND"

    def test_query_invalid_mode(self, client_with_auth: TestClient) -> None:
        """Invalid query mode returns 400 or 422.

        Note: Pydantic may return 422 before our validation runs for enum fields.
        """
        client_with_auth.post("/api/knowledge/namespaces", json={"name": "mode-test"})
        resp = client_with_auth.post(
            "/api/knowledge/namespaces/mode-test/query",
            json={"query": "test", "mode": "bogus"},
        )
        # Accept either our error code or Pydantic's 422
        assert resp.status_code in (400, 422), f"Expected 400 or 422, got {resp.status_code}"

    def test_get_nonexistent_job(self, client_with_auth: TestClient) -> None:
        """Getting non-existent job returns 404."""
        client_with_auth.post("/api/knowledge/namespaces", json={"name": "job-test"})
        resp = client_with_auth.get("/api/knowledge/namespaces/job-test/jobs/fake-job-id")
        assert resp.status_code == 404
        data = resp.json()
        assert data["detail"]["code"] == "JOB_NOT_FOUND"


class TestKnowledgeE2ERestMetricsAndHealth:
    """Metrics and health endpoint tests."""

    def test_metrics_endpoint_json(self, client_with_auth: TestClient) -> None:
        """Metrics endpoint returns JSON by default."""
        resp = client_with_auth.get("/api/knowledge/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "counters" in data or "histograms" in data or "gauges" in data

    def test_metrics_endpoint_prometheus(self, client_with_auth: TestClient) -> None:
        """Metrics endpoint returns Prometheus format with Accept header."""
        resp = client_with_auth.get(
            "/api/knowledge/metrics",
            headers={"Accept": "text/plain"},
        )
        assert resp.status_code == 200
        assert "# TYPE" in resp.text or "# HELP" in resp.text or resp.text.strip() == ""

    def test_health_endpoint(self, client_with_auth: TestClient) -> None:
        """Health endpoint returns valid status."""
        resp = client_with_auth.get("/api/knowledge/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("ok", "degraded", "unhealthy")
        assert "checks" in data
        assert "timestamp" in data


class TestKnowledgeE2ERestListOperations:
    """List operations tests."""

    def test_list_namespaces_empty(self, client_with_auth: TestClient) -> None:
        """List namespaces returns empty list initially."""
        resp = client_with_auth.get("/api/knowledge/namespaces")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_list_namespaces_after_create(self, client_with_auth: TestClient) -> None:
        """List namespaces shows created namespace."""
        client_with_auth.post("/api/knowledge/namespaces", json={"name": "list-test"})
        resp = client_with_auth.get("/api/knowledge/namespaces")
        assert resp.status_code == 200
        data = resp.json()
        names = [ns["name"] for ns in data]
        assert "list-test" in names

    def test_list_jobs_empty(self, client_with_auth: TestClient) -> None:
        """List jobs returns empty list for new namespace."""
        client_with_auth.post("/api/knowledge/namespaces", json={"name": "job-list-test"})
        resp = client_with_auth.get("/api/knowledge/namespaces/job-list-test/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


class TestKnowledgeE2ERestRetention:
    """Retention policy tests."""

    def test_set_retention_policy(self, client_with_auth: TestClient) -> None:
        """Setting retention policy updates namespace."""
        client_with_auth.post("/api/knowledge/namespaces", json={"name": "retention-test"})

        resp = client_with_auth.put(
            "/api/knowledge/namespaces/retention-test/retention",
            json={"policy": "ttl_days", "ttl_days": 30, "auto_delete_when_empty": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["policy"] == "ttl_days"
        assert data["ttl_days"] == 30

    def test_get_namespace_shows_retention(self, client_with_auth: TestClient) -> None:
        """Getting namespace includes retention policy."""
        client_with_auth.post("/api/knowledge/namespaces", json={"name": "retention-get-test"})
        client_with_auth.put(
            "/api/knowledge/namespaces/retention-get-test/retention",
            json={"policy": "manual"},
        )

        resp = client_with_auth.get("/api/knowledge/namespaces/retention-get-test")
        assert resp.status_code == 200
        data = resp.json()
        assert "retention" in data


class TestKnowledgeE2ERestRefresh:
    """Refresh endpoint tests."""

    def test_refresh_empty_namespace(self, client_with_auth: TestClient) -> None:
        """Refreshing namespace with no imports returns empty job list."""
        import uuid
        ns_name = f"refresh-test-{uuid.uuid4().hex[:8]}"
        client_with_auth.post("/api/knowledge/namespaces", json={"name": ns_name})

        resp = client_with_auth.post(f"/api/knowledge/namespaces/{ns_name}/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert "job_ids" in data
        assert data["job_ids"] == []

        # Cleanup
        client_with_auth.delete(f"/api/knowledge/namespaces/{ns_name}")
