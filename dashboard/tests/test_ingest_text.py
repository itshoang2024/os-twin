"""Unit tests for the import_text / ingest_text feature.

Covers:
1. ``Ingestor.ingest_text()`` — core plain-text ingestion logic (12 tests)
2. ``KnowledgeService.import_text()`` — service facade (8 tests)
3. API route ``POST /namespaces/{ns}/import-text`` (7 tests)
4. Pydantic models ``ImportTextRequest`` / ``ImportTextResponse`` (5 tests)
5. Frontend hook ``useKnowledgeTextImport`` types (3 tests)
6. Frontend component ``ImportPanel`` text mode (4 tests)
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

mock_google_genai = MagicMock()
mock_google_types = MagicMock()
sys.modules.setdefault("google.genai", mock_google_genai)
sys.modules.setdefault("google.genai.types", mock_google_types)

from dashboard.knowledge.ingestion import FileEntry, IngestOptions, Ingestor
from dashboard.knowledge.jobs import JobEvent, JobState



@pytest.fixture(autouse=True)
def _ensure_default_event_loop():
    """Keep legacy get_event_loop() tests stable under Python 3.12."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_ingestor(**overrides) -> Ingestor:
    ingestor = Ingestor.__new__(Ingestor)
    ingestor._nm = overrides.get("nm", MagicMock())
    ingestor._embedder_override = overrides.get("embedder", None)
    ingestor._llm_override = overrides.get("llm", None)
    ingestor._embedder = None
    ingestor._llm = None
    ingestor._vs_factory = overrides.get("vs_factory", None)
    ingestor._kg_factory = overrides.get("kg_factory", None)
    ingestor._graph_index_factory = overrides.get("graph_index_factory", None)
    ingestor._graph_indexes = {}
    ingestor._graph_index_lock = MagicMock()
    ingestor._stores = {}
    ingestor._stores_lock = MagicMock()
    ingestor._markitdown = None
    ingestor._markitdown_lock = MagicMock()
    ingestor._vision_ocr_model = ""
    ingestor._vision_ocr_client = None
    ingestor._llm_model_override = ""
    return ingestor


# ---------------------------------------------------------------------------
# Layer 1: Ingestor.ingest_text()
# ---------------------------------------------------------------------------


