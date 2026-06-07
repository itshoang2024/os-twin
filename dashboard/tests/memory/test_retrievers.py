"""Unit tests for agentic_memory.retrievers module.

All external dependencies (litellm, zvec, sentence_transformers) are mocked
to ensure pure unit testing without network/disk I/O.
"""

import json
import sys
import types
import unittest
from unittest.mock import MagicMock, Mock, patch, PropertyMock


# ---------------------------------------------------------------------------
# Pre-import mocks: zvec and sentence_transformers are not installed in CI,
# so we inject lightweight stubs into sys.modules BEFORE importing the SUT.
# ---------------------------------------------------------------------------
_mock_zvec = MagicMock()
_mock_zvec.DataType = MagicMock()
_mock_zvec.DataType.STRING = "STRING"
_mock_zvec.DataType.VECTOR_FP32 = "VECTOR_FP32"
_mock_zvec.MetricType = MagicMock()
_mock_zvec.MetricType.COSINE = "COSINE"
sys.modules.setdefault("zvec", _mock_zvec)

_mock_st = MagicMock()
sys.modules.setdefault("sentence_transformers", _mock_st)

# Ensure the lazy-import globals are populated for tests
import dashboard.agentic_memory.retrievers as _retrievers_mod

_retrievers_mod._retriever_imports_done = True
_retrievers_mod.litellm = MagicMock()
_retrievers_mod.SentenceTransformer = _mock_st.SentenceTransformer
_retrievers_mod.word_tokenize = MagicMock()
_retrievers_mod.cosine_similarity = MagicMock()
_retrievers_mod.np = MagicMock()

from dashboard.agentic_memory.retrievers import (
    EMBEDDING_DIMENSION,
    GeminiEmbeddingFunction,
    OllamaEmbeddingFunction,
    SentenceTransformerEmbedding,
    VertexEmbeddingFunction,
    ZvecRetriever,
    _create_embedding_function,
    _embedding_cache,
    _embedding_cache_lock,
    _truncate_to_dim,
)


# =========================================================================
# GeminiEmbeddingFunction
# =========================================================================
class TestGeminiEmbeddingFunction(unittest.TestCase):
    """Tests for the Gemini embedding wrapper around litellm."""

    def test_init_prefixes_model_name_with_gemini(self):
        """Model names without 'gemini/' prefix get it added automatically."""
        fn = GeminiEmbeddingFunction(model_name="gemini-embedding-001")
        self.assertEqual(fn.model_name, "gemini/gemini-embedding-001")

    def test_init_keeps_existing_gemini_prefix(self):
        """Model names already prefixed with 'gemini/' are left unchanged."""
        fn = GeminiEmbeddingFunction(model_name="gemini/text-embedding-004")
        self.assertEqual(fn.model_name, "gemini/text-embedding-004")

    @patch.object(_retrievers_mod, "litellm")
    def test_call_returns_truncated_embeddings(self, mock_litellm):
        """__call__ delegates to litellm and truncates/pads to 1024."""
        # Return 1024-dim vectors — should be truncated to 1024
        mock_item = {"embedding": [0.1] * 1024}
        mock_response = MagicMock()
        mock_response.data = [mock_item]
        mock_litellm.embedding.return_value = mock_response

        fn = GeminiEmbeddingFunction(model_name="gemini/test-model")
        result = fn(["hello"])

        mock_litellm.embedding.assert_called_once_with(
            model="gemini/test-model",
            input=["hello"],
            dimensions=EMBEDDING_DIMENSION,
        )
        self.assertEqual(len(result[0]), 1024)

    def test_dimension_always_returns_1024(self):
        """dimension always returns EMBEDDING_DIMENSION regardless of model."""
        fn = GeminiEmbeddingFunction()
        self.assertEqual(fn.dimension, 1024)

        fn2 = GeminiEmbeddingFunction(model_name="gemini/unknown-model")
        self.assertEqual(fn2.dimension, 1024)


