"""EPIC-003 evidence and provenance backbone tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from llama_index.core.schema import TextNode
from pydantic import ValidationError

from dashboard.knowledge.graph.core.graph_rag_extractor import GraphRAGExtractor
from dashboard.knowledge.ingestion import Ingestor
from dashboard.knowledge.namespace import NamespaceManager
from dashboard.knowledge.ontology.defaults import create_default_ontology_profile
from dashboard.knowledge.ontology.evidence import (
    EvidenceAnchor,
    EvidenceArtifact,
    EvidenceLocator,
    EvidenceStore,
    ProvenanceLink,
)
from dashboard.knowledge.ontology.candidates import OntologyCandidateStore


class FakeLLM:
    def extract_entities(self, text: str, language: str = "English", domain: str = "", ontology_profile_hint=None):  # noqa: ANN001, ARG002
        return ([{"name": "Dashboard", "type": "UnknownType", "confidence": 0.8}], [])


class FakeEmbedder:
    def embed(self, texts):  # noqa: ANN001
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_one(self, text: str):  # noqa: ARG002
        return [0.1, 0.2, 0.3]


def test_evidence_models_are_strict_and_require_unread_limitations() -> None:
    artifact_payload = {
        "id": "artifact:abc",
        "ontology_unit_id": "demo",
        "source_type": "document",
        "read_coverage": "unread",
        "source_state": "conversion_needed",
        "limitations": ["conversion_needed"],
        "extra": "forbidden",
    }
    with pytest.raises(ValidationError):
        EvidenceArtifact.model_validate(artifact_payload)

    with pytest.raises(ValidationError):
        EvidenceArtifact(
            id="artifact:abc",
            ontology_unit_id="demo",
            source_type="document",
            read_coverage="unread",
            source_state="conversion_needed",
            limitations=[],
        )


def test_evidence_store_persists_anchor_reuse_and_append_only_links(tmp_path: Path) -> None:
    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    store = EvidenceStore(nm)
    artifact = store.upsert_artifact(
        "demo",
        EvidenceArtifact(
            id="artifact:one",
            ontology_unit_id="demo",
            source_type="document",
            source_uri="file:///a.md",
            checksum="hash",
            read_coverage="full",
            source_state="read",
        ),
    )
    anchor = store.upsert_anchor(
        "demo",
        EvidenceAnchor(
            id="anchor:one",
            artifact_id=artifact.id,
            locator=EvidenceLocator(section="Intro", chunk_id="0"),
            excerpt="A supports B",
            extraction_method="parser",
        ),
    )

    first = store.create_provenance_link("demo", subject_type="candidate", subject_id="cand1", evidence_anchor_id=anchor.id)
    second = store.create_provenance_link("demo", subject_type="fact", subject_id="fact1", evidence_anchor_id=anchor.id)
    duplicate = store.create_provenance_link("demo", subject_type="candidate", subject_id="cand1", evidence_anchor_id=anchor.id)

    links = store.list_provenance("demo")
    assert {link.id for link in links} == {first.id, second.id}
    assert duplicate.id == first.id
    assert store.resolve_provenance("demo", first.id)["anchor"]["excerpt"] == "A supports B"


def test_graph_extractor_creates_candidate_provenance_link(tmp_path: Path) -> None:
    nm = NamespaceManager(base_dir=tmp_path)
    nm.create("demo")
    evidence = EvidenceStore(nm)
    candidates = OntologyCandidateStore(nm)
    artifact = evidence.upsert_artifact(
        "demo",
        EvidenceArtifact(id="artifact:one", ontology_unit_id="demo", source_type="document", read_coverage="full", source_state="read"),
    )
    anchor = evidence.upsert_anchor(
        "demo",
        EvidenceAnchor(id="anchor:one", artifact_id=artifact.id, locator=EvidenceLocator(chunk_id="0"), excerpt="Dashboard is a screen", extraction_method="parser"),
    )
    profile = create_default_ontology_profile("demo")
    node = TextNode(text="Dashboard is a screen", metadata={"file_hash": "hash", "file_path": "inline://demo", "evidence_anchor_id": anchor.id})
    extractor = GraphRAGExtractor(
        llm=FakeLLM(),
        embedder=FakeEmbedder(),
        ontology_profile=profile,
        candidate_store=candidates,
        evidence_store=evidence,
        namespace="demo",
    )

    extractor([node])

    stored = candidates.list("demo")
    assert len(stored) == 1
    assert stored[0].source_evidence_ref.startswith("prov:")
    resolved = evidence.resolve_provenance("demo", stored[0].source_evidence_ref)
    assert resolved["anchor"]["id"] == anchor.id


def test_image_only_ingestion_records_ocr_needed_without_claims(tmp_path: Path) -> None:
    nm = NamespaceManager(base_dir=tmp_path / "knowledge")
    nm.create("demo")
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "scan.png").write_bytes(b"not-real-image")
    ingestor = Ingestor(namespace_manager=nm)

    result = ingestor.run("demo", str(folder))

    assert result["files_skipped"] == 1
    evidence = EvidenceStore(nm)
    artifacts = evidence.list_artifacts("demo")
    assert artifacts[0].source_type == "image"
    assert artifacts[0].source_state == "ocr_needed"
    assert "ocr_needed" in artifacts[0].limitations
    assert evidence.list_anchors("demo") == []
    assert evidence.list_provenance("demo") == []
