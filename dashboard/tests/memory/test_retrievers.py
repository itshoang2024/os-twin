"""Unit tests for the current agentic_memory.retrievers contract.

Legacy provider-specific embedding wrappers were consolidated into
CentralizedEmbeddingFunction. These tests keep the older memory test module
collectable while asserting the supported behavior.
"""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

_mock_zvec = MagicMock()
_mock_zvec.DataType.STRING = "STRING"
_mock_zvec.DataType.VECTOR_FP32 = "VECTOR_FP32"
_mock_zvec.MetricType.COSINE = "COSINE"
sys.modules.setdefault("zvec", _mock_zvec)

from dashboard.agentic_memory.retrievers import (
    CentralizedEmbeddingFunction,
    EMBEDDING_DIMENSION,
    ZvecRetriever,
    _KNOWN_DIMENSIONS,
    _create_embedding_function,
)


def test_centralized_embedding_function_delegates_to_llm_client(monkeypatch):
    class FakeClient:
        def embed(self, items):
            return [[0.1] * EMBEDDING_DIMENSION for _ in items]

    create_client = MagicMock(return_value=FakeClient())
    monkeypatch.setattr("dashboard.llm_client.create_embedding_client", create_client)

    fn = CentralizedEmbeddingFunction(model_name="gemini-embedding-001", embedding_backend="gemini")
    result = fn(["hello"])

    create_client.assert_called_once_with(
        model="gemini-embedding-001",
        provider="google",
        dimension=EMBEDDING_DIMENSION,
    )
    assert len(result[0]) == EMBEDDING_DIMENSION
    assert fn.dimension == EMBEDDING_DIMENSION


@pytest.mark.parametrize("backend", ["ollama", "gemini", "google-vertex", "openai-compatible"])
def test_embedding_factory_uses_centralized_function_for_supported_backends(backend):
    fn = _create_embedding_function(backend, "gemini-embedding-001", shared=False)

    assert isinstance(fn, CentralizedEmbeddingFunction)
    assert fn._embedding_backend == backend
    assert fn._model_name == "gemini-embedding-001"


@pytest.mark.parametrize("backend", ["sentence-transformer", "sentence-transformers", "sentence_transformers"])
def test_legacy_sentence_transformer_backends_are_rejected(backend):
    with pytest.raises(ValueError, match="sentence-transformers embeddings are no longer supported"):
        _create_embedding_function(backend, "all-MiniLM-L6-v2", shared=False)


def test_known_dimensions_keep_current_embedding_models_only():
    assert _KNOWN_DIMENSIONS["gemini-embedding-001"] == 1024
    assert "all-MiniLM-L6-v2" not in _KNOWN_DIMENSIONS


def make_retriever(path_exists=False):
    _mock_zvec.reset_mock()
    with (
        patch("os.path.exists", return_value=path_exists),
        patch("os.path.join", side_effect=lambda *parts: "/".join(parts)),
    ):
        return ZvecRetriever(
            collection_name="test_col",
            model_name="leoipulsar/harrier-0.6b",
            persist_dir="/tmp/test_zvec_dir",
            embedding_backend="ollama",
        )


def test_zvec_init_with_nonexistent_path_defers_collection_creation():
    retriever = make_retriever(path_exists=False)

    assert retriever.collection is None
    assert retriever.count() == 0
    assert retriever.search("any query") == {"ids": [[]], "metadatas": [[]], "distances": [[]]}


def test_zvec_add_document_creates_collection_and_enhances_metadata_text():
    retriever = make_retriever(path_exists=False)
    embedded_texts = []

    def capture_embed(texts):
        embedded_texts.extend(texts)
        return [[0.1, 0.2, 0.3]]

    retriever.embedding_function = MagicMock(side_effect=capture_embed)
    retriever._dimension = 3
    collection = MagicMock()
    retriever._zvec.create_and_open.return_value = collection

    with patch("os.makedirs"):
        retriever.add_document(
            document="raw text",
            metadata={"summary": "summary text", "context": "Backend", "keywords": ["db", "sql"], "tags": ["#database"]},
            doc_id="doc-1",
        )

    assert retriever.collection is collection
    assert "summary text" in embedded_texts[0]
    assert "context: Backend" in embedded_texts[0]
    assert "keywords: db, sql" in embedded_texts[0]
    assert "tags: #database" in embedded_texts[0]
    collection.insert.assert_called_once()
    collection.optimize.assert_called_once()


def test_zvec_search_formats_results_and_deserializes_metadata():
    retriever = make_retriever(path_exists=False)
    retriever.embedding_function = MagicMock(return_value=[[0.5, 0.5]])

    doc1 = MagicMock()
    doc1.id = "id-1"
    doc1.score = 0.95
    doc1.fields = {"metadata_json": json.dumps({"name": "Note 1", "tags": '["a","b"]'})}
    doc2 = MagicMock()
    doc2.id = "id-2"
    doc2.score = 0.8
    doc2.fields = {"metadata_json": json.dumps({"name": "Note 2"})}

    collection = MagicMock()
    collection.query.return_value = [doc1, doc2]
    retriever.collection = collection

    result = retriever.search("find something", k=3)

    assert result["ids"] == [["id-1", "id-2"]]
    assert result["distances"] == [[0.95, 0.8]]
    assert result["metadatas"][0][0]["tags"] == ["a", "b"]
    collection.query.assert_called_once()


def test_zvec_existing_ids_and_hashes_handle_missing_collection():
    retriever = make_retriever(path_exists=False)

    assert retriever.existing_ids(["a", "b"]) == set()
    assert retriever.get_stored_hashes(["a"]) == {}
    retriever.delete_document("missing")


def test_zvec_clear_recreates_collection():
    retriever = make_retriever(path_exists=False)
    retriever._dimension = 3
    new_collection = MagicMock()
    retriever._zvec.create_and_open.reset_mock()
    retriever._zvec.create_and_open.return_value = new_collection

    with patch("os.makedirs"):
        retriever.clear()

    assert retriever.collection is new_collection
    retriever._zvec.create_and_open.assert_called_once()