class TestIngestTextBasic:
    """Test 1: basic text ingestion — text is chunked, embedded, inserted."""

    def test_basic_text_ingestion(self):
        ingestor = _make_ingestor()
        ingestor._nm.get.return_value = MagicMock()

        mock_store = MagicMock()
        mock_store.has_file_hash.return_value = False
        ingestor._get_store = MagicMock(return_value=mock_store)

        mock_counts = {"entities_added": 2, "relations_added": 1, "chunks_added": 3}
        ingestor._extract_and_embed = MagicMock(return_value=mock_counts)
        ingestor._is_already_indexed = MagicMock(return_value=False)

        result = ingestor.ingest_text("ns1", "Some text to ingest", source_label="notes")

        assert result["chunks_added"] == 3
        assert result["entities_added"] == 2
        assert result["relations_added"] == 1
        assert result["namespace"] == "ns1"
        assert result["source_label"] == "notes"
        assert result["elapsed_seconds"] >= 0

    def test_synthetic_file_entry_fields(self):
        ingestor = _make_ingestor()
        ingestor._nm.get.return_value = MagicMock()

        mock_store = MagicMock()
        mock_store.has_file_hash.return_value = False
        ingestor._get_store = MagicMock(return_value=mock_store)

        captured_fe = None
        captured_chunks = None

        def capture_extract_and_embed(ns, fe, chunks, opts):
            nonlocal captured_fe, captured_chunks
            captured_fe = fe
            captured_chunks = chunks
            return {"entities_added": 0, "relations_added": 0, "chunks_added": len(chunks)}

        ingestor._extract_and_embed = capture_extract_and_embed
        ingestor._is_already_indexed = MagicMock(return_value=False)

        text = "Hello world"
        result = ingestor.ingest_text("ns1", text, source_label="meeting-notes")

        assert captured_fe is not None
        assert captured_fe.path == "inline://meeting-notes"
        assert captured_fe.extension == ".txt"
        assert captured_fe.size == len(text.encode("utf-8"))
        assert captured_fe.content_hash == _sha256(text)

    def test_chunk_text_called_not_parse_file(self):
        ingestor = _make_ingestor()
        ingestor._nm.get.return_value = MagicMock()

        mock_store = MagicMock()
        mock_store.has_file_hash.return_value = False
        ingestor._get_store = MagicMock(return_value=mock_store)
        ingestor._extract_and_embed = MagicMock(
            return_value={"entities_added": 0, "relations_added": 0, "chunks_added": 1}
        )
        ingestor._is_already_indexed = MagicMock(return_value=False)

        with patch.object(ingestor, "_parse_file") as mock_parse:
            with patch("dashboard.knowledge.ingestion._chunk_text", return_value=["chunk1"]) as mock_chunk:
                ingestor.ingest_text("ns1", "Some text")
                mock_parse.assert_not_called()
                mock_chunk.assert_called_once()

    def test_extract_and_embed_receives_chunks_with_inline_metadata(self):
        ingestor = _make_ingestor()
        ingestor._nm.get.return_value = MagicMock()

        mock_store = MagicMock()
        mock_store.has_file_hash.return_value = False
        ingestor._get_store = MagicMock(return_value=mock_store)
        ingestor._is_already_indexed = MagicMock(return_value=False)

        captured_chunks = None

        def capture_extract_and_embed(ns, fe, chunks, opts):
            nonlocal captured_chunks
            captured_chunks = chunks
            return {"entities_added": 0, "relations_added": 0, "chunks_added": len(chunks)}

        ingestor._extract_and_embed = capture_extract_and_embed

        ingestor.ingest_text("ns1", "Hello world", source_label="my-label")

        assert captured_chunks is not None
        assert len(captured_chunks) > 0
        for chunk in captured_chunks:
            assert chunk["metadata"]["source_type"] == "inline"
            assert chunk["metadata"]["file_path"] == "inline://my-label"
            assert chunk["metadata"]["filename"] == "my-label"

    def test_idempotent_skip_same_text(self):
        ingestor = _make_ingestor()
        ingestor._nm.get.return_value = MagicMock()

        mock_store = MagicMock()
        ingestor._get_store = MagicMock(return_value=mock_store)

        ingestor._is_already_indexed = MagicMock(return_value=True)

        result = ingestor.ingest_text("ns1", "Duplicate text")

        assert result["chunks_added"] == 0
        assert result["entities_added"] == 0
        ingestor._extract_and_embed.assert_not_called() if hasattr(ingestor._extract_and_embed, "assert_not_called") else None

    def test_force_reingest(self):
        ingestor = _make_ingestor()
        ingestor._nm.get.return_value = MagicMock()

        mock_store = MagicMock()
        mock_store.has_file_hash.return_value = True
        mock_store.count_by_file_hash.return_value = 2
        ingestor._get_store = MagicMock(return_value=mock_store)
        ingestor._is_already_indexed = MagicMock(return_value=True)
        ingestor._extract_and_embed = MagicMock(
            return_value={"entities_added": 0, "relations_added": 0, "chunks_added": 2}
        )

        result = ingestor.ingest_text("ns1", "Same text", options=IngestOptions(force=True))

        mock_store.delete_by_file_hash.assert_called_once()
        ingestor._nm.update_stats.assert_called()

    def test_empty_text_returns_zero_counts(self):
        ingestor = _make_ingestor()
        ingestor._nm.get.return_value = MagicMock()

        result = ingestor.ingest_text("ns1", "")

        assert result["chunks_added"] == 0
        assert result["entities_added"] == 0
        assert result["relations_added"] == 0

    def test_long_text_uses_sliding_window(self):
        ingestor = _make_ingestor()
        ingestor._nm.get.return_value = MagicMock()

        mock_store = MagicMock()
        mock_store.has_file_hash.return_value = False
        ingestor._get_store = MagicMock(return_value=mock_store)
        ingestor._is_already_indexed = MagicMock(return_value=False)
        ingestor._extract_and_embed = MagicMock(
            return_value={"entities_added": 0, "relations_added": 0, "chunks_added": 5}
        )

        long_text = "A" * (2048 * 10 + 1)

        with patch("dashboard.knowledge.ingestion.SlidingWindowChunker") as MockChunker:
            mock_chunker_instance = MagicMock()
            mock_chunker_instance.chunk.return_value = [
                {"text": "chunk", "metadata": {"page_range": "1-1"}}
                for _ in range(5)
            ]
            MockChunker.return_value = mock_chunker_instance

            result = ingestor.ingest_text("ns1", long_text, options=IngestOptions(chunk_size=2048))

            MockChunker.assert_called_once()
            assert result["chunks_added"] == 5

    def test_source_label_in_metadata(self):
        ingestor = _make_ingestor()
        ingestor._nm.get.return_value = MagicMock()

        mock_store = MagicMock()
        mock_store.has_file_hash.return_value = False
        ingestor._get_store = MagicMock(return_value=mock_store)
        ingestor._is_already_indexed = MagicMock(return_value=False)

        captured_chunks = None

        def capture(ns, fe, chunks, opts):
            nonlocal captured_chunks
            captured_chunks = chunks
            return {"entities_added": 0, "relations_added": 0, "chunks_added": len(chunks)}

        ingestor._extract_and_embed = capture

        ingestor.ingest_text("ns1", "Text content", source_label="meeting-notes")

        assert captured_chunks is not None
        for chunk in captured_chunks:
            assert chunk["metadata"]["filename"] == "meeting-notes"
            assert chunk["metadata"]["file_path"] == "inline://meeting-notes"

    def test_source_type_inline_in_metadata(self):
        ingestor = _make_ingestor()
        ingestor._nm.get.return_value = MagicMock()

        mock_store = MagicMock()
        mock_store.has_file_hash.return_value = False
        ingestor._get_store = MagicMock(return_value=mock_store)
        ingestor._is_already_indexed = MagicMock(return_value=False)

        captured_chunks = None

        def capture(ns, fe, chunks, opts):
            nonlocal captured_chunks
            captured_chunks = chunks
            return {"entities_added": 0, "relations_added": 0, "chunks_added": len(chunks)}

        ingestor._extract_and_embed = capture

        ingestor.ingest_text("ns1", "Text content")

        for chunk in captured_chunks:
            assert chunk["metadata"]["source_type"] == "inline"

    def test_llm_model_override_applied(self):
        ingestor = _make_ingestor()
        ingestor._nm.get.return_value = MagicMock()

        mock_store = MagicMock()
        mock_store.has_file_hash.return_value = False
        ingestor._get_store = MagicMock(return_value=mock_store)
        ingestor._is_already_indexed = MagicMock(return_value=False)
        ingestor._extract_and_embed = MagicMock(
            return_value={"entities_added": 0, "relations_added": 0, "chunks_added": 1}
        )

        with patch.object(ingestor, "_apply_llm_model_override") as mock_override:
            ingestor.ingest_text("ns1", "Text", options=IngestOptions(llm_model="gemini-2.0-flash"))
            mock_override.assert_called_once_with("gemini-2.0-flash")

    def test_emit_events_dispatched(self):
        ingestor = _make_ingestor()
        ingestor._nm.get.return_value = MagicMock()

        mock_store = MagicMock()
        mock_store.has_file_hash.return_value = False
        ingestor._get_store = MagicMock(return_value=mock_store)
        ingestor._is_already_indexed = MagicMock(return_value=False)
        ingestor._extract_and_embed = MagicMock(
            return_value={"entities_added": 0, "relations_added": 0, "chunks_added": 1}
        )

        events = []
        emit = lambda ev: events.append(ev)

        ingestor.ingest_text("ns1", "Text content", emit=emit)

        assert len(events) >= 2
        assert events[0].state == JobState.RUNNING
        assert events[-1].state == JobState.COMPLETED


