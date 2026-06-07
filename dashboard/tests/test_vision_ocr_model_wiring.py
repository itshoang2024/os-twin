"""Unit tests for the vision_ocr_model and llm_model wiring through the
ingestion pipeline.

Covers:
1. ``create_openai_sync_client()`` in ``dashboard.llm_client``
2. ``Ingestor._get_markitdown_converter()`` with ``vision_ocr_model``
3. ``Ingestor._apply_llm_model_override()`` and ``_get_graph_index()`` with ``llm_model``
4. ``Ingestor._parse_file()`` passing ``llm_client``/``llm_model`` kwargs
5. ``KnowledgeService._build_graph_index()`` with ``llm_model`` kwarg
6. ``MarkitdownReader._get_markitdown()`` refactored to use ``create_openai_sync_client``
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-mock google.genai so llm_client imports cleanly
mock_google_genai = MagicMock()
mock_google_types = MagicMock()
sys.modules.setdefault("google.genai", mock_google_genai)
sys.modules.setdefault("google.genai.types", mock_google_types)

from dashboard.knowledge.ingestion import IngestOptions, Ingestor, FileEntry


# ---------------------------------------------------------------------------
# 1. create_openai_sync_client
# ---------------------------------------------------------------------------


class TestCreateOpenAISyncClient:
    """Tests for ``dashboard.llm_client.create_openai_sync_client``."""

    def test_openai_model_returns_sync_client(self):
        with patch("openai.OpenAI") as MockOpenAI:
            MockOpenAI.return_value = MagicMock()
            from dashboard.llm_client import create_openai_sync_client
            result = create_openai_sync_client("gpt-4o", api_key="sk-test")
            assert result is not None
            MockOpenAI.assert_called_once()
            call_kwargs = MockOpenAI.call_args[1]
            assert call_kwargs["api_key"] == "sk-test"

    def test_google_model_uses_gemini_endpoint(self):
        with patch("openai.OpenAI") as MockOpenAI:
            MockOpenAI.return_value = MagicMock()
            from dashboard.llm_client import create_openai_sync_client
            with patch.dict(os.environ, {"GEMINI_API_KEY": "gem-key"}, clear=False):
                result = create_openai_sync_client("gemini-2.0-flash")
            assert result is not None
            call_kwargs = MockOpenAI.call_args[1]
            assert call_kwargs["api_key"] == "gem-key"
            assert "googleapis" in (call_kwargs.get("base_url") or "")

    def test_google_vertex_model_uses_gemini_endpoint(self):
        with patch("openai.OpenAI") as MockOpenAI:
            MockOpenAI.return_value = MagicMock()
            from dashboard.llm_client import create_openai_sync_client
            with patch.dict(os.environ, {"GEMINI_API_KEY": "vtx-key"}, clear=False):
                result = create_openai_sync_client("google-vertex/gemini-2.0-flash")
            assert result is not None

    def test_ollama_model_returns_client_with_ollama_key(self):
        with patch("openai.OpenAI") as MockOpenAI:
            MockOpenAI.return_value = MagicMock()
            from dashboard.llm_client import create_openai_sync_client
            result = create_openai_sync_client("llama3.2", provider="ollama")
            assert result is not None
            call_kwargs = MockOpenAI.call_args[1]
            assert call_kwargs["api_key"] == "ollama"

    def test_no_api_key_returns_none(self):
        from dashboard.llm_client import create_openai_sync_client
        with patch("dashboard.llm_client._resolve_transport_api_key", return_value=None), \
             patch.dict(os.environ, {}, clear=False):
            for k in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"]:
                os.environ.pop(k, None)
            result = create_openai_sync_client("gpt-4o")
            assert result is None

    def test_custom_timeout_passed_through(self):
        with patch("openai.OpenAI") as MockOpenAI:
            MockOpenAI.return_value = MagicMock()
            from dashboard.llm_client import create_openai_sync_client
            create_openai_sync_client("gpt-4o", api_key="sk-test", timeout=30.0)
            call_kwargs = MockOpenAI.call_args[1]
            assert call_kwargs["timeout"] == 30.0

    def test_explicit_provider_overrides_detection(self):
        with patch("openai.OpenAI") as MockOpenAI:
            MockOpenAI.return_value = MagicMock()
            from dashboard.llm_client import create_openai_sync_client
            result = create_openai_sync_client("my-model", provider="deepseek", api_key="ds-key")
            assert result is not None

    def test_openai_import_failure_returns_none(self):
        with patch("openai.OpenAI", side_effect=ImportError("no openai")):
            from dashboard.llm_client import create_openai_sync_client
            result = create_openai_sync_client("gpt-4o", api_key="sk-test")
            assert result is None

    def test_explicit_api_key_takes_precedence(self):
        with patch("openai.OpenAI") as MockOpenAI:
            MockOpenAI.return_value = MagicMock()
            from dashboard.llm_client import create_openai_sync_client
            result = create_openai_sync_client("gpt-4o", api_key="explicit-key")
            assert result is not None
            call_kwargs = MockOpenAI.call_args[1]
            assert call_kwargs["api_key"] == "explicit-key"


# ---------------------------------------------------------------------------
# 2. Ingestor._get_markitdown_converter with vision_ocr_model
# ---------------------------------------------------------------------------


class TestGetMarkitdownConverterWithVisionModel:
    """Tests for _get_markitdown_converter accepting vision_ocr_model from IngestOptions."""

    def _make_ingestor(self) -> Ingestor:
        nm = MagicMock()
        return Ingestor(namespace_manager=nm)

    def test_vision_ocr_model_creates_sync_client(self):
        ing = self._make_ingestor()
        opts = IngestOptions(vision_ocr=True, vision_ocr_model="gemini-2.0-flash")
        mock_md = MagicMock()
        mock_md_type = MagicMock(return_value=mock_md)

        with patch("dashboard.knowledge.ingestion.VisionSlidingWindowConverter") as MockConv, \
             patch("dashboard.knowledge.graph.parsers.markitdown_reader.MarkitdownReader") as MockReader, \
             patch("dashboard.llm_client.create_openai_sync_client") as mock_create_sync:
            MockReader.return_value._get_markitdown.return_value = MagicMock()
            mock_create_sync.return_value = MagicMock()
            type(mock_md_type).return_value = mock_md_type
            MockConv.return_value = MagicMock()

            converter = ing._get_markitdown_converter(opts)
            mock_create_sync.assert_called_once_with(model="gemini-2.0-flash")

    def test_vision_ocr_model_falls_back_to_llm_model(self):
        ing = self._make_ingestor()
        opts = IngestOptions(vision_ocr=True, vision_ocr_model="", llm_model="gpt-4o")

        with patch("dashboard.knowledge.ingestion.VisionSlidingWindowConverter") as MockConv, \
             patch("dashboard.knowledge.graph.parsers.markitdown_reader.MarkitdownReader") as MockReader, \
             patch("dashboard.llm_client.create_openai_sync_client") as mock_create_sync:
            MockReader.return_value._get_markitdown.return_value = MagicMock()
            mock_create_sync.return_value = MagicMock()
            MockConv.return_value = MagicMock()

            ing._get_markitdown_converter(opts)
            mock_create_sync.assert_called_once_with(model="gpt-4o")

    def test_no_vision_model_does_not_create_sync_client(self):
        ing = self._make_ingestor()
        opts = IngestOptions(vision_ocr=True, vision_ocr_model="", llm_model="")

        with patch("dashboard.knowledge.ingestion.VisionSlidingWindowConverter") as MockConv, \
             patch("dashboard.knowledge.graph.parsers.markitdown_reader.MarkitdownReader") as MockReader, \
             patch("dashboard.llm_client.create_openai_sync_client") as mock_create_sync:
            MockReader.return_value._get_markitdown.return_value = MagicMock()
            MockConv.return_value = MagicMock()

            ing._get_markitdown_converter(opts)
            mock_create_sync.assert_not_called()

    def test_sync_client_failure_still_returns_converter(self):
        ing = self._make_ingestor()
        opts = IngestOptions(vision_ocr=True, vision_ocr_model="bad-model")

        with patch("dashboard.knowledge.ingestion.VisionSlidingWindowConverter") as MockConv, \
             patch("dashboard.knowledge.graph.parsers.markitdown_reader.MarkitdownReader") as MockReader, \
             patch("dashboard.llm_client.create_openai_sync_client", return_value=None):
            base_md = MagicMock()
            MockReader.return_value._get_markitdown.return_value = base_md
            MockConv.return_value = MagicMock()

            converter = ing._get_markitdown_converter(opts)
            assert converter is not None

    def test_vision_ocr_false_skips_converter_registration(self):
        ing = self._make_ingestor()
        opts = IngestOptions(vision_ocr=False)

        with patch("dashboard.knowledge.graph.parsers.markitdown_reader.MarkitdownReader") as MockReader:
            MockReader.return_value._get_markitdown.return_value = MagicMock()

            converter = ing._get_markitdown_converter(opts)
            assert converter is not None
            converter.register_converter.assert_not_called()

    def test_cached_converter_returned_when_model_unchanged(self):
        ing = self._make_ingestor()
        opts = IngestOptions(vision_ocr_model="gemini-2.0-flash")

        with patch("dashboard.knowledge.ingestion.VisionSlidingWindowConverter") as MockConv, \
             patch("dashboard.knowledge.graph.parsers.markitdown_reader.MarkitdownReader") as MockReader, \
             patch("dashboard.llm_client.create_openai_sync_client", return_value=MagicMock()):
            MockReader.return_value._get_markitdown.return_value = MagicMock()
            MockConv.return_value = MagicMock()

            first = ing._get_markitdown_converter(opts)
            second = ing._get_markitdown_converter(opts)
            assert first is second

    def test_cache_invalidated_when_model_changes(self):
        ing = self._make_ingestor()
        opts1 = IngestOptions(vision_ocr_model="gemini-2.0-flash")
        opts2 = IngestOptions(vision_ocr_model="gpt-4o")

        with patch("dashboard.knowledge.ingestion.VisionSlidingWindowConverter") as MockConv, \
             patch("dashboard.knowledge.graph.parsers.markitdown_reader.MarkitdownReader") as MockReader, \
             patch("dashboard.llm_client.create_openai_sync_client", return_value=MagicMock()):
            MockReader.return_value._get_markitdown.return_value = MagicMock()
            MockConv.return_value = MagicMock()

            first = ing._get_markitdown_converter(opts1)
            second = ing._get_markitdown_converter(opts2)
            assert first is not second


# ---------------------------------------------------------------------------
# 3. Ingestor._apply_llm_model_override and _get_graph_index with llm_model
# ---------------------------------------------------------------------------


class TestApplyLLMModelOverride:
    """Tests for _apply_llm_model_override and its effect on _get_graph_index."""

    def _make_ingestor(self) -> Ingestor:
        nm = MagicMock()
        ing = Ingestor(namespace_manager=nm)
        ing._graph_index_factory = MagicMock(return_value=MagicMock())
        return ing

    def test_override_stores_model(self):
        ing = self._make_ingestor()
        ing._apply_llm_model_override("gpt-4o")
        assert ing._llm_model_override == "gpt-4o"

    def test_override_clears_graph_index_cache(self):
        ing = self._make_ingestor()
        ing._graph_indexes["test-ns"] = MagicMock()
        ing._apply_llm_model_override("gpt-4o")
        assert len(ing._graph_indexes) == 0

    def test_get_graph_index_passes_llm_model_to_factory(self):
        ing = self._make_ingestor()
        ing._llm_model_override = "claude-sonnet-4-20250514"
        ing._get_graph_index("test-ns")
        ing._graph_index_factory.assert_called_once_with("test-ns", llm_model="claude-sonnet-4-20250514")

    def test_get_graph_index_no_llm_model_no_kwarg(self):
        ing = self._make_ingestor()
        ing._llm_model_override = ""
        ing._get_graph_index("test-ns")
        ing._graph_index_factory.assert_called_once_with("test-ns")

    def test_get_graph_index_caches_result(self):
        ing = self._make_ingestor()
        mock_idx = MagicMock()
        ing._graph_index_factory.return_value = mock_idx
        result1 = ing._get_graph_index("test-ns")
        result2 = ing._get_graph_index("test-ns")
        assert result1 is result2
        assert ing._graph_index_factory.call_count == 1

    def test_get_graph_index_returns_none_without_factory(self):
        ing = self._make_ingestor()
        ing._graph_index_factory = None
        assert ing._get_graph_index("test-ns") is None


# ---------------------------------------------------------------------------
# 4. Ingestor._parse_file passing llm_client/llm_model kwargs
# ---------------------------------------------------------------------------


class TestParseFilePassesVisionKwargs:
    """Tests for _parse_file passing llm_client and llm_model kwargs to converter.convert."""

    def _make_ingestor(self) -> Ingestor:
        nm = MagicMock()
        return Ingestor(namespace_manager=nm)

    def _make_file_entry(self, path: str = "/tmp/test.pdf") -> FileEntry:
        return FileEntry(
            path=path,
            size=100,
            mtime=0.0,
            extension=".pdf",
            content_hash="abc123",
        )

    def test_convert_called_with_vision_kwargs(self):
        ing = self._make_ingestor()
        ing._vision_ocr_client = MagicMock()
        ing._vision_ocr_model = "gemini-2.0-flash"

        mock_converter = MagicMock()
        mock_result = MagicMock()
        mock_result.text_content = "Extracted text"
        mock_converter.convert.return_value = mock_result
        ing._markitdown = mock_converter

        opts = IngestOptions(vision_ocr=True, vision_ocr_model="gemini-2.0-flash")
        entry = self._make_file_entry()

        with patch.object(ing, "_get_markitdown_converter", return_value=mock_converter):
            chunks = ing._parse_file(entry, opts)

        mock_converter.convert.assert_called_once()
        call_kwargs = mock_converter.convert.call_args[1]
        assert "llm_client" in call_kwargs
        assert "llm_model" in call_kwargs
        assert call_kwargs["llm_model"] == "gemini-2.0-flash"

    def test_convert_called_without_kwargs_when_no_vision_client(self):
        ing = self._make_ingestor()
        ing._vision_ocr_client = None
        ing._vision_ocr_model = ""

        mock_converter = MagicMock()
        mock_result = MagicMock()
        mock_result.text_content = "Extracted text"
        mock_converter.convert.return_value = mock_result
        ing._markitdown = mock_converter

        opts = IngestOptions(vision_ocr=True)
        entry = self._make_file_entry()

        with patch.object(ing, "_get_markitdown_converter", return_value=mock_converter):
            chunks = ing._parse_file(entry, opts)

        call_kwargs = mock_converter.convert.call_args[1]
        assert "llm_client" not in call_kwargs
        assert "llm_model" not in call_kwargs

    def test_convert_kwargs_only_include_client_when_set(self):
        ing = self._make_ingestor()
        mock_client = MagicMock()
        ing._vision_ocr_client = mock_client
        ing._vision_ocr_model = ""

        mock_converter = MagicMock()
        mock_result = MagicMock()
        mock_result.text_content = "Text"
        mock_converter.convert.return_value = mock_result
        ing._markitdown = mock_converter

        opts = IngestOptions()
        entry = self._make_file_entry()

        with patch.object(ing, "_get_markitdown_converter", return_value=mock_converter):
            ing._parse_file(entry, opts)

        call_kwargs = mock_converter.convert.call_args[1]
        assert "llm_client" in call_kwargs
        assert "llm_model" not in call_kwargs


# ---------------------------------------------------------------------------
# 5. KnowledgeService._build_graph_index with llm_model kwarg
# ---------------------------------------------------------------------------


class TestBuildGraphIndexWithLLMModel:
    """Tests for KnowledgeService._build_graph_index accepting llm_model."""

    def test_llm_model_creates_fresh_knowledge_llm(self):
        from dashboard.knowledge.service import KnowledgeService

        svc = KnowledgeService.__new__(KnowledgeService)
        svc._nm = MagicMock()
        svc._llm = MagicMock()
        svc._llm_override = None
        svc._embedder = None
        svc._embedder_override = None
        svc._ingestor = None
        svc._ingestor_override = None
        svc._job_manager = None
        svc._candidate_store = MagicMock()
        svc._evidence_store = MagicMock()
        svc._fact_store = MagicMock()

        with patch("dashboard.knowledge.service.KnowledgeService.get_kuzu_graph", return_value=MagicMock()), \
             patch("dashboard.knowledge.service.KnowledgeService.get_vector_store", return_value=MagicMock()), \
             patch("dashboard.knowledge.service.KnowledgeService.get_ontology_profile", return_value=None), \
             patch("dashboard.knowledge.service.KnowledgeService._get_embedder", return_value=MagicMock()), \
             patch("dashboard.knowledge.service.KnowledgeService._get_llm", return_value=MagicMock()), \
             patch("dashboard.knowledge.llm.KnowledgeLLM") as MockKnowledgeLLM, \
             patch("dashboard.knowledge.graph.core.graph_rag_store.GraphRAGStore", return_value=MagicMock()), \
             patch("dashboard.knowledge.graph.core.graph_rag_extractor.GraphRAGExtractor", return_value=MagicMock()), \
             patch("dashboard.knowledge.graph.core.llama_adapters.ZvecVectorStoreAdapter", return_value=MagicMock()), \
             patch("dashboard.knowledge.graph.core.llama_adapters.EmbedderAdapter", return_value=MagicMock()), \
             patch("llama_index.core.PropertyGraphIndex") as MockIndex:
            MockIndex.from_existing.return_value = MagicMock()
            MockKnowledgeLLM.return_value = MagicMock()

            svc._build_graph_index("test-ns", llm_model="gpt-4o")
            MockKnowledgeLLM.assert_called_once_with(model="gpt-4o")

    def test_no_llm_model_uses_service_default(self):
        from dashboard.knowledge.service import KnowledgeService

        svc = KnowledgeService.__new__(KnowledgeService)
        svc._nm = MagicMock()
        svc._llm = None
        svc._llm_override = None
        svc._embedder = None
        svc._embedder_override = None
        svc._ingestor = None
        svc._ingestor_override = None
        svc._job_manager = None
        svc._candidate_store = MagicMock()
        svc._evidence_store = MagicMock()
        svc._fact_store = MagicMock()

        mock_service_llm = MagicMock()
        with patch("dashboard.knowledge.service.KnowledgeService.get_kuzu_graph", return_value=MagicMock()), \
             patch("dashboard.knowledge.service.KnowledgeService.get_vector_store", return_value=MagicMock()), \
             patch("dashboard.knowledge.service.KnowledgeService.get_ontology_profile", return_value=None), \
             patch("dashboard.knowledge.service.KnowledgeService._get_embedder", return_value=MagicMock()), \
             patch("dashboard.knowledge.service.KnowledgeService._get_llm", return_value=mock_service_llm), \
             patch("dashboard.knowledge.graph.core.graph_rag_store.GraphRAGStore", return_value=MagicMock()), \
             patch("dashboard.knowledge.graph.core.graph_rag_extractor.GraphRAGExtractor", return_value=MagicMock()) as MockExtractor, \
             patch("dashboard.knowledge.graph.core.llama_adapters.ZvecVectorStoreAdapter", return_value=MagicMock()), \
             patch("dashboard.knowledge.graph.core.llama_adapters.EmbedderAdapter", return_value=MagicMock()), \
             patch("llama_index.core.PropertyGraphIndex") as MockIndex:
            MockIndex.from_existing.return_value = MagicMock()

            svc._build_graph_index("test-ns")

            MockExtractor.assert_called_once()
            extractor_kwargs = MockExtractor.call_args[1]
            assert extractor_kwargs["llm"] is mock_service_llm


# ---------------------------------------------------------------------------
# 6. MarkitdownReader._get_markitdown refactored
# ---------------------------------------------------------------------------


class TestMarkitdownReaderGetMarkitdown:
    """Tests for MarkitdownReader._get_markitdown using create_openai_sync_client."""

    def test_no_llm_model_returns_plain_markitdown(self):
        with patch("dashboard.knowledge.config.LLM_MODEL", ""):
            from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader
            reader = MarkitdownReader()
            with patch("markitdown.MarkItDown") as MockMD:
                MockMD.return_value = MagicMock()
                result = reader._get_markitdown()
                MockMD.assert_called_once_with()

    def test_with_llm_model_uses_create_openai_sync_client(self):
        with patch("dashboard.knowledge.config.LLM_MODEL", "gemini-2.0-flash"):
            from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader
            reader = MarkitdownReader()
            mock_sync = MagicMock()
            with patch("dashboard.llm_client.create_openai_sync_client", return_value=mock_sync) as mock_create, \
                 patch("markitdown.MarkItDown") as MockMD:
                MockMD.return_value = MagicMock()
                result = reader._get_markitdown()
                mock_create.assert_called_once()
                assert mock_create.call_args.kwargs["model"] == "gemini-2.0-flash"
                MockMD.assert_called_once_with(llm_client=mock_sync, llm_model="gemini-2.0-flash")

    def test_no_api_key_returns_plain_markitdown(self):
        with patch("dashboard.knowledge.config.LLM_MODEL", "gpt-4o"):
            from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader
            reader = MarkitdownReader()
            with patch("dashboard.llm_client.create_openai_sync_client", return_value=None) as mock_create, \
                 patch("markitdown.MarkItDown") as MockMD:
                MockMD.return_value = MagicMock()
                result = reader._get_markitdown()
                mock_create.assert_called_once()
                MockMD.assert_called_once_with()


# ---------------------------------------------------------------------------
# 7. IngestOptions model fields
# ---------------------------------------------------------------------------


class TestIngestOptionsFields:
    """Verify IngestOptions has the new fields with correct defaults."""

    def test_default_vision_ocr_model(self):
        opts = IngestOptions()
        assert opts.vision_ocr_model == ""

    def test_default_llm_model(self):
        opts = IngestOptions()
        assert opts.llm_model == ""

    def test_default_vision_ocr(self):
        opts = IngestOptions()
        assert opts.vision_ocr is True

    def test_custom_vision_ocr_model(self):
        opts = IngestOptions(vision_ocr_model="gemini-2.0-flash")
        assert opts.vision_ocr_model == "gemini-2.0-flash"

    def test_custom_llm_model(self):
        opts = IngestOptions(llm_model="gpt-4o")
        assert opts.llm_model == "gpt-4o"

    def test_chunk_size_default(self):
        opts = IngestOptions()
        assert opts.chunk_size == 2048

    def test_chunk_overlap_default(self):
        opts = IngestOptions()
        assert opts.chunk_overlap == 512


# ---------------------------------------------------------------------------
# 8. Ingestor.run applies llm_model override
# ---------------------------------------------------------------------------


class TestIngestorRunLLMModelOverride:
    """Tests for Ingestor.run() applying llm_model override from IngestOptions."""

    def _make_ingestor(self) -> Ingestor:
        nm = MagicMock()
        nm.get.return_value = MagicMock()
        return Ingestor(namespace_manager=nm)

    def test_run_with_llm_model_applies_override(self):
        ing = self._make_ingestor()
        opts = IngestOptions(llm_model="gpt-4o")

        with patch.object(ing, "_apply_llm_model_override") as mock_apply, \
             patch.object(ing, "_walk_folder", return_value=[]):
            try:
                ing.run("test-ns", "/tmp/fake", options=opts)
            except Exception:
                pass
            mock_apply.assert_called_once_with("gpt-4o")

    def test_run_without_llm_model_does_not_apply_override(self):
        ing = self._make_ingestor()
        opts = IngestOptions(llm_model="")

        with patch.object(ing, "_apply_llm_model_override") as mock_apply, \
             patch.object(ing, "_walk_folder", return_value=[]):
            try:
                ing.run("test-ns", "/tmp/fake", options=opts)
            except Exception:
                pass
            mock_apply.assert_not_called()