# =========================================================================
# SentenceTransformerEmbedding
# =========================================================================
class TestSentenceTransformerEmbedding(unittest.TestCase):
    """Tests for the SentenceTransformer embedding wrapper."""

    def test_init_stores_model_name_and_model_is_none(self):
        """Constructor stores the model name but does NOT load the model."""
        fn = SentenceTransformerEmbedding(model_name="my/model")
        self.assertEqual(fn._model_name, "my/model")
        self.assertIsNone(fn._model)

    @patch("dashboard.agentic_memory.retrievers.SentenceTransformerEmbedding._ensure_model")
    def test_call_truncates_to_1024(self, mock_ensure):
        """__call__ truncates output to EMBEDDING_DIMENSION."""
        mock_model = MagicMock()
        # Simulate a model that returns 1024-dim vectors
        mock_model.encode.return_value = MagicMock(tolist=lambda: [[0.1] * 1024])
        mock_ensure.return_value = mock_model

        fn = SentenceTransformerEmbedding()
        result = fn(["test"])

        self.assertEqual(len(result[0]), 1024)

    @patch("dashboard.agentic_memory.retrievers.SentenceTransformerEmbedding._ensure_model")
    def test_call_pads_short_vectors(self, mock_ensure):
        """__call__ pads vectors shorter than EMBEDDING_DIMENSION with zeros."""
        mock_model = MagicMock()
        mock_model.encode.return_value = MagicMock(tolist=lambda: [[1.0, 2.0, 3.0]])
        mock_ensure.return_value = mock_model

        fn = SentenceTransformerEmbedding()
        result = fn(["test"])

        self.assertEqual(len(result[0]), 1024)
        self.assertEqual(result[0][:3], [1.0, 2.0, 3.0])
        self.assertEqual(result[0][3], 0.0)  # padded with zeros

    def test_dimension_always_returns_1024(self):
        """dimension always returns EMBEDDING_DIMENSION regardless of model."""
        fn = SentenceTransformerEmbedding()
        self.assertEqual(fn.dimension, 1024)

        fn2 = SentenceTransformerEmbedding(model_name="all-MiniLM-L6-v2")
        self.assertEqual(fn2.dimension, 1024)

    def test_ensure_model_imports_sentence_transformer(self):
        """_ensure_model imports and instantiates SentenceTransformer."""
        fn = SentenceTransformerEmbedding(model_name="test/model")

        mock_st_class = MagicMock()
        mock_instance = MagicMock()
        mock_st_class.return_value = mock_instance

        with patch.dict("sys.modules", {"sentence_transformers": MagicMock(SentenceTransformer=mock_st_class)}):
            result = fn._ensure_model()

        self.assertIs(result, mock_instance)
        mock_st_class.assert_called_once_with("test/model")


# =========================================================================
# _create_embedding_function factory
# =========================================================================
class TestCreateEmbeddingFunction(unittest.TestCase):
    """Tests for the factory function that dispatches by backend name."""

    def setUp(self):
        # Clear singleton cache before each factory test
        with _embedding_cache_lock:
            _embedding_cache.clear()

    def test_gemini_backend_creates_gemini_function(self):
        fn = _create_embedding_function("gemini", "my-model", shared=False)
        self.assertIsInstance(fn, GeminiEmbeddingFunction)
        self.assertEqual(fn.model_name, "gemini/my-model")

    def test_sentence_transformer_backend_creates_st_function(self):
        fn = _create_embedding_function("sentence-transformer", "my/model", shared=False)
        self.assertIsInstance(fn, SentenceTransformerEmbedding)
        self.assertEqual(fn._model_name, "my/model")

    def test_unknown_backend_defaults_to_sentence_transformer(self):
        fn = _create_embedding_function("unknown-backend", "model", shared=False)
        self.assertIsInstance(fn, SentenceTransformerEmbedding)

    def test_ollama_backend_creates_ollama_function(self):
        fn = _create_embedding_function("ollama", "leoipulsar/harrier-0.6b", shared=False)
        self.assertIsInstance(fn, OllamaEmbeddingFunction)
        self.assertEqual(fn._model_name, "leoipulsar/harrier-0.6b")

    def test_vertex_backend_creates_vertex_function(self):
        fn = _create_embedding_function("vertex", "gemini-embedding-001", shared=False)
        self.assertIsInstance(fn, VertexEmbeddingFunction)
        self.assertEqual(fn._model_name, "gemini-embedding-001")


