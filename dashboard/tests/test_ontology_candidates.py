"""EPIC-004 profile-aware ingestion candidate tests."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from dashboard.knowledge.llm import KnowledgeLLM
from dashboard.knowledge.namespace import NamespaceManager
from dashboard.knowledge.ontology.candidates import OntologyCandidate, OntologyCandidateStore
from dashboard.knowledge.ontology.defaults import create_default_ontology_profile
from dashboard.routes.knowledge import router
from fastapi import FastAPI
from fastapi.testclient import TestClient


class CapturingLLM(KnowledgeLLM):
    def __init__(self) -> None:
        self.system_prompt = ""
        self.user_prompt = ""
        self.model = "fake"
        self.provider = "fake"

    def _complete(self, system: str, user: str, max_tokens: int = 2048) -> str:  # noqa: ARG002
        self.system_prompt = system
        self.user_prompt = user
        return '{"entities": [], "relationships": []}'


def test_extract_entities_prompt_includes_profile_vocab() -> None:
    profile = create_default_ontology_profile("demo")
    llm = CapturingLLM()

    llm.extract_entities("Feature API depends on service", ontology_profile_hint=profile)

    assert "Ontology profile hint" in llm.system_prompt
    assert "feature" in llm.system_prompt
    assert "depends_on" in llm.system_prompt


def test_candidate_store_reject_prevents_same_source_reappearing(tmp_path) -> None:
    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    store = OntologyCandidateStore(nm)

    candidate = store.upsert_pending(
        "demo",
        candidate_type="relationship_type",
        original_label="powers",
        source="inline://note",
        source_hash="hash-1",
        sample_text="A powers B",
    )
    store.update_status("demo", candidate.id, "rejected", reviewed_by="qa")

    again = store.upsert_pending(
        "demo",
        candidate_type="relationship_type",
        original_label="powers",
        source="inline://note",
        source_hash="hash-1",
        sample_text="A powers B",
    )

    assert again.id == candidate.id
    assert again.status == "rejected"
    assert len(store.list("demo")) == 1


def test_candidate_model_supports_broadened_types_payload_and_strictness(tmp_path) -> None:
    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    store = OntologyCandidateStore(nm)

    for candidate_type in ["metadata_field", "node", "edge", "validation_rule"]:
        candidate = store.upsert_pending(
            "demo",
            candidate_type=candidate_type,
            original_label=f"{candidate_type} proposal",
            source="inline://proposal",
            source_hash=f"hash-{candidate_type}",
            proposed_payload={"id": f"{candidate_type}_proposal", "kind": candidate_type},
            source_evidence_ref="prov-link-1",
        )
        assert candidate.candidate_type == candidate_type
        assert candidate.proposed_payload["kind"] == candidate_type
        assert candidate.source_evidence_ref == "prov-link-1"

    payload = store.list("demo")[0].model_dump(mode="json")
    with pytest.raises(ValidationError):
        OntologyCandidate.model_validate({**payload, "lifecycle_state": "candidate"})


def test_pending_candidate_upsert_merges_proposed_payload_and_evidence_ref(tmp_path) -> None:
    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    store = OntologyCandidateStore(nm)

    first = store.upsert_pending(
        "demo",
        candidate_type="node",
        original_label="Billing API",
        source="inline://proposal",
        source_hash="hash-node",
        proposed_payload={"name": "Billing API"},
        source_evidence_ref="prov-original",
    )
    second = store.upsert_pending(
        "demo",
        candidate_type="node",
        original_label="Billing API",
        source="inline://proposal",
        source_hash="hash-node",
        proposed_payload={"concept_type": "service"},
        source_evidence_ref="prov-later",
        confidence=0.9,
    )

    assert second.id == first.id
    assert second.confidence == 0.9
    assert second.proposed_payload == {"name": "Billing API", "concept_type": "service"}
    assert second.source_evidence_ref == "prov-original"


@pytest.fixture(autouse=True)
def _set_test_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OSTWIN_API_KEY", "test-api-key")


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"X-API-Key": "test-api-key"}


@pytest.fixture
def mock_service() -> MagicMock:
    return MagicMock()


@pytest.fixture
def client(mock_service: MagicMock) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router)
    with patch("dashboard.routes.knowledge._get_service", return_value=mock_service):
        with TestClient(app) as test_client:
            yield test_client


def test_candidate_review_routes_list_and_map(
    client: TestClient,
    auth_headers: dict[str, str],
    mock_service: MagicMock,
) -> None:
    candidate = {
        "id": "cand1",
        "namespace": "demo",
        "candidate_type": "relationship_type",
        "source": "inline://note",
        "original_label": "requires",
        "normalized_label": "requires",
        "suggested_canonical": "depends_on",
        "confidence": 0.8,
        "sample_text": "A requires B",
        "status": "pending",
        "source_hash": "hash",
        "created_at": "2026-06-01T00:00:00Z",
        "reviewed_at": None,
        "reviewed_by": None,
        "metadata": {},
    }
    mapped = dict(candidate, status="mapped", reviewed_by="tester")
    mock_service.list_ontology_candidates.return_value = [candidate]
    mock_service.map_ontology_candidate.return_value = mapped

    response = client.get("/api/knowledge/namespaces/demo/ontology/candidates", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["candidates"][0]["original_label"] == "requires"

    response = client.post(
        "/api/knowledge/namespaces/demo/ontology/candidates/cand1/map",
        headers=auth_headers,
        json={"canonical_id": "depends_on"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "mapped"
    mock_service.map_ontology_candidate.assert_called_once()


class FakeExtractorLLM:
    def extract_entities(self, text: str, language: str = "English", domain: str = "", ontology_profile_hint=None):  # noqa: ANN001, ARG002
        assert ontology_profile_hint is not None
        return (
            [{"name": "Dashboard", "type": "Screen", "description": "UI screen"}],
            [{"source": "Dashboard", "target": "API", "relation": "powers", "description": "runtime link"}],
        )


class FakeEmbedder:
    def embed(self, texts):  # noqa: ANN001
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_one(self, text: str):  # noqa: ARG002
        return [0.1, 0.2, 0.3]


def test_graph_extractor_normalizes_and_persists_unknown_candidates(tmp_path) -> None:
    from dashboard.knowledge.graph.core.graph_rag_extractor import GraphRAGExtractor
    from llama_index.core.graph_stores.types import KG_RELATIONS_KEY
    from llama_index.core.schema import TextNode

    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    store = OntologyCandidateStore(nm)
    profile = create_default_ontology_profile("demo")
    node = TextNode(text="Dashboard powers API", metadata={"file_hash": "source-hash", "file_path": "inline://demo"})

    legacy_llm = MagicMock()
    legacy_llm.extract_entities.return_value = (
        [{"name": "Dashboard", "type": "Screen", "description": "UI screen"}],
        [{"source": "Dashboard", "target": "API", "relation": "powers", "description": "runtime link"}],
    )
    extractor = GraphRAGExtractor(
        llm=legacy_llm,
        embedder=FakeEmbedder(),
        ontology_profile=profile,
        candidate_store=store,
        namespace="demo",
    )

    [result] = extractor([node])

    candidates = store.list("demo", status="pending")
    assert {c.candidate_type for c in candidates} == {"concept_type", "relationship_type"}
    assert extractor.metrics.candidate_count == 2
    relation = result.metadata[KG_RELATIONS_KEY][0]
    assert relation.label == "powers"
    assert relation.properties["ontology_normalization"] == "candidate"
    assert relation.properties["ontology_candidate_id"]


def test_candidate_approval_updates_profile_and_future_normalization(tmp_path) -> None:
    from dashboard.knowledge.ontology.normalizer import normalize_relation
    from dashboard.knowledge.service import KnowledgeService

    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    service = KnowledgeService(namespace_manager=nm)
    service.save_ontology_profile(create_default_ontology_profile("demo"))
    candidate = service._candidate_store.upsert_pending(  # noqa: SLF001
        "demo",
        candidate_type="relationship_type",
        original_label="powers",
        source="inline://demo",
        source_hash="hash-approve",
        sample_text="Dashboard powers API",
    )

    reviewed = service.approve_ontology_candidate("demo", candidate.id, reviewed_by="tester", canonical_id="powers")

    profile = service.get_ontology_profile("demo")
    assert reviewed["status"] == "approved"
    assert profile is not None
    assert "powers" in profile.relationship_types
    assert normalize_relation("powers", profile).classification == "canonical"



def test_candidate_approval_routes_metadata_fields_and_validation_rules(tmp_path) -> None:
    from dashboard.knowledge.ontology.approval import ObservationEventStore
    from dashboard.knowledge.service import KnowledgeService

    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    service = KnowledgeService(namespace_manager=nm)
    service.save_ontology_profile(create_default_ontology_profile("demo"))

    field_candidate = service._candidate_store.upsert_pending(  # noqa: SLF001
        "demo",
        candidate_type="metadata_field",
        original_label="Control Owner",
        source="inline://demo",
        source_hash="hash-field",
        proposed_payload={"field_type": "string", "description": "Named accountable control owner."},
        source_evidence_ref="prov-field",
    )
    rule_candidate = service._candidate_store.upsert_pending(  # noqa: SLF001
        "demo",
        candidate_type="validation_rule",
        original_label="Control owner required",
        source="inline://demo",
        source_hash="hash-rule",
        proposed_payload={
            "rule_type": "required_metadata",
            "severity": "warning",
            "message": "Controls should include an owner",
            "params": {"field": "control_owner"},
        },
    )

    approved_field = service.approve_ontology_candidate("demo", field_candidate.id, reviewed_by="tester", canonical_id="control_owner")
    approved_rule = service.approve_ontology_candidate("demo", rule_candidate.id, reviewed_by="tester", canonical_id="control_owner_required")

    profile = service.get_ontology_profile("demo")
    assert approved_field["status"] == "approved"
    assert approved_rule["status"] == "approved"
    assert profile is not None
    assert profile.metadata_fields["control_owner"].field_type == "string"
    assert profile.metadata_fields["control_owner"].description == "Named accountable control owner."
    assert any(rule.id == "control_owner_required" and rule.params["field"] == "control_owner" for rule in profile.validation_rules)

    events = ObservationEventStore(nm).list("demo")
    approved_events = [event for event in events if event.event_type == "OntologyCandidateApproved"]
    assert {event.subject_id for event in approved_events} == {field_candidate.id, rule_candidate.id}
    assert any(event.provenance_refs == ["prov-field"] for event in approved_events)


def test_candidate_map_and_reject_emit_observation_events(tmp_path) -> None:
    from dashboard.knowledge.ontology.approval import ObservationEventStore
    from dashboard.knowledge.service import KnowledgeService

    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    service = KnowledgeService(namespace_manager=nm)
    service.save_ontology_profile(create_default_ontology_profile("demo"))
    map_candidate = service._candidate_store.upsert_pending(  # noqa: SLF001
        "demo",
        candidate_type="concept_type",
        original_label="Screen",
        source="inline://demo",
        source_hash="hash-map",
        source_evidence_ref="prov-map",
    )
    reject_candidate = service._candidate_store.upsert_pending(  # noqa: SLF001
        "demo",
        candidate_type="relationship_type",
        original_label="powers",
        source="inline://demo",
        source_hash="hash-reject",
    )

    service.map_ontology_candidate("demo", map_candidate.id, "feature", reviewed_by="tester")
    service.reject_ontology_candidate("demo", reject_candidate.id, reviewed_by="tester", reason="too noisy")

    events = ObservationEventStore(nm).list("demo")
    by_type = {event.event_type: event for event in events}
    assert by_type["OntologyCandidateMapped"].subject_id == map_candidate.id
    assert by_type["OntologyCandidateMapped"].provenance_refs == ["prov-map"]
    assert by_type["OntologyCandidateRejected"].metadata["reason"] == "too noisy"

def test_graph_extractor_no_profile_preserves_legacy_labels(tmp_path) -> None:
    from dashboard.knowledge.graph.core.graph_rag_extractor import GraphRAGExtractor
    from llama_index.core.graph_stores.types import KG_NODES_KEY, KG_RELATIONS_KEY
    from llama_index.core.schema import TextNode

    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("legacy")
    store = OntologyCandidateStore(nm)
    node = TextNode(text="Dashboard powers API", metadata={"file_hash": "legacy-hash"})
    legacy_llm = MagicMock()
    legacy_llm.extract_entities.return_value = (
        [{"name": "Dashboard", "type": "Screen", "description": "UI screen"}],
        [{"source": "Dashboard", "target": "API", "relation": "powers", "description": "runtime link"}],
    )
    extractor = GraphRAGExtractor(
        llm=legacy_llm,
        embedder=FakeEmbedder(),
        ontology_profile=None,
        candidate_store=store,
        namespace="legacy",
    )

    [result] = extractor([node])

    assert result.metadata[KG_NODES_KEY][0].label == "Screen"
    assert result.metadata[KG_RELATIONS_KEY][0].label == "powers"
    assert store.list("legacy") == []
