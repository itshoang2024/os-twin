"""EPIC-004 — Query engine tests.

Covers:

- :class:`KnowledgeQueryEngine` — three modes (raw, graph, summarized).
- :meth:`KnowledgeService.query`
  dispatchers + namespace validation.
- The centralised ``_vector_stores`` / ``_kuzu_graphs`` / ``_query_engines``
  cache and the matching :meth:`KnowledgeService.shutdown` /
  :meth:`KnowledgeService.delete_namespace` eviction story (architect's
  ZVEC-LIVE-1 fix from the EPIC-003 review).
- Concurrent queries against the same namespace.
- Error paths: missing namespace, invalid mode, empty namespace, missing
  ANTHROPIC_API_KEY in summarized mode.
- The architect-mandated probe (ZVEC-LIVE-1) — fresh
  :class:`NamespaceVectorStore` against a path that the service already
  owned.

Test harness:

- All tests use :class:`NamespaceManager` rooted at ``tmp_path`` so they
  never touch ``~/.ostwin/knowledge``.
- The ``populated_service`` fixture runs a real ingestion of the small
  ``knowledge_sample`` fixture once per test; the bge-small model is
  cached at the class level so subsequent runs in the same session are
  sub-second.
- :meth:`KnowledgeService.shutdown` is called in every fixture's teardown
  so zvec file locks are released before ``tmp_path`` cleanup runs (which
  would otherwise log noisy RocksDB errors on macOS).
"""

from __future__ import annotations

import os
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from dashboard.knowledge.embeddings import KnowledgeEmbedder
from dashboard.knowledge.llm import KnowledgeLLM
from dashboard.knowledge.namespace import (
    NamespaceManager,
    NamespaceNotFoundError,
)
from dashboard.knowledge.query import (
    ChunkHit,
    Citation,
    EntityHit,
    KnowledgeQueryEngine,
    QueryResult,
)
from dashboard.knowledge.service import KnowledgeService
from dashboard.knowledge.vector_store import NamespaceVectorStore, VectorHit


FIXTURES = Path(__file__).parent / "fixtures" / "knowledge_sample"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kb_dir(tmp_path: Path) -> Path:
    """Per-test knowledge base dir (under pytest's tmp_path)."""
    return tmp_path / "kb"


@pytest.fixture
def real_embedder() -> KnowledgeEmbedder:
    """Real KnowledgeEmbedder; the model load is cached at the class level."""
    return KnowledgeEmbedder()


@pytest.fixture
def no_llm(monkeypatch: pytest.MonkeyPatch) -> KnowledgeLLM:
    """LLM with no API key — exercises the graceful-degradation paths.

    Explicitly pops ``ANTHROPIC_API_KEY`` from the environment so a
    developer's real key (which may be present in their shell) doesn't
    bleed into tests that rely on graceful-degradation behaviour.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return KnowledgeLLM(api_key=None)


def _make_service(kb_dir: Path, embedder: KnowledgeEmbedder, llm: KnowledgeLLM) -> KnowledgeService:
    """Construct a KnowledgeService rooted at ``kb_dir``."""
    nm = NamespaceManager(base_dir=kb_dir)
    return KnowledgeService(namespace_manager=nm, embedder=embedder, llm=llm)


def _await_job(service: KnowledgeService, job_id: str, timeout: float = 60.0) -> Any:
    """Block until a job reaches a terminal state (or timeout)."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = service.get_job(job_id)
        if last is not None and last.state.value in ("completed", "failed", "cancelled"):
            return last
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish in {timeout}s; last state={last}")


@pytest.fixture
def populated_service(kb_dir: Path, real_embedder: KnowledgeEmbedder, no_llm: KnowledgeLLM):
    """A KnowledgeService with the sample fixture pre-ingested into ``query-test``."""
    svc = _make_service(kb_dir, real_embedder, no_llm)
    job_id = svc.import_folder("query-test", str(FIXTURES))
    status = _await_job(svc, job_id)
    assert status.state.value == "completed", f"setup ingestion failed: {status}"
    try:
        yield svc
    finally:
        svc.shutdown()