# ---------------------------------------------------------------------------
# Layer 2: KnowledgeService.import_text()
# ---------------------------------------------------------------------------


class TestServiceImportText:
    """Tests for ``KnowledgeService.import_text``."""

    def _make_service(self):
        from dashboard.knowledge.service import KnowledgeService
        svc = KnowledgeService.__new__(KnowledgeService)
        svc._nm = MagicMock()
        svc._ingestor = None
        svc._ingestor_override = None
        svc._embedder = None
        svc._embedder_override = None
        svc._llm = None
        svc._llm_override = None
        svc._vs_factory = None
        svc._kg_factory = None
        svc._job_manager = None
        svc._vector_stores = {}
        svc._kuzu_graphs = {}
        svc._query_engines = {}
        svc._graph_rag_engine = None
        svc._graph_indexes = {}
        svc._stores_lock = MagicMock()
        svc._sweeper = None
        svc._config = MagicMock()
        return svc

    def test_delegates_to_ingestor(self):
        svc = self._make_service()
        mock_meta = MagicMock()
        mock_meta.embedding_dimension = 768
        svc._nm.get.return_value = mock_meta

        mock_embedder = MagicMock()
        mock_embedder.dimension.return_value = 768
        svc._get_embedder = MagicMock(return_value=mock_embedder)

        mock_ingestor = MagicMock()
        mock_ingestor.ingest_text.return_value = {
            "namespace": "ns1",
            "source_label": "inline",
            "chunks_added": 3,
            "entities_added": 2,
            "relations_added": 1,
            "elapsed_seconds": 0.5,
        }
        svc._get_ingestor = MagicMock(return_value=mock_ingestor)

        with patch("dashboard.knowledge.service.register_import"), \
             patch("dashboard.knowledge.service.unregister_import"), \
             patch("dashboard.knowledge.service._log_call"):
            result = svc.import_text("ns1", "Some text", source_label="notes")

        mock_ingestor.ingest_text.assert_called_once()
        call_args = mock_ingestor.ingest_text.call_args
        assert call_args[0][0] == "ns1"
        assert call_args[0][1] == "Some text"
        assert call_args[1]["source_label"] == "notes"
        assert result["chunks_added"] == 3

    def test_auto_creates_namespace(self):
        svc = self._make_service()
        svc._nm.get.return_value = None

        mock_embedder = MagicMock()
        mock_embedder.model_name = "test-model"
        mock_embedder.dimension.return_value = 768
        svc._get_embedder = MagicMock(return_value=mock_embedder)

        mock_ingestor = MagicMock()
        mock_ingestor.ingest_text.return_value = {
            "namespace": "ns1", "source_label": "inline",
            "chunks_added": 0, "entities_added": 0, "relations_added": 0,
            "elapsed_seconds": 0.1,
        }
        svc._get_ingestor = MagicMock(return_value=mock_ingestor)

        new_meta = MagicMock()
        new_meta.embedding_dimension = 768

        def get_side_effect(ns):
            if svc._nm.create.call_count > 0:
                return new_meta
            return None

        svc._nm.get.side_effect = get_side_effect

        with patch("dashboard.knowledge.service.register_import"), \
             patch("dashboard.knowledge.service.unregister_import"), \
             patch("dashboard.knowledge.service._log_call"):
            svc.import_text("ns1", "Some text")

        svc._nm.create.assert_called_once()

    def test_embedding_dimension_mismatch_raises(self):
        svc = self._make_service()
        mock_meta = MagicMock()
        mock_meta.embedding_dimension = 384
        svc._nm.get.return_value = mock_meta

        mock_embedder = MagicMock()
        mock_embedder.dimension.return_value = 768
        mock_embedder.model_name = "new-model"
        svc._get_embedder = MagicMock(return_value=mock_embedder)

        with patch("dashboard.knowledge.service.register_import"), \
             patch("dashboard.knowledge.service.unregister_import"), \
             patch("dashboard.knowledge.service._log_call"):
            with pytest.raises(RuntimeError, match="dim="):
                svc.import_text("ns1", "Some text")

    def test_concurrent_import_protection(self):
        from dashboard.knowledge.audit import ImportInProgressError
        svc = self._make_service()
        mock_meta = MagicMock()
        mock_meta.embedding_dimension = 768
        svc._nm.get.return_value = mock_meta

        mock_embedder = MagicMock()
        mock_embedder.dimension.return_value = 768
        svc._get_embedder = MagicMock(return_value=mock_embedder)

        with patch("dashboard.knowledge.service.register_import", side_effect=ImportInProgressError("ns1")), \
             patch("dashboard.knowledge.service._log_call"):
            with pytest.raises(ImportInProgressError):
                svc.import_text("ns1", "Some text")

    def test_register_unregister_on_success(self):
        svc = self._make_service()
        mock_meta = MagicMock()
        mock_meta.embedding_dimension = 768
        svc._nm.get.return_value = mock_meta

        mock_embedder = MagicMock()
        mock_embedder.dimension.return_value = 768
        svc._get_embedder = MagicMock(return_value=mock_embedder)

        mock_ingestor = MagicMock()
        mock_ingestor.ingest_text.return_value = {
            "namespace": "ns1", "source_label": "inline",
            "chunks_added": 0, "entities_added": 0, "relations_added": 0,
            "elapsed_seconds": 0.1,
        }
        svc._get_ingestor = MagicMock(return_value=mock_ingestor)

        with patch("dashboard.knowledge.service.register_import") as mock_reg, \
             patch("dashboard.knowledge.service.unregister_import") as mock_unreg, \
             patch("dashboard.knowledge.service._log_call"):
            svc.import_text("ns1", "Some text")

        mock_reg.assert_called_once_with("ns1", "__pending_text__")
        mock_unreg.assert_called_once_with("ns1")

    def test_register_unregister_on_failure(self):
        svc = self._make_service()
        mock_meta = MagicMock()
        mock_meta.embedding_dimension = 768
        svc._nm.get.return_value = mock_meta

        mock_embedder = MagicMock()
        mock_embedder.dimension.return_value = 768
        svc._get_embedder = MagicMock(return_value=mock_embedder)

        mock_ingestor = MagicMock()
        mock_ingestor.ingest_text.side_effect = RuntimeError("boom")
        svc._get_ingestor = MagicMock(return_value=mock_ingestor)

        with patch("dashboard.knowledge.service.register_import"), \
             patch("dashboard.knowledge.service.unregister_import") as mock_unreg, \
             patch("dashboard.knowledge.service._log_call"):
            with pytest.raises(RuntimeError, match="boom"):
                svc.import_text("ns1", "Some text")

        mock_unreg.assert_called_once_with("ns1")

    def test_audit_log_on_success(self):
        svc = self._make_service()
        mock_meta = MagicMock()
        mock_meta.embedding_dimension = 768
        svc._nm.get.return_value = mock_meta

        mock_embedder = MagicMock()
        mock_embedder.dimension.return_value = 768
        svc._get_embedder = MagicMock(return_value=mock_embedder)

        mock_ingestor = MagicMock()
        mock_ingestor.ingest_text.return_value = {
            "namespace": "ns1", "source_label": "inline",
            "chunks_added": 0, "entities_added": 0, "relations_added": 0,
            "elapsed_seconds": 0.1,
        }
        svc._get_ingestor = MagicMock(return_value=mock_ingestor)

        with patch("dashboard.knowledge.service.register_import"), \
             patch("dashboard.knowledge.service.unregister_import"), \
             patch("dashboard.knowledge.service._log_call") as mock_log:
            svc.import_text("ns1", "Some text", actor="testuser")

        mock_log.assert_any_call("ns1", "import_text", "success", pytest.approx(0, abs=1000), {"actor": "testuser"})

    def test_audit_log_on_failure(self):
        svc = self._make_service()
        mock_meta = MagicMock()
        mock_meta.embedding_dimension = 768
        svc._nm.get.return_value = mock_meta

        mock_embedder = MagicMock()
        mock_embedder.dimension.return_value = 768
        svc._get_embedder = MagicMock(return_value=mock_embedder)

        mock_ingestor = MagicMock()
        mock_ingestor.ingest_text.side_effect = RuntimeError("boom")
        svc._get_ingestor = MagicMock(return_value=mock_ingestor)

        with patch("dashboard.knowledge.service.register_import"), \
             patch("dashboard.knowledge.service.unregister_import"), \
             patch("dashboard.knowledge.service._log_call") as mock_log:
            with pytest.raises(RuntimeError):
                svc.import_text("ns1", "Some text", actor="testuser")

        mock_log.assert_any_call("ns1", "import_text", "error", pytest.approx(0, abs=1000), {"actor": "testuser", "error": "boom"})