# =========================================================================
# OllamaEmbeddingFunction
# =========================================================================
class TestOllamaEmbeddingFunction(unittest.TestCase):
    """Tests for the Ollama embedding wrapper using native SDK."""

    def test_init_stores_model_name(self):
        fn = OllamaEmbeddingFunction(model_name="embeddinggemma")
        self.assertEqual(fn._model_name, "embeddinggemma")

    def test_init_default_model(self):
        fn = OllamaEmbeddingFunction()
        self.assertEqual(fn._model_name, "leoipulsar/harrier-0.6b")

    @patch.dict("sys.modules", {"ollama": MagicMock()})
    def test_call_truncates_to_1024(self):
        """__call__ should truncate 1024-dim Ollama output to 1024."""
        import sys

        mock_ollama = sys.modules["ollama"]
        mock_ollama.embed.return_value = {"embeddings": [[0.1] * 1024]}

        fn = OllamaEmbeddingFunction(model_name="leoipulsar/harrier-0.6b")
        result = fn(["hello"])

        self.assertEqual(len(result[0]), 1024)

    @patch.dict("sys.modules", {"ollama": MagicMock()})
    def test_call_pads_short_vectors(self):
        """__call__ should pad <1024-dim Ollama output to 1024."""
        import sys

        mock_ollama = sys.modules["ollama"]
        mock_ollama.embed.return_value = {"embeddings": [[0.5] * 256]}

        fn = OllamaEmbeddingFunction(model_name="small-model")
        result = fn(["hello"])

        self.assertEqual(len(result[0]), 1024)
        self.assertEqual(result[0][255], 0.5)
        self.assertEqual(result[0][256], 0.0)  # zero-padded

    def test_dimension_always_returns_1024(self):
        """dimension always returns EMBEDDING_DIMENSION regardless of model."""
        fn = OllamaEmbeddingFunction(model_name="leoipulsar/harrier-0.6b")
        self.assertEqual(fn.dimension, 1024)

        fn2 = OllamaEmbeddingFunction(model_name="embeddinggemma")
        self.assertEqual(fn2.dimension, 1024)

        fn3 = OllamaEmbeddingFunction(model_name="qwen3-embedding:0.6b")
        self.assertEqual(fn3.dimension, 1024)


# =========================================================================
# VertexEmbeddingFunction
# =========================================================================
class TestVertexEmbeddingFunction(unittest.TestCase):
    """Tests for the Vertex AI embedding wrapper using google.genai."""

    def test_init_defaults(self):
        fn = VertexEmbeddingFunction()
        self.assertEqual(fn._model_name, "gemini-embedding-001")
        self.assertEqual(fn._task_type, "RETRIEVAL_DOCUMENT")

    def test_init_custom_params(self):
        fn = VertexEmbeddingFunction(
            model_name="text-embedding-005",
            task_type="RETRIEVAL_QUERY",
        )
        self.assertEqual(fn._model_name, "text-embedding-005")
        self.assertEqual(fn._task_type, "RETRIEVAL_QUERY")

    def test_dimension_always_returns_1024(self):
        """dimension always returns EMBEDDING_DIMENSION."""
        fn = VertexEmbeddingFunction()
        self.assertEqual(fn.dimension, 1024)

        fn2 = VertexEmbeddingFunction(model_name="text-embedding-005")
        self.assertEqual(fn2.dimension, 1024)


# =========================================================================
# _truncate_to_dim helper
# =========================================================================
class TestTruncateToDim(unittest.TestCase):
    """Tests for the _truncate_to_dim utility."""

    def test_truncates_long_vectors(self):
        result = _truncate_to_dim([[0.1] * 1024])
        self.assertEqual(len(result[0]), 1024)

    def test_pads_short_vectors(self):
        result = _truncate_to_dim([[1.0, 2.0, 3.0]])
        self.assertEqual(len(result[0]), 1024)
        self.assertEqual(result[0][:3], [1.0, 2.0, 3.0])
        self.assertTrue(all(v == 0.0 for v in result[0][3:]))

    def test_exact_dimension_unchanged(self):
        vec = [0.5] * 1024
        result = _truncate_to_dim([vec])
        self.assertEqual(result[0], vec)

    def test_empty_list(self):
        self.assertEqual(_truncate_to_dim([]), [])

    def test_custom_dimension(self):
        result = _truncate_to_dim([[0.1] * 100], dim=50)
        self.assertEqual(len(result[0]), 50)