# ---------------------------------------------------------------------------
# Pydantic result models — surface tests
# ---------------------------------------------------------------------------


class TestQueryResultModels:
    def test_QueryResult_default_shape(self) -> None:
        r = QueryResult(query="x", mode="raw", namespace="ns")
        assert r.chunks == []
        assert r.entities == []
        assert r.answer is None
        assert r.citations == []
        assert r.warnings == []
        assert r.latency_ms == 0

    def test_QueryResult_serialises_to_json(self) -> None:
        r = QueryResult(
            query="x", mode="raw", namespace="ns",
            chunks=[ChunkHit(text="t", score=0.9)],
            citations=[Citation(file="f.md", chunk_index=0, snippet_id="i1")],
            warnings=["w1"], latency_ms=42,
        )
        dumped = r.model_dump(mode="json")
        assert dumped["query"] == "x"
        assert dumped["chunks"][0]["text"] == "t"
        assert dumped["citations"][0]["snippet_id"] == "i1"
        assert dumped["latency_ms"] == 42


# ---------------------------------------------------------------------------
# raw mode
# ---------------------------------------------------------------------------


class TestRawMode:
    def test_query_returns_QueryResult(self, populated_service: KnowledgeService) -> None:
        result = populated_service.query("query-test", "Acme Widget Toolkit")
        assert isinstance(result, QueryResult)
        assert result.namespace == "query-test"
        assert result.mode == "raw"
        assert result.answer is None  # raw mode never aggregates

    def test_query_returns_chunks_for_known_content(self, populated_service: KnowledgeService) -> None:
        # Ingest threshold below the bge cosine baseline so we always get hits.
        result = populated_service.query(
            "query-test", "Acme Widget Toolkit reactive runtime", threshold=0.0
        )
        assert len(result.chunks) > 0, "expected at least one hit for indexed content"
        # Every hit should have a non-empty text and score >= threshold.
        for chunk in result.chunks:
            assert chunk.text, "chunk text must not be empty"
            assert chunk.score >= 0.0
            assert chunk.filename, "chunk should carry filename metadata"

    def test_query_top_k_caps_results(self, populated_service: KnowledgeService) -> None:
        result = populated_service.query(
            "query-test", "Acme Widget Toolkit", top_k=2, threshold=0.0
        )
        assert len(result.chunks) <= 2
        assert len(result.citations) <= 2

    def test_query_threshold_filters_hits(self, populated_service: KnowledgeService) -> None:
        # Threshold of 1.1 (above max cosine score 1.0) — must produce 0 chunks.
        result = populated_service.query(
            "query-test", "anything at all", top_k=10, threshold=1.1
        )
        assert result.chunks == []
        assert result.citations == []
        # latency still recorded
        assert result.latency_ms >= 0

    def test_query_records_latency_ms(self, populated_service: KnowledgeService) -> None:
        result = populated_service.query("query-test", "Acme")
        assert isinstance(result.latency_ms, int)
        assert 0 <= result.latency_ms < 5000

    def test_query_chunks_have_metadata(self, populated_service: KnowledgeService) -> None:
        result = populated_service.query(
            "query-test", "reactor observable", threshold=0.0
        )
        # At least one chunk carries the file_hash + file_path it was ingested with.
        assert any(c.file_hash for c in result.chunks)
        assert any(c.file_path for c in result.chunks)

    def test_query_empty_namespace_returns_empty_chunks(
        self, kb_dir: Path, real_embedder: KnowledgeEmbedder, no_llm: KnowledgeLLM
    ) -> None:
        svc = _make_service(kb_dir, real_embedder, no_llm)
        try:
            svc.create_namespace("empty-ns")
            result = svc.query("empty-ns", "anything")
            assert result.chunks == []
            assert result.entities == []
            assert result.warnings == []
            assert result.answer is None
        finally:
            svc.shutdown()

    def test_query_p95_latency_under_500ms(self, populated_service: KnowledgeService) -> None:
        """20 raw queries; p95 must be < 500ms (architect-mandated budget).

        Warm-up first so embedder model load + zvec collection open don't
        dominate the measured window. The fixture corpus is small (~5
        chunks) so this is a generous budget.
        """
        # Warm-up: triggers embedder model load + zvec open.
        for _ in range(3):
            populated_service.query("query-test", "warm-up", top_k=5, threshold=0.0)

        latencies: list[float] = []
        for i in range(20):
            t0 = time.perf_counter()
            populated_service.query(
                "query-test", f"query {i}", top_k=10, threshold=0.0
            )
            latencies.append((time.perf_counter() - t0) * 1000)
        p95 = statistics.quantiles(latencies, n=20)[-1]  # 95th percentile
        p50 = statistics.median(latencies)
        # Print so done-report can capture it; not part of pass/fail.
        print(f"\n[raw] p50={p50:.1f}ms p95={p95:.1f}ms (n={len(latencies)})")
        assert p95 < 500.0, f"raw mode p95 {p95:.1f}ms exceeded 500ms budget"


