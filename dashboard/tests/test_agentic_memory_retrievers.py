"""Tests for current agentic-memory retriever embedding behavior."""

import inspect

import pytest

from dashboard.agentic_memory.retrievers import (
    CentralizedEmbeddingFunction,
    ChromaRetriever,
    ZvecRetriever,
    _KNOWN_DIMENSIONS,
    _create_embedding_function,
)


@pytest.mark.parametrize("backend", ["sentence-transformer", "sentence-transformers", "sentence_transformers"])
def test_sentence_transformer_embedding_backends_are_rejected(backend):
    with pytest.raises(ValueError, match="sentence-transformers embeddings are no longer supported"):
        _create_embedding_function(backend, "all-MiniLM-L6-v2", shared=False)


@pytest.mark.parametrize("model", ["all-MiniLM-L6-v2", "BAAI/bge-small-en-v1.5"])
def test_legacy_sentence_transformer_model_ids_are_rejected(model):
    with pytest.raises(ValueError, match="legacy sentence-transformer embedding models are no longer supported"):
        _create_embedding_function("ollama", model, shared=False)


def test_embedding_function_factory_uses_centralized_client():
    fn = _create_embedding_function("ollama", "leoipulsar/harrier-0.6b", shared=False)

    assert isinstance(fn, CentralizedEmbeddingFunction)
    assert fn._embedding_backend == "ollama"
    assert fn._model_name == "leoipulsar/harrier-0.6b"


@pytest.mark.parametrize("retriever_cls", [ChromaRetriever, ZvecRetriever])
def test_retriever_defaults_no_longer_point_at_sentence_transformers(retriever_cls):
    sig = inspect.signature(retriever_cls)

    assert sig.parameters["embedding_backend"].default == "ollama"
    assert sig.parameters["model_name"].default == "leoipulsar/harrier-0.6b"


def test_known_dimensions_do_not_include_legacy_sentence_transformer_models():
    legacy_models = {
        "all-MiniLM-L6-v2",
        "all-MiniLM-L12-v2",
        "all-mpnet-base-v2",
        "paraphrase-MiniLM-L6-v2",
        "paraphrase-multilingual-MiniLM-L12-v2",
    }

    assert legacy_models.isdisjoint(_KNOWN_DIMENSIONS)