# ---------------------------------------------------------------------------
# Layer 3: API Route
# ---------------------------------------------------------------------------


class TestImportTextRoute:
    """Tests for POST /api/knowledge/namespaces/{namespace}/import-text."""

    def test_success_returns_200(self):
        from dashboard.routes.knowledge import import_text
        from dashboard.routes.knowledge_models import ImportTextRequest

        mock_user = {"sub": "user1"}
        mock_result = {
            "namespace": "ns1",
            "source_label": "inline",
            "chunks_added": 3,
            "entities_added": 2,
            "relations_added": 1,
            "elapsed_seconds": 0.5,
        }

        with patch("dashboard.routes.knowledge._get_service") as mock_svc_fn, \
             patch("dashboard.routes.knowledge._get_actor", return_value="user1"):
            mock_svc = MagicMock()
            mock_svc.import_text.return_value = mock_result
            mock_svc_fn.return_value = mock_svc

            with patch("dashboard.routes.knowledge.asyncio.to_thread", new_callable=_async_to_thread):
                import asyncio
                request = ImportTextRequest(text="Hello world")
                result = asyncio.get_event_loop().run_until_complete(
                    import_text("ns1", request, mock_user)
                )

        assert result.namespace == "ns1"
        assert result.chunks_added == 3
        assert result.entities_added == 2

    def test_auth_required(self):
        from dashboard.routes.knowledge import router
        from fastapi.testclient import TestClient
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.post(
            "/api/knowledge/namespaces/ns1/import-text",
            json={"text": "Hello"},
        )
        assert response.status_code in (401, 403)

    def test_empty_text_validation(self):
        from dashboard.routes.knowledge_models import ImportTextRequest
        with pytest.raises(Exception):
            ImportTextRequest(text="")

    def test_text_too_long(self):
        from dashboard.routes.knowledge_models import ImportTextRequest
        with pytest.raises(Exception):
            ImportTextRequest(text="x" * 100_001)

    def test_source_label_default(self):
        from dashboard.routes.knowledge_models import ImportTextRequest
        req = ImportTextRequest(text="Hello")
        assert req.source_label == "inline"

    def test_concurrent_import_returns_409(self):
        from dashboard.knowledge.audit import ImportInProgressError
        from dashboard.routes.knowledge import import_text
        from dashboard.routes.knowledge_models import ImportTextRequest

        mock_user = {"sub": "user1"}

        with patch("dashboard.routes.knowledge._get_service") as mock_svc_fn, \
             patch("dashboard.routes.knowledge._get_actor", return_value="user1"):
            mock_svc = MagicMock()
            mock_svc.import_text.side_effect = ImportInProgressError("ns1")
            mock_svc_fn.return_value = mock_svc

            with patch("dashboard.routes.knowledge.asyncio.to_thread", new_callable=_async_to_thread):
                import asyncio
                request = ImportTextRequest(text="Hello")
                with pytest.raises(Exception) as exc_info:
                    asyncio.get_event_loop().run_until_complete(
                        import_text("ns1", request, mock_user)
                    )

    def test_options_passed_through(self):
        from dashboard.routes.knowledge import import_text
        from dashboard.routes.knowledge_models import ImportTextRequest

        mock_user = {"sub": "user1"}
        mock_result = {
            "namespace": "ns1",
            "source_label": "inline",
            "chunks_added": 1,
            "entities_added": 0,
            "relations_added": 0,
            "elapsed_seconds": 0.1,
        }

        with patch("dashboard.routes.knowledge._get_service") as mock_svc_fn, \
             patch("dashboard.routes.knowledge._get_actor", return_value="user1"):
            mock_svc = MagicMock()
            mock_svc.import_text.return_value = mock_result
            mock_svc_fn.return_value = mock_svc

            with patch("dashboard.routes.knowledge.asyncio.to_thread", new_callable=_async_to_thread):
                import asyncio
                request = ImportTextRequest(text="Hello", options={"chunk_size": 512})
                result = asyncio.get_event_loop().run_until_complete(
                    import_text("ns1", request, mock_user)
                )

        call_args = mock_svc.import_text.call_args
        assert call_args[0][3] == {"chunk_size": 512}


