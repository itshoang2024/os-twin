# ruff: noqa: E501
"""Deterministic fakes for EPIC-010 ontology lifecycle tests.

The production ingestion path depends on parser, embedding, vector, and graph backends.
These fakes keep the release-gate lifecycle deterministic while still exercising the
KnowledgeService facade, ontology profile persistence, pack install state, candidate
review storage, query-mode dispatch, and explorer serialization contracts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dashboard.knowledge.jobs import JobEvent, JobState
from dashboard.knowledge.namespace import ImportRecord
from dashboard.knowledge.query import ChunkHit, Citation, EntityHit, QueryResult


class FakeEmbedder:
    """Small deterministic embedder that avoids external model backends in tests.

    It implements both the KnowledgeEmbedder facade (`embed`, `embed_one`,
    `dimension`) and the method shape expected by the LlamaIndex adapter used
    during ingestion/query setup.  The constant non-zero vector is sufficient
    for regression tests that assert storage/query plumbing, not semantic rank.
    """

    model_name = "fake-ontology-e2e-embedder"
    provider = "fake"

    def dimension(self) -> int:
        return 1024

    def embed_one(self, text: str) -> list[float]:
        # Match the graph/vector default dimensionality used by test Kuzu stores.
        return [0.1] * self.dimension()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(text) for text in texts]


class DeterministicOntologyIngestor:
    """Fake folder ingestor that records manifest stats and candidate output.

    It validates the fixture folder, emits normal job progress events, appends a
    completed import record, updates namespace counters, and creates one pending
    `relationship_type` candidate for the non-canonical `powers` relation. This
    gives EPIC-010 a repeatable extraction path without invoking MarkItDown,
    Kuzu, zvec, or an LLM.
    """

    def __init__(self, service: Any) -> None:
        self.service = service

    def run(self, namespace: str, folder_path: str, options: Any | None = None, *, emit=None, cancel_check=None) -> dict[str, Any]:
        started = datetime.now(UTC)
        fixture = Path(folder_path)
        if not fixture.is_dir():
            raise NotADirectoryError(folder_path)
        files = sorted(path for path in fixture.iterdir() if path.is_file() and not path.name.startswith("."))
        emit = emit or (lambda event: None)
        emit(JobEvent(timestamp=started, state=JobState.RUNNING, message="Deterministic ontology fixture ingest", progress_current=0, progress_total=len(files)))
        for idx, path in enumerate(files, start=1):
            emit(JobEvent(timestamp=datetime.now(UTC), state=JobState.RUNNING, message=f"Indexed {path.name}", progress_current=idx, progress_total=len(files), detail={"file": str(path), "deterministic": True}))
        self.service._nm.update_stats(namespace, files_indexed=len(files), chunks=3, entities=5, relations=4, vectors=3)  # noqa: SLF001
        self.service._nm.append_import(namespace, ImportRecord(folder_path=str(fixture), started_at=started, finished_at=datetime.now(UTC), status="completed", file_count=len(files), error_count=0))  # noqa: SLF001
        if hasattr(self.service, "_kuzu_graphs"):
            self.service._kuzu_graphs[namespace] = FakeKnowledgeRegressionGraph()  # noqa: SLF001
        candidate = self.service._candidate_store.upsert_pending(  # noqa: SLF001
            namespace,
            candidate_type="relationship_type",
            original_label="powers",
            source="deterministic-fixture",
            suggested_canonical="powers",
            confidence=0.91,
            sample_text="KYC Screening Service powers Loan Origination workflow.",
            source_hash="ontology-lifecycle-fixture",
            metadata={"fixture": "loan-origination.md"},
        )
        return {"files_indexed": len(files), "chunks_added": 3, "entities_added": 5, "relations_added": 4, "candidates_added": 1, "candidate_id": candidate.id}


class FakeQueryEngine:
    """Query engine that proves service dispatch for raw, graph, and summarized modes."""

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace
        self.calls: list[str] = []

    def query(self, query: str, *, mode: str, top_k: int = 10, threshold: float = 0.5, category: str | None = None, parameter: str = "") -> QueryResult:
        self.calls.append(mode)
        return QueryResult(
            query=query,
            mode=mode,
            namespace=self.namespace,
            chunks=[ChunkHit(text="Loan Origination depends on KYC Screening Service.", score=0.99, file_path="loan-origination.md", filename="loan-origination.md")],
            entities=[EntityHit(id="kyc_service", name="KYC Screening Service", label="service", score=0.88)] if mode in {"graph", "summarized"} else [],
            answer="KYC Screening is a prerequisite for loan origination." if mode == "summarized" else None,
            citations=[Citation(file="loan-origination.md", chunk_index=0, snippet_id="fixture-0")],
            latency_ms=7,
            warnings=[] if mode != "summarized" else ["fake_llm_summary"],
        )


@dataclass
class FakeChunkNode:
    id: str
    text: str
    label: str = "text_chunk"
    properties: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.properties is None:
            self.properties = {
                "file_path": "readme.md",
                "filename": "readme.md",
                "chunk_index": 0,
                "total_chunks": 1,
                "file_hash": "fake-knowledge-regression",
                "mime_type": "text/markdown",
            }


class FakeKnowledgeRegressionGraph:
    """KuzuGraph test double for legacy Knowledge query/REST regressions.

    Raw queries return deterministic chunk nodes, while entity expansion returns
    an empty graph to preserve the legacy no-LLM expectations in
    tests/test_knowledge_query.py.
    """

    def __init__(self) -> None:
        self.chunks = [
            FakeChunkNode(
                id="chunk-1",
                text="Acme Widget Toolkit reactive runtime test document for Knowledge regression.",
            )
        ]

    def count_entities(self) -> int:
        return 0

    def count_chunks(self) -> int:
        return len(self.chunks)

    def count_relations(self) -> int:
        return 0

    def get_all_nodes(self, **kwargs):
        if kwargs.get("context") is not None:
            try:
                from dashboard.knowledge.graph.index.kuzudb import _get_embedder

                _get_embedder().embed_one(str(kwargs.get("context") or ""))
            except Exception as exc:
                if "model offline" in str(exc):
                    return []
            limit = kwargs.get("limit", len(self.chunks))
            return self.chunks[:limit]
        return []

    def get_all_relations(self):
        return []

    def pagerank(self, personalize: dict[str, float], **_kwargs):
        return []

    def close_connection(self) -> None:
        return None


@dataclass
class FakeEntityNode:
    id: str
    name: str
    label: str
    properties: dict[str, Any]


@dataclass
class FakeRelation:
    source_id: str
    target_id: str
    label: str
    properties: dict[str, Any]


class FakeEnterpriseGraph:
    """Graph double consumed by KnowledgeExplorer for enterprise map seed tests."""

    def __init__(self, ontology_profile: Any) -> None:
        self.ontology_profile = ontology_profile
        self.nodes = [
            FakeEntityNode("loan_product", "Loan Product", "financial_product", {"concept_type": "financial_product", "layer": "product", "pack_id": "financial-services", "metadata": {"owner": "Lending"}}),
            FakeEntityNode("kyc_obligation", "KYC Obligation", "regulatory_obligation", {"concept_type": "regulatory_obligation", "layer": "governance", "pack_id": "financial-services", "metadata": {"owner": "Compliance"}}),
            FakeEntityNode("kyc_service", "KYC Screening Service", "service", {"concept_type": "service", "layer": "platform", "metadata": {"owner": "Platform"}}),
        ]
        self.relations = [
            FakeRelation("loan_product", "kyc_obligation", "regulated_by", {"relation_label": "regulated_by", "weight": 0.8}),
            FakeRelation("kyc_service", "loan_product", "enables", {"relation_label": "enables", "weight": 0.7}),
        ]
        self.triplets = [(self.nodes[0], self.relations[0], self.nodes[1]), (self.nodes[2], self.relations[1], self.nodes[0])]

    def count_entities(self) -> int:
        return len(self.nodes)

    def count_chunks(self) -> int:
        return 3

    def count_relations(self) -> int:
        return len(self.relations)

    @property
    def connection(self):
        class _Conn:
            def execute(self, *_args, **_kwargs):
                return iter([])
        return _Conn()

    def get_all_nodes(self, **kwargs):
        if kwargs.get("graph"):
            import networkx as nx
            graph = nx.MultiGraph()
            for node in self.nodes:
                graph.add_node(node.id, id=node.id)
            for source, relation, target in self.triplets:
                graph.add_edge(source.id, target.id, weight=relation.properties.get("weight", 1.0), relation_label=relation.label)
            return graph
        if kwargs.get("context"):
            return self.nodes[: kwargs.get("limit", len(self.nodes))]
        return self.nodes

    def get_all_relations(self):
        return self.relations

    def get_by_ids(self, ids: list[str]):
        wanted = set(ids)
        return [node for node in self.nodes if node.id in wanted]

    def get_node(self, id_: str):
        return next((node for node in self.nodes if node.id == id_), None)

    def get_triplets(self, ids: list[str] | None = None):
        if not ids:
            return self.triplets
        wanted = set(ids)
        return [(s, r, t) for s, r, t in self.triplets if s.id in wanted or t.id in wanted]

    def pagerank(self, personalize: dict[str, float], **_kwargs):
        time.sleep(0)  # keep interface realistic while remaining deterministic
        return [(node_id, 1.0) for node_id in personalize]
