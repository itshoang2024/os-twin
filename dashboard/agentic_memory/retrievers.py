"""Retriever backends for the Agentic Memory vector store.

Provides ChromaDB and Zvec retriever implementations with pluggable
embedding functions.

Embedding is handled via an injected ``embed_fn`` callable or, when
no function is injected, via the centralized embedding client
(ollama, google, google-vertex, or openai-compatible).
The legacy per-class embedding logic has been consolidated.

Memory-management design:
- Heavy ML imports (nltk, sklearn) are lazy-loaded on first use (F11).
- ZvecRetriever holds a single persistent collection handle; zvec handles concurrency internally.
- Embedding dimension is cached per model to avoid test-embedding calls (F9).
"""

from typing import List, Dict, Any, Optional, Union, Protocol, runtime_checkable
import os
import json
import logging
import threading

logger = logging.getLogger(__name__)

# --- Lazy imports ---------------------------------------------------------
# Populated on first use via _ensure_retriever_imports().  Individual classes
# also lazy-import within _ensure_model() for extra safety.

_retriever_imports_done = False
_import_lock = threading.Lock()

# Sentinel — the *module-level* names stay None until lazy-loaded.
BM25Okapi = None
word_tokenize = None
cosine_similarity = None
np = None


def _ensure_retriever_imports():
    """Import heavy ML libraries on first use (lazy pattern — F11)."""
    global _retriever_imports_done, BM25Okapi
    global word_tokenize, cosine_similarity, np

    if _retriever_imports_done:
        return

    with _import_lock:
        if _retriever_imports_done:
            return

        from rank_bm25 import BM25Okapi as _BM
        from nltk.tokenize import word_tokenize as _wt
        from sklearn.metrics.pairwise import cosine_similarity as _cs
        import numpy as _np

        BM25Okapi = _BM
        word_tokenize = _wt
        cosine_similarity = _cs
        np = _np
        _retriever_imports_done = True


@runtime_checkable
class EmbeddingFunction(Protocol):
    """Protocol for embedding functions (avoiding chromadb import)."""

    def __call__(self, input: List[str]) -> List[List[float]]: ...


Documents = List[str]
Embeddings = List[List[float]]


class _WrappedEmbedFn:
    """Wrap a plain callable to satisfy zvec's embedding function interface.

    zvec internally calls ``embedding_function.name()`` which fails on
    plain lambdas or functions.  This wrapper provides the required method.
    """

    def __init__(self, fn, label: str = "gateway"):
        self._fn = fn
        self._label = label

    def __call__(self, input: Documents) -> Embeddings:
        return self._fn(input)

    def name(self) -> str:
        return self._label

    @property
    def dimension(self) -> int:
        return EMBEDDING_DIMENSION


def simple_tokenize(text):
    _ensure_retriever_imports()
    return word_tokenize(text)


# --- Global embedding dimension -------------------------------------------
try:
    from dashboard.llm_client import DEFAULT_EMBEDDING_DIMENSION as EMBEDDING_DIMENSION
except ImportError:
    EMBEDDING_DIMENSION = 768  # fallback for tests / standalone mode

# Native model dimensions (before truncation) — used as a fast path
# to avoid test-embedding calls (F9).
_KNOWN_DIMENSIONS: Dict[str, int] = {
    "gemini-embedding-001": 1024,
    "gemini/gemini-embedding-001": 1024,
    "text-embedding-004": 1024,
    "leoipulsar/harrier-0.6b": 1024,
    "embeddinggemma": 1024,
    "qwen3-embedding:0.6b": 896,
    "text-embedding-005": 1024,
}

_UNSUPPORTED_EMBEDDING_BACKENDS = frozenset({
    "sentence-transformer",
    "sentence-transformers",
})

_LEGACY_SENTENCE_TRANSFORMER_MODELS = frozenset({
    "all-minilm-l6-v2",
    "all-minilm-l12-v2",
    "all-mpnet-base-v2",
    "paraphrase-minilm-l6-v2",
    "paraphrase-multilingual-minilm-l12-v2",
    "baai/bge-small-en-v1.5",
    "baai/bge-base-en-v1.5",
    "baai/bge-large-en-v1.5",
})


def _normalize_embedding_backend(backend: str) -> str:
    return (backend or "").lower().replace("_", "-")


def _normalize_embedding_model(model: str) -> str:
    return (model or "").lower().replace("_", "-")