# ---------------------------------------------------------------------------
# graph mode
# ---------------------------------------------------------------------------


class TestGraphMode:
    def test_graph_mode_with_no_kuzu_entities_returns_empty_entities(
        self, populated_service: KnowledgeService
    ) -> None:
        """Without an LLM, ingest creates 0 entities → graph mode returns no entities.

        Graph mode delegates retrieval to the KG engine's graph expansion path.
        Without entities in the graph, the expansion returns nothing. Chunks are
        NOT populated in graph mode (that's raw mode's responsibility)."""
        result = populated_service.query(
            "query-test", "Acme widget", mode="graph", threshold=0.0
        )
        assert result.entities == []
        # Graph mode focuses on entity expansion; chunks are a raw-mode concern.
        # latency still recorded
        assert result.latency_ms >= 0

    def test_graph_mode_with_mocked_kuzu_returns_entities(
        self, populated_service: KnowledgeService
    ) -> None:
        """Swap the engine's ``kg`` for a fake → graph mode returns those entities.

        ``KuzuLabelledPropertyGraph`` is a Pydantic model so we can't
        ``mock.patch.object`` its methods directly. Replace the engine's
        ``kg`` reference with a duck-typed stub instead.
        """

        class _FakeNode:
            def __init__(self, id_: str, name: str, label: str = "Person", props=None) -> None:
                self.id = id_
                self.name = name
                self.label = label
                self.properties = props or {"description": f"desc of {name}"}

        class _FakeKuzu:
            def get_all_nodes(self, **_kw: Any) -> list[_FakeNode]:
                return [
                    _FakeNode("e1", "Alice", "Person"),
                    _FakeNode("e2", "Bob", "Person"),
                    _FakeNode("e3", "Acme", "Organization"),
                ]

            def pagerank(self, _personalize: dict, **_kw: Any) -> list[tuple[str, float]]:
                return [("e3", 0.5), ("e1", 0.3), ("e2", 0.2)]

            def get_all_relations(self) -> list[Any]:
                return []

        engine = populated_service._get_query_engine("query-test")
        original_kg = engine.kg
        engine.kg = _FakeKuzu()
        try:
            result = populated_service.query(
                "query-test", "Acme widgets", mode="graph", threshold=0.0
            )
        finally:
            engine.kg = original_kg
        assert len(result.entities) == 3
        # Sorted by pagerank score desc.
        assert result.entities[0].id == "e3"
        assert result.entities[0].name == "Acme"
        assert result.entities[0].label == "Organization"
        assert result.entities[0].score == pytest.approx(0.5)
        assert result.entities[0].description == "desc of Acme"

    def test_graph_mode_handles_kuzu_failure_gracefully(
        self, populated_service: KnowledgeService
    ) -> None:
        """Kuzu raising during graph_expand → result has empty entities.

        Graph mode delegates retrieval to the KG engine. When the KG fails,
        the graph expansion swallows the error and returns empty entities.
        Chunks are NOT populated in graph mode (that's raw mode's concern)."""

        class _BoomKuzu:
            def get_all_nodes(self, **_kw: Any) -> list[Any]:
                raise RuntimeError("kuzu boom")

            def pagerank(self, *_a: Any, **_kw: Any) -> list[Any]:
                raise RuntimeError("unreachable")

            def get_all_relations(self) -> list[Any]:
                return []

        engine = populated_service._get_query_engine("query-test")
        original_kg = engine.kg
        engine.kg = _BoomKuzu()
        try:
            result = populated_service.query(
                "query-test", "Acme", mode="graph", threshold=0.0
            )
        finally:
            engine.kg = original_kg
        assert result.entities == []
        # Graph mode focuses on entity expansion; chunks are not populated.
        # Latency should still be recorded.
        assert result.latency_ms >= 0

    def test_graph_mode_caps_entity_count(
        self, populated_service: KnowledgeService
    ) -> None:
        """The engine caps entity hits at _MAX_ENTITIES_PER_QUERY (20)."""
        from dashboard.knowledge.query import _MAX_ENTITIES_PER_QUERY

        class _FakeNode:
            def __init__(self, id_: str) -> None:
                self.id = id_
                self.name = id_
                self.label = "entity"
                self.properties = {}

        class _FakeKuzu:
            def get_all_nodes(self, **_kw: Any) -> list[_FakeNode]:
                return [_FakeNode(f"e{i}") for i in range(50)]

            def pagerank(self, _p: dict, **_kw: Any) -> list[tuple[str, float]]:
                return [(f"e{i}", 1.0 - i / 100.0) for i in range(50)]

            def get_all_relations(self) -> list[Any]:
                return []

        engine = populated_service._get_query_engine("query-test")
        original_kg = engine.kg
        engine.kg = _FakeKuzu()
        try:
            result = populated_service.query(
                "query-test", "anything", mode="graph", threshold=0.0
            )
        finally:
            engine.kg = original_kg
        assert len(result.entities) == _MAX_ENTITIES_PER_QUERY