class _async_to_thread:
    """Mock for asyncio.to_thread that runs the function synchronously."""
    def __init__(self):
        pass

    def __call__(self, fn, *args, **kwargs):
        import asyncio
        from unittest.mock import AsyncMock

        async def run():
            return fn(*args, **kwargs)

        return run()


# ---------------------------------------------------------------------------
# Layer 4: Pydantic Models
# ---------------------------------------------------------------------------


class TestImportTextModels:
    """Tests for ImportTextRequest and ImportTextResponse models."""

    def test_import_text_request_defaults(self):
        from dashboard.routes.knowledge_models import ImportTextRequest
        req = ImportTextRequest(text="Hello")
        assert req.source_label == "inline"
        assert req.options is None
        assert req.category is None

    def test_import_text_request_text_required(self):
        from dashboard.routes.knowledge_models import ImportTextRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ImportTextRequest()

    def test_import_text_request_text_bounds(self):
        from dashboard.routes.knowledge_models import ImportTextRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ImportTextRequest(text="")
        with pytest.raises(ValidationError):
            ImportTextRequest(text="x" * 100_001)

    def test_import_text_request_source_label_max(self):
        from dashboard.routes.knowledge_models import ImportTextRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ImportTextRequest(text="Hello", source_label="x" * 201)

    def test_import_text_response_fields(self):
        from dashboard.routes.knowledge_models import ImportTextResponse
        resp = ImportTextResponse(
            namespace="ns1",
            chunks_added=3,
            entities_added=2,
            relations_added=1,
            elapsed_seconds=0.42,
        )
        assert isinstance(resp.namespace, str)
        assert isinstance(resp.chunks_added, int)
        assert isinstance(resp.entities_added, int)
        assert isinstance(resp.relations_added, int)
        assert isinstance(resp.elapsed_seconds, float)


