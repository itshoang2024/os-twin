"""Folder → graph + vectors ingestion pipeline (EPIC-003).

The :class:`Ingestor` walks a directory, parses each supported file with
MarkItDown, chunks the markdown, optionally extracts entities + relations via
Anthropic, embeds the chunks through the configured embedding provider, and writes everything
into the namespace's Kuzu graph + zvec vector store.

Design points:

- **Per-file isolation.** A single bad file logs an error and increments the
  job's error counter — it does NOT crash the whole job.
- **Idempotency.** A SHA-256 of the file content is stored in every chunk's
  metadata as ``file_hash``. A second import skips files whose ``file_hash``
  is already present in the namespace's vector collection (unless
  ``force=True``).
- **Force re-ingest balances stats.** When ``force=True`` and the file is
  already present, the previous chunk count is subtracted from the manifest
  stats BEFORE the new chunks are added — so re-ingesting an unchanged
  folder leaves ``stats.files_indexed`` / ``stats.chunks`` invariant
  (Defect 2 in EPIC-003 QA).
- **Graceful LLM degradation.** When ``KnowledgeLLM.is_available()`` is False
  (no LLM model/API key configured), entity extraction is skipped silently — chunks
  still get embedded + indexed and the job completes.
- **Per-namespace base-dir isolation.** The Ingestor uses the
  :class:`NamespaceManager` instance's path methods, so a manager constructed
  with a custom ``base_dir`` writes vectors + graph under that directory
  (Defect 1 in EPIC-003 QA).
- **Lazy heavy imports.** ``markitdown``, ``zvec`` and ``kuzu`` are not imported
  until the worker thread actually needs them (``Ingestor.__init__`` is cheap).

The Ingestor is normally driven by :class:`dashboard.knowledge.jobs.JobManager`
through :meth:`KnowledgeService.import_folder`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from dashboard.knowledge.chunking import (
    SlidingWindowChunker,
    VisionSlidingWindowConverter,
    flat_chunk_text,
)
from dashboard.knowledge.config import (
    EMBEDDING_DIMENSION,
    IMAGE_EXTENSIONS,
    SLIDING_WINDOW_OVERLAP,
    SLIDING_WINDOW_SIZE,
    SUPPORTED_DOCUMENT_EXTENSIONS,
)
from dashboard.knowledge.jobs import JobEvent, JobState
from dashboard.knowledge.metrics import get_metrics_registry
from dashboard.knowledge.namespace import (
    ImportRecord,
    NamespaceManager,
    NamespaceNotFoundError,
)
from dashboard.knowledge.vector_store import NamespaceVectorStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class IngestOptions(BaseModel):
    """Tunable knobs for a single ingestion run."""

    chunk_size: int = 2048
    chunk_overlap: int = 512
    max_file_size_mb: int = 50
    force: bool = False
    extract_entities: bool = True
    language: str = "English"
    domain: str = ""
    llm_model: str = ""
    vision_ocr: bool = True
    vision_ocr_model: str = ""
    sliding_window_size: int = SLIDING_WINDOW_SIZE
    sliding_window_overlap: int = SLIDING_WINDOW_OVERLAP
    vision_ocr_dpi: int = 144


class FileEntry(BaseModel):
    """One concrete file discovered during the walk phase."""

    path: str
    size: int
    mtime: float
    extension: str
    content_hash: str = ""  # filled in once we read the bytes


# ---------------------------------------------------------------------------
# Helpers (chunking, hashing, walk)
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split ``text`` into overlapping windows of ~``chunk_size`` chars.

    Delegates to :func:`dashboard.knowledge.chunking.flat_chunk_text` so
    file_hash-based idempotency stays stable across this module and the
    legacy reader.
    """
    return flat_chunk_text(text, chunk_size=chunk_size, overlap=overlap)


def _is_hidden(path: Path) -> bool:
    """True iff any component of the path begins with a dot (POSIX hidden)."""
    return any(part.startswith(".") and part not in (".", "..") for part in path.parts)


# ---------------------------------------------------------------------------
# _NamespaceStore — thin per-namespace storage facade
# ---------------------------------------------------------------------------


