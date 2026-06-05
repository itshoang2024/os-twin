"""EPIC-009 ontology governance, history, diff, and migration safety tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from dashboard.knowledge.namespace import NamespaceManager
from dashboard.knowledge.ontology.defaults import create_default_ontology_profile
from dashboard.knowledge.service import KnowledgeService
from dashboard.routes.knowledge import router
from fastapi import FastAPI
from fastapi.testclient import TestClient


@dataclass
class FakeRelation:
    label: str


class FakeGraph:
    def __init__(self, labels: list[str]) -> None:
        self._labels = labels
        self.ontology_profile = None

    def get_all_relations(self) -> list[FakeRelation]:
        return [FakeRelation(label) for label in self._labels]


def make_service(tmp_path: Path) -> KnowledgeService:
    nm = NamespaceManager(base_dir=tmp_path / "kb")
    nm.create("demo")
    return KnowledgeService(namespace_manager=nm)


def test_profile_save_history_records_actor_reason_versions_and_changed_paths(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    first = create_default_ontology_profile("demo")
    service.save_ontology_profile(first, actor="alice@example.com", reason="Initial ontology seed")
    second = first.model_copy(deep=True)
    second.version = "1.1.0"
    second.status = "deprecated"

    service.save_ontology_profile(second, actor="bob@example.com", reason="Deprecate profile before migration")

    history = service.list_ontology_profile_history("demo")
    latest = history[0]
    assert latest["actor"] == "bob@example.com"
    assert latest["reason"] == "Deprecate profile before migration"
    assert latest["previous_version"] == "1.0.0"
    assert latest["new_version"] == "1.1.0"
    assert "version" in latest["changed_paths"]
    assert "status" in latest["changed_paths"]


def test_profile_diff_reports_added_removed_and_changed_definitions(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    base = create_default_ontology_profile("demo")
    target = base.model_copy(deep=True)
    target.version = "1.1.0"
    target.relationship_types.pop("reads_writes")
    changed = target.concept_types["feature"].model_copy(update={"label": "Capability"})
    target.concept_types["feature"] = changed

    result = service.diff_ontology_profiles(
        "demo",
        base_profile=base.model_dump(mode="json"),
        target_profile=target.model_dump(mode="json"),
    )

    assert result["would_mutate"] is False
    assert "reads_writes" in result["diff"]["removed"]["relationship_types"]
    assert "feature" in result["diff"]["changed"]["concept_types"]
    assert "relationship_types.reads_writes" in result["diff"]["changed_paths"]


def test_dangerous_relation_removal_requires_override_when_graph_edges_still_use_it(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    profile = create_default_ontology_profile("demo")
    service.save_ontology_profile(profile, actor="alice", reason="Seed")
    service._kuzu_graphs["demo"] = FakeGraph(["depends_on"])  # noqa: SLF001
    next_profile = profile.model_copy(deep=True)
    next_profile.version = "1.1.0"
    next_profile.relationship_types.pop("depends_on")
    next_profile.relationship_types["enables"].inverse = None

    with pytest.raises(ValueError, match="validation_override"):
        service.save_ontology_profile(next_profile, actor="alice", reason="Remove in-use relation")

    saved = service.save_ontology_profile(
        next_profile,
        actor="alice",
        reason="Remove in-use relation with migration approval",
        validation_override={"approved_by": "architect", "ticket": "ONT-9"},
    )
    assert saved.version == "1.1.0"
    latest = service.list_ontology_profile_history("demo")[0]
    assert latest["validation_override"] == {"approved_by": "architect", "ticket": "ONT-9"}
    assert latest["migration_issues"][0]["code"] == "RELATION_TYPE_REMOVED"


def test_rename_creates_alias_and_rollback_preview_does_not_mutate_current_profile(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    profile = create_default_ontology_profile("demo")
    service.save_ontology_profile(profile, actor="alice", reason="Seed")
    renamed = profile.model_copy(deep=True)
    renamed.version = "1.1.0"
    rel = renamed.relationship_types.pop("depends_on")
    renamed.relationship_types["requires"] = rel.model_copy(update={"id": "requires"})

    saved = service.save_ontology_profile(renamed, actor="alice", reason="Rename dependency relation")

    assert saved.aliases["depends_on"] == "requires"
    preview = service.preview_ontology_profile_rollback("demo", "1.0.0")
    assert preview["would_mutate"] is False
    assert service.get_ontology_profile("demo").version == "1.1.0"



def test_view_plane_graph_instruction_changes_appear_in_profile_diff(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    base = create_default_ontology_profile("demo")
    target = base.model_copy(deep=True)
    target.version = "1.1.0"
    payload = target.model_dump(mode="json")
    payload["graph_instruction"]["default_views"] = [
        {"id": "ontology_visual_analysis", "label": "Analysis", "lane_dimension": "layer", "color_by": "lifecycle"}
    ]

    result = service.diff_ontology_profiles("demo", base_profile=base.model_dump(mode="json"), target_profile=payload)

    assert "default_views" in result["diff"]["changed"]["graph_instruction"]
    assert "graph_instruction.default_views" in result["diff"]["changed_paths"]


def test_dangerous_override_requires_ticket_and_approver_metadata(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    profile = create_default_ontology_profile("demo")
    service.save_ontology_profile(profile, actor="alice", reason="Seed")
    service._kuzu_graphs["demo"] = FakeGraph(["depends_on"])  # noqa: SLF001
    next_profile = profile.model_copy(deep=True)
    next_profile.version = "1.1.0"
    next_profile.relationship_types.pop("depends_on")
    next_profile.relationship_types["enables"].inverse = None

    with pytest.raises(ValueError, match="ticket and approved_by"):
        service.save_ontology_profile(next_profile, actor="alice", reason="Remove relation", validation_override={"ticket": "ONT-9"})

def test_candidate_approval_is_auditable(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.save_ontology_profile(create_default_ontology_profile("demo"), actor="alice", reason="Seed")
    candidate = service._candidate_store.upsert_pending(  # noqa: SLF001
        "demo",
        candidate_type="relationship_type",
        original_label="powers",
        source="test",
    )

    reviewed = service.approve_ontology_candidate("demo", candidate.id, reviewed_by="qa", canonical_id="powers")

    assert reviewed["status"] == "approved"
    # Candidate audit is emitted to the global audit log; the profile history still records the profile mutation.
    assert service.list_ontology_profile_history("demo")[0]["actor"] == "qa"


def test_governance_rest_endpoints_expose_history_diff_and_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OSTWIN_API_KEY", "test-api-key")
    service = make_service(tmp_path)
    profile = create_default_ontology_profile("demo")
    service.save_ontology_profile(profile, actor="alice", reason="Seed")
    newer = profile.model_copy(deep=True)
    newer.version = "1.1.0"
    service.save_ontology_profile(newer, actor="bob", reason="Bump version")

    app = FastAPI()
    app.include_router(router)
    import dashboard.routes.knowledge as knowledge_routes

    monkeypatch.setattr(knowledge_routes, "_get_service", lambda: service)
    client = TestClient(app)
    headers = {"X-API-Key": "test-api-key"}

    history = client.get("/api/knowledge/namespaces/demo/ontology/profile/history", headers=headers)
    assert history.status_code == 200
    assert history.json()["history"][0]["new_version"] == "1.1.0"

    diff = client.post(
        "/api/knowledge/namespaces/demo/ontology/profile/diff",
        headers=headers,
        json={"target_version": "1.0.0"},
    )
    assert diff.status_code == 200
    assert diff.json()["would_mutate"] is False

    preview = client.get("/api/knowledge/namespaces/demo/ontology/profile/history/1.0.0/preview", headers=headers)
    assert preview.status_code == 200
    assert preview.json()["target_version"] == "1.0.0"
