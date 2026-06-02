# ruff: noqa: E501
"""EPIC-010 release-gate lifecycle coverage for ontology operations."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).parent / "support"))

from dashboard.knowledge.jobs import JobManager, JobState
from dashboard.knowledge.namespace import NamespaceManager
from dashboard.knowledge.service import KnowledgeService
from ontology_lifecycle_fakes import (
    DeterministicOntologyIngestor,
    FakeEmbedder,
    FakeEnterpriseGraph,
    FakeQueryEngine,
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


def test_full_ontology_operations_lifecycle_with_deterministic_ingestion(tmp_path: Path) -> None:
    """Create namespace -> profile -> Financial Services pack -> ingest -> review -> enterprise map."""

    nm = NamespaceManager(base_dir=tmp_path / "knowledge")
    jm = JobManager(base_dir=tmp_path / "knowledge", max_workers=1)
    service = KnowledgeService(namespace_manager=nm, job_manager=jm, embedder=FakeEmbedder())
    service._ingestor_override = DeterministicOntologyIngestor(service)  # noqa: SLF001 - deterministic release-gate path

    namespace = "epic-010-ontology"
    service.create_namespace(namespace, description="EPIC-010 deterministic lifecycle")

    # Bootstrap a profile and install the Financial Services domain pack.
    profile, replaced = service.reset_default_ontology_profile(namespace)
    assert replaced is False
    assert profile.profile_id == "enterprise_feature_map"

    install = service.install_domain_pack(namespace, "financial-services", actor="qa-release-gate")
    assert install["namespace"] == namespace
    assert install["profile"]["relationship_types"]["regulated_by"]["family"] == "validation"
    installed = service.list_installed_domain_packs(namespace)
    assert "financial-services" in installed["installed_packs"]

    # Ingest through a deterministic fake extraction path so candidate review is stable.
    job_id = service.import_folder(namespace, str(FIXTURE_DIR.resolve()), actor="qa-release-gate")
    status = _wait_for_job(service, job_id)
    assert status.state == JobState.COMPLETED, status
    assert status.result is not None
    assert status.result["candidates_added"] == 1

    pending = service.list_ontology_candidates(namespace, status="pending")
    assert [candidate["original_label"] for candidate in pending] == ["powers"]
    mapped = service.map_ontology_candidate(namespace, pending[0]["id"], canonical_id="enables", reviewed_by="qa-release-gate")
    assert mapped["status"] == "mapped"
    assert service.get_ontology_summary(namespace)["candidate_count"] == 0

    # Existing query-mode contract still dispatches raw, graph, and summarized modes.
    service._query_engines[namespace] = FakeQueryEngine(namespace)  # noqa: SLF001
    raw = service.query(namespace, "loan", mode="raw", top_k=3)
    graph = service.query(namespace, "kyc dependencies", mode="graph", top_k=3)
    summarized = service.query(namespace, "summarize kyc", mode="summarized", top_k=3)
    assert raw.mode == "raw" and raw.chunks
    assert graph.mode == "graph" and graph.entities
    assert summarized.mode == "summarized" and summarized.answer

    # Existing Nexus/Explorer seed works for profile-enabled namespaces and carries ontology metadata.
    service._kuzu_graphs[namespace] = FakeEnterpriseGraph(service.get_ontology_profile(namespace))  # noqa: SLF001
    seed = service.explorer_seed(namespace, top_k=3)
    assert seed["meta"]["profile_exists"] is True
    assert seed["meta"]["ontology_profile"]["profile_id"] == "enterprise_feature_map"
    assert {node["pack_id"] for node in seed["nodes"] if node.get("pack_id")} == {"financial-services"}
    assert {edge["relationship_type"] for edge in seed["edges"]} >= {"regulated_by", "enables"}


def test_nexus_explorer_seed_preserves_legacy_namespace_shape(tmp_path: Path) -> None:
    """Legacy namespaces without a saved ontology profile still produce explorer seed data."""

    nm = NamespaceManager(base_dir=tmp_path / "knowledge")
    service = KnowledgeService(namespace_manager=nm, job_manager=JobManager(base_dir=tmp_path / "knowledge", max_workers=1), embedder=FakeEmbedder())
    namespace = "legacy-explorer"
    service.create_namespace(namespace, description="Legacy namespace without ontology profile")
    service._kuzu_graphs[namespace] = FakeEnterpriseGraph(None)  # noqa: SLF001

    seed = service.explorer_seed(namespace, top_k=2)

    assert seed["meta"]["profile_exists"] is False
    assert seed["nodes"]
    assert all("validation_issues" in node for node in seed["nodes"])
    assert all("relationship_type" in edge for edge in seed["edges"])