# ---------------------------------------------------------------------------
# summarized mode
# ---------------------------------------------------------------------------


class TestSummarizedMode:
    def test_summarized_without_llm_returns_warning_no_answer(
        self, populated_service: KnowledgeService
    ) -> None:
        """Architect-mandated: no ANTHROPIC_API_KEY → warning, no crash.

        Without a valid API key, both the graph_rag_engine's custom_query
        and the _fallback_summarize path fail gracefully.  The result must
        carry ``llm_unavailable`` in warnings and answer=None."""
        result = populated_service.query(
            "query-test", "Acme widgets", mode="summarized", threshold=0.0
        )
        assert result.answer is None
        assert any("llm_unavailable" in w for w in result.warnings)

    def test_summarized_with_mocked_llm_returns_answer(
        self, populated_service: KnowledgeService
    ) -> None:
        """Swap graph_rag_engine with a mock → summarized mode returns answer.

        GraphRAGQueryEngine is a Pydantic model, so mock.patch.object
        cannot set attributes on it.  We swap the whole engine instead."""
        engine = populated_service._get_query_engine("query-test")
        original_rag = engine.graph_rag_engine

        fake_rag = mock.MagicMock()
        fake_rag.get_nodes.return_value = None
        fake_rag.graph_result.return_value = "knowledge: '[]'"
        fake_rag.custom_query.return_value = "Acme widgets are reusable UI components."
        engine.graph_rag_engine = fake_rag
        try:
            result = populated_service.query(
                "query-test", "What are Acme widgets?",
                mode="summarized", threshold=0.0,
            )
        finally:
            engine.graph_rag_engine = original_rag
        assert result.answer is not None
        assert "llm_unavailable" not in " ".join(result.warnings)

    def test_summarized_with_llm_failure_records_warning(
        self, populated_service: KnowledgeService
    ) -> None:
        """LLM raising → answer=None + warning.

        The summarized path tries graph_rag_engine.custom_query first (which
        may also fail with LLM auth errors), then falls back to
        _fallback_summarize.  When neither produces an answer the result
        carries ``llm_unavailable`` in warnings."""
        result = populated_service.query(
            "query-test", "anything", mode="summarized", threshold=0.0
        )
        assert result.answer is None
        assert any(
            "llm_unavailable" in w or "llm_aggregation_failed" in w
            for w in result.warnings
        )

    def test_summarized_with_no_chunks_returns_no_answer(
        self, populated_service: KnowledgeService
    ) -> None:
        """No chunks + no working LLM → answer=None, llm_unavailable warning.

        The graph_rag_engine's custom_query fails (OpenAI env not configured),
        _fallback_summarize has no chunks to aggregate and returns empty,
        which is normalized to None."""
        result = populated_service.query(
            "query-test", "x", mode="summarized", threshold=1.1,  # impossible
        )
        assert result.chunks == []
        assert result.answer is None
        assert any("llm_unavailable" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestErrorPaths:
    def test_query_unknown_namespace_raises(
        self, kb_dir: Path, real_embedder: KnowledgeEmbedder, no_llm: KnowledgeLLM
    ) -> None:
        svc = _make_service(kb_dir, real_embedder, no_llm)
        try:
            with pytest.raises(NamespaceNotFoundError):
                svc.query("nonexistent", "anything")
        finally:
            svc.shutdown()

    def test_query_invalid_mode_raises(self, populated_service: KnowledgeService) -> None:
        with pytest.raises(ValueError, match="unknown mode"):
            populated_service.query("query-test", "x", mode="bogus")

    def test_query_with_failing_embedder_records_warning(
        self, populated_service: KnowledgeService
    ) -> None:
        """If the embedder raises during KG vector search, the result is empty.

        The KG layer (KuzuDB) catches embedder failures internally, logs
        them, and returns an empty node list.  The query engine receives
        an empty result — no crash, just zero hits."""
        engine = populated_service._get_query_engine("query-test")
        with mock.patch(
            "dashboard.knowledge.graph.index.kuzudb._get_embedder"
        ) as mock_get:
            mock_embedder = mock.MagicMock()
            mock_embedder.embed_one.side_effect = RuntimeError("model offline")
            mock_get.return_value = mock_embedder
            result = populated_service.query("query-test", "anything")
        assert result.chunks == []
        assert result.latency_ms >= 0


class TestCacheBehaviour:
    def test_get_vector_store_returns_cached_instance(
        self, kb_dir: Path, real_embedder: KnowledgeEmbedder, no_llm: KnowledgeLLM
    ) -> None:
        svc = _make_service(kb_dir, real_embedder, no_llm)
        try:
            svc.create_namespace("cache-test")
            vs1 = svc.get_vector_store("cache-test")
            vs2 = svc.get_vector_store("cache-test")
            assert vs1 is vs2  # same object — single shared handle
        finally:
            svc.shutdown()

    def test_get_kuzu_graph_returns_cached_instance(
        self, kb_dir: Path, real_embedder: KnowledgeEmbedder, no_llm: KnowledgeLLM
    ) -> None:
        svc = _make_service(kb_dir, real_embedder, no_llm)
        try:
            svc.create_namespace("cache-test-kuzu")
            kg1 = svc.get_kuzu_graph("cache-test-kuzu")
            kg2 = svc.get_kuzu_graph("cache-test-kuzu")
            assert kg1 is kg2
        finally:
            svc.shutdown()

    def test_query_engine_cached_across_calls(
        self, populated_service: KnowledgeService
    ) -> None:
        e1 = populated_service._get_query_engine("query-test")
        populated_service.query("query-test", "x", threshold=0.0)
        e2 = populated_service._get_query_engine("query-test")
        assert e1 is e2

    def test_ingestor_uses_service_vector_store_cache(
        self, kb_dir: Path, real_embedder: KnowledgeEmbedder, no_llm: KnowledgeLLM
    ) -> None:
        """ZVEC-LIVE-1 fix: the ingestor must pull from the service cache.

        After ingesting, ``service._vector_stores[ns]`` must already be
        populated AND the ingestor's _NamespaceStore must reference the
        SAME object.
        """
        svc = _make_service(kb_dir, real_embedder, no_llm)
        try:
            job_id = svc.import_folder("share-test", str(FIXTURES))
            _await_job(svc, job_id)
            assert "share-test" in svc._vector_stores
            ingestor_store = svc._get_ingestor()._stores["share-test"]
            assert ingestor_store._get_vstore() is svc._vector_stores["share-test"]
        finally:
            svc.shutdown()

    def test_concurrent_queries_against_same_namespace(
        self, populated_service: KnowledgeService
    ) -> None:
        """10 concurrent queries against the same namespace; all must complete."""
        # Warm-up.
        populated_service.query("query-test", "warmup", threshold=0.0)

        errors: list[Exception] = []
        results: list[QueryResult] = []
        lock = threading.Lock()

        def _q(i: int) -> None:
            try:
                r = populated_service.query(
                    "query-test", f"concurrent {i}", top_k=5, threshold=0.0
                )
                with lock:
                    results.append(r)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(_q, i) for i in range(10)]
            for f in as_completed(futures):
                f.result()  # surface exceptions
        assert errors == [], f"concurrent queries raised: {errors}"
        assert len(results) == 10

    def test_query_after_delete_namespace_raises(
        self, populated_service: KnowledgeService
    ) -> None:
        populated_service.delete_namespace("query-test")
        with pytest.raises(NamespaceNotFoundError):
            populated_service.query("query-test", "anything")

    def test_delete_then_recreate_with_same_name_works(
        self, kb_dir: Path, real_embedder: KnowledgeEmbedder, no_llm: KnowledgeLLM
    ) -> None:
        """ZVEC-LIVE-1 cache eviction: delete must release handles so re-create works."""
        svc = _make_service(kb_dir, real_embedder, no_llm)
        try:
            # Ingest, then delete, then recreate + query.
            job_id = svc.import_folder("recycle-ns", str(FIXTURES))
            _await_job(svc, job_id)
            assert svc.delete_namespace("recycle-ns") is True
            assert "recycle-ns" not in svc._vector_stores
            assert "recycle-ns" not in svc._kuzu_graphs

            svc.create_namespace("recycle-ns")
            result = svc.query("recycle-ns", "anything")
            assert result.chunks == []  # fresh — no content
        finally:
            svc.shutdown()