class CentralizedEmbeddingFunction:
    """Embedding function backed by ``dashboard.llm_client.create_embedding_client``.

    Implements the ``EmbeddingFunction`` protocol (``__call__(input) -> list[list[float]]``).
    Output is always truncated/padded to ``EMBEDDING_DIMENSION`` for
    cross-backend consistency with existing zvec/chroma collections.
    """

    def __init__(
        self,
        model_name: str = "leoipulsar/harrier-0.6b",
        embedding_backend: str = "ollama",
    ):
        self._model_name = model_name
        self._embedding_backend = embedding_backend
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        from dashboard.llm_client import create_embedding_client

        current_dim = int(os.environ.get("OSTWIN_EMBEDDING_DIM", "1024"))

        provider = self._embedding_backend
        if provider == "gemini":
            provider = "google"

        self._client = create_embedding_client(
            model=self._model_name,
            provider=provider,
            dimension=current_dim,
        )
        return self._client

    def invalidate(self):
        self._client = None

    def __call__(self, input: Documents) -> Embeddings:
        if not input:
            return []
        return self._get_client().embed(input)

    @property
    def dimension(self) -> int:
        return int(os.environ.get("OSTWIN_EMBEDDING_DIM", "1024"))


_embedding_cache: Dict[tuple, Any] = {}
_embedding_cache_lock = threading.Lock()


def _create_embedding_function(
    embedding_backend: str,
    model_name: str,
    *,
    shared: bool = True,
    fresh: bool = False,
):
    """Create or retrieve a cached embedding function.

    Delegates to ``CentralizedEmbeddingFunction`` which wraps the
    centralized ``dashboard.llm_client.EmbeddingClient``.
    """
    if _normalize_embedding_backend(embedding_backend) in _UNSUPPORTED_EMBEDDING_BACKENDS:
        raise ValueError(
            "sentence-transformers embeddings are no longer supported; "
            "use ollama, gemini, google-vertex, or openai-compatible instead."
        )
    if _normalize_embedding_model(model_name) in _LEGACY_SENTENCE_TRANSFORMER_MODELS:
        raise ValueError(
            "legacy sentence-transformer embedding models are no longer supported; "
            "use an Ollama, Gemini, Vertex, or OpenAI-compatible embedding model instead."
        )

    cache_key = (embedding_backend, model_name)

    if fresh and shared:
        with _embedding_cache_lock:
            old = _embedding_cache.pop(cache_key, None)
            if old is not None and hasattr(old, "invalidate"):
                old.invalidate()

    if shared:
        with _embedding_cache_lock:
            cached = _embedding_cache.get(cache_key)
            if cached is not None:
                return cached

    fn = CentralizedEmbeddingFunction(
        model_name=model_name,
        embedding_backend=embedding_backend,
    )

    if shared:
        with _embedding_cache_lock:
            existing = _embedding_cache.get(cache_key)
            if existing is not None:
                return existing
            _embedding_cache[cache_key] = fn

    return fn


def _parse_json_field(metadata: Dict, field: str) -> list:
    """Parse a metadata field that may be a list or JSON string, returning a list."""
    value = metadata.get(field)
    if not value:
        return []
    if isinstance(value, list):
        return value
    return json.loads(value)


def _build_enhanced_document(document: str, metadata: Dict) -> str:
    """Build an enhanced document string by appending context, keywords, and tags."""
    summary = metadata.get("summary")
    enhanced = summary if summary else document

    if "context" in metadata and metadata["context"] != "General":
        enhanced += f" context: {metadata['context']}"

    keywords = _parse_json_field(metadata, "keywords")
    if keywords:
        enhanced += f" keywords: {', '.join(str(k) for k in keywords)}"

    tags = _parse_json_field(metadata, "tags")
    if tags:
        enhanced += f" tags: {', '.join(str(t) for t in tags)}"

    return enhanced


def _serialize_metadata(metadata: Dict) -> Dict[str, str]:
    """Convert metadata values to ChromaDB-compatible string format."""
    processed = {}
    for key, value in metadata.items():
        if isinstance(value, (list, dict)):
            processed[key] = json.dumps(value)
        else:
            processed[key] = str(value)
    return processed


def _deserialize_json_value(value: str) -> Any:
    """Try to parse a string as JSON list/dict, or as a number."""
    try:
        if value.startswith("[") or value.startswith("{"):
            return json.loads(value)
    except ValueError:
        pass
    return value