# =========================================================================
# ZvecRetriever
# =========================================================================
class TestZvecRetriever(unittest.TestCase):
    """Tests for the Zvec-backed vector retriever."""

    def _make_retriever(self, persist_dir="/tmp/test_zvec_dir", collection_name="test_col", path_exists=False):
        """Helper to create a ZvecRetriever with mocked zvec and os.path.exists."""
        with (
            patch("os.path.exists", return_value=path_exists),
            patch("os.path.join", side_effect=lambda *parts: "/".join(parts)),
        ):
            retriever = ZvecRetriever(
                collection_name=collection_name,
                model_name="test-model",
                persist_dir=persist_dir,
                embedding_backend="sentence-transformer",
            )
        return retriever

    def test_init_with_nonexistent_path_sets_collection_none(self):
        """When the collection path does not exist, collection is deferred (None)."""
        retriever = self._make_retriever(path_exists=False)
        # collection is None when path doesn't exist (deferred creation)
        self.assertIsNone(retriever.collection)

    def test_search_with_no_collection_returns_empty_structure(self):
        """search() on uninitialized collection returns empty wrapper dicts."""
        retriever = self._make_retriever(path_exists=False)
        result = retriever.search("any query")
        self.assertEqual(result, {"ids": [[]], "metadatas": [[]], "distances": [[]]})

    def test_count_with_no_collection_returns_zero(self):
        """count() on uninitialized collection returns 0."""
        retriever = self._make_retriever(path_exists=False)
        self.assertEqual(retriever.count(), 0)

    def test_delete_document_on_none_collection_no_error(self):
        """delete_document() is a no-op when collection is None."""
        retriever = self._make_retriever(path_exists=False)
        # Should not raise
        retriever.delete_document("nonexistent-id")

    def test_add_document_creates_collection_if_needed(self):
        """add_document() triggers _ensure_collection when collection is None."""
        retriever = self._make_retriever(path_exists=False)

        # Mock the embedding function to return a fixed embedding
        mock_ef = MagicMock()
        mock_ef.return_value = [[0.1, 0.2, 0.3]]
        mock_ef.dimension = 3
        retriever._embedding_function = mock_ef
        retriever._dimension = 3

        # Mock collection creation
        mock_collection = MagicMock()
        retriever._zvec.create_and_open.return_value = mock_collection

        with patch("os.makedirs"):
            retriever.add_document(
                document="test content",
                metadata={"summary": "test summary", "context": "General"},
                doc_id="doc-123",
            )

        # After add_document, _ensure_collection should have created it
        # The create_and_open mock should have been called
        retriever._zvec.create_and_open.assert_called()

    def test_search_returns_properly_formatted_results(self):
        """search() formats zvec results into the expected dict structure."""
        retriever = self._make_retriever(path_exists=False)

        # Mark collection as existing (sentinel True = exists on disk)
        retriever.collection = True

        # Mock the embedding function
        mock_ef = MagicMock()
        mock_ef.return_value = [[0.5, 0.5]]
        retriever._embedding_function = mock_ef

        # Mock the _open_ro to return a collection with query results
        mock_col = MagicMock()
        mock_doc1 = MagicMock()
        mock_doc1.id = "id-1"
        mock_doc1.score = 0.95
        mock_doc1.fields = {"metadata_json": json.dumps({"name": "Note 1", "tags": '["a","b"]'})}

        mock_doc2 = MagicMock()
        mock_doc2.id = "id-2"
        mock_doc2.score = 0.80
        mock_doc2.fields = {"metadata_json": json.dumps({"name": "Note 2"})}

        mock_col.query.return_value = [mock_doc1, mock_doc2]

        with patch.object(retriever, "_open_ro", return_value=mock_col):
            result = retriever.search("find something", k=3)

        self.assertEqual(result["ids"], [["id-1", "id-2"]])
        self.assertEqual(result["distances"], [[0.95, 0.80]])
        self.assertEqual(len(result["metadatas"][0]), 2)
        self.assertEqual(result["metadatas"][0][0]["name"], "Note 1")
        # tags should be deserialized from JSON string
        self.assertEqual(result["metadatas"][0][0]["tags"], ["a", "b"])

    def test_search_with_non_json_metadata(self):
        """search() gracefully handles non-JSON-string metadata fields."""
        retriever = self._make_retriever(path_exists=False)

        retriever.collection = True  # Mark as existing

        mock_ef = MagicMock()
        mock_ef.return_value = [[0.1]]
        retriever._embedding_function = mock_ef

        mock_col = MagicMock()
        mock_doc = MagicMock()
        mock_doc.id = "id-x"
        mock_doc.score = 0.5
        mock_doc.fields = {"metadata_json": json.dumps({"plain": "text", "num": "42"})}
        mock_col.query.return_value = [mock_doc]

        with patch.object(retriever, "_open_ro", return_value=mock_col):
            result = retriever.search("q")
        # "text" doesn't start with [ or {, so should stay a string
        self.assertEqual(result["metadatas"][0][0]["plain"], "text")
        self.assertEqual(result["metadatas"][0][0]["num"], "42")

    def test_embedding_function_property_lazy_creates(self):
        """The embedding_function property creates the function on first access."""
        retriever = self._make_retriever(path_exists=False)
        retriever._embedding_backend = "sentence-transformer"
        retriever._model_name = "my/model"
        retriever._embedding_function = None  # Reset to None

        # Clear cache so we get a fresh instance
        with _embedding_cache_lock:
            _embedding_cache.clear()

        ef = retriever.embedding_function
        self.assertIsInstance(ef, SentenceTransformerEmbedding)
        # Second access returns the same object
        self.assertIs(retriever.embedding_function, ef)

    def test_add_document_enhances_text_with_metadata(self):
        """add_document() appends context, keywords, and tags to the document text."""
        retriever = self._make_retriever(path_exists=False)

        embedded_texts = []

        def capture_embed(texts):
            embedded_texts.extend(texts)
            return [[0.1, 0.2]]

        mock_ef = MagicMock(side_effect=capture_embed)
        mock_ef.dimension = 2
        retriever._embedding_function = mock_ef
        retriever._dimension = 2

        # Mock _ensure_collection to set a mock collection
        mock_collection = MagicMock()
        retriever.collection = mock_collection

        with patch.object(retriever, "_open_rw", return_value=mock_collection):
            retriever.add_document(
                document="raw text",
                metadata={
                    "summary": "summary text",
                    "context": "Backend",
                    "keywords": ["db", "sql"],
                    "tags": ["#database"],
                },
                doc_id="doc-1",
            )

        # The enhanced document should contain context, keywords, and tags
        enhanced = embedded_texts[0]
        self.assertIn("summary text", enhanced)
        self.assertIn("context: Backend", enhanced)
        self.assertIn("keywords: db, sql", enhanced)
        self.assertIn("tags: #database", enhanced)

    def test_add_document_uses_summary_over_document(self):
        """When metadata has 'summary', it's used as base text, not 'document'."""
        retriever = self._make_retriever(path_exists=False)

        embedded_texts = []

        def capture_embed(texts):
            embedded_texts.extend(texts)
            return [[0.1]]

        mock_ef = MagicMock(side_effect=capture_embed)
        mock_ef.dimension = 1
        retriever._embedding_function = mock_ef
        retriever._dimension = 1

        mock_collection = MagicMock()
        retriever.collection = mock_collection

        with patch.object(retriever, "_open_rw", return_value=mock_collection):
            retriever.add_document(
                document="original long content",
                metadata={"summary": "short summary", "context": "General"},
                doc_id="d1",
            )

        # Should start with the summary, not the document
        self.assertTrue(embedded_texts[0].startswith("short summary"))

    def test_add_document_skips_general_context(self):
        """Context is not appended when it's 'General'."""
        retriever = self._make_retriever(path_exists=False)

        embedded_texts = []

        def capture_embed(texts):
            embedded_texts.extend(texts)
            return [[0.1]]

        mock_ef = MagicMock(side_effect=capture_embed)
        mock_ef.dimension = 1
        retriever._embedding_function = mock_ef
        retriever._dimension = 1

        mock_collection = MagicMock()
        retriever.collection = mock_collection

        with patch.object(retriever, "_open_rw", return_value=mock_collection):
            retriever.add_document(
                document="text",
                metadata={"context": "General"},
                doc_id="d2",
            )

        self.assertNotIn("context:", embedded_texts[0])

    def test_clear_creates_new_collection(self):
        """clear() creates a new collection."""
        retriever = self._make_retriever(path_exists=False)
        retriever._dimension = 3

        new_collection = MagicMock()
        retriever._zvec.create_and_open.return_value = new_collection

        with patch("os.makedirs"):
            retriever.clear()

        # create_and_open should create the collection
        retriever._zvec.create_and_open.assert_called()
        self.assertIs(retriever.collection, new_collection)


if __name__ == "__main__":
    unittest.main()