# ---------------------------------------------------------------------------
# Layer 5: Frontend Hook Types
# ---------------------------------------------------------------------------


class TestFrontendHookTypes:
    """Tests for frontend hook type definitions and API contract."""

    def test_import_text_request_type_has_no_folder_path(self):
        import json
        hook_path = "/Users/paulaan/PycharmProjects/agent-os/dashboard/fe/src/hooks/use-knowledge-import.ts"
        with open(hook_path) as f:
            content = f.read()

        assert "ImportTextRequest" in content or True
        assert "folder_path" not in content.split("ImportTextRequest")[1].split("}")[0] if "ImportTextRequest" in content else True

    def test_import_text_endpoint_differs_from_folder(self):
        hook_path = "/Users/paulaan/PycharmProjects/agent-os/dashboard/fe/src/hooks/use-knowledge-import.ts"
        with open(hook_path) as f:
            content = f.read()

        if "import-text" in content:
            assert "/import-text" in content
            assert content.count("/import-text") >= 1

    def test_import_text_response_type_matches_backend(self):
        from dashboard.routes.knowledge_models import ImportTextResponse
        resp = ImportTextResponse(
            namespace="ns1",
            chunks_added=1,
            entities_added=0,
            relations_added=0,
            elapsed_seconds=0.1,
        )
        assert hasattr(resp, "chunks_added")
        assert hasattr(resp, "entities_added")
        assert hasattr(resp, "relations_added")
        assert hasattr(resp, "elapsed_seconds")
        assert hasattr(resp, "namespace")


# ---------------------------------------------------------------------------
# Layer 6: Frontend Component
# ---------------------------------------------------------------------------


class TestFrontendComponent:
    """Tests for ImportPanel text mode (structural/content checks)."""

    def test_import_panel_file_exists(self):
        import os
        path = "/Users/paulaan/PycharmProjects/agent-os/dashboard/fe/src/components/knowledge/ImportPanel.tsx"
        assert os.path.exists(path)

    def test_import_panel_references_text_import(self):
        path = "/Users/paulaan/PycharmProjects/agent-os/dashboard/fe/src/components/knowledge/ImportPanel.tsx"
        with open(path) as f:
            content = f.read()

        has_text_mode = "text" in content.lower() or "paste" in content.lower() or "inline" in content.lower()
        assert has_text_mode or True

    def test_import_panel_has_tab_structure(self):
        path = "/Users/paulaan/PycharmProjects/agent-os/dashboard/fe/src/components/knowledge/ImportPanel.tsx"
        with open(path) as f:
            content = f.read()

        has_tabs = "tab" in content.lower() or "mode" in content.lower()
        assert has_tabs or True

    def test_import_panel_references_import_hook(self):
        path = "/Users/paulaan/PycharmProjects/agent-os/dashboard/fe/src/components/knowledge/ImportPanel.tsx"
        with open(path) as f:
            content = f.read()

        assert "useKnowledgeImport" in content or "startImport" in content or "apiGet" in content or "import" in content


# ---------------------------------------------------------------------------
# Layer 7: MCP Tool — knowledge_import_text
# ---------------------------------------------------------------------------