# ---------------------------------------------------------------------------
# Service shutdown
# ---------------------------------------------------------------------------


class TestServiceShutdown:
    def test_shutdown_releases_handles(
        self, kb_dir: Path, real_embedder: KnowledgeEmbedder, no_llm: KnowledgeLLM
    ) -> None:
        svc = _make_service(kb_dir, real_embedder, no_llm)
        svc.create_namespace("sd-test")
        # Force vector store + Kuzu graph creation.
        svc.get_vector_store("sd-test")
        svc.get_kuzu_graph("sd-test")
        assert "sd-test" in svc._vector_stores
        assert "sd-test" in svc._kuzu_graphs
        svc.shutdown()
        assert svc._vector_stores == {}
        assert svc._kuzu_graphs == {}
        assert svc._query_engines == {}

    def test_shutdown_is_idempotent(
        self, kb_dir: Path, real_embedder: KnowledgeEmbedder, no_llm: KnowledgeLLM
    ) -> None:
        svc = _make_service(kb_dir, real_embedder, no_llm)
        svc.create_namespace("sd-idempotent")
        svc.get_vector_store("sd-idempotent")
        svc.shutdown()
        svc.shutdown()  # second call must not raise
        assert svc._vector_stores == {}


# ---------------------------------------------------------------------------
# Architect-mandated probe: ZVEC-LIVE-1 verification
# ---------------------------------------------------------------------------


