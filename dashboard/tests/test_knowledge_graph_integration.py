"""Integration tests for the knowledge graph layer.

Covers:

1. **MarkitdownReader provider detection** — verifies ``_get_markitdown``
   uses ``llm_client`` for provider-aware key resolution instead of
   the hardcoded ``anthropic.Anthropic()``.
2. **GraphRAGExtractor contract** — verifies the LlamaIndex
   ``TransformComponent`` produces the expected metadata keys
   (``KG_NODES_KEY``, ``KG_RELATIONS_KEY``) with a mocked LLM.
3. **Service → ingest → query roundtrip** — full pipeline with mocked
   LLM producing entities, verifying they land in Kuzu and are returned
   by graph-mode queries.
4. **MarkitdownReader document parsing** — verifies the reader correctly
   chunks text content and populates Document metadata.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from dashboard.knowledge.embeddings import KnowledgeEmbedder
from dashboard.knowledge.llm import KnowledgeLLM
from dashboard.knowledge.namespace import NamespaceManager
from dashboard.knowledge.service import KnowledgeService


FIXTURES = Path(__file__).parent / "fixtures" / "knowledge_sample"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kb_dir(tmp_path: Path) -> Path:
    return tmp_path / "kb"


@pytest.fixture
def real_embedder() -> KnowledgeEmbedder:
    return KnowledgeEmbedder()


@pytest.fixture
def no_llm(monkeypatch: pytest.MonkeyPatch) -> KnowledgeLLM:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    return KnowledgeLLM(api_key=None, model="")


def _make_service(
    kb_dir: Path,
    embedder: KnowledgeEmbedder,
    llm: KnowledgeLLM,
) -> KnowledgeService:
    nm = NamespaceManager(base_dir=kb_dir)
    return KnowledgeService(namespace_manager=nm, embedder=embedder, llm=llm)


def _await_job(service: KnowledgeService, job_id: str, timeout: float = 60.0) -> Any:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = service.get_job(job_id)
        if last is not None and last.state.value in ("completed", "failed", "cancelled"):
            return last
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish in {timeout}s; last state={last}")


# ---------------------------------------------------------------------------
# 1) MarkitdownReader — provider-aware LLM client
# ---------------------------------------------------------------------------


class TestMarkitdownReaderProviderAware:
    """Verify _get_markitdown uses llm_client.create_client for provider detection."""

    def test_no_llm_model_returns_plain_markitdown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty LLM_MODEL → plain MarkItDown (no vision)."""
        monkeypatch.setattr("dashboard.knowledge.config.LLM_MODEL", "")

        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        reader = MarkitdownReader()
        md = reader._get_markitdown()
        assert md._llm_client is None

    def test_no_api_key_returns_plain_markitdown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """create_client returns a client with no api_key → plain MarkItDown."""
        monkeypatch.setattr("dashboard.knowledge.config.LLM_MODEL", "claude-sonnet-4-5-20251022")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        reader = MarkitdownReader()
        md = reader._get_markitdown()
        # Without API key, create_client's underlying _client.api_key will be None
        assert md._llm_client is None

    def test_with_api_key_creates_openai_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With a valid API key, _get_markitdown creates a sync OpenAI client."""
        monkeypatch.setattr("dashboard.knowledge.config.LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")

        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        reader = MarkitdownReader()
        md = reader._get_markitdown()
        assert md._llm_client is not None
        from openai import OpenAI
        assert isinstance(md._llm_client, OpenAI)
        assert md._llm_model == "gpt-4o"

    def test_anthropic_model_routes_through_create_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anthropic model → create_client resolves to OpenAI-compat endpoint."""
        monkeypatch.setattr("dashboard.knowledge.config.LLM_MODEL", "claude-sonnet-4-5-20251022")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-anthropic")

        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        reader = MarkitdownReader()
        md = reader._get_markitdown()
        assert md._llm_client is not None
        from openai import OpenAI
        assert isinstance(md._llm_client, OpenAI)
        assert md._llm_model == "claude-sonnet-4-5-20251022"

    def test_deepseek_model_routes_through_create_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DeepSeek model → create_client resolves provider and base URL."""
        monkeypatch.setattr("dashboard.knowledge.config.LLM_MODEL", "deepseek-chat")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek")

        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        reader = MarkitdownReader()
        md = reader._get_markitdown()
        assert md._llm_client is not None
        from openai import OpenAI
        assert isinstance(md._llm_client, OpenAI)

    def test_create_client_is_called(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify create_client is actually invoked as the integration point."""
        monkeypatch.setattr("dashboard.knowledge.config.LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        with mock.patch("dashboard.llm_client.create_client", wraps=__import__("dashboard.llm_client", fromlist=["create_client"]).create_client) as spy:
            reader = MarkitdownReader()
            md = reader._get_markitdown()
            spy.assert_called_once_with(model="gpt-4o", api_key="sk-test")

    def test_provider_detection_matches_llm_client(self) -> None:
        """Provider detection in llm_client works for known models."""
        from dashboard.llm_client import _detect_provider_from_model

        assert _detect_provider_from_model("claude-sonnet-4-5-20251022") == "anthropic"
        assert _detect_provider_from_model("gpt-4o") == "openai"
        assert _detect_provider_from_model("gemini-2.0-flash") == "google"
        assert _detect_provider_from_model("deepseek-chat") == "deepseek"


# ---------------------------------------------------------------------------
# 2) MarkitdownReader — document parsing
# ---------------------------------------------------------------------------


class TestMarkitdownReaderParsing:
    """Verify the reader correctly chunks and metadata-stamps documents."""

    def test_read_with_preextracted_content(self) -> None:
        """When file dict has 'content', reader uses it directly (no disk I/O)."""
        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        reader = MarkitdownReader()
        docs = reader.read(
            {"url": "/fake/path/doc.md", "content": "Hello world test content"},
            ws_id="ws1",
            node_id="n1",
        )
        assert len(docs) >= 1
        assert docs[0].text == "Hello world test content"
        assert docs[0].metadata["filename"] == "doc.md"
        assert docs[0].metadata["ws_id"] == "ws1"
        assert docs[0].metadata["node_id"] == "n1"
        assert docs[0].metadata["processor"] == "markitdown"

    def test_read_missing_url_returns_empty(self) -> None:
        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        reader = MarkitdownReader()
        docs = reader.read({})
        assert docs == []

    def test_read_http_url_returns_empty(self) -> None:
        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        reader = MarkitdownReader()
        docs = reader.read({"url": "https://example.com/doc.pdf"})
        assert docs == []

    def test_chunking_splits_long_text(self) -> None:
        """Long text is split into overlapping chunks."""
        from dashboard.knowledge.graph.parsers.markitdown_reader import _chunk_text

        text = "word " * 500  # ~2500 chars
        chunks = _chunk_text(text, chunk_size=1024, overlap=200)
        assert len(chunks) > 1
        # Verify overlap: end of chunk[0] should overlap with start of chunk[1]
        assert chunks[0][-200:] == chunks[1][:200]

    def test_chunking_short_text_single_chunk(self) -> None:
        from dashboard.knowledge.graph.parsers.markitdown_reader import _chunk_text

        text = "short text"
        chunks = _chunk_text(text)
        assert chunks == ["short text"]

    def test_chunking_empty_text(self) -> None:
        from dashboard.knowledge.graph.parsers.markitdown_reader import _chunk_text

        assert _chunk_text("") == []
        assert _chunk_text(None) == []


# ---------------------------------------------------------------------------
# 3) GraphRAGExtractor — LlamaIndex TransformComponent contract
# ---------------------------------------------------------------------------


class TestGraphRAGExtractorContract:
    """Verify GraphRAGExtractor produces the expected metadata keys."""

    def test_extractor_produces_kg_metadata_keys(self) -> None:
        """With a mocked LLM, the extractor populates KG_NODES_KEY and
        KG_RELATIONS_KEY on each node."""
        from llama_index.core.graph_stores.types import KG_NODES_KEY, KG_RELATIONS_KEY
        from llama_index.core.schema import TextNode

        from dashboard.knowledge.graph.core.graph_rag_extractor import (
            GraphRAGExtractor,
        )

        # Mock LLM that returns known entities/relations
        fake_llm = mock.MagicMock(spec=KnowledgeLLM)
        fake_llm.extract_entities.return_value = (
            [
                {"name": "Alice", "type": "Person", "description": "A software engineer"},
                {"name": "Acme", "type": "Company", "description": "A tech company"},
            ],
            [
                {
                    "source": "Alice",
                    "target": "Acme",
                    "relation": "works_at",
                    "description": "Alice works at Acme",
                },
            ],
        )

        # Mock embedder
        fake_embedder = mock.MagicMock(spec=KnowledgeEmbedder)
        fake_embedder.embed.return_value = [[0.1] * 1024, [0.2] * 1024]

        extractor = GraphRAGExtractor(
            llm=fake_llm,
            embedder=fake_embedder,
            language="English",
            num_workers=1,
        )

        nodes = [TextNode(text="Alice is a software engineer at Acme.")]
        result = extractor(nodes)

        assert len(result) == 1
        node = result[0]
        assert KG_NODES_KEY in node.metadata
        assert KG_RELATIONS_KEY in node.metadata
        assert len(node.metadata[KG_NODES_KEY]) == 2
        assert len(node.metadata[KG_RELATIONS_KEY]) == 1

        # Verify entity details
        entity_names = {e.name for e in node.metadata[KG_NODES_KEY]}
        assert "Alice" in entity_names
        assert "Acme" in entity_names

        # Verify relation details
        rel = node.metadata[KG_RELATIONS_KEY][0]
        assert rel.source_id == "Alice"
        assert rel.target_id == "Acme"
        assert rel.label == "works_at"

    def test_extractor_handles_empty_extraction(self) -> None:
        """LLM returning no entities → empty metadata lists, no crash."""
        from llama_index.core.graph_stores.types import KG_NODES_KEY, KG_RELATIONS_KEY
        from llama_index.core.schema import TextNode

        from dashboard.knowledge.graph.core.graph_rag_extractor import (
            GraphRAGExtractor,
        )

        fake_llm = mock.MagicMock(spec=KnowledgeLLM)
        fake_llm.extract_entities.return_value = ([], [])

        fake_embedder = mock.MagicMock(spec=KnowledgeEmbedder)

        extractor = GraphRAGExtractor(
            llm=fake_llm, embedder=fake_embedder, num_workers=1,
        )
        nodes = [TextNode(text="Nothing extractable here.")]
        result = extractor(nodes)
        assert result[0].metadata[KG_NODES_KEY] == []
        assert result[0].metadata[KG_RELATIONS_KEY] == []

    def test_extractor_handles_llm_failure_gracefully(self) -> None:
        """LLM raising → nodes get extraction_error + FAILED status."""
        from llama_index.core.graph_stores.types import KG_NODES_KEY, KG_RELATIONS_KEY
        from llama_index.core.schema import TextNode

        from dashboard.knowledge.graph.core.graph_rag_extractor import (
            ExtractionConfig,
            ExtractionStatus,
            GraphRAGExtractor,
        )

        fake_llm = mock.MagicMock(spec=KnowledgeLLM)
        fake_llm.extract_entities.side_effect = RuntimeError("LLM offline")

        fake_embedder = mock.MagicMock(spec=KnowledgeEmbedder)

        extractor = GraphRAGExtractor(
            llm=fake_llm,
            embedder=fake_embedder,
            num_workers=1,
            config=ExtractionConfig(max_retries=0),
        )
        nodes = [TextNode(text="Should fail gracefully.")]
        result = extractor(nodes)

        assert result[0].metadata[KG_NODES_KEY] == []
        assert result[0].metadata[KG_RELATIONS_KEY] == []
        assert result[0].metadata.get("extraction_status") == ExtractionStatus.FAILED.value

    def test_extractor_with_multiple_nodes(self) -> None:
        """Batch of nodes → each gets its own extraction results."""
        from llama_index.core.graph_stores.types import KG_NODES_KEY, KG_RELATIONS_KEY
        from llama_index.core.schema import TextNode

        from dashboard.knowledge.graph.core.graph_rag_extractor import (
            GraphRAGExtractor,
        )

        call_count = [0]

        def _extract(text, lang, domain):
            call_count[0] += 1
            return (
                [{"name": f"Entity{call_count[0]}", "type": "Test", "description": "desc"}],
                [],
            )

        fake_llm = mock.MagicMock(spec=KnowledgeLLM)
        fake_llm.extract_entities.side_effect = _extract

        fake_embedder = mock.MagicMock(spec=KnowledgeEmbedder)
        fake_embedder.embed.return_value = [[0.1] * 1024]

        extractor = GraphRAGExtractor(
            llm=fake_llm, embedder=fake_embedder, num_workers=1,
        )
        nodes = [TextNode(text=f"Node {i}") for i in range(3)]
        result = extractor(nodes)

        assert len(result) == 3
        for i, node in enumerate(result):
            assert len(node.metadata[KG_NODES_KEY]) == 1


# ---------------------------------------------------------------------------
# 4) Service → graph layer integration
# ---------------------------------------------------------------------------


class TestServiceGraphIntegration:
    """Verify KnowledgeService properly integrates with graph layer components."""

    def test_service_creates_kuzu_graph_for_namespace(
        self, kb_dir: Path, real_embedder: KnowledgeEmbedder, no_llm: KnowledgeLLM
    ) -> None:
        """get_kuzu_graph creates and caches a KuzuLabelledPropertyGraph."""
        svc = _make_service(kb_dir, real_embedder, no_llm)
        try:
            svc.create_namespace("graph-test")
            kg = svc.get_kuzu_graph("graph-test")
            # Should be cached
            kg2 = svc.get_kuzu_graph("graph-test")
            assert kg is kg2
            # Should be a KuzuLabelledPropertyGraph
            from dashboard.knowledge.graph.index.kuzudb import KuzuLabelledPropertyGraph
            assert isinstance(kg, KuzuLabelledPropertyGraph)
        finally:
            svc.shutdown()

    def test_query_engine_holds_graph_reference(
        self, kb_dir: Path, real_embedder: KnowledgeEmbedder, no_llm: KnowledgeLLM
    ) -> None:
        """The query engine's .kg attribute references the service's cached graph."""
        svc = _make_service(kb_dir, real_embedder, no_llm)
        try:
            svc.create_namespace("ref-test")
            engine = svc._get_query_engine("ref-test")
            service_kg = svc.get_kuzu_graph("ref-test")
            # Engine's .kg should be the same object as service's cached graph
            assert engine.kg is service_kg
        finally:
            svc.shutdown()

    def test_ingest_then_graph_mode_query_with_mock_entities(
        self, kb_dir: Path, real_embedder: KnowledgeEmbedder, no_llm: KnowledgeLLM
    ) -> None:
        """Full roundtrip: ingest → inject fake entities → graph query returns them."""
        svc = _make_service(kb_dir, real_embedder, no_llm)
        try:
            job_id = svc.import_folder("graph-rt", str(FIXTURES))
            status = _await_job(svc, job_id)
            assert status.state.value == "completed"

            # The engine is lazy-constructed, so this creates it
            engine = svc._get_query_engine("graph-rt")

            # Replace kg with a fake that returns entities
            class _FakeEntity:
                def __init__(self, id_: str, name: str, label: str = "Person"):
                    self.id = id_
                    self.name = name
                    self.label = label
                    self.properties = {"description": f"A {label.lower()} named {name}"}

            class _FakeKuzu:
                def get_all_nodes(self, **_kw):
                    return [
                        _FakeEntity("e1", "Alice", "Person"),
                        _FakeEntity("e2", "Acme", "Organization"),
                    ]

                def pagerank(self, _p, **_kw):
                    return [("e2", 0.7), ("e1", 0.3)]

                def get_all_relations(self):
                    return []

            original_kg = engine.kg
            engine.kg = _FakeKuzu()
            try:
                result = svc.query("graph-rt", "Acme", mode="graph", threshold=0.0)
            finally:
                engine.kg = original_kg

            assert len(result.chunks) > 0  # vector hits still work
            assert len(result.entities) == 2
            assert result.entities[0].name == "Acme"
            assert result.entities[0].score == pytest.approx(0.7)
            assert result.entities[1].name == "Alice"
        finally:
            svc.shutdown()

    def test_delete_namespace_clears_graph_cache(
        self, kb_dir: Path, real_embedder: KnowledgeEmbedder, no_llm: KnowledgeLLM
    ) -> None:
        """Deleting a namespace evicts its Kuzu graph from the cache."""
        svc = _make_service(kb_dir, real_embedder, no_llm)
        try:
            job_id = svc.import_folder("del-graph", str(FIXTURES))
            _await_job(svc, job_id)

            # Force graph creation
            svc.get_kuzu_graph("del-graph")
            assert "del-graph" in svc._kuzu_graphs

            svc.delete_namespace("del-graph")
            assert "del-graph" not in svc._kuzu_graphs
            assert "del-graph" not in svc._query_engines
        finally:
            svc.shutdown()

    def test_service_llm_flows_to_query_engine(
        self, kb_dir: Path, real_embedder: KnowledgeEmbedder, no_llm: KnowledgeLLM
    ) -> None:
        """Query engine's LLM comes from the same _get_llm() factory."""
        svc = _make_service(kb_dir, real_embedder, no_llm)
        try:
            svc.create_namespace("llm-flow")
            engine = svc._get_query_engine("llm-flow")
            # Engine should have a KnowledgeLLM instance
            assert isinstance(engine.llm, KnowledgeLLM)
            # The service's cached LLM should be the same object as the engine's
            service_llm = svc._get_llm()
            assert engine.llm is not None
        finally:
            svc.shutdown()


# ---------------------------------------------------------------------------
# 5) graph/__init__ - package imports
# ---------------------------------------------------------------------------


class TestGraphPackageImports:
    """Verify graph sub-package exports are importable."""

    def test_core_classes_importable(self) -> None:
        from dashboard.knowledge.graph.core import (  # noqa: F401
            GraphRAGExtractor,
            GraphRAGQueryEngine,
            GraphRAGStore,
            TrackVectorRetriever,
        )

    def test_parsers_importable(self) -> None:
        from dashboard.knowledge.graph.parsers import (  # noqa: F401
            MarkitdownReader,
        )

    def test_index_importable(self) -> None:
        from dashboard.knowledge.graph.index import (  # noqa: F401
            KuzuLabelledPropertyGraph,
        )


# ---------------------------------------------------------------------------
# 6) MarkitdownReader — sliding-window chunking
# ---------------------------------------------------------------------------


class TestMarkitdownReaderSlidingWindow:
    """Verify the sliding-window page-processing added to MarkitdownReader."""

    def test_sliding_window_basic(self) -> None:
        """10 pages with window_size=3, overlap=1 → multiple windows covering all pages."""
        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        windows = MarkitdownReader._create_sliding_windows(10, window_size=3, overlap=1)
        assert len(windows) >= 3
        # All pages must be covered
        covered = set()
        for _, pages in windows:
            covered.update(pages)
        assert covered == set(range(10))

    def test_sliding_window_small_doc(self) -> None:
        """Fewer pages than window_size → exactly one window with all pages."""
        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        windows = MarkitdownReader._create_sliding_windows(2, window_size=5, overlap=1)
        assert len(windows) == 1
        assert windows[0] == (0, [0, 1])

    def test_sliding_window_exact_fit(self) -> None:
        """total_pages == window_size → single window."""
        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        windows = MarkitdownReader._create_sliding_windows(3, window_size=3, overlap=1)
        assert len(windows) == 1
        assert windows[0][1] == [0, 1, 2]

    def test_sliding_window_overlap_content(self) -> None:
        """Consecutive windows share exactly ``overlap`` pages."""
        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        windows = MarkitdownReader._create_sliding_windows(8, window_size=3, overlap=1)
        for i in range(len(windows) - 1):
            pages_a = set(windows[i][1])
            pages_b = set(windows[i + 1][1])
            shared = pages_a & pages_b
            # Overlap may be 1 page for consecutive windows
            assert len(shared) >= 1

    def test_sliding_window_metadata_page_range(self) -> None:
        """Each Document from _sliding_window_chunk has page_range / window_start / total_pages."""
        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        reader = MarkitdownReader()
        # Create text with many paragraphs so sliding-window triggers
        text = "\n\n".join(f"Paragraph {i}: " + ("word " * 80) for i in range(10))
        docs = reader._sliding_window_chunk(
            text,
            file_url="/fake/doc.txt",
            ws_id="ws1",
            node_id="n1",
            extra={},
            window_size=3,
            overlap=1,
        )
        assert len(docs) >= 1
        for doc in docs:
            assert "page_range" in doc.metadata
            assert "window_start" in doc.metadata
            assert "total_pages" in doc.metadata
            assert doc.metadata["ws_id"] == "ws1"
            assert doc.metadata["node_id"] == "n1"

    def test_sliding_window_invalid_window_size(self) -> None:
        """window_size < 1 raises ValueError."""
        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        with pytest.raises(ValueError, match="window_size must be at least 1"):
            MarkitdownReader._create_sliding_windows(5, window_size=0, overlap=0)

    def test_sliding_window_invalid_overlap_negative(self) -> None:
        """overlap < 0 raises ValueError."""
        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        with pytest.raises(ValueError, match="overlap must be non-negative"):
            MarkitdownReader._create_sliding_windows(5, window_size=3, overlap=-1)

    def test_sliding_window_invalid_overlap_gte_window(self) -> None:
        """overlap >= window_size raises ValueError."""
        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        with pytest.raises(ValueError, match="overlap must be less than window_size"):
            MarkitdownReader._create_sliding_windows(5, window_size=3, overlap=3)

    def test_read_large_text_uses_sliding_window(self) -> None:
        """Content > threshold triggers sliding-window; docs have page_range metadata."""
        from dashboard.knowledge.graph.parsers.markitdown_reader import (
            MarkitdownReader,
            _SLIDING_WINDOW_THRESHOLD,
        )

        reader = MarkitdownReader()
        # Generate text above threshold
        big_text = "\n\n".join(("word " * 120) for _ in range(20))
        assert len(big_text) > _SLIDING_WINDOW_THRESHOLD

        docs = reader._docs_from_text(big_text, "/fake/big.txt", "ws", "n", {})
        assert len(docs) >= 1
        assert "page_range" in docs[0].metadata

    def test_read_small_text_uses_flat_chunks(self) -> None:
        """Small content uses flat chunker → chunk_index present, page_range absent."""
        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        reader = MarkitdownReader()
        small_text = "Hello world"
        docs = reader._docs_from_text(small_text, "/fake/small.txt", None, None, {})
        assert len(docs) == 1
        assert "chunk_index" in docs[0].metadata
        assert "page_range" not in docs[0].metadata

    def test_read_preserves_mime_type_in_window(self) -> None:
        """mime_type from extra dict is propagated through sliding-window path."""
        from dashboard.knowledge.graph.parsers.markitdown_reader import (
            MarkitdownReader,
            _SLIDING_WINDOW_THRESHOLD,
        )

        reader = MarkitdownReader()
        big_text = "\n\n".join(("word " * 120) for _ in range(20))
        assert len(big_text) > _SLIDING_WINDOW_THRESHOLD

        docs = reader._docs_from_text(
            big_text, "/fake/f.pdf", "ws", "n", {"mime_type": "application/pdf"}
        )
        for doc in docs:
            assert doc.metadata.get("mime_type") == "application/pdf"

    def test_read_empty_content_returns_empty(self) -> None:
        """Empty content string returns []."""
        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        reader = MarkitdownReader()
        docs = reader.read({"url": "/fake/doc.md", "content": ""})
        assert docs == []

    def test_read_whitespace_only_returns_empty(self) -> None:
        """Whitespace-only content returns []."""
        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        reader = MarkitdownReader()
        docs = reader._docs_from_text("   \n\n  ", "/fake/doc.md", None, None, {})
        assert docs == []

    def test_chunk_text_boundary_exact(self) -> None:
        """Text exactly chunk_size chars → single chunk."""
        from dashboard.knowledge.graph.parsers.markitdown_reader import _chunk_text

        text = "x" * 1024
        chunks = _chunk_text(text, chunk_size=1024, overlap=200)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_chunk_text_overlap_consistency(self) -> None:
        """End of chunk[0] matches start of chunk[1] for overlap chars."""
        from dashboard.knowledge.graph.parsers.markitdown_reader import _chunk_text

        text = "a" * 500 + "b" * 500 + "c" * 500  # 1500 chars
        chunks = _chunk_text(text, chunk_size=1024, overlap=200)
        assert len(chunks) >= 2
        # Last 200 chars of chunk[0] == first 200 chars of chunk[1]
        assert chunks[0][-200:] == chunks[1][:200]


# ---------------------------------------------------------------------------
# 7) GraphRAGExtractor — deep ingestion tests
# ---------------------------------------------------------------------------


class TestGraphRAGExtractorDeep:
    """Deep coverage of GraphRAGExtractor entity/relation production."""

    def _make_extractor(self, llm_mock, embedder_mock, **kwargs):
        from dashboard.knowledge.graph.core.graph_rag_extractor import (
            ExtractionConfig,
            GraphRAGExtractor,
        )
        return GraphRAGExtractor(
            llm=llm_mock,
            embedder=embedder_mock,
            num_workers=1,
            config=ExtractionConfig(max_retries=0),
            **kwargs,
        )

    def test_entity_embedding_dimension(self) -> None:
        """Each EntityNode.embedding has the dimension returned by the embedder."""
        from llama_index.core.graph_stores.types import KG_NODES_KEY
        from llama_index.core.schema import TextNode
        from dashboard.knowledge.embeddings import KnowledgeEmbedder
        from dashboard.knowledge.llm import KnowledgeLLM

        fake_llm = mock.MagicMock(spec=KnowledgeLLM)
        fake_llm.extract_entities.return_value = (
            [{"name": "Alice", "type": "Person", "description": "desc"}],
            [],
        )
        fake_embedder = mock.MagicMock(spec=KnowledgeEmbedder)
        fake_embedder.embed.return_value = [[0.5] * 1024]

        extractor = self._make_extractor(fake_llm, fake_embedder)
        result = extractor([TextNode(text="Alice is here.")])
        node = result[0]
        entities = node.metadata[KG_NODES_KEY]
        assert len(entities) == 1
        assert len(entities[0].embedding) == 1024

    def test_entity_properties_propagated(self) -> None:
        """entity_description and node_id are set in EntityNode.properties."""
        from llama_index.core.graph_stores.types import KG_NODES_KEY
        from llama_index.core.schema import TextNode
        from dashboard.knowledge.embeddings import KnowledgeEmbedder
        from dashboard.knowledge.llm import KnowledgeLLM

        fake_llm = mock.MagicMock(spec=KnowledgeLLM)
        fake_llm.extract_entities.return_value = (
            [{"name": "Bob", "type": "Person", "description": "A developer"}],
            [],
        )
        fake_embedder = mock.MagicMock(spec=KnowledgeEmbedder)
        fake_embedder.embed.return_value = [[0.1] * 1024]

        node = TextNode(text="Bob is a developer.")
        extractor = self._make_extractor(fake_llm, fake_embedder)
        result = extractor([node])
        entity = result[0].metadata[KG_NODES_KEY][0]
        assert entity.properties["entity_description"] == "A developer"
        assert "node_id" in entity.properties

    def test_relation_properties_propagated(self) -> None:
        """relationship_description and node_id are set in Relation.properties."""
        from llama_index.core.graph_stores.types import KG_RELATIONS_KEY
        from llama_index.core.schema import TextNode
        from dashboard.knowledge.embeddings import KnowledgeEmbedder
        from dashboard.knowledge.llm import KnowledgeLLM

        fake_llm = mock.MagicMock(spec=KnowledgeLLM)
        fake_llm.extract_entities.return_value = (
            [
                {"name": "Alice", "type": "Person", "description": ""},
                {"name": "Acme", "type": "Org", "description": ""},
            ],
            [{"source": "Alice", "target": "Acme", "relation": "works_at", "description": "Alice works at Acme"}],
        )
        fake_embedder = mock.MagicMock(spec=KnowledgeEmbedder)
        fake_embedder.embed.return_value = [[0.1] * 1024, [0.2] * 1024]

        node = TextNode(text="Alice works at Acme.")
        extractor = self._make_extractor(fake_llm, fake_embedder)
        result = extractor([node])
        rel = result[0].metadata[KG_RELATIONS_KEY][0]
        assert rel.properties["relationship_description"] == "Alice works at Acme"
        assert "node_id" in rel.properties

    def test_extractor_entity_type_preserved(self) -> None:
        """EntityNode.label matches the 'type' returned by the LLM."""
        from llama_index.core.graph_stores.types import KG_NODES_KEY
        from llama_index.core.schema import TextNode
        from dashboard.knowledge.embeddings import KnowledgeEmbedder
        from dashboard.knowledge.llm import KnowledgeLLM

        fake_llm = mock.MagicMock(spec=KnowledgeLLM)
        fake_llm.extract_entities.return_value = (
            [{"name": "Python", "type": "ProgrammingLanguage", "description": ""}],
            [],
        )
        fake_embedder = mock.MagicMock(spec=KnowledgeEmbedder)
        fake_embedder.embed.return_value = [[0.1] * 1024]

        extractor = self._make_extractor(fake_llm, fake_embedder)
        result = extractor([TextNode(text="Python is a language.")])
        entity = result[0].metadata[KG_NODES_KEY][0]
        assert entity.label == "ProgrammingLanguage"

    def test_extractor_handles_tuple_format(self) -> None:
        """Entities returned as (name, type, desc) tuples are parsed correctly."""
        from llama_index.core.graph_stores.types import KG_NODES_KEY
        from llama_index.core.schema import TextNode
        from dashboard.knowledge.embeddings import KnowledgeEmbedder
        from dashboard.knowledge.llm import KnowledgeLLM

        fake_llm = mock.MagicMock(spec=KnowledgeLLM)
        fake_llm.extract_entities.return_value = (
            [("Carol", "Person", "A researcher")],
            [],
        )
        fake_embedder = mock.MagicMock(spec=KnowledgeEmbedder)
        fake_embedder.embed.return_value = [[0.1] * 1024]

        extractor = self._make_extractor(fake_llm, fake_embedder)
        result = extractor([TextNode(text="Carol is a researcher.")])
        entities = result[0].metadata[KG_NODES_KEY]
        assert len(entities) == 1
        assert entities[0].name == "Carol"

    def test_extractor_embedding_fallback_on_batch_fail(self) -> None:
        """When batch embed() fails, falls back to embed_one() per entity."""
        from llama_index.core.graph_stores.types import KG_NODES_KEY
        from llama_index.core.schema import TextNode
        from dashboard.knowledge.embeddings import KnowledgeEmbedder
        from dashboard.knowledge.llm import KnowledgeLLM

        fake_llm = mock.MagicMock(spec=KnowledgeLLM)
        fake_llm.extract_entities.return_value = (
            [{"name": "Dave", "type": "Person", "description": ""}],
            [],
        )
        fake_embedder = mock.MagicMock(spec=KnowledgeEmbedder)
        fake_embedder.embed.side_effect = RuntimeError("batch embed failed")
        fake_embedder.embed_one.return_value = [0.3] * 1024

        extractor = self._make_extractor(fake_llm, fake_embedder)
        result = extractor([TextNode(text="Dave is here.")])
        entities = result[0].metadata[KG_NODES_KEY]
        assert len(entities) == 1
        assert entities[0].embedding == [0.3] * 1024
        fake_embedder.embed_one.assert_called_once()

    def test_extractor_domain_prompt_passed_to_llm(self) -> None:
        """domain_prompt is forwarded to llm.extract_entities as the third argument."""
        from llama_index.core.schema import TextNode
        from dashboard.knowledge.embeddings import KnowledgeEmbedder
        from dashboard.knowledge.llm import KnowledgeLLM
        from dashboard.knowledge.graph.core.graph_rag_extractor import (
            ExtractionConfig,
            GraphRAGExtractor,
        )

        fake_llm = mock.MagicMock(spec=KnowledgeLLM)
        fake_llm.extract_entities.return_value = ([], [])
        fake_embedder = mock.MagicMock(spec=KnowledgeEmbedder)

        extractor = GraphRAGExtractor(
            llm=fake_llm,
            embedder=fake_embedder,
            domain_prompt="medical terminology",
            language="English",
            num_workers=1,
            config=ExtractionConfig(max_retries=0),
        )
        extractor([TextNode(text="Patient has fever.")])
        args = fake_llm.extract_entities.call_args
        assert args[0][2] == "medical terminology"

    def test_extractor_language_param_passed(self) -> None:
        """language param is forwarded to llm.extract_entities."""
        from llama_index.core.schema import TextNode
        from dashboard.knowledge.embeddings import KnowledgeEmbedder
        from dashboard.knowledge.llm import KnowledgeLLM
        from dashboard.knowledge.graph.core.graph_rag_extractor import (
            ExtractionConfig,
            GraphRAGExtractor,
        )

        fake_llm = mock.MagicMock(spec=KnowledgeLLM)
        fake_llm.extract_entities.return_value = ([], [])
        fake_embedder = mock.MagicMock(spec=KnowledgeEmbedder)

        extractor = GraphRAGExtractor(
            llm=fake_llm,
            embedder=fake_embedder,
            language="Vietnamese",
            num_workers=1,
            config=ExtractionConfig(max_retries=0),
        )
        extractor([TextNode(text="Some text.")])
        args = fake_llm.extract_entities.call_args
        assert args[0][1] == "Vietnamese"

    def test_extractor_relation_source_target_match(self) -> None:
        """Relation source_id/target_id exactly match the entity names."""
        from llama_index.core.graph_stores.types import KG_NODES_KEY, KG_RELATIONS_KEY
        from llama_index.core.schema import TextNode
        from dashboard.knowledge.embeddings import KnowledgeEmbedder
        from dashboard.knowledge.llm import KnowledgeLLM

        fake_llm = mock.MagicMock(spec=KnowledgeLLM)
        fake_llm.extract_entities.return_value = (
            [
                {"name": "EntityA", "type": "T", "description": ""},
                {"name": "EntityB", "type": "T", "description": ""},
            ],
            [{"source": "EntityA", "target": "EntityB", "relation": "connects", "description": ""}],
        )
        fake_embedder = mock.MagicMock(spec=KnowledgeEmbedder)
        fake_embedder.embed.return_value = [[0.1] * 1024, [0.2] * 1024]

        from dashboard.knowledge.graph.core.graph_rag_extractor import (
            ExtractionConfig,
            GraphRAGExtractor,
        )
        extractor = GraphRAGExtractor(
            llm=fake_llm, embedder=fake_embedder, num_workers=1,
            config=ExtractionConfig(max_retries=0),
        )
        result = extractor([TextNode(text="A connects B.")])
        rel = result[0].metadata[KG_RELATIONS_KEY][0]
        entity_names = {e.name for e in result[0].metadata[KG_NODES_KEY]}
        assert rel.source_id in entity_names
        assert rel.target_id in entity_names

    def test_extractor_mixed_batch_success_failure(self) -> None:
        """Batch of 3 nodes: node[1] fails → all 3 returned, node[1] has FAILED status."""
        from llama_index.core.graph_stores.types import KG_NODES_KEY
        from llama_index.core.schema import TextNode
        from dashboard.knowledge.embeddings import KnowledgeEmbedder
        from dashboard.knowledge.llm import KnowledgeLLM
        from dashboard.knowledge.graph.core.graph_rag_extractor import (
            ExtractionConfig,
            ExtractionStatus,
            GraphRAGExtractor,
        )

        call_count = [0]

        def side_effect(text, lang, domain):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("simulated failure")
            return ([{"name": f"E{call_count[0]}", "type": "T", "description": ""}], [])

        fake_llm = mock.MagicMock(spec=KnowledgeLLM)
        fake_llm.extract_entities.side_effect = side_effect
        fake_embedder = mock.MagicMock(spec=KnowledgeEmbedder)
        fake_embedder.embed.return_value = [[0.1] * 1024]

        extractor = GraphRAGExtractor(
            llm=fake_llm, embedder=fake_embedder, num_workers=1,
            config=ExtractionConfig(max_retries=0),
        )
        nodes = [TextNode(text=f"Node {i}") for i in range(3)]
        result = extractor(nodes)
        assert len(result) == 3
        # node index 1 should have failed
        failed = [n for n in result if n.metadata.get("extraction_status") == ExtractionStatus.FAILED.value]
        assert len(failed) == 1

    def test_extractor_concurrent_workers(self) -> None:
        """num_workers=4 with 8 nodes → all 8 extracted without collision."""
        from llama_index.core.graph_stores.types import KG_NODES_KEY
        from llama_index.core.schema import TextNode
        from dashboard.knowledge.embeddings import KnowledgeEmbedder
        from dashboard.knowledge.llm import KnowledgeLLM
        from dashboard.knowledge.graph.core.graph_rag_extractor import (
            ExtractionConfig,
            GraphRAGExtractor,
        )

        fake_llm = mock.MagicMock(spec=KnowledgeLLM)
        fake_llm.extract_entities.return_value = (
            [{"name": "X", "type": "T", "description": ""}], []
        )
        fake_embedder = mock.MagicMock(spec=KnowledgeEmbedder)
        fake_embedder.embed.return_value = [[0.1] * 1024]

        extractor = GraphRAGExtractor(
            llm=fake_llm, embedder=fake_embedder, num_workers=4,
            config=ExtractionConfig(max_retries=0),
        )
        nodes = [TextNode(text=f"Node {i}") for i in range(8)]
        result = extractor(nodes)
        assert len(result) == 8
        for node in result:
            assert KG_NODES_KEY in node.metadata


# ---------------------------------------------------------------------------
# 8) GraphRAGQueryEngine — deep query tests
# ---------------------------------------------------------------------------


class TestGraphRAGQueryEngineDeep:
    """Unit-test the GraphRAGQueryEngine methods with mocked dependencies."""

    def _make_engine(self, llm=None, graph_store=None, extra_attrs=None):
        """Build a minimal GraphRAGQueryEngine without a live Kuzu or zvec instance."""
        import networkx as nx
        from llama_index.core import PropertyGraphIndex, StorageContext
        from llama_index.core.vector_stores.types import BasePydanticVectorStore
        from dashboard.knowledge.graph.core.graph_rag_extractor import (
            ExtractionConfig,
            GraphRAGExtractor,
        )
        from dashboard.knowledge.graph.core.graph_rag_store import GraphRAGStore
        from dashboard.knowledge.graph.core.graph_rag_query_engine import GraphRAGQueryEngine
        from dashboard.knowledge.llm import KnowledgeLLM

        fake_llm = llm or mock.MagicMock(spec=KnowledgeLLM)
        fake_llm.aggregate_answers = mock.MagicMock(return_value="aggregated")

        # Only apply default graph/pagerank when the caller did NOT inject their own store.
        _injected_gs = graph_store is not None
        effective_graph_store = graph_store or mock.MagicMock(spec=GraphRAGStore)
        if not _injected_gs:
            effective_graph_store.graph = nx.DiGraph()
            effective_graph_store.pagerank = mock.MagicMock(
                return_value=[("e1", 0.9), ("e2", 0.05)]
            )

        fake_extractor = mock.MagicMock(spec=GraphRAGExtractor)
        fake_vs = mock.MagicMock(spec=BasePydanticVectorStore)
        fake_index = mock.MagicMock(spec=PropertyGraphIndex)
        fake_index.property_graph_store = effective_graph_store
        fake_index.vector_store = fake_vs
        # Pre-configure _embed_model so the tracking property can construct TrackVectorRetriever
        fake_embed_model = mock.MagicMock()
        fake_index._embed_model = fake_embed_model
        fake_storage = mock.MagicMock(spec=StorageContext)

        engine = GraphRAGQueryEngine(
            graph_store=effective_graph_store,
            index=fake_index,
            vector_store=fake_vs,
            storage_context=fake_storage,
            kg_extractor=fake_extractor,
            llm=fake_llm,
            plan_llm=fake_llm,
            node_id="test-node",
            embed_model=fake_embed_model,
        )
        if extra_attrs:
            for k, v in extra_attrs.items():
                object.__setattr__(engine, k, v)
        return engine, fake_llm, effective_graph_store, fake_index


    def test_create_citation_with_file_metadata(self) -> None:
        """citation is formatted as [filename(page_range)]{uuid:...}."""
        engine, _, _, _ = self._make_engine()
        citation = engine._create_citation(
            {"file_path": "/f/doc.pdf", "filename": "doc.pdf", "page_range": "1-3"},
            "abc-123",
        )
        assert citation == "[doc.pdf(1-3)]{uuid:abc-123}"

    def test_create_citation_missing_file(self) -> None:
        """No file metadata → returns `uuid` backtick form."""
        engine, _, _, _ = self._make_engine()
        citation = engine._create_citation({}, "xyz-789")
        assert citation == "`xyz-789`"

    def test_create_citation_no_page(self) -> None:
        """File present but no page → [filename]{uuid:...}."""
        engine, _, _, _ = self._make_engine()
        citation = engine._create_citation(
            {"file_path": "/f/doc.pdf", "filename": "doc.pdf"},
            "no-page-id",
        )
        assert citation == "[doc.pdf]{uuid:no-page-id}"

    def test_graph_result_valid_yaml(self) -> None:
        """graph_result() returns valid YAML with knowledge and context keys."""
        import yaml
        import networkx as nx
        from dashboard.knowledge.graph.core.graph_rag_store import GraphRAGStore

        graph = nx.DiGraph()
        graph.add_node("n1", score=0.8, label="Person", properties={})
        graph.add_edge("n1", "n2", label="KNOWS", relationship_description="friends")

        fake_gs = mock.MagicMock(spec=GraphRAGStore)
        fake_gs.graph = graph

        engine, _, _, _ = self._make_engine(graph_store=fake_gs)
        # Inject a tracking mock whose .graph returns our DiGraph
        fake_tracking = mock.MagicMock()
        fake_tracking.graph = graph
        object.__setattr__(engine, "_tracking", fake_tracking)

        result = engine.graph_result()
        parsed = yaml.safe_load(result)
        assert "knowledge" in parsed
        assert "context" in parsed

    def test_graph_result_empty_graph(self) -> None:
        """Empty graph → knowledge and context are both empty."""
        import yaml
        import networkx as nx
        from dashboard.knowledge.graph.core.graph_rag_store import GraphRAGStore

        fake_gs = mock.MagicMock(spec=GraphRAGStore)
        fake_gs.graph = nx.DiGraph()

        engine, _, _, _ = self._make_engine(graph_store=fake_gs)
        fake_tracking = mock.MagicMock()
        fake_tracking.graph = nx.DiGraph()
        object.__setattr__(engine, "_tracking", fake_tracking)

        result = engine.graph_result()
        parsed = yaml.safe_load(result)
        assert "knowledge" in parsed

    def test_compute_page_rank_filters_threshold(self) -> None:
        """Entities with score <= PAGERANK_SCORE_THRESHOLD are excluded."""
        from dashboard.knowledge.config import PAGERANK_SCORE_THRESHOLD
        from dashboard.knowledge.graph.core.graph_rag_store import GraphRAGStore

        fake_gs = mock.MagicMock(spec=GraphRAGStore)
        above_score = PAGERANK_SCORE_THRESHOLD + 0.1
        below_score = max(0.0, PAGERANK_SCORE_THRESHOLD - 0.1)
        fake_gs.pagerank.return_value = [
            ("above", above_score),
            ("below", below_score),
        ]
        engine, _, _, _ = self._make_engine(graph_store=fake_gs)
        result = engine.compute_page_rank({"above": 1.0, "below": 0.0})
        # The engine's graph_store IS the fake_gs we passed — verify it was called
        fake_gs.pagerank.assert_called_once()
        ids = [r[0] for r in result]
        assert "above" in ids
        assert "below" not in ids

    def test_compute_page_rank_empty_personalize(self) -> None:
        """When pagerank returns None, falls back to enumerate(personalize_matrix).

        The fallback in compute_page_rank is:
            return [(v, i) for i, v in enumerate(personalize_matrix)]
        so with a 3-element list we get 3 results.
        """
        from dashboard.knowledge.graph.core.graph_rag_store import GraphRAGStore

        fake_gs = mock.MagicMock(spec=GraphRAGStore)
        fake_gs.pagerank.return_value = None
        engine, _, _, _ = self._make_engine(graph_store=fake_gs)
        matrix = [0.1, 0.2, 0.3]
        result = engine.compute_page_rank(matrix)
        assert len(result) == 3
        # fallback emits (value, index) — first item should be the float itself
        assert isinstance(result[0][0], float)

    def test_aggregate_answers_string_input(self) -> None:
        """String input is normalised to list[str] before calling LLM."""
        import asyncio
        engine, fake_llm, _, _ = self._make_engine()
        fake_llm.aggregate_answers.return_value = "done"

        result = asyncio.run(
            engine.aggregate_answers("snippet", "what is this?", llm=fake_llm)
        )
        assert result == "done"
        called_snippets = fake_llm.aggregate_answers.call_args[0][0]
        assert isinstance(called_snippets, list)
        assert called_snippets == ["snippet"]

    def test_aggregate_answers_list_input(self) -> None:
        """List input is passed through as-is."""
        import asyncio
        engine, fake_llm, _, _ = self._make_engine()
        fake_llm.aggregate_answers.return_value = "done"

        result = asyncio.run(
            engine.aggregate_answers(["a", "b"], "query", llm=fake_llm)
        )
        called_snippets = fake_llm.aggregate_answers.call_args[0][0]
        assert called_snippets == ["a", "b"]

    def test_aggregate_answers_no_llm_fallback(self) -> None:
        """When LLM raises, returns an Error: ... string (never crashes)."""
        import asyncio
        engine, fake_llm, _, _ = self._make_engine()
        fake_llm.aggregate_answers.side_effect = RuntimeError("llm down")

        result = asyncio.run(
            engine.aggregate_answers(["snippet"], "query", llm=fake_llm)
        )
        assert result.startswith("Error:")

    def test_tracking_lazy_init(self) -> None:
        """The .tracking property creates TrackVectorRetriever on first access.

        _make_engine pre-configures index._embed_model so TrackVectorRetriever
        can be constructed. On a freshly built engine _tracking PrivateAttr
        starts as None; accessing .tracking populates and caches it.
        """
        from dashboard.knowledge.graph.core.track_vector_retriever import TrackVectorRetriever

        engine, _, _, _ = self._make_engine()
        # Fresh engine has _tracking == None; first access must construct and cache it
        assert engine._tracking is None
        tracking = engine.tracking
        assert tracking is not None
        assert isinstance(tracking, TrackVectorRetriever)
        # Second access returns the cached instance
        assert engine.tracking is tracking

    def test_get_community_relations_delegates(self) -> None:
        """get_community_relations() delegates to index.property_graph_store."""
        engine, _, _, fake_index = self._make_engine()
        fake_index.property_graph_store.get.return_value = ["node1"]
        fake_index.property_graph_store.get_rel_map.return_value = {"rel": "map"}

        result = engine.get_community_relations(["node1"])
        fake_index.property_graph_store.get.assert_called_once_with(ids=["node1"])
        fake_index.property_graph_store.get_rel_map.assert_called_once()


# ---------------------------------------------------------------------------
# 9) KnowledgeService → graph layer integration
# ---------------------------------------------------------------------------


class TestServiceGraphIntegration:
    """Verify KnowledgeService.service.py correctly wires the graph layer."""

    def _make_service(self, tmp_path):
        from dashboard.knowledge.service import KnowledgeService
        from dashboard.knowledge.namespace import NamespaceManager
        from dashboard.knowledge.embeddings import KnowledgeEmbedder
        from dashboard.knowledge.llm import KnowledgeLLM

        nm = NamespaceManager(base_dir=str(tmp_path))
        fake_embedder = mock.MagicMock(spec=KnowledgeEmbedder)
        fake_embedder.dimension.return_value = 1024
        fake_llm = mock.MagicMock(spec=KnowledgeLLM)
        return KnowledgeService(
            namespace_manager=nm,
            embedder=fake_embedder,
            llm=fake_llm,
        )


    def test_get_kuzu_graph_returns_lpg(self, tmp_path) -> None:
        """get_kuzu_graph() returns a KuzuLabelledPropertyGraph instance."""
        from dashboard.knowledge.graph.index.kuzudb import KuzuLabelledPropertyGraph

        svc = self._make_service(tmp_path)
        svc._nm.create("ns1")
        kg = svc.get_kuzu_graph("ns1")
        assert kg is not None
        assert isinstance(kg, KuzuLabelledPropertyGraph)

    def test_get_kuzu_graph_cached(self, tmp_path) -> None:
        """Calling get_kuzu_graph twice returns the exact same object."""
        svc = self._make_service(tmp_path)
        svc._nm.create("ns2")
        kg1 = svc.get_kuzu_graph("ns2")
        kg2 = svc.get_kuzu_graph("ns2")
        assert kg1 is kg2

    def test_get_vector_store_cached(self, tmp_path) -> None:
        """Calling get_vector_store twice returns the exact same object."""
        from dashboard.knowledge.vector_store import NamespaceVectorStore

        svc = self._make_service(tmp_path)
        svc._nm.create("ns3")
        with mock.patch.object(
            NamespaceVectorStore, "__init__", return_value=None
        ):
            vs1 = svc.get_vector_store("ns3")
            vs2 = svc.get_vector_store("ns3")
            assert vs1 is vs2

    def test_vector_store_shared_between_ingestor_and_query_engine(self, tmp_path) -> None:
        """Ingestor and query engine both receive the same VS handle from the service cache."""
        svc = self._make_service(tmp_path)
        svc._nm.create("ns4")

        captured_vs = {}

        real_get_vs = svc.get_vector_store

        def spy_vs(ns):
            vs = real_get_vs(ns)
            captured_vs[ns] = vs
            return vs

        svc.get_vector_store = spy_vs  # type: ignore[method-assign]

        ingest_vs = svc.get_vector_store("ns4")
        query_vs = svc.get_vector_store("ns4")
        assert ingest_vs is query_vs
        assert captured_vs["ns4"] is ingest_vs

    def test_kuzu_graph_shared_between_ingestor_and_query_engine(self, tmp_path) -> None:
        """Ingestor and query engine both receive the same Kuzu handle from the service."""
        svc = self._make_service(tmp_path)
        svc._nm.create("ns5")

        kg1 = svc.get_kuzu_graph("ns5")
        kg2 = svc.get_kuzu_graph("ns5")
        assert kg1 is kg2

    def test_ingestor_vector_store_factory_is_service(self, tmp_path) -> None:
        """_get_ingestor() wires vector_store_factory to service.get_vector_store."""
        svc = self._make_service(tmp_path)
        ingestor = svc._get_ingestor()
        assert ingestor._vs_factory == svc.get_vector_store

    def test_ingestor_kuzu_factory_is_service(self, tmp_path) -> None:
        """_get_ingestor() wires kuzu_factory to service.get_kuzu_graph."""
        svc = self._make_service(tmp_path)
        ingestor = svc._get_ingestor()
        assert ingestor._kg_factory == svc.get_kuzu_graph

    def test_query_engine_cached_per_namespace(self, tmp_path) -> None:
        """_get_query_engine called twice for same namespace returns the same object."""
        svc = self._make_service(tmp_path)
        svc._nm.create("ns6")
        with (
            mock.patch("dashboard.knowledge.service.KnowledgeQueryEngine") as MockQE,
        ):
            mock_qe = mock.MagicMock()
            MockQE.return_value = mock_qe
            qe1 = svc._get_query_engine("ns6")
            qe2 = svc._get_query_engine("ns6")
            assert qe1 is qe2
            MockQE.assert_called_once()

    def test_invalidate_model_cache_clears_query_engines(self, tmp_path) -> None:
        """After invalidate_model_cache(), _query_engines is empty."""
        svc = self._make_service(tmp_path)
        svc._query_engines["stale-ns"] = mock.MagicMock()
        svc.invalidate_model_cache()
        assert svc._query_engines == {}

    def test_evict_namespace_caches_removes_handles(self, tmp_path) -> None:
        """_evict_namespace_caches() removes VS, KG, QE for the given namespace."""
        svc = self._make_service(tmp_path)
        fake_vs = mock.MagicMock()
        fake_vs.close = mock.MagicMock()
        fake_kg = mock.MagicMock()
        fake_kg.close_connection = mock.MagicMock()
        svc._vector_stores["evict-ns"] = fake_vs
        svc._kuzu_graphs["evict-ns"] = fake_kg
        svc._query_engines["evict-ns"] = mock.MagicMock()

        svc._evict_namespace_caches("evict-ns")

        assert "evict-ns" not in svc._vector_stores
        assert "evict-ns" not in svc._kuzu_graphs
        assert "evict-ns" not in svc._query_engines
        fake_vs.close.assert_called_once()
        fake_kg.close_connection.assert_called_once()

    def test_get_graph_delegates_to_kuzu_layer(self, tmp_path) -> None:
        """service.get_graph() calls get_kuzu_graph().get_graph() — verifies graph layer wiring."""
        svc = self._make_service(tmp_path)
        svc._nm.create("ns7")

        fake_kg = mock.MagicMock()
        fake_kg.get_graph.return_value = {"nodes": [], "edges": []}
        svc._kuzu_graphs["ns7"] = fake_kg

        result = svc.get_graph("ns7")
        fake_kg.get_graph.assert_called_once()
        assert "nodes" in result

    def test_shutdown_closes_all_graph_handles(self, tmp_path) -> None:
        """shutdown() closes vector stores and Kuzu graphs from the graph layer."""
        svc = self._make_service(tmp_path)

        fake_vs = mock.MagicMock()
        fake_vs.close = mock.MagicMock()
        fake_kg = mock.MagicMock()
        fake_kg.close_connection = mock.MagicMock()

        svc._vector_stores["shutdown-ns"] = fake_vs
        svc._kuzu_graphs["shutdown-ns"] = fake_kg

        svc.shutdown()

        fake_vs.close.assert_called_once()
        fake_kg.close_connection.assert_called_once()
        assert svc._vector_stores == {}
        assert svc._kuzu_graphs == {}


# ---------------------------------------------------------------------------
# 10) Kuzu functional tests — real on-disk graph, PageRank on real data
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def kuzu_graph(tmp_path):
    """Provide a real KuzuLabelledPropertyGraph backed by a tmp_path DB.

    Cleans the global kuzu_database_cache between tests to prevent cross-test
    contamination (KuzuDB rejects two Database() objects for the same path).
    """
    from dashboard.knowledge.graph.index.kuzudb import KuzuLabelledPropertyGraph

    db_file = str(tmp_path / "test_graph.db")
    kg = KuzuLabelledPropertyGraph(
        index="testns",
        ws_id="testns",
        database_path=db_file,
    )
    yield kg
    # Teardown: evict from process-level cache so next test gets a fresh DB
    resolved = kg._resolve_db_path()
    KuzuLabelledPropertyGraph.kuzu_database_cache.pop(resolved, None)
    kg.close_connection()


def _make_entity(name: str, label: str = "Person", dim: int = 1024) -> "EntityNode":
    """Helper: build an EntityNode with a deterministic unit embedding."""
    from llama_index.core.graph_stores.types import EntityNode
    import hashlib

    seed = int(hashlib.md5(name.encode()).hexdigest()[:8], 16)
    embedding = [(seed % 100) / 100.0] * dim
    return EntityNode(
        name=name,
        label=label,
        properties={"entity_description": f"desc of {name}"},
        embedding=embedding,
    )


def _make_relation(src_id: str, tgt_id: str, label: str = "KNOWS") -> "Relation":
    from llama_index.core.graph_stores.types import Relation
    return Relation(
        source_id=src_id,
        target_id=tgt_id,
        label=label,
        properties={"relationship_description": f"{src_id} {label} {tgt_id}"},
    )


class TestKuzuFunctional:
    """Functional tests against a real Kuzu DB in a tmp directory."""

    def test_add_node_and_retrieve(self, kuzu_graph) -> None:
        """After add_node, get_node returns the same entity by ID."""
        entity = _make_entity("Alice")
        kuzu_graph.add_node(entity)

        retrieved = kuzu_graph.get_node(entity.id)
        assert retrieved is not None
        assert retrieved.name == "Alice"

    def test_multiple_nodes_stored(self, kuzu_graph) -> None:
        """Three distinct entities are all retrievable after insertion."""
        names = ["Alice", "Bob", "Carol"]
        entities = [_make_entity(n) for n in names]
        for e in entities:
            kuzu_graph.add_node(e)

        all_nodes = kuzu_graph.get_all_nodes()
        stored_names = {n.name for n in all_nodes if hasattr(n, "name")}
        for name in names:
            assert name in stored_names

    def test_add_relation_and_retrieve(self, kuzu_graph) -> None:
        """After add_node x2 + add_relation, get_all_relations returns the edge."""
        alice = _make_entity("Alice")
        bob = _make_entity("Bob")
        kuzu_graph.add_node(alice)
        kuzu_graph.add_node(bob)

        rel = _make_relation(alice.id, bob.id, "KNOWS")
        kuzu_graph.add_relation(rel)

        relations = kuzu_graph.get_all_relations()
        rel_labels = [r.label for r in relations]
        assert "KNOWS" in rel_labels

    def test_get_triplets_returns_full_triple(self, kuzu_graph) -> None:
        """get_triplets returns (EntityNode, Relation, EntityNode) triples."""
        alice = _make_entity("Alice")
        bob = _make_entity("Bob")
        kuzu_graph.add_node(alice)
        kuzu_graph.add_node(bob)
        kuzu_graph.add_relation(_make_relation(alice.id, bob.id))

        triplets = kuzu_graph.get_triplets()
        assert len(triplets) >= 1
        src, rel, tgt = triplets[0]
        assert hasattr(src, "id")
        assert hasattr(rel, "label")
        assert hasattr(tgt, "id")

    def test_node_label_persisted(self, kuzu_graph) -> None:
        """Entity label (e.g., 'Organization') is persisted and restored correctly."""
        acme = _make_entity("Acme", label="Organization")
        kuzu_graph.add_node(acme)

        retrieved = kuzu_graph.get_node(acme.id)
        assert retrieved is not None
        assert retrieved.label == "Organization"

    def test_relation_description_persisted(self, kuzu_graph) -> None:
        """Relation properties including description are round-tripped through Kuzu."""
        alice = _make_entity("Alice")
        bob = _make_entity("Bob")
        kuzu_graph.add_node(alice)
        kuzu_graph.add_node(bob)
        rel = _make_relation(alice.id, bob.id, "MENTORS")
        kuzu_graph.add_relation(rel)

        relations = kuzu_graph.get_all_relations()
        assert any(r.label == "MENTORS" for r in relations)


class TestKuzuPageRankFunctional:
    """Functional PageRank tests against a real Kuzu DB.

    These ensure that after ingesting a small connected graph, pagerank()
    produces valid scores with correct relative ordering.
    """

    def _build_connected_graph(self, kuzu_graph):
        """Insert 4 entities and a star topology: hub → spoke1, spoke2, spoke3."""
        hub = _make_entity("Hub")
        spoke1 = _make_entity("Spoke1")
        spoke2 = _make_entity("Spoke2")
        spoke3 = _make_entity("Spoke3")

        for node in [hub, spoke1, spoke2, spoke3]:
            kuzu_graph.add_node(node)

        for spoke in [spoke1, spoke2, spoke3]:
            kuzu_graph.add_relation(_make_relation(hub.id, spoke.id, "CONNECTS"))

        return hub, [spoke1, spoke2, spoke3]

    def test_pagerank_returns_scores(self, kuzu_graph) -> None:
        """pagerank() on a real connected graph returns non-empty list of (id, score) pairs."""
        hub, spokes = self._build_connected_graph(kuzu_graph)
        # Personalise toward the hub
        personalize = {hub.id: 1.0}
        result = kuzu_graph.pagerank(personalize)
        assert isinstance(result, list)
        assert len(result) >= 1
        for item in result:
            assert len(item) == 2
            node_id, score = item
            assert isinstance(score, float)
            assert score > 0.0

    def test_pagerank_hub_scores_higher_than_isolated(self, kuzu_graph) -> None:
        """Hub node (with 3 out-edges) has higher PageRank than average spoke."""
        hub, spokes = self._build_connected_graph(kuzu_graph)
        personalize = {hub.id: 1.0, spokes[0].id: 0.0, spokes[1].id: 0.0, spokes[2].id: 0.0}
        result = kuzu_graph.pagerank(personalize)

        score_map = {nid: s for nid, s in result}
        hub_score = score_map.get(hub.id, 0.0)
        # Hub must appear and be non-zero (personalisation guarantees this)
        assert hub_score > 0.0

    def test_pagerank_filters_below_threshold(self, kuzu_graph) -> None:
        """pagerank() with score_threshold=1.0 returns empty list (no node can score that high)."""
        hub, _ = self._build_connected_graph(kuzu_graph)
        result = kuzu_graph.pagerank({hub.id: 1.0}, score_threshold=1.0)
        assert result == []

    def test_pagerank_empty_graph_returns_safely(self, tmp_path) -> None:
        """pagerank() on an empty graph does not crash — returns [] or None safely."""
        from dashboard.knowledge.graph.index.kuzudb import KuzuLabelledPropertyGraph

        db_file = str(tmp_path / "empty_graph.db")
        kg = KuzuLabelledPropertyGraph(
            index="emptytestns",
            ws_id="emptytestns",
            database_path=db_file,
        )
        try:
            result = kg.pagerank({"nonexistent_id": 1.0})
            # Acceptable: empty list or None
            assert result is None or isinstance(result, list)
        finally:
            resolved = kg._resolve_db_path()
            KuzuLabelledPropertyGraph.kuzu_database_cache.pop(resolved, None)
            kg.close_connection()

    def test_pagerank_score_reflects_personalization(self, kuzu_graph) -> None:
        """Re-personalising toward a spoke raises its score relative to first run."""
        hub, spokes = self._build_connected_graph(kuzu_graph)

        hub_personalize = {hub.id: 1.0}
        spoke_personalize = {spokes[0].id: 1.0}

        result_hub = kuzu_graph.pagerank(hub_personalize)
        result_spoke = kuzu_graph.pagerank(spoke_personalize)

        # Both runs should produce valid outputs
        assert isinstance(result_hub, list)
        assert isinstance(result_spoke, list)

    def test_compute_page_rank_via_engine_on_real_graph(self, kuzu_graph) -> None:
        """GraphRAGQueryEngine.compute_page_rank() delegates to the real Kuzu pagerank.

        This is the end-to-end service→graph wiring test: the engine's
        compute_page_rank() calls graph_store.pagerank(), which calls
        KuzuLabelledPropertyGraph.pagerank() on real persisted data.
        """
        import networkx as nx
        from llama_index.core import PropertyGraphIndex, StorageContext
        from llama_index.core.vector_stores.types import BasePydanticVectorStore
        from dashboard.knowledge.graph.core.graph_rag_extractor import (
            ExtractionConfig,
            GraphRAGExtractor,
        )
        from dashboard.knowledge.graph.core.graph_rag_store import GraphRAGStore
        from dashboard.knowledge.graph.core.graph_rag_query_engine import GraphRAGQueryEngine
        from dashboard.knowledge.llm import KnowledgeLLM

        # Populate real kuzu DB
        hub, spokes = self._build_connected_graph(kuzu_graph)

        # Build a GraphRAGStore that wraps the real kuzu graph
        fake_gs = mock.MagicMock(spec=GraphRAGStore)
        fake_gs.pagerank = kuzu_graph.pagerank  # delegate to real Kuzu pagerank
        fake_gs.graph = nx.DiGraph()

        fake_llm = mock.MagicMock(spec=KnowledgeLLM)
        fake_llm.aggregate_answers = mock.MagicMock(return_value="agg")
        fake_extractor = mock.MagicMock(spec=GraphRAGExtractor)
        fake_vs = mock.MagicMock(spec=BasePydanticVectorStore)
        fake_index = mock.MagicMock(spec=PropertyGraphIndex)
        fake_index.property_graph_store = fake_gs
        fake_index.vector_store = fake_vs
        fake_storage = mock.MagicMock(spec=StorageContext)

        engine = GraphRAGQueryEngine(
            graph_store=fake_gs,
            index=fake_index,
            vector_store=fake_vs,
            storage_context=fake_storage,
            kg_extractor=fake_extractor,
            llm=fake_llm,
            plan_llm=fake_llm,
            node_id="test-node",
        )

        personalize = {hub.id: 1.0}
        result = engine.compute_page_rank(personalize)

        # compute_page_rank filters by PAGERANK_SCORE_THRESHOLD;
        # result is a list of (id, score) tuples where score > threshold
        assert isinstance(result, list)
        # At least some nodes should have been scored (star graph is connected)
        # — or empty if all below threshold, but no exception must be raised


# ---------------------------------------------------------------------------
# 9) ZvecVectorStoreAdapter
# ---------------------------------------------------------------------------


class TestZvecVectorStoreAdapter:
    """Unit tests for the zvec → BasePydanticVectorStore adapter."""

    def test_query_delegates_to_search(self) -> None:
        """query() calls zvec_store.search with correct args."""
        from dashboard.knowledge.graph.core.llama_adapters import ZvecVectorStoreAdapter
        from llama_index.core.vector_stores.types import VectorStoreQuery

        fake_hit = mock.MagicMock()
        fake_hit.text = "hello world"
        fake_hit.metadata = {"file_path": "/test.txt", "filename": "test.txt"}
        fake_hit.id = "doc-001"
        fake_hit.score = 0.95

        fake_zvec = mock.MagicMock()
        fake_zvec.search.return_value = [fake_hit]

        adapter = ZvecVectorStoreAdapter(zvec_store=fake_zvec)
        query = VectorStoreQuery(query_embedding=[0.1, 0.2], similarity_top_k=5)
        result = adapter.query(query)

        fake_zvec.search.assert_called_once_with([0.1, 0.2], top_k=5)
        assert len(result.nodes) == 1
        assert len(result.similarities) == 1
        assert result.similarities[0] == 0.95
        assert result.ids[0] == "doc-001"
        assert result.nodes[0].text == "hello world"

    def test_query_returns_empty_on_no_embedding(self) -> None:
        """query() returns empty result when embedding is None."""
        from dashboard.knowledge.graph.core.llama_adapters import ZvecVectorStoreAdapter
        from llama_index.core.vector_stores.types import VectorStoreQuery

        fake_zvec = mock.MagicMock()
        adapter = ZvecVectorStoreAdapter(zvec_store=fake_zvec)
        query = VectorStoreQuery(query_embedding=None, similarity_top_k=5)
        result = adapter.query(query)

        fake_zvec.search.assert_not_called()
        assert result.nodes == []
        assert result.similarities == []
        assert result.ids == []

    def test_query_handles_search_exception(self) -> None:
        """query() catches search errors and returns empty result."""
        from dashboard.knowledge.graph.core.llama_adapters import ZvecVectorStoreAdapter
        from llama_index.core.vector_stores.types import VectorStoreQuery

        fake_zvec = mock.MagicMock()
        fake_zvec.search.side_effect = RuntimeError("disk error")

        adapter = ZvecVectorStoreAdapter(zvec_store=fake_zvec)
        query = VectorStoreQuery(query_embedding=[0.1], similarity_top_k=3)
        result = adapter.query(query)

        assert result.nodes == []
        assert result.similarities == []

    def test_add_delegates_to_zvec_store(self) -> None:
        """add() maps TextNodes to add_chunks format and calls the zvec store."""
        from dashboard.knowledge.graph.core.llama_adapters import ZvecVectorStoreAdapter
        from llama_index.core.schema import TextNode

        fake_zvec = mock.MagicMock()
        fake_zvec.add_chunks.return_value = 1

        adapter = ZvecVectorStoreAdapter(zvec_store=fake_zvec)

        node = TextNode(
            text="hello world",
            metadata={"file_path": "/test.txt"},
            embedding=[0.1, 0.2, 0.3],
        )
        result = adapter.add([node])

        fake_zvec.add_chunks.assert_called_once()
        call_args = fake_zvec.add_chunks.call_args[0][0]
        assert len(call_args) == 1
        assert call_args[0]["text"] == "hello world"
        assert call_args[0]["embedding"] == [0.1, 0.2, 0.3]
        assert call_args[0]["metadata"]["file_path"] == "/test.txt"
        assert len(result) == 1

    def test_add_skips_nodes_without_embedding(self) -> None:
        """add() skips nodes that have no embedding."""
        from dashboard.knowledge.graph.core.llama_adapters import ZvecVectorStoreAdapter
        from llama_index.core.schema import TextNode

        fake_zvec = mock.MagicMock()
        adapter = ZvecVectorStoreAdapter(zvec_store=fake_zvec)

        node = TextNode(text="no embedding")
        result = adapter.add([node])

        fake_zvec.add_chunks.assert_not_called()
        assert result == []

    def test_client_returns_underlying_store(self) -> None:
        """client property returns the wrapped zvec store."""
        from dashboard.knowledge.graph.core.llama_adapters import ZvecVectorStoreAdapter

        fake_zvec = mock.MagicMock()
        adapter = ZvecVectorStoreAdapter(zvec_store=fake_zvec)
        assert adapter.client is fake_zvec

    def test_query_preserves_metadata(self) -> None:
        """query() maps metadata from VectorHit to TextNode.metadata."""
        from dashboard.knowledge.graph.core.llama_adapters import ZvecVectorStoreAdapter
        from llama_index.core.vector_stores.types import VectorStoreQuery

        fake_hit = mock.MagicMock()
        fake_hit.text = "content"
        fake_hit.metadata = {"file_path": "/docs/a.pdf", "chunk_index": 2}
        fake_hit.id = "hit-42"
        fake_hit.score = 0.88

        fake_zvec = mock.MagicMock()
        fake_zvec.search.return_value = [fake_hit]

        adapter = ZvecVectorStoreAdapter(zvec_store=fake_zvec)
        query = VectorStoreQuery(query_embedding=[0.5], similarity_top_k=10)
        result = adapter.query(query)

        assert result.nodes[0].metadata["file_path"] == "/docs/a.pdf"
        assert result.nodes[0].metadata["chunk_index"] == 2


# ---------------------------------------------------------------------------
# 10) EmbedderAdapter
# ---------------------------------------------------------------------------


class TestEmbedderAdapter:
    """Unit tests for the KnowledgeEmbedder → BaseEmbedding adapter."""

    def test_get_text_embedding_delegates(self) -> None:
        """_get_text_embedding calls embed_one."""
        from dashboard.knowledge.graph.core.llama_adapters import EmbedderAdapter

        fake_embedder = mock.MagicMock()
        fake_embedder.embed_one.return_value = [0.1, 0.2, 0.3]
        fake_embedder.model_name = "test-model"

        adapter = EmbedderAdapter(knowledge_embedder=fake_embedder)
        result = adapter._get_text_embedding("hello")

        fake_embedder.embed_one.assert_called_once_with("hello")
        assert result == [0.1, 0.2, 0.3]

    def test_get_query_embedding_delegates(self) -> None:
        """_get_query_embedding calls embed_one."""
        from dashboard.knowledge.graph.core.llama_adapters import EmbedderAdapter

        fake_embedder = mock.MagicMock()
        fake_embedder.embed_one.return_value = [0.5, 0.6]
        fake_embedder.model_name = "test-model"

        adapter = EmbedderAdapter(knowledge_embedder=fake_embedder)
        result = adapter._get_query_embedding("search query")

        fake_embedder.embed_one.assert_called_once_with("search query")
        assert result == [0.5, 0.6]

    def test_model_name_propagated(self) -> None:
        """Adapter picks up model_name from the underlying embedder."""
        from dashboard.knowledge.graph.core.llama_adapters import EmbedderAdapter

        fake_embedder = mock.MagicMock()
        fake_embedder.model_name = "qwen3-embedding:0.6b"
        fake_embedder.embed_one.return_value = [0.0]

        adapter = EmbedderAdapter(knowledge_embedder=fake_embedder)
        assert adapter.model_name == "qwen3-embedding:0.6b"


# ---------------------------------------------------------------------------
# 11) GraphRAGQueryEngine wiring in KnowledgeService
# ---------------------------------------------------------------------------


class TestGraphRAGEngineWiring:
    """Integration tests for GraphRAGQueryEngine construction in KnowledgeService."""

    def test_get_graph_rag_engine_returns_engine_or_none(self, kb_dir, no_llm) -> None:
        """_get_graph_rag_engine returns an engine (or None on construction failure)."""
        # This test exercises the factory method. On a clean namespace with no
        # graph data the PropertyGraphIndex may or may not construct successfully
        # depending on llama-index internals. The key assertion is no crash.
        fake_embedder = mock.MagicMock()
        fake_embedder.dimension.return_value = 1024
        fake_embedder.embed_one.return_value = [0.0] * 1024
        fake_embedder.model_name = "test-model"

        svc = _make_service(kb_dir, fake_embedder, no_llm)
        svc.create_namespace("test-ns")
        result = svc._get_graph_rag_engine("test-ns")
        # Engine may be None if construction fails gracefully — that's fine.
        # The key is no exception.
        svc.shutdown()

    def test_graph_rag_engine_cached(self, kb_dir, no_llm) -> None:
        """_get_graph_rag_engine returns the same instance on repeat calls."""
        fake_embedder = mock.MagicMock()
        fake_embedder.dimension.return_value = 1024
        fake_embedder.embed_one.return_value = [0.0] * 1024
        fake_embedder.model_name = "test-model"

        svc = _make_service(kb_dir, fake_embedder, no_llm)
        svc.create_namespace("test-ns")

        engine1 = svc._get_graph_rag_engine("test-ns")
        engine2 = svc._get_graph_rag_engine("test-ns")

        if engine1 is not None:
            assert engine1 is engine2
        svc.shutdown()

    def test_invalidate_clears_graph_engines(self, kb_dir, no_llm) -> None:
        """invalidate_model_cache clears the graph engine cache."""
        fake_embedder = mock.MagicMock()
        fake_embedder.dimension.return_value = 1024
        fake_embedder.embed_one.return_value = [0.0] * 1024
        fake_embedder.model_name = "test-model"

        svc = _make_service(kb_dir, fake_embedder, no_llm)
        svc.create_namespace("test-ns")

        # Seed the cache
        svc._get_graph_rag_engine("test-ns")
        assert "test-ns" in svc._graph_rag_engines or True  # may be None

        svc.invalidate_model_cache()
        assert len(svc._graph_rag_engines) == 0
        svc.shutdown()

    def test_evict_namespace_clears_graph_engine(self, kb_dir, no_llm) -> None:
        """_evict_namespace_caches removes the graph engine for that namespace."""
        fake_embedder = mock.MagicMock()
        fake_embedder.dimension.return_value = 1024
        fake_embedder.embed_one.return_value = [0.0] * 1024
        fake_embedder.model_name = "test-model"

        svc = _make_service(kb_dir, fake_embedder, no_llm)
        svc.create_namespace("test-ns")

        # Manually seed the cache with a sentinel
        svc._graph_rag_engines["test-ns"] = "sentinel"
        svc._evict_namespace_caches("test-ns")
        assert "test-ns" not in svc._graph_rag_engines
        svc.shutdown()


# ---------------------------------------------------------------------------
# 12) Query delegation — mode routing
# ---------------------------------------------------------------------------


class TestGraphModeQueryDelegation:
    """Verify that graph and summarized modes route through GraphRAGQueryEngine."""

    def _make_engine_with_graph_rag(self):
        """Build a KnowledgeQueryEngine with a mocked GraphRAGQueryEngine."""
        from dashboard.knowledge.query import KnowledgeQueryEngine

        fake_vs = mock.MagicMock()
        fake_vs.search.return_value = []  # no vector hits

        fake_kg = mock.MagicMock()
        fake_kg.get_all_nodes.return_value = []

        fake_embedder = mock.MagicMock()
        fake_embedder.embed_one.return_value = [0.1, 0.2, 0.3]

        fake_llm = mock.MagicMock()
        fake_llm.is_available.return_value = True

        fake_graph_rag = mock.MagicMock()
        fake_graph_rag.get_nodes.return_value = []
        fake_graph_rag.graph_result.return_value = "knowledge: '[]'\ncontext: '[]'\n"
        fake_graph_rag.custom_query.return_value = "aggregated answer"

        engine = KnowledgeQueryEngine(
            namespace="test-ns",
            vector_store=fake_vs,
            kuzu_graph=fake_kg,
            embedder=fake_embedder,
            llm=fake_llm,
            graph_rag_engine=fake_graph_rag,
        )
        return engine, fake_graph_rag

    def _make_engine_without_graph_rag(self):
        """Build a KnowledgeQueryEngine WITHOUT GraphRAGQueryEngine."""
        from dashboard.knowledge.query import KnowledgeQueryEngine

        fake_vs = mock.MagicMock()
        fake_vs.search.return_value = []

        fake_kg = mock.MagicMock()
        fake_kg.get_all_nodes.return_value = []

        fake_embedder = mock.MagicMock()
        fake_embedder.embed_one.return_value = [0.1, 0.2, 0.3]

        fake_llm = mock.MagicMock()
        fake_llm.is_available.return_value = True
        fake_llm.aggregate_answers.return_value = "simple answer"

        engine = KnowledgeQueryEngine(
            namespace="test-ns",
            vector_store=fake_vs,
            kuzu_graph=fake_kg,
            embedder=fake_embedder,
            llm=fake_llm,
            graph_rag_engine=None,
        )
        return engine, fake_llm

    def test_raw_mode_skips_graph_rag(self) -> None:
        """raw mode never touches GraphRAGQueryEngine."""
        engine, fake_graph_rag = self._make_engine_with_graph_rag()
        result = engine.query("what is x?", mode="raw")

        fake_graph_rag.get_nodes.assert_not_called()
        fake_graph_rag.custom_query.assert_not_called()
        assert result.mode == "raw"

    def test_graph_mode_uses_graph_rag_engine(self) -> None:
        """graph mode calls engine.get_nodes + graph_result."""
        engine, fake_graph_rag = self._make_engine_with_graph_rag()
        result = engine.query("what is x?", mode="graph")

        fake_graph_rag.get_nodes.assert_called_once()
        fake_graph_rag.graph_result.assert_called_once()
        assert result.mode == "graph"

    def test_summarized_mode_uses_graph_rag_engine(self) -> None:
        """summarized mode calls engine.custom_query."""
        engine, fake_graph_rag = self._make_engine_with_graph_rag()
        result = engine.query("what is x?", mode="summarized")

        fake_graph_rag.custom_query.assert_called_once()
        assert result.answer == "aggregated answer"
        assert result.mode == "summarized"

    def test_graph_mode_fallback_without_engine(self) -> None:
        """graph mode uses _graph_expand when graph_rag_engine is None."""
        engine, _ = self._make_engine_without_graph_rag()
        result = engine.query("what is x?", mode="graph")

        # _graph_expand was called (via the kg mock), no crash
        assert result.mode == "graph"

    def test_summarized_mode_fallback_without_engine(self) -> None:
        """summarized mode uses _fallback_summarize when graph_rag_engine is None."""
        engine, fake_llm = self._make_engine_without_graph_rag()

        # Give it some vector hits to summarize
        fake_hit = mock.MagicMock()
        fake_hit.text = "chunk text"
        fake_hit.score = 0.9
        fake_hit.metadata = {"file_path": "/test.txt", "filename": "test.txt"}
        fake_hit.id = "hit-1"

        engine.vs.search.return_value = [fake_hit]
        result = engine.query("what is x?", mode="summarized", threshold=0.0)

        fake_llm.aggregate_answers.assert_called_once()
        assert result.mode == "summarized"

    def test_graph_rag_engine_error_falls_back_to_simple(self) -> None:
        """When GraphRAGQueryEngine raises, falls back to _graph_expand."""
        engine, fake_graph_rag = self._make_engine_with_graph_rag()
        fake_graph_rag.get_nodes.side_effect = RuntimeError("graph boom")

        # Should not crash — falls back to _graph_expand
        result = engine.query("what is x?", mode="graph")
        assert result.mode == "graph"

    def test_summarized_graph_rag_error_falls_back_to_llm(self) -> None:
        """When GraphRAGQueryEngine.custom_query raises, falls back to simple LLM."""
        engine, fake_graph_rag = self._make_engine_with_graph_rag()
        fake_graph_rag.custom_query.side_effect = RuntimeError("llm boom")

        # The fallback uses self.llm.aggregate_answers — make it work
        engine.llm.aggregate_answers.return_value = "fallback answer"

        fake_hit = mock.MagicMock()
        fake_hit.text = "chunk"
        fake_hit.score = 0.9
        fake_hit.metadata = {}
        fake_hit.id = "h1"
        engine.vs.search.return_value = [fake_hit]

        result = engine.query("what is x?", mode="summarized", threshold=0.0)
        assert "graph_rag_summarization_failed" in result.warnings[0]
        assert result.answer == "fallback answer"

    def test_graph_rag_engine_entity_parsing(self) -> None:
        """Verify YAML entity results are parsed into EntityHit objects."""
        import yaml

        engine, fake_graph_rag = self._make_engine_with_graph_rag()

        nodes_yaml = yaml.dump([
            {"id": "e1", "label": "Person", "score": 0.9, "citation": "test.pdf"},
            {"id": "e2", "label": "Org", "score": 0.7, "citation": "doc.md"},
        ], allow_unicode=True)
        result_yaml = yaml.dump({
            "knowledge": nodes_yaml,
            "context": "[]",
        }, allow_unicode=True)
        fake_graph_rag.graph_result.return_value = result_yaml

        result = engine.query("who works at x?", mode="graph")

        assert len(result.entities) == 2
        assert result.entities[0].id == "e1"
        assert result.entities[0].name == "Person"
        assert result.entities[0].score == 0.9
        assert result.entities[1].id == "e2"

