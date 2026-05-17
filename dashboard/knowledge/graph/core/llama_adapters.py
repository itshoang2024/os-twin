"""Thin adapters bridging native handles to llama-index abstract types.

``GraphRAGQueryEngine`` and ``PropertyGraphIndex`` expect llama-index base
classes (``BasePydanticVectorStore``, ``BaseEmbedding``).  Our native
implementations (``NamespaceVectorStore`` / zvec, ``KnowledgeEmbedder`` /
configured embedding provider) don't inherit from those bases.

This module provides two lightweight adapters so the graph-RAG query path
can reuse the *exact same* cached handles that the ingestion and raw-query
paths use — no duplicate connections, no extra model loads.

Both classes are intentionally thin: they delegate every real operation to
the wrapped handle and do the minimum conversion to satisfy the llama-index
contract.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Sequence

from pydantic import ConfigDict

from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.schema import TextNode
from llama_index.core.vector_stores.types import (
    BasePydanticVectorStore,
    VectorStoreQuery,
    VectorStoreQueryResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vector store adapter
# ---------------------------------------------------------------------------


class ZvecVectorStoreAdapter(BasePydanticVectorStore):
    """Wrap :class:`NamespaceVectorStore` (zvec) as a llama-index vector store.

    Only ``query()`` is implemented for retrieval.  ``add()`` is a no-op
    because ingestion writes through :class:`NamespaceVectorStore` directly.
    ``delete()`` delegates to the underlying store's ``delete`` if present.

    The adapter holds a *reference* to the shared ``NamespaceVectorStore``
    instance managed by ``KnowledgeService`` — it never opens its own
    collection.
    """

    # Pydantic v2 — we store the native store as a private attribute so
    # Pydantic doesn't try to validate/serialize it.
    _zvec_store: Any = None

    # BasePydanticVectorStore requires ``stores_text`` on the class.
    stores_text: bool = True

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, zvec_store: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._zvec_store = zvec_store

    # -- Required abstract implementations ---------------------------------

    @property
    def client(self) -> Any:
        """Return the underlying zvec collection handle."""
        return self._zvec_store

    def add(self, nodes: List[Any], **kwargs: Any) -> List[str]:
        """Persist llama-index TextNodes to the underlying zvec collection.

        Called by ``PropertyGraphIndex._insert_nodes_to_vector_index`` to
        write entity embeddings during ingestion.  Each node is mapped to
        the ``{text, embedding, metadata}`` dict that
        :meth:`NamespaceVectorStore.add_chunks` expects.
        """
        if not nodes or self._zvec_store is None:
            return []
        chunks: list[dict] = []
        ids: list[str] = []
        for node in nodes:
            embedding = getattr(node, "embedding", None)
            if embedding is None:
                continue
            metadata = getattr(node, "metadata", {}) or {}
            text = getattr(node, "text", "") or ""
            node_id = getattr(node, "id_", "") or getattr(node, "node_id", "")
            chunks.append(
                {
                    "text": text,
                    "embedding": embedding,
                    "metadata": metadata,
                }
            )
            ids.append(str(node_id))
        if chunks:
            try:
                self._zvec_store.add_chunks(chunks)
            except Exception as exc:  # noqa: BLE001
                logger.error("ZvecVectorStoreAdapter.add failed: %s", exc)
        return ids

    def delete(self, ref_doc_id: str, **kwargs: Any) -> None:
        """Delegate to the underlying store if it supports deletion."""
        if hasattr(self._zvec_store, "delete"):
            self._zvec_store.delete(ref_doc_id, **kwargs)

    def query(self, query: VectorStoreQuery, **kwargs: Any) -> VectorStoreQueryResult:
        """Execute a vector similarity search via the wrapped zvec store.

        Converts the llama-index ``VectorStoreQuery`` into parameters for
        ``NamespaceVectorStore.search(embedding, top_k)`` and maps the
        ``VectorHit`` results back into a ``VectorStoreQueryResult``.
        """
        embedding = query.query_embedding
        top_k = query.similarity_top_k or 10

        if embedding is None:
            return VectorStoreQueryResult(nodes=[], similarities=[], ids=[])

        try:
            hits = self._zvec_store.search(embedding, top_k=top_k)
        except Exception as exc:  # noqa: BLE001
            logger.error("ZvecVectorStoreAdapter.query failed: %s", exc)
            return VectorStoreQueryResult(nodes=[], similarities=[], ids=[])

        nodes: list[TextNode] = []
        similarities: list[float] = []
        ids: list[str] = []

        for hit in hits:
            text = getattr(hit, "text", "") or ""
            metadata = getattr(hit, "metadata", None) or {}
            hit_id = str(getattr(hit, "id", ""))
            score = float(getattr(hit, "score", 0.0))

            node = TextNode(
                text=text,
                id_=hit_id,
                metadata=metadata,
            )
            nodes.append(node)
            similarities.append(score)
            ids.append(hit_id)

        return VectorStoreQueryResult(
            nodes=nodes,
            similarities=similarities,
            ids=ids,
        )


# ---------------------------------------------------------------------------
# Embedding adapter
# ---------------------------------------------------------------------------


class EmbedderAdapter(BaseEmbedding):
    """Wrap :class:`KnowledgeEmbedder` as a llama-index ``BaseEmbedding``.

    Delegates all embedding calls to the shared ``KnowledgeEmbedder``
    instance. The adapter exposes ``embed_dim`` derived from the
    underlying embedder's ``dimension()`` method.
    """

    _knowledge_embedder: Any = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, knowledge_embedder: Any, **kwargs: Any) -> None:
        # BaseEmbedding uses model_name; pass a sensible default.
        model_name = kwargs.pop("model_name", None) or getattr(
            knowledge_embedder, "model_name", "knowledge-embedder"
        )
        super().__init__(model_name=model_name, **kwargs)
        self._knowledge_embedder = knowledge_embedder

    # -- Required abstract implementations ---------------------------------

    def _get_text_embedding(self, text: str) -> List[float]:
        """Embed a single text string."""
        return self._knowledge_embedder.embed_one(text)

    def _get_query_embedding(self, query: str) -> List[float]:
        """Embed a query string (same logic as text embedding)."""
        return self._knowledge_embedder.embed_one(query)

    async def _aget_query_embedding(self, query: str) -> List[float]:
        """Async query embedding — delegates to sync (model is local)."""
        return self._get_query_embedding(query)


__all__ = ["EmbedderAdapter", "ZvecVectorStoreAdapter"]
