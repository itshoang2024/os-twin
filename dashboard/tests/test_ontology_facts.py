"""EPIC-006 Facts plane tests."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from dashboard.knowledge.namespace import NamespaceManager
from dashboard.knowledge.ontology.approval import InMemoryGraphInstanceStore, ObservationEventStore, OntologyMutationError
from dashboard.knowledge.ontology.defaults import create_default_ontology_profile
from dashboard.knowledge.ontology.facts import FactSubjectRef, OntologyFact, OntologyFactPromotionService, OntologyFactStore, SuggestedRelationshipMapping
from dashboard.knowledge.ontology.instances import OntologyNode
from dashboard.knowledge.ontology.store import OntologyProfileStore
from dashboard.routes.knowledge import router


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


def test_fact_model_validation_and_store_persistence(tmp_path) -> None:
    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    store = OntologyFactStore(nm)

    fact = store.create_assistive(
        "demo",
        statement="Dashboard summarizes API reliability.",
        subjects=[FactSubjectRef(kind="label", id="Dashboard", label="Dashboard")],
        confidence=0.74,
        source="assistant",
        evidence_refs=["prov:one", "prov:one"],
    )

    assert fact.review_state == "assistive"
    assert fact.subject_ids == ["Dashboard"]
    assert fact.evidence_refs == ["prov:one"]
    assert store.list("demo")[0].statement == "Dashboard summarizes API reliability."
    with pytest.raises(ValidationError):
        OntologyFact.model_validate({**fact.model_dump(mode="json"), "canonical_edge": True})


def test_unreviewed_fact_cannot_create_edge_and_approved_fact_promotes_with_provenance(tmp_path) -> None:
    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    OntologyProfileStore(nm).write(create_default_ontology_profile("demo"))
    graph = InMemoryGraphInstanceStore()
    graph.upsert_node(OntologyNode(id="dashboard", ontology_unit_id="demo", concept_type="feature", name="Dashboard"))
    graph.upsert_node(OntologyNode(id="api", ontology_unit_id="demo", concept_type="feature", name="API"))
    store = OntologyFactStore(nm)
    fact = store.create_assistive(
        "demo",
        statement="Dashboard depends on API.",
        subjects=[FactSubjectRef(kind="node", id="dashboard"), FactSubjectRef(kind="node", id="api")],
        confidence=0.91,
        evidence_refs=["prov:fact"],
        provenance_refs=["prov:fact"],
        suggested_mapping=SuggestedRelationshipMapping(relationship_type="depends_on", source_id="dashboard", target_id="api"),
    )
    promoter = OntologyFactPromotionService(nm, graph)

    with pytest.raises(OntologyMutationError):
        promoter.promote_to_edge("demo", fact.id, reviewed_by="po")

    store.update_review_state("demo", fact.id, "approved", reviewed_by="po")
    edge = promoter.promote_to_edge("demo", fact.id, reviewed_by="po")

    assert edge.review_state == "approved"
    assert edge.relationship_type == "depends_on"
    assert fact.id in edge.provenance_refs
    reviewed_fact = store.get("demo", fact.id)
    assert reviewed_fact is not None
    assert reviewed_fact.review_state == "reviewed"
    assert reviewed_fact.promoted_edge_id == edge.id
    events = ObservationEventStore(nm).list("demo")
    assert any(event.event_type == "OntologyFactPromoted" for event in events)


def test_fact_promotion_blocks_invalid_relationship_source_type(tmp_path) -> None:
    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    OntologyProfileStore(nm).write(create_default_ontology_profile("demo"))
    graph = InMemoryGraphInstanceStore()
    graph.upsert_node(OntologyNode(id="domain", ontology_unit_id="demo", concept_type="business_domain", name="Domain"))
    graph.upsert_node(OntologyNode(id="api", ontology_unit_id="demo", concept_type="feature", name="API"))
    store = OntologyFactStore(nm)
    fact = store.create_assistive(
        "demo",
        statement="Domain depends on API.",
        subjects=[FactSubjectRef(kind="node", id="domain"), FactSubjectRef(kind="node", id="api")],
        confidence=0.88,
        suggested_mapping=SuggestedRelationshipMapping(
            relationship_type="depends_on",
            source_id="domain",
            target_id="api",
        ),
    )
    store.update_review_state("demo", fact.id, "approved", reviewed_by="po")

    with pytest.raises(OntologyMutationError, match="allows sources"):
        OntologyFactPromotionService(nm, graph).promote_to_edge("demo", fact.id, reviewed_by="po")

    assert graph.edges == {}


def test_fact_promotion_blocks_invalid_relationship_target_type(tmp_path) -> None:
    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    OntologyProfileStore(nm).write(create_default_ontology_profile("demo"))
    graph = InMemoryGraphInstanceStore()
    graph.upsert_node(OntologyNode(id="dashboard", ontology_unit_id="demo", concept_type="feature", name="Dashboard"))
    graph.upsert_node(
        OntologyNode(id="capability", ontology_unit_id="demo", concept_type="capability", name="Capability")
    )
    store = OntologyFactStore(nm)
    fact = store.create_assistive(
        "demo",
        statement="Dashboard depends on Capability.",
        subjects=[FactSubjectRef(kind="node", id="dashboard"), FactSubjectRef(kind="node", id="capability")],
        confidence=0.88,
        suggested_mapping=SuggestedRelationshipMapping(
            relationship_type="depends_on",
            source_id="dashboard",
            target_id="capability",
        ),
    )
    store.update_review_state("demo", fact.id, "approved", reviewed_by="po")

    with pytest.raises(OntologyMutationError, match="allows targets"):
        OntologyFactPromotionService(nm, graph).promote_to_edge("demo", fact.id, reviewed_by="po")

    assert graph.edges == {}


def test_missing_relationship_type_raises_candidate_instead_of_invalid_edge(tmp_path) -> None:
    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    OntologyProfileStore(nm).write(create_default_ontology_profile("demo"))
    store = OntologyFactStore(nm)
    fact = store.create_assistive(
        "demo",
        statement="Dashboard powers API.",
        subjects=[FactSubjectRef(kind="label", id="Dashboard"), FactSubjectRef(kind="label", id="API")],
        confidence=0.66,
        suggested_mapping=SuggestedRelationshipMapping(source_id="Dashboard", target_id="API"),
        source_hash="hash-fact",
    )

    promoter = OntologyFactPromotionService(nm, InMemoryGraphInstanceStore())
    candidate = promoter.raise_relationship_candidate("demo", fact.id, relationship_label="powers", reviewed_by="po")

    assert candidate.candidate_type == "relationship_type"
    assert candidate.metadata["fact_id"] == fact.id
    assert OntologyFactStore(nm).get("demo", fact.id).metadata["relationship_candidate_id"] == candidate.id


class FakeEmbedder:
    def embed(self, texts):  # noqa: ANN001
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_one(self, text: str):  # noqa: ARG002
        return [0.1, 0.2, 0.3]


def test_graph_extractor_creates_assistive_fact_for_uncertain_relation(tmp_path) -> None:
    from dashboard.knowledge.graph.core.graph_rag_extractor import GraphRAGExtractor
    from llama_index.core.graph_stores.types import KG_RELATIONS_KEY
    from llama_index.core.schema import TextNode

    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    fact_store = OntologyFactStore(nm)
    profile = create_default_ontology_profile("demo")
    node = TextNode(text="Dashboard powers API", metadata={"file_hash": "source-hash", "file_path": "inline://demo"})
    llm = MagicMock()
    llm.extract_entities.return_value = (
        [{"name": "Dashboard", "type": "Feature"}, {"name": "API", "type": "Feature"}],
        [{"source": "Dashboard", "target": "API", "relation": "powers", "description": "Dashboard powers API", "confidence": 0.7}],
    )
    extractor = GraphRAGExtractor(llm=llm, embedder=FakeEmbedder(), ontology_profile=profile, namespace="demo", fact_store=fact_store)

    [result] = extractor([node])

    facts = fact_store.list("demo")
    assert len(facts) == 1
    assert facts[0].review_state == "assistive"
    relation = result.metadata[KG_RELATIONS_KEY][0]
    assert relation.properties["ontology_fact_id"] == facts[0].id


def test_fact_routes_list_create_review_and_relationship_candidate(client: TestClient, auth_headers: dict[str, str], mock_service: MagicMock) -> None:
    fact = {
        "id": "fact:one",
        "namespace": "demo",
        "statement": "Dashboard depends on API.",
        "subjects": [{"kind": "label", "id": "Dashboard", "label": "Dashboard"}],
        "subject_ids": ["Dashboard"],
        "confidence": 0.8,
        "review_state": "assistive",
        "source": "assistant",
        "evidence_refs": ["prov:one"],
        "provenance_refs": ["prov:one"],
        "suggested_mapping": {"relationship_type": "depends_on", "source_id": "dashboard", "target_id": "api", "source_kind": "node", "target_kind": "node", "direction": "forward", "confidence": 0.8},
        "source_hash": "",
        "promoted_edge_id": None,
        "created_at": "2026-06-01T00:00:00Z",
        "reviewed_at": None,
        "reviewed_by": None,
        "metadata": {},
    }
    mock_service.list_ontology_facts.return_value = [fact]
    mock_service.create_ontology_fact.return_value = fact
    mock_service.review_ontology_fact.return_value = {**fact, "review_state": "approved", "reviewed_by": "tester"}
    mock_service.raise_fact_relationship_candidate.return_value = {
        "id": "cand1",
        "namespace": "demo",
        "candidate_type": "relationship_type",
        "source": "fact:assistant",
        "original_label": "powers",
        "normalized_label": "powers",
        "suggested_canonical": "powers",
        "confidence": 0.5,
        "sample_text": "Dashboard powers API",
        "status": "pending",
        "source_hash": "hash",
        "proposed_payload": {},
        "source_evidence_ref": None,
        "created_at": "2026-06-01T00:00:00Z",
        "reviewed_at": None,
        "reviewed_by": None,
        "metadata": {},
    }

    response = client.get("/api/knowledge/namespaces/demo/ontology/facts", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["facts"][0]["statement"] == "Dashboard depends on API."

    response = client.post(
        "/api/knowledge/namespaces/demo/ontology/facts",
        headers=auth_headers,
        json={"statement": "Dashboard depends on API.", "source": "assistant", "evidence_refs": ["prov:one"]},
    )
    assert response.status_code == 200
    assert response.json()["review_state"] == "assistive"
    mock_service.create_ontology_fact.assert_called_once()
    assert mock_service.create_ontology_fact.call_args.kwargs["source"] == "assistant"
    assert mock_service.create_ontology_fact.call_args.kwargs["evidence_refs"] == ["prov:one"]
    assert not mock_service.promote_ontology_fact_to_edge.called

    response = client.post("/api/knowledge/namespaces/demo/ontology/facts/fact:one/review", headers=auth_headers, json={"review_state": "approved"})
    assert response.status_code == 200
    assert response.json()["review_state"] == "approved"

    response = client.post("/api/knowledge/namespaces/demo/ontology/facts/fact:one/relationship-candidate", headers=auth_headers, json={"relationship_label": "powers"})
    assert response.status_code == 200
    assert response.json()["candidate"]["candidate_type"] == "relationship_type"


def test_facts_routes_are_registered_on_runtime_app() -> None:
    from dashboard.api import app

    paths = {getattr(route, "path", "") for route in app.routes}

    assert "/api/knowledge/namespaces/{namespace}/ontology/facts" in paths
    assert "/api/knowledge/namespaces/{namespace}/ontology/facts/{fact_id}/review" in paths
    assert "/api/knowledge/namespaces/{namespace}/ontology/facts/{fact_id}/promote-edge" in paths
    assert "/api/knowledge/namespaces/{namespace}/ontology/facts/{fact_id}/relationship-candidate" in paths