class ChromaRetriever:
    """Vector database retrieval using ChromaDB (lazy import)."""

    def __init__(
        self,
        collection_name: str = "memories",
        model_name: str = "leoipulsar/harrier-0.6b",
        persist_dir: str = None,
        embedding_backend: str = "ollama",
        embed_fn: Optional[Any] = None,
    ):
        """Initialize ChromaDB retriever.

        Args:
            collection_name: Name of the ChromaDB collection
            model_name: Name of the embedding model
            persist_dir: Directory for persistent storage. If None, uses in-memory mode.
            embedding_backend: "ollama", "gemini", "google-vertex", or "openai-compatible"
            embed_fn: Optional external embedding function (from gateway)
        """
        import chromadb
        from chromadb.config import Settings

        if persist_dir:
            self.client = chromadb.PersistentClient(path=persist_dir)
        else:
            self.client = chromadb.Client(Settings(allow_reset=True))
        self.persist_dir = persist_dir

        if embed_fn is not None and not hasattr(embed_fn, 'name'):
            embed_fn = _WrappedEmbedFn(embed_fn)
        self.embedding_function = embed_fn or _create_embedding_function(
            embedding_backend, model_name
        )
        self.collection = self.client.get_or_create_collection(
            name=collection_name, embedding_function=self.embedding_function
        )

    def close(self):
        """Release resources held by this retriever.

        Note: the embedding function is shared (singleton) and is NOT
        closed here — it may be in use by other retrievers.
        """
        self.collection = None
        self.client = None

    def start_batch(self):
        """No-op — ChromaDB does not require batch optimization."""

    def end_batch(self):
        """No-op — ChromaDB does not require batch optimization."""

    def add_document(self, document: str, metadata: Dict, doc_id: str):
        """Add a document to ChromaDB with enhanced embedding using metadata.

        Args:
            document: Text content to add
            metadata: Dictionary of metadata including keywords, tags, context
            doc_id: Unique identifier for the document
        """
        enhanced_document = _build_enhanced_document(document, metadata)
        processed_metadata = _serialize_metadata(metadata)
        processed_metadata["enhanced_content"] = enhanced_document

        self.collection.add(
            documents=[enhanced_document], metadatas=[processed_metadata], ids=[doc_id]
        )

    def clear(self):
        """Delete all documents and recreate the collection."""
        self.client.delete_collection("memories")
        self.collection = self.client.get_or_create_collection(
            name="memories", embedding_function=self.embedding_function
        )

    def has_document(self, doc_id: str) -> bool:
        """Check if a document exists in ChromaDB."""
        results = self.collection.get(ids=[doc_id])
        return bool(results and results.get("ids"))

    def existing_ids(self, doc_ids: List[str]) -> set:
        """Return the subset of *doc_ids* that exist in the collection."""
        if not doc_ids:
            return set()
        results = self.collection.get(ids=doc_ids)
        return set(results.get("ids", []))

    def get_stored_hashes(self, doc_ids: List[str]) -> Dict[str, Optional[str]]:
        """Return {doc_id: content_hash} for each ID. Missing IDs omitted."""
        if not doc_ids:
            return {}
        results = self.collection.get(ids=doc_ids, include=["metadatas"])
        out: Dict[str, Optional[str]] = {}
        for i, did in enumerate(results.get("ids", [])):
            meta = (
                (results.get("metadatas") or [])[i] if results.get("metadatas") else {}
            )
            out[did] = (meta or {}).get("content_hash")
        return out

    def delete_document(self, doc_id: str):
        """Delete a document from ChromaDB.

        Args:
            doc_id: ID of document to delete
        """
        self.collection.delete(ids=[doc_id])

    @staticmethod
    def _deserialize_metadata_value(value):
        """Attempt to deserialize a single metadata value from its string representation.

        Converts JSON strings back to lists/dicts and numeric strings back to
        int/float.  Returns the original value unchanged on failure.
        """
        if not isinstance(value, str):
            return value
        parsed = _deserialize_json_value(value)
        if parsed is not value:
            return parsed
        if value.replace(".", "", 1).isdigit():
            return float(value) if "." in value else int(value)
        return value

    @staticmethod
    def _deserialize_metadata_dict(metadata: dict) -> None:
        """Deserialize all values in a single metadata dict in-place."""
        for key, value in metadata.items():
            metadata[key] = ChromaRetriever._deserialize_metadata_value(value)

    def search(self, query: str, k: int = 5):
        """Search for similar documents.

        Args:
            query: Query text
            k: Number of results to return

        Returns:
            Dict with documents, metadatas, ids, and distances
        """
        results = self.collection.query(query_texts=[query], n_results=k)

        # Convert string metadata back to original types
        if results.get("metadatas"):
            for query_metadatas in results["metadatas"]:
                if not isinstance(query_metadatas, list):
                    continue
                for metadata in query_metadatas:
                    if isinstance(metadata, dict):
                        self._deserialize_metadata_dict(metadata)

        return results