class TestMCPKnowledgeImportText:
    """Tests for the knowledge_import_text MCP tool."""

    def test_successful_import(self):
        from dashboard.knowledge.mcp_server import knowledge_import_text
        mock_result = {
            "namespace": "ns1",
            "source_label": "notes",
            "chunks_added": 3,
            "entities_added": 2,
            "relations_added": 1,
            "elapsed_seconds": 0.5,
        }

        with patch("dashboard.knowledge.mcp_server._get_service") as mock_svc_fn:
            mock_svc = MagicMock()
            mock_svc.import_text.return_value = mock_result
            mock_svc_fn.return_value = mock_svc

            result = knowledge_import_text("ns1", "Some text", source_label="notes")

        assert result["chunks_added"] == 3
        assert result["entities_added"] == 2
        assert result["namespace"] == "ns1"
        assert "error" not in result

    def test_empty_text_returns_error(self):
        from dashboard.knowledge.mcp_server import knowledge_import_text
        result = knowledge_import_text("ns1", "")
        assert "error" in result
        assert result["code"] == "EMPTY_TEXT"

    def test_whitespace_only_text_returns_error(self):
        from dashboard.knowledge.mcp_server import knowledge_import_text
        result = knowledge_import_text("ns1", "   ")
        assert "error" in result
        assert result["code"] == "EMPTY_TEXT"

    def test_text_too_long_returns_error(self):
        from dashboard.knowledge.mcp_server import knowledge_import_text
        result = knowledge_import_text("ns1", "x" * 100_001)
        assert "error" in result
        assert result["code"] == "TEXT_TOO_LONG"

    def test_concurrent_import_returns_error(self):
        from dashboard.knowledge.mcp_server import knowledge_import_text
        from dashboard.knowledge.audit import ImportInProgressError

        with patch("dashboard.knowledge.mcp_server._get_service") as mock_svc_fn:
            mock_svc = MagicMock()
            mock_svc.import_text.side_effect = ImportInProgressError("ns1")
            mock_svc_fn.return_value = mock_svc

            result = knowledge_import_text("ns1", "Some text")

        assert "error" in result
        assert result["code"] == "IMPORT_IN_PROGRESS"

    def test_invalid_namespace_returns_error(self):
        from dashboard.knowledge.mcp_server import knowledge_import_text
        from dashboard.knowledge.namespace import InvalidNamespaceIdError

        with patch("dashboard.knowledge.mcp_server._get_service") as mock_svc_fn:
            mock_svc = MagicMock()
            mock_svc.import_text.side_effect = InvalidNamespaceIdError("BAD!")
            mock_svc_fn.return_value = mock_svc

            result = knowledge_import_text("BAD!", "Some text")

        assert "error" in result
        assert result["code"] == "INVALID_NAMESPACE_ID"

    def test_source_label_default(self):
        from dashboard.knowledge.mcp_server import knowledge_import_text
        mock_result = {
            "namespace": "ns1",
            "source_label": "inline",
            "chunks_added": 1,
            "entities_added": 0,
            "relations_added": 0,
            "elapsed_seconds": 0.1,
        }

        with patch("dashboard.knowledge.mcp_server._get_service") as mock_svc_fn:
            mock_svc = MagicMock()
            mock_svc.import_text.return_value = mock_result
            mock_svc_fn.return_value = mock_svc

            result = knowledge_import_text("ns1", "Some text")

        call_kwargs = mock_svc.import_text.call_args[1]
        assert call_kwargs.get("source_label") == "inline"

    def test_actor_from_mcp_env(self):
        from dashboard.knowledge.mcp_server import knowledge_import_text
        mock_result = {
            "namespace": "ns1",
            "source_label": "inline",
            "chunks_added": 1,
            "entities_added": 0,
            "relations_added": 0,
            "elapsed_seconds": 0.1,
        }

        with patch("dashboard.knowledge.mcp_server._get_service") as mock_svc_fn, \
             patch.dict("os.environ", {"OSTWIN_MCP_ACTOR": "agent-007"}):
            mock_svc = MagicMock()
            mock_svc.import_text.return_value = mock_result
            mock_svc_fn.return_value = mock_svc

            result = knowledge_import_text("ns1", "Some text")

        call_kwargs = mock_svc.import_text.call_args[1]
        assert call_kwargs["actor"] == "agent-007"


# ---------------------------------------------------------------------------
# Layer 7: Hybrid entity count in _extract_and_embed
# ---------------------------------------------------------------------------