class _NamespaceStore:
    """Per-namespace storage facade.

    Wraps a :class:`NamespaceVectorStore` (for chunk vectors, backed by zvec)
    and a :class:`KuzuLabelledPropertyGraph` (for the entity/relation graph).
    All heavy imports happen lazily so constructing the store is cheap.

    The vector path is computed via the supplied :class:`NamespaceManager`'s
    instance method (``nm.vector_dir(namespace)``) so a manager constructed
    with a custom ``base_dir`` writes to the test-isolated location instead
    of leaking into ``KNOWLEDGE_DIR`` (Defect 1 in EPIC-003 QA).

    EPIC-004: optional ``vector_store_factory`` and ``kuzu_factory`` kwargs
    let the caller (e.g. :class:`KnowledgeService`) inject cache-aware
    factories so this store reuses the service-level singletons instead of
    constructing duplicate handles. When omitted (standalone Ingestor use)
    the original lazy-create behaviour is preserved.

    Tests can substitute this whole class via :meth:`Ingestor._get_store` (we
    use duck-typing on the public method surface, not isinstance).
    """

    def __init__(
        self,
        namespace: str,
        namespace_manager: NamespaceManager | None = None,
        embedding_dimension: int = EMBEDDING_DIMENSION,
        vector_store_factory: Callable[[str], NamespaceVectorStore] | None = None,
        kuzu_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.namespace = namespace
        # Fall back to a default manager for back-compat with any external
        # callers (e.g. the EPIC-002 namespace tests directly instantiated
        # _NamespaceStore("ns") without passing a manager).
        self._nm = namespace_manager or NamespaceManager()
        self._dim = int(embedding_dimension)
        self._vs_factory = vector_store_factory
        self._kg_factory = kuzu_factory
        self._vstore: NamespaceVectorStore | None = None
        self._graph: Any = None
        self._vstore_lock = threading.Lock()
        self._graph_lock = threading.Lock()

    # ---- Vector store (zvec) -------------------------------------------

    def _get_vstore(self) -> NamespaceVectorStore:
        """Lazy-create / open the per-namespace zvec vector store.

        When a ``vector_store_factory`` was injected (e.g. by
        :class:`KnowledgeService`), the factory is used so the store comes
        from a centralised cache. Otherwise we construct our own — keeping
        standalone Ingestor use working.
        """
        if self._vstore is not None:
            return self._vstore
        with self._vstore_lock:
            if self._vstore is not None:
                return self._vstore
            if self._vs_factory is not None:
                self._vstore = self._vs_factory(self.namespace)
            else:
                self._vstore = NamespaceVectorStore(
                    vector_path=self._nm.vector_dir(self.namespace),
                    dimension=self._dim,
                    schema_name=f"knowledge_{self.namespace}",
                )
            return self._vstore

    # Back-compat shim: tests / external code that previously used
    # ``store._collection`` won't crash — they'll just see ``None`` until
    # something actually accesses the vector store.
    @property
    def _collection(self) -> Any:  # pragma: no cover — back-compat only
        return self._vstore

    def add_chunks(self, chunks: list[dict]) -> int:
        """Append a batch of embedded chunks to the namespace's vector store.

        Each ``chunk`` dict must have keys ``text``, ``embedding`` and
        ``metadata``. ``metadata`` is the dict produced by ``_parse_file``
        — its recognised keys are described in :meth:`NamespaceVectorStore.add_chunks`.
        Returns the count actually persisted (some may fail individually; logged).
        """
        if not chunks:
            return 0
        return self._get_vstore().add_chunks(chunks)

    def has_file_hash(self, file_hash: str) -> bool:
        """True iff the namespace already has at least one chunk with this file_hash."""
        if not file_hash:
            return False
        return self._get_vstore().has_file_hash(file_hash)

    def count_by_file_hash(self, file_hash: str) -> int:
        """Return the number of chunks currently stored with this file_hash."""
        if not file_hash:
            return 0
        return self._get_vstore().count_by_file_hash(file_hash)

    def delete_by_file_hash(self, file_hash: str) -> int:
        """Delete every chunk in this namespace with the given file_hash. Returns the count."""
        if not file_hash:
            return 0
        return self._get_vstore().delete_by_file_hash(file_hash)

    # ---- Kuzu graph ----------------------------------------------------

    def _get_graph(self) -> Any:
        """Lazy-create / open the per-namespace Kuzu graph.

        EPIC-004: when a ``kuzu_factory`` was injected by
        :class:`KnowledgeService`, that factory is used so the graph
        reference comes from the centralised cache. Otherwise we fall back
        to the per-namespace constructor — preserves standalone use.
        """
        with self._graph_lock:
            if self._graph is not None:
                return self._graph
            if self._kg_factory is not None:
                self._graph = self._kg_factory(self.namespace)
                return self._graph
            from dashboard.knowledge.graph.index.kuzudb import (  # noqa: WPS433
                KuzuLabelledPropertyGraph,
            )

            self._graph = KuzuLabelledPropertyGraph.for_namespace(self.namespace)
            return self._graph




# ---------------------------------------------------------------------------
# Ingestor
# ---------------------------------------------------------------------------


class Ingestor:
    """Orchestrates folder → graph + vectors ingestion.

    Construction is cheap; heavy work happens inside :meth:`run`. The Ingestor
    is intended to be used either directly (sync) or via
    :class:`dashboard.knowledge.jobs.JobManager` for background execution.
    """

    def __init__(
        self,
        namespace_manager: NamespaceManager | None = None,
        embedder: Any | None = None,
        llm: Any | None = None,
        vector_store_factory: Callable[[str], NamespaceVectorStore] | None = None,
        kuzu_factory: Callable[[str], Any] | None = None,
        graph_index_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self._nm = namespace_manager or NamespaceManager()
        # Embedder + llm are lazy-instantiated on first use to keep imports
        # cheap when ingestion is never invoked.
        self._embedder_override = embedder
        self._llm_override = llm
        self._embedder: Any = None
        self._llm: Any = None
        # EPIC-004: cache-aware factories let the KnowledgeService inject
        # its centralised handles. When None, the per-namespace store
        # constructs its own (standalone-Ingestor mode).
        self._vs_factory = vector_store_factory
        self._kg_factory = kuzu_factory
        # Graph-RAG integration: when injected, _extract_and_embed()
        # delegates to PropertyGraphIndex.insert_nodes() so entity
        # extraction, graph writes, and vector writes all flow through
        # the llama-index pipeline — matching the query-engine schema.
        self._graph_index_factory = graph_index_factory
        self._graph_indexes: dict[str, Any] = {}
        self._graph_index_lock = threading.Lock()
        # One store per namespace — keeps zvec handle / Kuzu connection alive
        # across files in the same run.
        self._stores: dict[str, _NamespaceStore] = {}
        self._stores_lock = threading.Lock()
        # Cached MarkItDown converter — vision-enabled when an Anthropic
        # key is in the environment (ADR-14). Lazily constructed to keep
        # __init__ cheap and to honour env-var changes between Ingestor
        # constructions.
        self._markitdown: Any = None
        self._markitdown_lock = threading.Lock()
        self._vision_ocr_model: str = ""
        self._vision_ocr_client: Any = None
        self._llm_model_override: str = ""

    # ---- Lazy accessors ------------------------------------------------

    def _get_embedder(self) -> Any:
        if self._embedder is not None:
            return self._embedder
        if self._embedder_override is not None:
            self._embedder = self._embedder_override
            return self._embedder
        from dashboard.knowledge.embeddings import KnowledgeEmbedder  # noqa: WPS433

        self._embedder = KnowledgeEmbedder()
        return self._embedder

    def _get_llm(self, model: str | None = None) -> Any:
        if self._llm is not None:
            return self._llm
        if self._llm_override is not None:
            self._llm = self._llm_override
            return self._llm
        from dashboard.knowledge.llm import KnowledgeLLM  # noqa: WPS433

        self._llm = KnowledgeLLM(model=model or None)
        return self._llm

    def _apply_llm_model_override(self, model: str) -> None:
        """Reset cached LLM and graph indexes so ``model`` is used for entity extraction.

        When the caller specifies ``IngestOptions.llm_model``, the service-level
        ``KnowledgeLLM`` singleton may be using a different model. This method
        stores the override model and invalidates any cached graph indexes so
        they pick up the new LLM on next access via :meth:`_get_graph_index`.
        """
        self._llm_model_override = model
        with self._graph_index_lock:
            self._graph_indexes.clear()

    def _get_markitdown_converter(self, options: IngestOptions | None = None) -> Any:
        """Lazy-construct the per-Ingestor MarkItDown client.

        Uses :func:`dashboard.llm_client.create_openai_sync_client` to build
        an OpenAI-compatible sync client from the configured vision OCR model.
        This single client serves both MarkItDown's ``ImageConverter`` and
        :class:`VisionSlidingWindowConverter._vision_ocr` Path 2.

        When ``options.vision_ocr`` is True (default), registers a
        :class:`VisionSlidingWindowConverter` at higher priority than the
        built-in PdfConverter so PDFs are routed through vision LLM OCR
        when an LLM client is available.
        """
        vision_model = ""
        if options:
            vision_model = options.vision_ocr_model or options.llm_model

        if self._markitdown is not None and self._vision_ocr_model == vision_model:
            return self._markitdown

        with self._markitdown_lock:
            if self._markitdown is not None and self._vision_ocr_model == vision_model:
                return self._markitdown

            from dashboard.knowledge.graph.parsers.markitdown_reader import (  # noqa: WPS433
                MarkitdownReader,
            )

            md = MarkitdownReader()._get_markitdown()

            vision_client = None
            if vision_model:
                try:
                    from dashboard.llm_client import create_openai_sync_client  # noqa: WPS433
                    vision_client = create_openai_sync_client(model=vision_model)
                except Exception as exc:
                    logger.warning(
                        "Failed to create vision OCR client for %s: %s",
                        vision_model, exc,
                    )

            if vision_client is not None:
                md = type(md)(
                    llm_client=vision_client,
                    llm_model=vision_model,
                )
                self._vision_ocr_client = vision_client

            if options is None or options.vision_ocr:
                ws = options.sliding_window_size if options else SLIDING_WINDOW_SIZE
                ov = options.sliding_window_overlap if options else SLIDING_WINDOW_OVERLAP
                dpi = options.vision_ocr_dpi if options else 144
                converter = VisionSlidingWindowConverter(
                    window_size=ws,
                    overlap=ov,
                    dpi=dpi,
                )
                md.register_converter(converter, priority=-1.0)

            self._markitdown = md
            self._vision_ocr_model = vision_model
            return self._markitdown

    def _get_graph_index(self, namespace: str) -> Any:
        """Return a cached PropertyGraphIndex for ``namespace``.

        Delegates to the ``graph_index_factory`` injected by
        :class:`KnowledgeService`. Returns ``None`` when no factory is
        configured (standalone Ingestor mode — should not happen in
        production since the service always injects one).

        When ``_llm_model_override`` is set (via ``IngestOptions.llm_model``),
        passes it to the factory so the graph extractor uses the requested model.
        """
        if self._graph_index_factory is None:
            return None
        with self._graph_index_lock:
            idx = self._graph_indexes.get(namespace)
            if idx is None:
                factory_kwargs: dict[str, Any] = {}
                if getattr(self, "_llm_model_override", None):
                    factory_kwargs["llm_model"] = self._llm_model_override
                idx = self._graph_index_factory(namespace, **factory_kwargs)
                self._graph_indexes[namespace] = idx
            return idx

    def _get_store(self, namespace: str) -> _NamespaceStore:
        """Return the per-namespace store, creating it on first request.

        The store is bound to ``self._nm`` so its vector + graph paths honour
        any custom ``base_dir`` (Defect 1 fix). When the Ingestor was
        constructed with cache-aware factories (EPIC-004), the store
        forwards them so the underlying vstore / kuzu refs come from the
        service-level cache instead of being constructed locally.
        """
        with self._stores_lock:
            store = self._stores.get(namespace)
            if store is None:
                store = _NamespaceStore(
                    namespace,
                    namespace_manager=self._nm,
                    vector_store_factory=self._vs_factory,
                    kuzu_factory=self._kg_factory,
                )
                self._stores[namespace] = store
            return store

    # ---- Walk ----------------------------------------------------------

    def _walk_folder(
        self, folder_path: Path, options: IngestOptions
    ) -> Iterator[FileEntry]:
        """Yield FileEntry records for every supported file under ``folder_path``."""
        max_bytes = options.max_file_size_mb * 1024 * 1024
        # rglob walks recursively; sort for deterministic ordering.
        for path in sorted(folder_path.rglob("*")):
            if not path.is_file():
                continue
            # Skip hidden files / dotted directories anywhere in the relative path.
            try:
                rel = path.relative_to(folder_path)
            except ValueError:
                rel = path
            if any(part.startswith(".") for part in rel.parts):
                continue
            ext = path.suffix.lower()
            if ext not in SUPPORTED_DOCUMENT_EXTENSIONS:
                continue
            try:
                stat = path.stat()
            except OSError as exc:
                logger.exception("Could not stat %s: %s", path, exc)
                continue
            if stat.st_size > max_bytes:
                logger.info(
                    "Skipping %s: %d bytes exceeds cap %d", path, stat.st_size, max_bytes
                )
                continue
            yield FileEntry(
                path=str(path.resolve()),
                size=stat.st_size,
                mtime=stat.st_mtime,
                extension=ext,
            )

    # ---- Hash ----------------------------------------------------------

    def _hash_file(self, path: Path) -> str:
        """Compute SHA-256 of file contents (streaming, 64 KiB chunks)."""
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(64 * 1024), b""):
                h.update(block)
        return h.hexdigest()

    # ---- Parse / chunk -------------------------------------------------

    def _parse_file(
        self, file_entry: FileEntry, options: IngestOptions
    ) -> list[dict]:
        """Return a list of chunk dicts: ``{text, metadata}``.

        Strategy:
        1. Try MarkItDown for any supported type; it covers Office, PDF, HTML,
           and many text formats out of the box. When ``options.vision_ocr`` is
           True and a vision LLM is available, PDFs are routed through
           :class:`VisionSlidingWindowConverter` for page-level OCR.
        2. If MarkItDown returns nothing or fails, fall back to a UTF-8 read
           (with replacement) for text-ish extensions.
        3. Chunk the resulting text. Large documents (>
           ``chunk_size * 10`` chars) use :class:`SlidingWindowChunker`
           with page-range metadata; smaller documents use flat char chunking.

        Empty list on parse failure or empty file — caller treats this as a
        skip, not a hard error.
        """
        path = Path(file_entry.path)
        parse_t0 = time.monotonic()

        # --- 1) MarkItDown (with Anthropic vision when key set, ADR-14) ---
        text = ""
        t_markitdown_start = time.monotonic()
        try:
            converter = self._get_markitdown_converter(options)
            convert_kwargs: dict[str, Any] = {}
            if self._vision_ocr_client is not None:
                convert_kwargs["llm_client"] = self._vision_ocr_client
            if self._vision_ocr_model:
                convert_kwargs["llm_model"] = self._vision_ocr_model
            result = converter.convert(str(path), **convert_kwargs)
            text = (
                getattr(result, "text_content", None)
                or getattr(result, "text", None)
                or ""
            )
            t_markitdown = time.monotonic() - t_markitdown_start
            logger.info(
                "[TRACE] parse_file/markitdown: %.3fs, %s, %d chars extracted",
                t_markitdown, file_entry.path, len(text),
            )
        except Exception as exc:  # noqa: BLE001
            t_markitdown = time.monotonic() - t_markitdown_start
            exc_name = type(exc).__name__
            if "MissingDependency" in exc_name:
                # Dependency-resolution errors are environment problems, not
                # transient failures.  Surface them loudly so the operator can
                # ``pip install markitdown[all]`` (or the missing extra).
                logger.exception(
                    "MarkItDown dependency error on %s — %s. "
                    "Install missing extras: pip install 'markitdown[all]'",
                    path.name, exc,
                )
                raise  # Let the caller report as "Failed", not "Skipped"
            logger.error("debussing on %s: %s", path, exc)
            logger.info(
                "[TRACE] parse_file/markitdown: %.3fs, %s, FAILED (%s)",
                t_markitdown, file_entry.path, exc_name,
            )
            text = ""

        # --- 2) Fallback: plain-text read for text-ish files ----------
        if not text and file_entry.extension in {
            ".txt", ".md", ".json", ".csv", ".xml", ".yaml", ".yml", ".html", ".htm"
        }:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.exception("Could not read %s as text: %s", path, exc)
                return []

        # --- 3) Image-specific empty-content warning (ADR-14) -----------
        # Image files produce no markdown when no Anthropic key is present
        # (or when MarkItDown's vision call fails). Log once per file then
        # treat as a skip — never a hard failure.
        if file_entry.extension in IMAGE_EXTENSIONS and not (text and text.strip()):
            if os.environ.get("ANTHROPIC_API_KEY"):
                logger.warning(
                    "Image %s: produced no text (ANTHROPIC_API_KEY set but vision "
                    "failed or returned empty). Skipping.",
                    file_entry.path,
                )
            else:
                logger.warning(
                    "Image %s: produced no text (ANTHROPIC_API_KEY not set; vision "
                    "OCR disabled). Skipping.",
                    file_entry.path,
                )
            return []

        if not text or not text.strip():
            return []

        # --- 4) Chunk -------------------------------------------------
        t_chunk_start = time.monotonic()

        sliding_window_threshold = options.chunk_size * 10
        if len(text) > sliding_window_threshold:
            chunker = SlidingWindowChunker(
                window_size=options.sliding_window_size,
                overlap=options.sliding_window_overlap,
                page_chars=options.chunk_size,
            )
            raw_chunks = chunker.chunk(text)
            chunks_text = [c["text"] for c in raw_chunks]
            chunk_metas = [c["metadata"] for c in raw_chunks]
        else:
            chunks_text = _chunk_text(text, options.chunk_size, options.chunk_overlap)
            chunk_metas = [{} for _ in chunks_text]

        t_chunk = time.monotonic() - t_chunk_start
        if not chunks_text:
            return []

        out: list[dict] = []
        for i, (chunk, cmeta) in enumerate(zip(chunks_text, chunk_metas)):
            metadata = {
                "file_path": file_entry.path,
                "filename": path.name,
                "chunk_index": i,
                "total_chunks": len(chunks_text),
                "file_size": file_entry.size,
                "mtime": file_entry.mtime,
                "extension": file_entry.extension,
                "file_hash": file_entry.content_hash,
                "chunk_hash": _sha256(chunk.encode("utf-8")),
            }
            metadata.update(cmeta)
            out.append({"text": chunk, "metadata": metadata})

        parse_total = time.monotonic() - parse_t0
        logger.info(
            "[TRACE] parse_file total: %.3fs (markitdown+chunk), %s, %d chunks, %d chars",
            parse_total, file_entry.path, len(chunks_text), len(text),
        )
        get_metrics_registry().histogram("ingest_parse_seconds").observe(parse_total)
        return out

    # ---- Per-file pipeline --------------------------------------------

    def _is_already_indexed(self, namespace: str, content_hash: str) -> bool:
        """True iff Chroma already has at least one chunk with this file_hash."""
        try:
            store = self._get_store(namespace)
            return store.has_file_hash(content_hash)
        except Exception as exc:  # noqa: BLE001
            logger.exception("is_already_indexed check failed: %s", exc)
            return False

    def _extract_and_embed(
        self,
        namespace: str,
        file_entry: FileEntry,
        chunks: list[dict],
        options: IngestOptions,
    ) -> dict:
        """Insert chunks via PropertyGraphIndex — embeddings, entity extraction,
        vector writes, and graph writes are all handled by the llama-index
        pipeline in a single ``insert_nodes()`` call.

        Returns counts: ``{entities_added, relations_added, chunks_added, chunks_skipped}``.
        """
        if not chunks:
            return {
                "entities_added": 0,
                "relations_added": 0,
                "chunks_added": 0,
                "chunks_skipped": 0,
            }

        embed_t0 = time.monotonic()

        graph_index = self._get_graph_index(namespace)
        if graph_index is None:
            # No PropertyGraphIndex available — this is a programming error
            # in production (service must always inject the factory).
            logger.error(
                "No graph_index_factory configured — cannot ingest into %r. "
                "Ensure KnowledgeService provides the factory.",
                namespace,
            )
            raise RuntimeError(
                f"graph_index_factory not configured for namespace {namespace!r}"
            )

        # Convert chunk dicts → llama-index TextNode objects.
        from llama_index.core.schema import TextNode  # noqa: WPS433

        text_nodes: list[TextNode] = []
        for c in chunks:
            node = TextNode(
                text=c["text"],
                metadata=c["metadata"],
            )
            text_nodes.append(node)

        # Let PropertyGraphIndex handle the full pipeline:
        #  1. Run nodes through GraphRAGExtractor (entity extraction + retry)
        #  2. Embed text chunks + entity nodes via EmbedderAdapter
        #  3. Write entities + relations to Kuzu via GraphRAGStore
        #  4. Write text chunks as ChunkNode to Kuzu (entity→chunk linkage)
        #  5. Write entity embeddings to zvec via ZvecVectorStoreAdapter
        #
        # Capture graph counts BEFORE insert_nodes so we can compute the
        # delta as a fallback.  We prefer reading extractor metrics because
        # they align with the KG_NODES_KEY / KG_RELATIONS_KEY contract —
        # the same extractor that populates those keys also updates
        # ExtractionMetrics.total_entities / total_relationships.
        # However, the extractor metrics are cumulative across ALL calls to
        # the extractor (they reset on each __call__ invocation), so for a
        # single insert_nodes() call they should be accurate.
        store_pre = self._get_store(namespace)
        kg_pre = store_pre._get_graph()
        pre_entities = kg_pre.count_entities()
        pre_relations = kg_pre.count_relations()

        t_insert_start = time.monotonic()
        try:
            graph_index.insert_nodes(text_nodes)
        except Exception as exc:  # noqa: BLE001
            t_insert = time.monotonic() - t_insert_start
            logger.info(
                "[TRACE] extract_and_embed/insert_nodes: %.3fs, %s, FAILED",
                t_insert, file_entry.path,
            )
            logger.exception(
                "PropertyGraphIndex.insert_nodes failed for %s: %s",
                file_entry.path,
                exc,
            )
            raise
        t_insert = time.monotonic() - t_insert_start
        logger.info(
            "[TRACE] extract_and_embed/insert_nodes: %.3fs, %s, %d nodes",
            t_insert, file_entry.path, len(text_nodes),
        )
        get_metrics_registry().histogram("ingest_insert_nodes_seconds").observe(t_insert)

        # Primary: read entity/relation counts from extractor metrics.
        # These are populated by the same GraphRAGExtractor.__call__ that
        # sets KG_NODES_KEY / KG_RELATIONS_KEY on the transformed nodes,
        # so they are aligned with the llama-index contract.
        entities_added = 0
        relations_added = 0
        for ext in getattr(graph_index, "kg_extractors", []):
            m = getattr(ext, "metrics", None)
            if m is not None:
                entities_added += getattr(m, "total_entities", 0)
                relations_added += getattr(m, "total_relationships", 0)

        # Fallback: if extractor metrics are zero (e.g. extractor didn't
        # run or metrics attribute missing), compute delta from Kuzu graph
        # counts before/after insert_nodes().
        if entities_added == 0 and relations_added == 0:
            store_post = self._get_store(namespace)
            kg_post = store_post._get_graph()
            entities_added = max(0, kg_post.count_entities() - pre_entities)
            relations_added = max(0, kg_post.count_relations() - pre_relations)
            logger.debug(
                "Extractor metrics were zero; using Kuzu delta: %d entities, %d relations",
                entities_added, relations_added,
            )
        else:
            logger.debug(
                "Extractor metrics: %d entities, %d relations",
                entities_added, relations_added,
            )

        # Persist text chunks to the NamespaceVectorStore (zvec) for
        # file-hash-based idempotency tracking. The PropertyGraphIndex
        # writes entity embeddings to its own vector store, but the
        # per-file chunk vectors need to live in the namespace store so
        # _is_already_indexed / count_by_file_hash / delete_by_file_hash
        # can function correctly for skip-if-unchanged and force-reingest.
        t_vstore_start = time.monotonic()
        store = self._get_store(namespace)
        embedder = self._get_embedder()
        texts = [c["text"] for c in chunks]
        t_embed_start = time.monotonic()
        vectors = embedder.embed(texts)
        t_embed = time.monotonic() - t_embed_start
        logger.info(
            "[TRACE] extract_and_embed/embed_chunks: %.3fs, %s, %d texts",
            t_embed, file_entry.path, len(texts),
        )
        get_metrics_registry().histogram("ingest_embed_seconds").observe(t_embed)

        store_chunks = []
        for c, vec in zip(chunks, vectors):
            store_chunks.append({
                "text": c["text"],
                "embedding": vec,
                "metadata": c["metadata"],
            })
        try:
            store.add_chunks(store_chunks)
        except Exception as exc:  # noqa: BLE001
            t_vstore = time.monotonic() - t_vstore_start
            logger.info(
                "[TRACE] extract_and_embed/vstore_write: %.3fs, %s, FAILED",
                t_vstore, file_entry.path,
            )
            logger.exception(
                "Failed to persist chunks to namespace store for %s: %s",
                file_entry.path,
                exc,
            )
            raise
        t_vstore = time.monotonic() - t_vstore_start
        logger.info(
            "[TRACE] extract_and_embed/vstore_write: %.3fs, %s, %d chunks",
            t_vstore, file_entry.path, len(store_chunks),
        )
        get_metrics_registry().histogram("ingest_vstore_write_seconds").observe(t_vstore)

        embed_total = time.monotonic() - embed_t0
        logger.info(
            "[TRACE] extract_and_embed total: %.3fs, %s, %d entities, %d relations, %d chunks",
            embed_total, file_entry.path, entities_added, relations_added, len(text_nodes),
        )
        get_metrics_registry().histogram("ingest_extract_and_embed_seconds").observe(embed_total)

        return {
            "entities_added": entities_added,
            "relations_added": relations_added,
            "chunks_added": len(text_nodes),
            "chunks_skipped": 0,
        }

    # ---- run -----------------------------------------------------------

    def run(
        self,
        namespace: str,
        folder_path: str,
        options: IngestOptions | None = None,
        *,
        emit: Callable[[JobEvent], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict:
        """Synchronously ingest ``folder_path`` into ``namespace``.

        Designed to be invoked from a worker thread of
        :class:`~dashboard.knowledge.jobs.JobManager`. ``emit`` is the
        progress-event sink; ``cancel_check`` is polled before each file so
        a JobManager.cancel() can short-circuit the loop.

        Returns a result summary dict, suitable for ``JobStatus.result``.
        """
        options = options or IngestOptions()
        emit = emit or (lambda ev: None)
        cancel_check = cancel_check or (lambda: False)

        # When the caller specifies an LLM model override, ensure the
        # graph-index and KnowledgeLLM use it for entity extraction.
        if options.llm_model:
            self._apply_llm_model_override(options.llm_model)

        started_at = _utcnow()
        run_t0 = time.monotonic()

        # Get metrics registry for instrumentation
        metrics = get_metrics_registry()

        # ---- 1) Validate inputs --------------------------------------
        folder = Path(folder_path)
        if not folder.exists():
            raise FileNotFoundError(folder_path)
        if not folder.is_dir():
            raise NotADirectoryError(folder_path)
        # Namespace must exist; KnowledgeService.import_folder pre-creates.
        meta = self._nm.get(namespace)
        if meta is None:
            raise NamespaceNotFoundError(namespace)

        # ---- 2) Walk -------------------------------------------------
        emit(
            JobEvent(
                timestamp=_utcnow(),
                state=JobState.RUNNING,
                message="Walking folder",
                progress_current=0,
                progress_total=0,
            )
        )
        t_walk_start = time.monotonic()
        files = list(self._walk_folder(folder, options))
        t_walk = time.monotonic() - t_walk_start
        logger.info("[TRACE] walk_folder: %.3fs, %d files discovered", t_walk, len(files))

        # Compute file hashes upfront so we can dedup.
        t_hash_start = time.monotonic()
        for fe in files:
            try:
                fe.content_hash = self._hash_file(Path(fe.path))
            except OSError as exc:
                logger.exception("Could not hash %s: %s", fe.path, exc)
                fe.content_hash = ""
        t_hash = time.monotonic() - t_hash_start
        logger.info("[TRACE] hash_files: %.3fs, %d files hashed", t_hash, len(files))

        n = len(files)
        emit(
            JobEvent(
                timestamp=_utcnow(),
                state=JobState.RUNNING,
                message=f"Found {n} file(s)",
                progress_current=0,
                progress_total=n,
                detail={"file_count": n},
            )
        )

        # ---- 3) Per-file pipeline ------------------------------------
        files_indexed = 0
        files_skipped = 0
        files_failed = 0
        total_chunks = 0
        total_entities = 0
        total_relations = 0
        errors: list[str] = []

        for i, fe in enumerate(files, start=1):
            if cancel_check():
                emit(
                    JobEvent(
                        timestamp=_utcnow(),
                        state=JobState.CANCELLED,
                        message=f"Cancelled after {i-1}/{n} files",
                        progress_current=i - 1,
                        progress_total=n,
                    )
                )
                break

            filename = Path(fe.path).name

            # 3a) Idempotency check.
            if not options.force and fe.content_hash and self._is_already_indexed(namespace, fe.content_hash):
                files_skipped += 1
                emit(
                    JobEvent(
                        timestamp=_utcnow(),
                        state=JobState.RUNNING,
                        message=f"Skipped {filename} (already indexed)",
                        progress_current=i,
                        progress_total=n,
                        detail={"file": fe.path, "status": "skipped"},
                    )
                )
                continue

            # 3b) Force-reingest: subtract previous-run contribution from
            # manifest stats BEFORE deleting + re-adding the chunks. This
            # is the Defect 2 fix from EPIC-003 QA — without it, re-ingesting
            # an unchanged folder doubles ``files_indexed`` / ``chunks``.
            if options.force and fe.content_hash:
                store_for_force = self._get_store(namespace)
                try:
                    if store_for_force.has_file_hash(fe.content_hash):
                        old_chunk_count = 0
                        try:
                            old_chunk_count = store_for_force.count_by_file_hash(fe.content_hash)
                        except Exception as exc:  # noqa: BLE001
                            logger.exception("count_by_file_hash failed for %s: %s", fe.path, exc)
                        try:
                            store_for_force.delete_by_file_hash(fe.content_hash)
                        except Exception as exc:  # noqa: BLE001
                            logger.exception("Force-delete failed for %s: %s", fe.path, exc)
                        # Roll back the previous run's contribution so the
                        # new add doesn't double-count. Negative deltas are
                        # supported by NamespaceManager.update_stats.
                        if old_chunk_count > 0:
                            try:
                                self._nm.update_stats(
                                    namespace,
                                    files_indexed=-1,
                                    chunks=-int(old_chunk_count),
                                    vectors=-int(old_chunk_count),
                                )
                            except Exception as exc:  # noqa: BLE001
                                logger.exception(
                                    "Could not roll back stats before force re-ingest of %s: %s",
                                    fe.path,
                                    exc,
                                )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Force-reingest pre-cleanup failed for %s: %s", fe.path, exc)

            # 3c) Parse → chunk.
            t_parse_start = time.monotonic()
            try:
                chunks = self._parse_file(fe, options)
            except Exception as exc:  # noqa: BLE001
                t_parse = time.monotonic() - t_parse_start
                files_failed += 1
                logger.exception("Parse failed for %s (%.3fs)", fe.path, t_parse)
                err = f"{fe.path}: parse failed: {exc}"
                errors.append(err)
                emit(
                    JobEvent(
                        timestamp=_utcnow(),
                        state=JobState.RUNNING,
                        message=f"Failed {filename}",
                        progress_current=i,
                        progress_total=n,
                        detail={"file": fe.path, "status": "failed", "error": err},
                    )
                )
                continue

            if not chunks:
                # Empty / unreadable — count as skipped, not a hard failure.
                files_skipped += 1
                emit(
                    JobEvent(
                        timestamp=_utcnow(),
                        state=JobState.RUNNING,
                        message=f"Skipped {filename} (no content)",
                        progress_current=i,
                        progress_total=n,
                        detail={"file": fe.path, "status": "skipped"},
                    )
                )
                continue

            # 3d) Embed + (optional) extract.
            t_extract_start = time.monotonic()
            try:
                counts = self._extract_and_embed(namespace, fe, chunks, options)
            except Exception as exc:  # noqa: BLE001
                t_extract = time.monotonic() - t_extract_start
                files_failed += 1
                logger.exception("embed/extract failed for %s (%.3fs)", fe.path, t_extract)
                err = f"{fe.path}: embed/extract failed: {exc}"
                errors.append(err)
                emit(
                    JobEvent(
                        timestamp=_utcnow(),
                        state=JobState.RUNNING,
                        message=f"Failed {filename}",
                        progress_current=i,
                        progress_total=n,
                        detail={"file": fe.path, "status": "failed", "error": err},
                    )
                )
                continue

            files_indexed += 1
            total_chunks += counts["chunks_added"]
            total_entities += counts["entities_added"]
            total_relations += counts["relations_added"]
            t_file_total = time.monotonic() - t_parse_start
            # Record metrics for this file
            metrics.counter("ingest_files_total").inc()
            metrics.counter("ingest_bytes_total").inc(fe.size)
            logger.info(
                "[TRACE] file_total: %.3fs, %s, parse+embed, %d chunks, %d entities",
                t_file_total, fe.path, counts["chunks_added"], counts["entities_added"],
            )
            emit(
                JobEvent(
                    timestamp=_utcnow(),
                    state=JobState.RUNNING,
                    message=f"Processed {filename}",
                    progress_current=i,
                    progress_total=n,
                    detail={
                        "file": fe.path,
                        "status": "processed",
                        "chunks": counts["chunks_added"],
                        "entities": counts["entities_added"],
                    },
                )
            )

        # ---- 4) Update manifest stats + import record ----------------
        finished_at = _utcnow()
        try:
            self._nm.update_stats(
                namespace,
                files_indexed=files_indexed,
                chunks=total_chunks,
                entities=total_entities,
                relations=total_relations,
                vectors=total_chunks,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Could not update namespace stats: %s", exc)

        try:
            self._nm.append_import(
                namespace,
                ImportRecord(
                    folder_path=str(folder),
                    started_at=started_at,
                    finished_at=finished_at,
                    status="completed" if files_failed == 0 else "completed_with_errors",
                    file_count=n,
                    error_count=files_failed,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Could not append import record: %s", exc)

        elapsed = time.monotonic() - run_t0
        # Record ingestion latency
        metrics.histogram("ingest_latency_seconds").observe(elapsed)
        logger.info(
            "[TRACE] run total: %.3fs, namespace=%s, %d/%d indexed, %d skipped, %d failed, "
            "%d chunks, %d entities, %d relations",
            elapsed, namespace, files_indexed, n, files_skipped, files_failed,
            total_chunks, total_entities, total_relations,
        )
        result = {
            "namespace": namespace,
            "folder_path": str(folder),
            "files_total": n,
            "files_indexed": files_indexed,
            "files_skipped": files_skipped,
            "files_failed": files_failed,
            "chunks_added": total_chunks,
            "entities_added": total_entities,
            "relations_added": total_relations,
            "errors": errors,
            "elapsed_seconds": round(elapsed, 3),
        }
        return result


    # ---- ingest_text ---------------------------------------------------

    def ingest_text(
        self,
        namespace: str,
        text: str,
        *,
        source_label: str = "inline",
        options: IngestOptions | None = None,
        emit: Callable[[JobEvent], None] | None = None,
    ) -> dict:
        """Synchronously ingest plain text into ``namespace``.

        Unlike :meth:`run` (which walks a folder and parses files), this
        method skips file-walking, MarkItDown parsing, and vision OCR
        entirely — the text is already parsed.  It goes straight to
        chunking → embedding → entity extraction.

        A synthetic :class:`FileEntry` is created with
        ``path="inline://{source_label}"`` so downstream metadata and
        idempotency logic work without modification.

        Returns a result summary dict matching the shape returned by
        :meth:`run`.
        """
        options = options or IngestOptions()
        emit = emit or (lambda ev: None)

        if options.llm_model:
            self._apply_llm_model_override(options.llm_model)

        started_at = _utcnow()
        run_t0 = time.monotonic()
        metrics = get_metrics_registry()

        meta = self._nm.get(namespace)
        if meta is None:
            raise NamespaceNotFoundError(namespace)

        emit(JobEvent(
            timestamp=_utcnow(),
            state=JobState.RUNNING,
            message="Ingesting text",
            progress_current=0,
            progress_total=1,
        ))

        text_bytes = text.encode("utf-8")
        content_hash = _sha256(text_bytes)
        now_ts = time.time()

        fe = FileEntry(
            path=f"inline://{source_label}",
            size=len(text_bytes),
            mtime=now_ts,
            extension=".txt",
            content_hash=content_hash,
        )

        if not options.force and content_hash and self._is_already_indexed(namespace, content_hash):
            elapsed = time.monotonic() - run_t0
            emit(JobEvent(
                timestamp=_utcnow(),
                state=JobState.RUNNING,
                message="Skipped (already indexed)",
                progress_current=1,
                progress_total=1,
                detail={"source": source_label, "status": "skipped"},
            ))
            return {
                "namespace": namespace,
                "source_label": source_label,
                "chunks_added": 0,
                "entities_added": 0,
                "relations_added": 0,
                "errors": [],
                "elapsed_seconds": round(elapsed, 3),
            }

        if options.force and content_hash:
            store_for_force = self._get_store(namespace)
            try:
                if store_for_force.has_file_hash(content_hash):
                    old_chunk_count = 0
                    try:
                        old_chunk_count = store_for_force.count_by_file_hash(content_hash)
                    except Exception as exc:
                        logger.exception("count_by_file_hash failed for inline %s: %s", source_label, exc)
                    try:
                        store_for_force.delete_by_file_hash(content_hash)
                    except Exception as exc:
                        logger.exception("Force-delete failed for inline %s: %s", source_label, exc)
                    if old_chunk_count > 0:
                        try:
                            self._nm.update_stats(
                                namespace,
                                files_indexed=-1,
                                chunks=-int(old_chunk_count),
                                vectors=-int(old_chunk_count),
                            )
                        except Exception as exc:
                            logger.exception(
                                "Could not roll back stats before force re-ingest of inline %s: %s",
                                source_label, exc,
                            )
            except Exception as exc:
                logger.exception("Force-reingest pre-cleanup failed for inline %s: %s", source_label, exc)

        if not text or not text.strip():
            elapsed = time.monotonic() - run_t0
            return {
                "namespace": namespace,
                "source_label": source_label,
                "chunks_added": 0,
                "entities_added": 0,
                "relations_added": 0,
                "errors": [],
                "elapsed_seconds": round(elapsed, 3),
            }

        t_chunk_start = time.monotonic()
        sliding_window_threshold = options.chunk_size * 10
        if len(text) > sliding_window_threshold:
            chunker = SlidingWindowChunker(
                window_size=options.sliding_window_size,
                overlap=options.sliding_window_overlap,
                page_chars=options.chunk_size,
            )
            raw_chunks = chunker.chunk(text)
            chunks_text = [c["text"] for c in raw_chunks]
            chunk_metas = [c["metadata"] for c in raw_chunks]
        else:
            chunks_text = _chunk_text(text, options.chunk_size, options.chunk_overlap)
            chunk_metas = [{} for _ in chunks_text]
        t_chunk = time.monotonic() - t_chunk_start

        if not chunks_text:
            elapsed = time.monotonic() - run_t0
            return {
                "namespace": namespace,
                "source_label": source_label,
                "chunks_added": 0,
                "entities_added": 0,
                "relations_added": 0,
                "errors": [],
                "elapsed_seconds": round(elapsed, 3),
            }

        chunks: list[dict] = []
        for i, (chunk, cmeta) in enumerate(zip(chunks_text, chunk_metas)):
            metadata = {
                "file_path": fe.path,
                "filename": source_label,
                "chunk_index": i,
                "total_chunks": len(chunks_text),
                "file_size": fe.size,
                "mtime": fe.mtime,
                "extension": fe.extension,
                "file_hash": fe.content_hash,
                "chunk_hash": _sha256(chunk.encode("utf-8")),
                "source_type": "inline",
            }
            metadata.update(cmeta)
            chunks.append({"text": chunk, "metadata": metadata})

        t_extract_start = time.monotonic()
        try:
            counts = self._extract_and_embed(namespace, fe, chunks, options)
        except Exception as exc:
            t_extract = time.monotonic() - t_extract_start
            logger.exception("embed/extract failed for inline %s (%.3fs)", source_label, t_extract)
            elapsed = time.monotonic() - run_t0
            return {
                "namespace": namespace,
                "source_label": source_label,
                "chunks_added": 0,
                "entities_added": 0,
                "relations_added": 0,
                "errors": [f"inline://{source_label}: embed/extract failed: {exc}"],
                "elapsed_seconds": round(elapsed, 3),
            }

        total_chunks = counts["chunks_added"]
        total_entities = counts["entities_added"]
        total_relations = counts["relations_added"]

        try:
            self._nm.update_stats(
                namespace,
                files_indexed=1,
                chunks=total_chunks,
                entities=total_entities,
                relations=total_relations,
                vectors=total_chunks,
            )
        except Exception as exc:
            logger.exception("Could not update namespace stats: %s", exc)

        try:
            self._nm.append_import(
                namespace,
                ImportRecord(
                    folder_path=f"inline://{source_label}",
                    started_at=started_at,
                    finished_at=_utcnow(),
                    status="completed",
                    file_count=1,
                    error_count=0,
                ),
            )
        except Exception as exc:
            logger.exception("Could not append import record: %s", exc)

        elapsed = time.monotonic() - run_t0
        metrics.counter("ingest_files_total").inc()
        metrics.counter("ingest_bytes_total").inc(fe.size)
        metrics.histogram("ingest_latency_seconds").observe(elapsed)

        emit(JobEvent(
            timestamp=_utcnow(),
            state=JobState.COMPLETED,
            message="Text ingested",
            progress_current=1,
            progress_total=1,
            detail={
                "source": source_label,
                "status": "processed",
                "chunks": total_chunks,
                "entities": total_entities,
            },
        ))

        return {
            "namespace": namespace,
            "source_label": source_label,
            "chunks_added": total_chunks,
            "entities_added": total_entities,
            "relations_added": total_relations,
            "errors": [],
            "elapsed_seconds": round(elapsed, 3),
        }


__all__ = [
    "FileEntry",
    "IngestOptions",
    "Ingestor",
]