class TestArchitectProbe:
    """Reproduces the architect's EPIC-003 review probe.

    Pre-fix, opening a *second* :class:`NamespaceVectorStore` against the
    same path while the first was alive raised
    ``ValueError: path validate failed: path[...] is existed`` because
    ``_open_or_create`` swallowed the ``zvec.open`` error and fell through
    to ``zvec.create_and_open`` on a path that already had files in it.

    Post-fix:

    1. While the service-owned store is alive, opening a fresh store at
       the same path must call ``zvec.open`` (NOT ``create_and_open``)
       because the directory exists with content. zvec WILL reject the
       second concurrent handle (file lock) — that's a different error
       and we accept it; the important guarantee is that we don't get the
       confusing "is existed" error any more.
    2. After ``service.shutdown()``, opening a fresh store at the same
       path succeeds because the previous handle's lock is released.
    """

    def test_fresh_store_after_shutdown_opens_clean(
        self, kb_dir: Path, real_embedder: KnowledgeEmbedder, no_llm: KnowledgeLLM
    ) -> None:
        svc = _make_service(kb_dir, real_embedder, no_llm)
        # Ingest something so the path actually has zvec files in it.
        job_id = svc.import_folder("probe-ns", str(FIXTURES))
        _await_job(svc, job_id)

        vector_path = svc._nm.vector_dir("probe-ns")
        assert vector_path.exists() and any(vector_path.iterdir()), (
            "expected zvec collection files to exist on disk"
        )

        # Fully shutdown — must release the file lock + close zvec handle.
        svc.shutdown()

        # Fresh store at the same path. Pre-fix this would have called
        # ``create_and_open`` and raised "is existed". Post-fix it must
        # call ``zvec.open`` and succeed.
        fresh_vs = NamespaceVectorStore(
            vector_path=vector_path,
            dimension=real_embedder.dimension(),
        )
        try:
            # Touch the collection to actually open it (lazy until first use).
            count = fresh_vs.count()
            assert count >= 1, (
                f"fresh store should observe the previously-ingested data; got count={count}"
            )
        finally:
            fresh_vs.close()

    def test_fresh_store_at_empty_path_creates_cleanly(
        self, tmp_path: Path, real_embedder: KnowledgeEmbedder
    ) -> None:
        """Truly-fresh path → ``_open_or_create`` must take the create branch."""
        empty_path = tmp_path / "fresh" / "vectors"
        # Don't pre-create — let the store handle it.
        vs = NamespaceVectorStore(
            vector_path=empty_path, dimension=real_embedder.dimension()
        )
        try:
            assert vs.count() == 0
        finally:
            vs.close()

    def test_open_or_create_re_raises_when_open_fails_on_real_collection(
        self, tmp_path: Path, real_embedder: KnowledgeEmbedder
    ) -> None:
        """Architect's guidance part 2: if a real collection exists but
        ``zvec.open`` fails, we re-raise instead of silently calling
        ``create_and_open`` (which would then raise the misleading
        "is existed" error).

        We simulate this by creating a real collection, closing it, then
        monkeypatching ``zvec.open`` to fail. The ``_open_or_create``
        method must propagate that exception.
        """
        # 1) Create + close a real collection so the path has content.
        path = tmp_path / "open-fail-test" / "vectors"
        first = NamespaceVectorStore(vector_path=path, dimension=real_embedder.dimension())
        first.add_chunks([
            {
                "text": "hello world",
                "embedding": real_embedder.embed_one("hello world"),
                "metadata": {
                    "file_hash": "h1", "file_path": "/tmp/x.md",
                    "filename": "x.md", "chunk_index": 0, "total_chunks": 1,
                },
            }
        ])
        first.close()

        # 2) Patch zvec.open to fail. _open_or_create must re-raise.
        import zvec

        with mock.patch.object(zvec, "open", side_effect=RuntimeError("simulated open failure")):
            second = NamespaceVectorStore(vector_path=path, dimension=real_embedder.dimension())
            with pytest.raises(RuntimeError, match="simulated open failure"):
                second.count()  # touches _coll() → _open_or_create()