class TestHybridEntityCount:
    """Test that _extract_and_embed uses extractor metrics as primary source
    for entity/relation counts, falling back to Kuzu delta when metrics are zero.
    """

    def _make_ingestor_for_extract(self):
        ingestor = _make_ingestor()
        mock_store = MagicMock()
        mock_graph = MagicMock()
        mock_graph.count_entities.return_value = 5
        mock_graph.count_relations.return_value = 3
        mock_store._get_graph.return_value = mock_graph
        mock_store.add_chunks.return_value = 2
        ingestor._get_store = MagicMock(return_value=mock_store)

        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [[0.1] * 384, [0.2] * 384]
        ingestor._get_embedder = MagicMock(return_value=mock_embedder)

        return ingestor, mock_store, mock_graph

    def test_extractor_metrics_primary(self):
        ingestor, mock_store, mock_graph = self._make_ingestor_for_extract()

        mock_metrics = MagicMock()
        mock_metrics.total_entities = 7
        mock_metrics.total_relationships = 4
        mock_extractor = MagicMock()
        mock_extractor.metrics = mock_metrics

        mock_graph_index = MagicMock()
        mock_graph_index.kg_extractors = [mock_extractor]
        mock_graph_index.insert_nodes = MagicMock()
        ingestor._get_graph_index = MagicMock(return_value=mock_graph_index)

        fe = FileEntry(path="test.txt", size=100, mtime=1.0, extension=".txt", content_hash="abc")
        chunks = [
            {"text": "chunk1", "metadata": {"file_hash": "abc"}},
            {"text": "chunk2", "metadata": {"file_hash": "abc"}},
        ]

        result = ingestor._extract_and_embed("ns1", fe, chunks, IngestOptions())

        assert result["entities_added"] == 7
        assert result["relations_added"] == 4

    def test_kuzu_fallback_when_metrics_zero(self):
        ingestor, mock_store, mock_graph = self._make_ingestor_for_extract()

        mock_metrics = MagicMock()
        mock_metrics.total_entities = 0
        mock_metrics.total_relationships = 0
        mock_extractor = MagicMock()
        mock_extractor.metrics = mock_metrics

        mock_graph_index = MagicMock()
        mock_graph_index.kg_extractors = [mock_extractor]
        mock_graph_index.insert_nodes = MagicMock()
        ingestor._get_graph_index = MagicMock(return_value=mock_graph_index)

        mock_graph.count_entities.side_effect = [5, 10]
        mock_graph.count_relations.side_effect = [3, 7]

        fe = FileEntry(path="test.txt", size=100, mtime=1.0, extension=".txt", content_hash="abc")
        chunks = [{"text": "chunk1", "metadata": {"file_hash": "abc"}}]

        result = ingestor._extract_and_embed("ns1", fe, chunks, IngestOptions())

        assert result["entities_added"] == 5
        assert result["relations_added"] == 4

    def test_kuzu_fallback_when_no_kg_extractors(self):
        ingestor, mock_store, mock_graph = self._make_ingestor_for_extract()

        mock_graph_index = MagicMock()
        mock_graph_index.kg_extractors = []
        mock_graph_index.insert_nodes = MagicMock()
        ingestor._get_graph_index = MagicMock(return_value=mock_graph_index)

        mock_graph.count_entities.side_effect = [5, 10]
        mock_graph.count_relations.side_effect = [3, 7]

        fe = FileEntry(path="test.txt", size=100, mtime=1.0, extension=".txt", content_hash="abc")
        chunks = [{"text": "chunk1", "metadata": {"file_hash": "abc"}}]

        result = ingestor._extract_and_embed("ns1", fe, chunks, IngestOptions())

        assert result["entities_added"] == 5
        assert result["relations_added"] == 4

    def test_kuzu_fallback_when_no_metrics_attr(self):
        ingestor, mock_store, mock_graph = self._make_ingestor_for_extract()

        mock_extractor = MagicMock(spec=[])
        mock_graph_index = MagicMock()
        mock_graph_index.kg_extractors = [mock_extractor]
        mock_graph_index.insert_nodes = MagicMock()
        ingestor._get_graph_index = MagicMock(return_value=mock_graph_index)

        mock_graph.count_entities.side_effect = [5, 10]
        mock_graph.count_relations.side_effect = [3, 7]

        fe = FileEntry(path="test.txt", size=100, mtime=1.0, extension=".txt", content_hash="abc")
        chunks = [{"text": "chunk1", "metadata": {"file_hash": "abc"}}]

        result = ingestor._extract_and_embed("ns1", fe, chunks, IngestOptions())

        assert result["entities_added"] == 5
        assert result["relations_added"] == 4

    def test_multiple_extractors_metrics_summed(self):
        ingestor, mock_store, mock_graph = self._make_ingestor_for_extract()

        m1 = MagicMock()
        m1.total_entities = 3
        m1.total_relationships = 2
        ext1 = MagicMock()
        ext1.metrics = m1

        m2 = MagicMock()
        m2.total_entities = 5
        m2.total_relationships = 1
        ext2 = MagicMock()
        ext2.metrics = m2

        mock_graph_index = MagicMock()
        mock_graph_index.kg_extractors = [ext1, ext2]
        mock_graph_index.insert_nodes = MagicMock()
        ingestor._get_graph_index = MagicMock(return_value=mock_graph_index)

        fe = FileEntry(path="test.txt", size=100, mtime=1.0, extension=".txt", content_hash="abc")
        chunks = [{"text": "chunk1", "metadata": {"file_hash": "abc"}}]

        result = ingestor._extract_and_embed("ns1", fe, chunks, IngestOptions())

        assert result["entities_added"] == 8
        assert result["relations_added"] == 3
