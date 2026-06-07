"""Unit tests for agentic_memory.retrievers.

These tests target the current centralized embedding implementation. External
dependencies such as zvec are mocked so the suite stays pure unit-level.
"""

import json
import sys
import unittest
from unittest.mock import MagicMock, patch


# zvec is optional in CI; provide the symbols used by ZvecRetriever before the
# system under test imports it.
_mock_zvec = MagicMock()
_mock_zvec.DataType.STRING = "STRING"
_mock_zvec.DataType.VECTOR_FP32 = "VECTOR_FP32"
_mock_zvec.MetricType.COSINE = "COSINE"
sys.modules.setdefault("zvec", _mock_zvec)

from dashboard.agentic_memory import retrievers as _retrievers_mod
from dashboard.agentic_memory.retrievers import (
    EMBEDDING_DIMENSION,
    CentralizedEmbeddingFunction,
    ZvecRetriever,
    _WrappedEmbedFn,
    _create_embedding_function,
    _embedding_cache,
    _embedding_cache_lock,
)


class TestWrappedEmbedFn(unittest.TestCase):
    def test_wraps_plain_callable_for_zvec_interface(self):
        wrapper = _WrappedEmbedFn(lambda texts: [[float(len(t))] for t in texts], label="custom")

        self.assertEqual(wrapper(["hi"]), [[2.0]])
        self.assertEqual(wrapper.name(), "custom")
        self.assertEqual(wrapper.dimension, EMBEDDING_DIMENSION)


class TestCentralizedEmbeddingFunction(unittest.TestCase):
    def test_get_client_maps_legacy_gemini_backend_to_google(self):
        mock_client = MagicMock()
        mock_client.embed.return_value = [[0.1] * EMBEDDING_DIMENSION]

        with patch("dashboard.llm_client.create_embedding_client", return_value=mock_client) as create_client:
            fn = CentralizedEmbeddingFunction(model_name="gemini-embedding-001", embedding_backend="gemini")
            result = fn(["hello"])

        create_client.assert_called_once_with(
            model="gemini-embedding-001",
            provider="google",
            dimension=EMBEDDING_DIMENSION,
        )
        self.assertEqual(result, [[0.1] * EMBEDDING_DIMENSION])

    def test_empty_input_does_not_create_client(self):
        with patch("dashboard.llm_client.create_embedding_client") as create_client:
            fn = CentralizedEmbeddingFunction()
            self.assertEqual(fn([]), [])

        create_client.assert_not_called()

    def test_invalidate_recreates_client_on_next_call(self):
        first_client = MagicMock()
        second_client = MagicMock()
        first_client.embed.return_value = [[1.0]]
        second_client.embed.return_value = [[2.0]]

        with patch(
            "dashboard.llm_client.create_embedding_client",
            side_effect=[first_client, second_client],
        ):
            fn = CentralizedEmbeddingFunction(model_name="m", embedding_backend="ollama")
            self.assertEqual(fn(["a"]), [[1.0]])
            fn.invalidate()
            self.assertEqual(fn(["b"]), [[2.0]])


class TestCreateEmbeddingFunction(unittest.TestCase):
    def setUp(self):
        with _embedding_cache_lock:
            _embedding_cache.clear()

    def test_creates_centralized_function_for_supported_backends(self):
        fn = _create_embedding_function("ollama", "leoipulsar/harrier-0.6b", shared=False)

        self.assertIsInstance(fn, CentralizedEmbeddingFunction)
        self.assertEqual(fn._embedding_backend, "ollama")
        self.assertEqual(fn._model_name, "leoipulsar/harrier-0.6b")

    def test_shared_cache_returns_singleton(self):
        first = _create_embedding_function("gemini", "gemini-embedding-001", shared=True)
        second = _create_embedding_function("gemini", "gemini-embedding-001", shared=True)

        self.assertIs(first, second)

    def test_fresh_invalidates_cached_embedding_function(self):
        first = _create_embedding_function("ollama", "m", shared=True)
        first.invalidate = MagicMock()

        second = _create_embedding_function("ollama", "m", shared=True, fresh=True)

        first.invalidate.assert_called_once()
        self.assertIsNot(first, second)

    def test_sentence_transformer_backend_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "sentence-transformers embeddings are no longer supported"):
            _create_embedding_function("sentence-transformer", "my/model", shared=False)

    def test_legacy_sentence_transformer_model_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "legacy sentence-transformer embedding models"):
            _create_embedding_function("ollama", "all-MiniLM-L6-v2", shared=False)


