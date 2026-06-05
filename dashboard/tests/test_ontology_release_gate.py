"""EPIC-016 release-gate observability and quality audit tests."""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from dashboard.knowledge.jobs import JobManager, JobState
from dashboard.knowledge.namespace import NamespaceManager
from dashboard.knowledge.ontology.evidence import EvidenceAnchor, EvidenceArtifact, EvidenceLocator
from dashboard.knowledge.service import KnowledgeService
from dashboard.routes.knowledge import router
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).parent / "support"))
from ontology_lifecycle_fakes import (  # noqa: E402
    DeterministicOntologyIngestor,
    FakeEmbedder,
    FakeEnterpriseGraph,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ontology_lifecycle"


def _wait_for_job(service: KnowledgeService, job_id: str, timeout_s: float = 5.0):
    deadline = time.time() + timeout_s
    status = None
    while time.time() < deadline:
        status = service.get_job(job_id)
        if status and status.state in {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED}:
            return status
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach terminal state; latest={status}")


def _service(tmp_path: Path) -> KnowledgeService:
    nm = NamespaceManager(base_dir=tmp_path / "knowledge")
    jm = JobManager(base_dir=tmp_path / "knowledge", max_workers=1)
    service = KnowledgeService(namespace_manager=nm, job_manager=jm, embedder=FakeEmbedder())
    service._ingestor_override = DeterministicOntologyIngestor(service)  # noqa: SLF001 - deterministic release-gate path
    return service


def test_release_observability_covers_raw_doc_to_ontology_lifecycle(tmp_path: Path) -> None:
    """Import -> evidence -> extraction -> candidates/facts -> review -> projection -> events."""

    service = _service(tmp_path)
    namespace = "epic-016-release"
    service.create_namespace(namespace, description="EPIC-016 release observability")
    service.reset_default_ontology_profile(namespace)
    service.install_domain_pack(namespace, "audit-risk", actor="qa-release-gate")
    service.install_domain_pack(namespace, "esg", actor="qa-release-gate")

    artifact = EvidenceArtifact(
        id="artifact:release-doc",
        ontology_unit_id=namespace,
        source_type="document",
        source_uri="fixtures/ontology_lifecycle/release.md",
        title="Release gate source",
        checksum="fixture-release",
        read_coverage="full",
        source_state="read",
        limitations=[],
    )
    service._evidence_store.upsert_artifact(namespace, artifact)  # noqa: SLF001 - release fixture setup
    anchor = EvidenceAnchor(
        id="anchor:release-doc:1",
        artifact_id=artifact.id,
        locator=EvidenceLocator(line_start=1, line_end=4, chunk_id="release-doc-1"),
        excerpt="KYC review enables onboarding and requires control evidence.",
        extraction_method="parser",
        confidence=0.98,
    )
    service._evidence_store.upsert_anchor(namespace, anchor)  # noqa: SLF001 - release fixture setup

    job_id = service.import_folder(namespace, str(FIXTURE_DIR.resolve()), actor="qa-release-gate")
    status = _wait_for_job(service, job_id)
    assert status.state == JobState.COMPLETED, status
    assert status.result and status.result["candidates_added"] == 1

    pending = service.list_ontology_candidates(namespace, status="pending")
    assert pending
    service.map_ontology_candidate(namespace, pending[0]["id"], canonical_id="enables", reviewed_by="qa-release-gate")

    fact = service.create_ontology_fact(
        namespace,
        statement="KYC review enables customer onboarding.",
        subjects=[{"kind": "label", "id": "kyc", "label": "KYC Review"}],
        source="extraction",
        evidence_refs=[anchor.id],
        provenance_refs=[anchor.id],
        suggested_mapping={"relationship_type": "enables", "source_id": "kyc", "target_id": "onboarding"},
        metadata={"created_by": "qa-release-gate"},
    )
    service.review_ontology_fact(namespace, fact["id"], "approved", reviewed_by="qa-release-gate")
    service._kuzu_graphs[namespace] = FakeEnterpriseGraph(service.get_ontology_profile(namespace))  # noqa: SLF001
    projection = service.ontology_enterprise_map(namespace, limit=5)
    assert projection["stats"]["ontology_candidate_count"] == 0

    report = service.get_ontology_release_observability(namespace)

    assert report["profile"]["version"] == "1.0.0"
    assert report["candidates"]["by_status"] == {"mapped": 1}
    assert report["facts"]["by_review_state"] == {"approved": 1}
    assert report["evidence"]["artifact_count"] >= 1
    assert report["evidence"]["anchor_count"] >= 1
    assert report["evidence"]["provenance_link_count"] >= 0
    assert report["observations"]["event_count"] >= 4
    assert report["assistant"]["advisory_only"] is True
    assert {"audit-risk", "esg"}.issubset(set(report["packs"]["installed_pack_ids"]))
    release_pack_results = [
        item for item in report["packs"]["load_results"] if item["pack_id"] in {"audit-risk", "esg"}
    ]
    assert all(item["relationship_families"] for item in release_pack_results)
    assert report["release_blockers"] == []
    assert report["release_ready"] is True


def test_release_observability_flags_unreviewed_assistant_facts_and_extraction_warnings(tmp_path: Path) -> None:
    service = _service(tmp_path)
    namespace = "epic-016-blockers"
    service.create_namespace(namespace)
    service.reset_default_ontology_profile(namespace)

    service._evidence_store.upsert_artifact(  # noqa: SLF001 - release fixture setup
        namespace,
        EvidenceArtifact(
            id="artifact:partial-doc",
            ontology_unit_id=namespace,
            source_type="document",
            source_uri="fixtures/partial.md",
            title="Partial source",
            checksum="partial",
            read_coverage="partial",
            source_state="partial",
            limitations=["partial"],
        ),
    )
    service.create_ontology_fact(
        namespace,
        statement="Assistant suggested a new relationship but JSON parsing failed.",
        source="assistant",
        metadata={"parse_error": "invalid json", "created_by": "assistant"},
    )

    report = service.get_ontology_release_observability(namespace)

    assert report["evidence"]["extraction_warning_count"] == 1
    assert report["evidence"]["partial_source_count"] == 1
    assert report["assistant"]["error_count"] == 1
    codes = {blocker["code"] for blocker in report["release_blockers"]}
    assert {"ASSISTANT_ERRORS", "UNREVIEWED_FACTS"}.issubset(codes)
    assert report["release_ready"] is False


@pytest.fixture(autouse=True)
def _set_test_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OSTWIN_API_KEY", "test-api-key")


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"X-API-Key": "test-api-key"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client


def test_release_observability_api_returns_report(client: TestClient, auth_headers: dict[str, str]) -> None:
    mock_service = MagicMock()
    mock_service.get_ontology_release_observability.return_value = {
        "namespace": "demo",
        "generated_at": "2026-06-04T00:00:00+00:00",
        "profile": {"version": "1.0.0", "validation_issue_count": 0},
        "candidates": {"pending": 0},
        "facts": {"total": 0},
        "evidence": {"extraction_warning_count": 0},
        "observations": {"event_count": 0},
        "assistant": {"advisory_only": True, "error_count": 0},
        "packs": {"load_results": []},
        "release_blockers": [],
        "release_ready": True,
    }
    with patch("dashboard.routes.knowledge._get_service", return_value=mock_service):
        response = client.get("/api/knowledge/namespaces/demo/ontology/release-observability", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["release_ready"] is True
    mock_service.get_ontology_release_observability.assert_called_once_with("demo")