class ZvecRetriever:
    """Vector database retrieval using Zvec.

    Uses deferred collection initialization (``self.collection`` is ``None``
    until the first write or until ``_ensure_collection()`` is called).  This
    allows the retriever to be created cheaply even when the underlying
    zvec path doesn't exist yet.

    Zvec handles its own concurrency: reads, writes, and ``optimize()`` are
    all thread-safe and can run concurrently without external locking or GC.
    We hold a single persistent collection handle for the lifetime of the
    retriever.

    The public ``embedding_function`` attribute is a *property* that
    lazy-creates the embedding function on first access and caches it.
    """

    def __init__(
        self,
        collection_name: str = "memories",
        model_name: str = "leoipulsar/harrier-0.6b",
        persist_dir: str = None,
        embedding_backend: str = "ollama",
        embed_fn: Optional[Any] = None,
    ):
        import zvec as _zvec

        self._zvec = _zvec
        self._model_name = model_name
        self._embedding_backend = embedding_backend
        # If an external embed_fn is injected (e.g. from memory_system),
        # wrap it so zvec can call .name() / .dimension on it.
        if embed_fn is not None and not hasattr(embed_fn, 'name'):
            embed_fn = _WrappedEmbedFn(embed_fn)
        self._embedding_function: Optional[Any] = embed_fn

        self.persist_dir = persist_dir
        self._dimension: Optional[int] = None

        collection_path = (
            os.path.join(persist_dir, collection_name)
            if persist_dir
            else os.path.join("/tmp/zvec", collection_name)
        )
        # Resolve to absolute path so later opens work regardless of CWD
        self._collection_path = os.path.abspath(collection_path)
        self._collection_name = collection_name

        self._batch_mode = False

        # Deferred initialization: collection is None until first use.
        self.collection = None

        # If the collection already exists on disk, open a persistent handle.
        if os.path.exists(collection_path):
            try:
                self.collection = _zvec.open(path=self._collection_path)
            except Exception:
                self.collection = None

    # --- Embedding property (lazy, cached) --------------------------------

    @property
    def embedding_function(self):
        """Lazily create and cache the embedding function (F1 singleton)."""
        if self._embedding_function is None:
            self._embedding_function = _create_embedding_function(
                self._embedding_backend, self._model_name
            )
        return self._embedding_function

    @embedding_function.setter
    def embedding_function(self, value):
        """Allow external override (used by tests)."""
        self._embedding_function = value

    # --- Dimension detection ------------------------------------------

    def _get_dimension(self) -> int:
        """Get embedding dimension, using cache of known models (F9)."""
        if self._dimension is not None:
            return self._dimension

        # Check known dimensions first
        dim = _KNOWN_DIMENSIONS.get(self._model_name)
        if dim is not None:
            self._dimension = dim
            return dim

        # Check embedding function's own dimension tracking
        ef = self.embedding_function
        if hasattr(ef, "dimension"):
            try:
                self._dimension = ef.dimension
                return self._dimension
            except Exception:
                pass

        # Fallback: test embed
        logger.info("Unknown dimension for '%s', computing via test embed", self._model_name)
        test_embedding = ef(["dimension probe"])
        self._dimension = len(test_embedding[0]) if test_embedding else 384
        _KNOWN_DIMENSIONS[self._model_name] = self._dimension
        return self._dimension

    # --- Collection management ----------------------------------------

    def _ensure_collection(self):
        """Create or open the zvec collection if not already open."""
        if self.collection is not None:
            return self.collection

        dim = self._get_dimension()

        if not os.path.exists(self._collection_path):
            os.makedirs(os.path.dirname(self._collection_path), exist_ok=True)
            self.collection = self._zvec.create_and_open(
                path=self._collection_path,
                schema=self._build_schema(self._zvec, self._collection_name, dim),
            )
        else:
            self.collection = self._zvec.open(path=self._collection_path)

        return self.collection

    def _build_schema(self, _zvec, collection_name: str, dimension: int = None):
        """Build a Zvec collection schema for memory storage."""
        dim = dimension or self._get_dimension()
        return _zvec.CollectionSchema(
            name=collection_name,
            fields=[
                _zvec.FieldSchema(
                    name="metadata_json", data_type=_zvec.DataType.STRING
                ),
            ],
            vectors=[
                _zvec.VectorSchema(
                    name="embedding",
                    data_type=_zvec.DataType.VECTOR_FP32,
                    dimension=dim,
                    index_param=_zvec.HnswIndexParam(
                        metric_type=_zvec.MetricType.COSINE
                    ),
                ),
            ],
        )

    def start_batch(self):
        """Enter batch mode — defer ``optimize()`` until ``end_batch()``."""
        self._batch_mode = True

    def end_batch(self):
        """Exit batch mode and run a single ``optimize()``."""
        self._batch_mode = False
        if self.collection is not None:
            try:
                self.collection.optimize()
            except Exception:
                logger.exception("end_batch optimize failed")

    def close(self):
        """Release the collection handle and embedding function reference.

        Note: the embedding function is shared (singleton) and is NOT
        closed here — it may be in use by other retrievers.
        """
        self.collection = None
        self._embedding_function = None

    def count(self) -> int:
        """Return the number of documents in the collection."""
        if self.collection is None:
            return 0
        try:
            return self.collection.count()
        except Exception:
            return 0

    # --- Write operations (read-write lock) --------------------------

    def clear(self):
        """Delete all documents and recreate the collection."""
        if self.collection is not None:
            self.collection.destroy()
            self.collection = None

        dim = self._get_dimension()
        os.makedirs(os.path.dirname(self._collection_path), exist_ok=True)
        self.collection = self._zvec.create_and_open(
            path=self._collection_path,
            schema=self._build_schema(self._zvec, self._collection_name, dim),
        )

    def add_document(self, document: str, metadata: Dict, doc_id: str) -> None:
        """Add a document to Zvec with enhanced embedding using metadata."""
        self._ensure_collection()

        enhanced_document = _build_enhanced_document(document, metadata)
        embedding = self.embedding_function([enhanced_document])[0]

        processed_metadata = self._prepare_zvec_metadata(metadata)
        doc = self._zvec.Doc(
            id=doc_id,
            vectors={"embedding": embedding},
            fields={
                "metadata_json": json.dumps(processed_metadata, ensure_ascii=False)
            },
        )

        self.collection.insert(doc)
        if not self._batch_mode:
            self.collection.optimize()

    def delete_document(self, doc_id: str):
        """Delete a document from Zvec."""
        if self.collection is None:
            return
        self.collection.delete(ids=doc_id)
        if not self._batch_mode:
            self.collection.optimize()

    # --- Read operations (read-only, no exclusive lock) ---------------

    def has_document(self, doc_id: str) -> bool:
        """Check if a document exists in the Zvec collection."""
        if self.collection is None:
            return False
        result = self.collection.fetch(doc_id)
        return bool(result)

    def existing_ids(self, doc_ids: List[str]) -> set:
        """Return the subset of *doc_ids* that exist in the collection."""
        if not doc_ids or self.collection is None:
            return set()
        result = self.collection.fetch(doc_ids)
        return set(result.keys())

    def get_stored_hashes(self, doc_ids: List[str]) -> Dict[str, Optional[str]]:
        """Return {doc_id: content_hash} for each ID. Missing IDs omitted."""
        if not doc_ids or self.collection is None:
            return {}
        fetched = self.collection.fetch(doc_ids)
        out: Dict[str, Optional[str]] = {}
        for did, doc in fetched.items():
            meta = json.loads(doc.fields.get("metadata_json", "{}"))
            out[did] = meta.get("content_hash")
        return out

    def search(self, query: str, k: int = 5) -> dict:
        """Search for similar documents. Returns ChromaDB-compatible result format."""
        empty_result: dict = {"ids": [[]], "metadatas": [[]], "distances": [[]]}

        if self.collection is None:
            return empty_result

        embeddings = self.embedding_function([query])
        if not embeddings:
            return empty_result

        results = self.collection.query(
            vectors=self._zvec.VectorQuery(
                field_name="embedding", vector=embeddings[0]
            ),
            topk=k,
        )

        if not results:
            return empty_result

        ids = []
        metadatas = []
        distances = []

        for doc in results:
            ids.append(doc.id)
            distances.append(doc.score)
            metadatas.append(self._parse_doc_metadata(doc))

        return {
            "ids": [ids],
            "metadatas": [metadatas],
            "distances": [distances],
        }

    # --- Helpers ------------------------------------------------------

    @staticmethod
    def _prepare_zvec_metadata(metadata: Dict) -> Dict:
        """Convert metadata values for Zvec JSON storage."""
        processed = {}
        for key, value in metadata.items():
            if isinstance(value, (list, dict)):
                processed[key] = value
            elif value is None:
                processed[key] = None
            else:
                processed[key] = str(value)
        return processed

    @staticmethod
    def _parse_doc_metadata(doc) -> dict:
        """Deserialize metadata from a Zvec doc's fields."""
        meta_str = doc.fields.get("metadata_json", "{}")
        meta = json.loads(meta_str) if isinstance(meta_str, str) else {}
        for key, value in meta.items():
            if isinstance(value, str):
                meta[key] = _deserialize_json_value(value)
        return meta