class TestZvecRetriever(unittest.TestCase):
    def _make_retriever(self, persist_dir="/tmp/test_zvec_dir", collection_name="test_col", path_exists=False):
        with (
            patch("os.path.exists", return_value=path_exists),
            patch("os.path.join", side_effect=lambda *parts: "/".join(parts)),
        ):
            retriever = ZvecRetriever(
                collection_name=collection_name,
                model_name="test-model",
                persist_dir=persist_dir,
                embedding_backend="ollama",
            )
        return retriever

    def test_init_with_nonexistent_path_sets_collection_none(self):
        retriever = self._make_retriever(path_exists=False)
        self.assertIsNone(retriever.collection)

    def test_search_with_no_collection_returns_empty_structure(self):
        retriever = self._make_retriever(path_exists=False)
        self.assertEqual(retriever.search("any query"), {"ids": [[]], "metadatas": [[]], "distances": [[]]})

    def test_count_with_no_collection_returns_zero(self):
        retriever = self._make_retriever(path_exists=False)
        self.assertEqual(retriever.count(), 0)

    def test_delete_document_on_none_collection_no_error(self):
        retriever = self._make_retriever(path_exists=False)
        retriever.delete_document("nonexistent-id")

    def test_add_document_creates_collection_if_needed(self):
        retriever = self._make_retriever(path_exists=False)
        retriever._embedding_function = MagicMock(return_value=[[0.1, 0.2, 0.3]])
        retriever._dimension = 3
        mock_collection = MagicMock()
        retriever._zvec.create_and_open.return_value = mock_collection

        with patch("os.makedirs"):
            retriever.add_document(
                document="test content",
                metadata={"summary": "test summary", "context": "General"},
                doc_id="doc-123",
            )

        retriever._zvec.create_and_open.assert_called()
        self.assertIs(retriever.collection, mock_collection)
        mock_collection.insert.assert_called_once()
        mock_collection.optimize.assert_called_once()

    def test_search_returns_properly_formatted_results(self):
        retriever = self._make_retriever(path_exists=False)
        retriever._embedding_function = MagicMock(return_value=[[0.5, 0.5]])

        mock_doc1 = MagicMock()
        mock_doc1.id = "id-1"
        mock_doc1.score = 0.95
        mock_doc1.fields = {"metadata_json": json.dumps({"name": "Note 1", "tags": '["a","b"]'})}
        mock_doc2 = MagicMock()
        mock_doc2.id = "id-2"
        mock_doc2.score = 0.80
        mock_doc2.fields = {"metadata_json": json.dumps({"name": "Note 2"})}

        mock_collection = MagicMock()
        mock_collection.query.return_value = [mock_doc1, mock_doc2]
        retriever.collection = mock_collection

        result = retriever.search("find something", k=3)

        self.assertEqual(result["ids"], [["id-1", "id-2"]])
        self.assertEqual(result["distances"], [[0.95, 0.80]])
        self.assertEqual(result["metadatas"][0][0]["name"], "Note 1")
        self.assertEqual(result["metadatas"][0][0]["tags"], ["a", "b"])

    def test_search_with_non_json_metadata_keeps_plain_strings(self):
        retriever = self._make_retriever(path_exists=False)
        retriever._embedding_function = MagicMock(return_value=[[0.1]])
        mock_doc = MagicMock()
        mock_doc.id = "id-x"
        mock_doc.score = 0.5
        mock_doc.fields = {"metadata_json": json.dumps({"plain": "text", "num": "42"})}
        mock_collection = MagicMock()
        mock_collection.query.return_value = [mock_doc]
        retriever.collection = mock_collection

        result = retriever.search("q")

        self.assertEqual(result["metadatas"][0][0]["plain"], "text")
        self.assertEqual(result["metadatas"][0][0]["num"], "42")

    def test_embedding_function_property_lazy_creates(self):
        retriever = self._make_retriever(path_exists=False)
        retriever._embedding_backend = "ollama"
        retriever._model_name = "leoipulsar/harrier-0.6b"
        retriever._embedding_function = None

        with _embedding_cache_lock:
            _embedding_cache.clear()

        ef = retriever.embedding_function
        self.assertIsInstance(ef, CentralizedEmbeddingFunction)
        self.assertIs(retriever.embedding_function, ef)

    def test_add_document_enhances_text_with_metadata(self):
        retriever = self._make_retriever(path_exists=False)
        embedded_texts = []

        def capture_embed(texts):
            embedded_texts.extend(texts)
            return [[0.1, 0.2]]

        retriever._embedding_function = MagicMock(side_effect=capture_embed)
        retriever.collection = MagicMock()

        retriever.add_document(
            document="raw text",
            metadata={"summary": "summary text", "context": "Backend", "keywords": ["db", "sql"], "tags": ["#database"]},
            doc_id="doc-1",
        )

        enhanced = embedded_texts[0]
        self.assertIn("summary text", enhanced)
        self.assertIn("context: Backend", enhanced)
        self.assertIn("keywords: db, sql", enhanced)
        self.assertIn("tags: #database", enhanced)

    def test_add_document_uses_summary_over_document(self):
        retriever = self._make_retriever(path_exists=False)
        embedded_texts = []
        retriever._embedding_function = MagicMock(side_effect=lambda texts: embedded_texts.extend(texts) or [[0.1]])
        retriever.collection = MagicMock()

        retriever.add_document(
            document="original long content",
            metadata={"summary": "short summary", "context": "General"},
            doc_id="d1",
        )

        self.assertTrue(embedded_texts[0].startswith("short summary"))

    def test_add_document_skips_general_context(self):
        retriever = self._make_retriever(path_exists=False)
        embedded_texts = []
        retriever._embedding_function = MagicMock(side_effect=lambda texts: embedded_texts.extend(texts) or [[0.1]])
        retriever.collection = MagicMock()

        retriever.add_document(document="text", metadata={"context": "General"}, doc_id="d2")

        self.assertNotIn("context:", embedded_texts[0])

    def test_clear_creates_new_collection(self):
        retriever = self._make_retriever(path_exists=False)
        retriever._dimension = 3
        new_collection = MagicMock()
        retriever._zvec.create_and_open.return_value = new_collection

        with patch("os.makedirs"):
            retriever.clear()

        retriever._zvec.create_and_open.assert_called()
        self.assertIs(retriever.collection, new_collection)


if __name__ == "__main__":
    unittest.main()
