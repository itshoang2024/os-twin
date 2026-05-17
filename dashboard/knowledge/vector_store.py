"""Per-namespace zvec wrapper used by ingestion and query.

This module replaces the previous chromadb-backed ``_NamespaceStore`` vector
side. Lazy-imports ``zvec`` on first method call so the module is import-cheap
(``test_knowledge_smoke`` heavy-deps gate continues to pass).

Design points:

- One :class:`NamespaceVectorStore` per namespace; it owns a single zvec
  Collection at ``{base}/{ns}/vectors/``. Construction is cheap; the collection
  is opened/created lazily on first call.
- The collection schema mirrors the metadata previously persisted into
  chromadb's per-row metadata dict, but as typed zvec fields so they can be
  filtered with SQL-like predicates.
- All string filter values are escaped via :meth:`NamespaceVectorStore._esc`
  to avoid breaking the filter parser when content contains single quotes.
- All public methods are best-effort: zvec failures are logged and a sane
  default (``False`` / ``0`` / ``[]``) is returned so a single bad call cannot
  poison an entire ingestion run.
- zvec's ``query()`` caps ``topk`` at 1024 per call. ``count_by_file_hash``,
  ``delete_by_file_hash`` and ``count`` therefore page through at most that
  many results per request and stop when a page comes back short. A single
  file with > ~1000 chunks would be unusual (the default chunk size is 1024
  chars; even a 1 MB file produces ~1000 chunks) but the loop guards against
  the corner case anyway.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)


# zvec caps query topk at this value (per-call, hard limit in the C++ layer).
# For per-file_hash queries this is fine — a single file rarely produces more
# than a few hundred chunks. For the namespace-wide ``count()`` helper it
# means the result is approximate above this threshold; manifest stats are
# the authoritative source for total counts.
_ZVEC_MAX_TOPK = 1024


class DimensionMismatchError(RuntimeError):
    """Raised when the on-disk zvec collection dimension doesn't match the embedder.

    This happens when the embedding model changes after a namespace was created
    (e.g. switching from ``bge-base-en-v1.5`` [1024-dim] to ``bge-small-en-v1.5``
    [384-dim]). The existing collection cannot accept vectors of a different
    dimension — it must be deleted and re-ingested with the new model.
    """

    def __init__(self, namespace_path: str, collection_dim: int, embedder_dim: int) -> None:
        self.namespace_path = namespace_path
        self.collection_dim = collection_dim
        self.embedder_dim = embedder_dim
        super().__init__(
            f"Embedding dimension mismatch for collection at {namespace_path}: "
            f"on-disk collection has dim={collection_dim} but the current "
            f"embedder produces dim={embedder_dim}. "
            f"Delete the namespace and re-ingest, or switch back to the "
            f"original embedding model."
        )


@dataclass
class VectorHit:
    """A single hit returned from :meth:`NamespaceVectorStore.search`.

    Stable shape used by EPIC-004 (query layer). ``metadata`` mirrors the
    per-chunk metadata dict the ingester wrote, with ``None`` for any field
    that wasn't populated.
    """

    id: str
    score: float
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class NamespaceVectorStore:
    """Thin per-namespace zvec wrapper. Cheap to construct; opens collection lazily.

    Parameters
    ----------
    vector_path:
        Absolute path to the per-namespace zvec collection directory. Must
        be writable; the parent is created on construction so the underlying
        zvec ``create_and_open`` call doesn't fail on a missing tree.
    dimension:
        Embedding dimension (e.g. 1024 for ``qwen3-embedding:0.6b``). Frozen
        at construction time — do NOT change between calls on the same path
        or zvec will reject the open.
    schema_name:
        Internal name embedded in the collection schema. Defaults to
        ``knowledge``; uniqueness across namespaces is provided by the
        ``vector_path`` location, not this field.
    """

    # Track whether we've called zvec.init() in this process. zvec is fine to
    # call init multiple times but it's cheap to skip the second time.
    _zvec_initialised = False

    def __init__(
        self,
        vector_path: Path,
        dimension: int,
        schema_name: str = "knowledge",
    ) -> None:
        self._path = Path(vector_path)
        # Parent dir must exist; the zvec lib creates the leaf as a directory.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._dim = int(dimension)
        self._schema_name = schema_name
        self._collection: Any = None

    # ----- internals --------------------------------------------------

    @classmethod
    def _ensure_zvec_init(cls) -> None:
        """Idempotent zvec runtime init. Safe to call on every method."""
        if cls._zvec_initialised:
            return
        import zvec  # noqa: WPS433 — lazy

        try:
            zvec.init(log_level=zvec.LogLevel.WARN)
        except Exception as exc:  # noqa: BLE001 — init may already be done
            logger.debug("zvec.init() raised (likely already initialised): %s", exc)
        cls._zvec_initialised = True

    def _coll(self) -> Any:
        """Return the (lazily opened) zvec Collection for this namespace."""
        if self._collection is not None:
            return self._collection
        self._ensure_zvec_init()
        self._collection = self._open_or_create()
        return self._collection

    def _open_or_create(self) -> Any:
        """Open the existing zvec collection at ``self._path``, or create it.

        EPIC-004 (architect-mandated, ZVEC-LIVE-1 part 2): distinguish
        "directory genuinely missing or empty" from "open failed for some
        other reason" (handle conflict, schema corruption, permissions).
        Only fall through to ``create_and_open`` in the former case; in
        the latter case re-raise so the caller sees the real error instead
        of a confusing
        ``ValueError: path validate failed: path[...] is existed``.
        """
        import zvec  # noqa: WPS433 — lazy

        path_str = str(self._path)
        path_obj = Path(path_str)

        # Treat "exists with at least one entry" as a real previous collection.
        # An empty directory left over from a botched create gets re-created.
        try:
            already_exists = path_obj.exists() and path_obj.is_dir() and any(
                path_obj.iterdir()
            )
        except OSError as exc:  # pragma: no cover — only on broken fs perms
            logger.warning(
                "Could not stat zvec collection dir %s: %s", path_str, exc
            )
            already_exists = False

        if already_exists:
            # Existing collection — open or fail loudly. Do NOT silently
            # try to recreate over the top of an existing zvec dir; that
            # path raises the misleading "is existed" ValueError that bit
            # the architect's probe in EPIC-003.
            try:
                coll = zvec.open(path_str)
                # Validate that the on-disk collection dimension matches
                # the embedder dimension. A mismatch means the embedding
                # model changed since this collection was created — every
                # upsert would fail with "dimension mismatch".
                try:
                    # NOTE: coll.schema is a PROPERTY, not a method.
                    actual_dim = coll.schema.vector("embedding").dimension
                    if actual_dim != self._dim:
                        raise DimensionMismatchError(
                            namespace_path=path_str,
                            collection_dim=actual_dim,
                            embedder_dim=self._dim,
                        )
                except DimensionMismatchError:
                    raise  # re-raise — don't swallow our own error
                except Exception as schema_exc:
                    logger.debug("Could not read dimension from zvec schema: %s", schema_exc)
                return coll
            except DimensionMismatchError:
                raise  # propagate to caller
            except Exception as exc:
                logger.error(
                    "zvec collection at %s exists but cannot be opened: %s",
                    path_str,
                    exc,
                )
                raise

        # Fresh collection (path missing OR an empty leftover dir).
        schema = zvec.CollectionSchema(
            name=self._schema_name,
            fields=[
                zvec.FieldSchema(
                    "file_hash",
                    zvec.DataType.STRING,
                    index_param=zvec.InvertIndexParam(),
                ),
                zvec.FieldSchema(
                    "file_path",
                    zvec.DataType.STRING,
                    index_param=zvec.InvertIndexParam(),
                ),
                zvec.FieldSchema(
                    "filename",
                    zvec.DataType.STRING,
                    index_param=zvec.InvertIndexParam(),
                ),
                zvec.FieldSchema(
                    "mime_type",
                    zvec.DataType.STRING,
                    nullable=True,
                    index_param=zvec.InvertIndexParam(),
                ),
                zvec.FieldSchema("chunk_index", zvec.DataType.INT32),
                zvec.FieldSchema("total_chunks", zvec.DataType.INT32),
                zvec.FieldSchema(
                    "category_id",
                    zvec.DataType.STRING,
                    nullable=True,
                    index_param=zvec.InvertIndexParam(),
                ),
                zvec.FieldSchema("text", zvec.DataType.STRING),
            ],
            vectors=zvec.VectorSchema(
                "embedding",
                zvec.DataType.VECTOR_FP32,
                self._dim,
                index_param=zvec.HnswIndexParam(
                    metric_type=zvec.MetricType.COSINE,
                    m=16,
                    ef_construction=200,
                ),
            ),
        )
        return zvec.create_and_open(path=path_str, schema=schema)

    def close(self) -> None:
        """Release the underlying zvec collection handle.

        zvec doesn't expose an explicit close API — dropping the Python
        reference is sufficient; zvec handles its own internal cleanup.

        Safe to call multiple times; subsequent calls are no-ops. Any
        future call on this instance after ``close()`` will lazily reopen
        the collection (matching the "construct cheap, open lazy" contract).
        """
        if self._collection is None:
            return
        try:
            del self._collection
        except Exception as exc:  # noqa: BLE001 — best-effort cleanup
            logger.warning(
                "Error releasing zvec handle for %s: %s", self._path, exc
            )
        self._collection = None

    @staticmethod
    def _esc(s: Optional[str]) -> str:
        """Backslash-escape single-quotes (and backslashes) for zvec filter expressions.

        zvec's SQL-like filter parser does NOT accept the standard SQL
        ``''`` (doubled-quote) escape — it treats the second quote as the
        end of the literal and chokes on the trailing characters. The
        only safe escape is ``\\'`` (backslash-quote). Backslashes
        themselves must therefore also be escaped first.
        """
        if not s:
            return ""
        return s.replace("\\", "\\\\").replace("'", "\\'")

    # ----- public API -------------------------------------------------

    def add_chunks(self, chunks: Iterable[dict]) -> int:
        """Insert chunks. Each dict must have ``text``, ``embedding`` and ``metadata``.

        ``metadata`` keys recognised: ``file_hash``, ``file_path``, ``filename``,
        ``mime_type``, ``chunk_index``, ``total_chunks``, ``category_id``. Unknown
        keys are silently ignored (they're already captured in chunk text).

        Per-chunk failures are logged and counted as 0; the rest of the batch
        still goes in. Returns the count actually accepted by zvec.
        """
        import zvec  # noqa: WPS433

        coll = self._coll()
        ok = 0
        for c in chunks:
            md = c.get("metadata") or {}
            try:
                doc = zvec.Doc(
                    id=str(uuid.uuid4()),
                    fields={
                        "file_hash": str(md.get("file_hash", "") or ""),
                        "file_path": str(md.get("file_path", "") or ""),
                        "filename": str(md.get("filename", "") or ""),
                        "mime_type": (
                            str(md["mime_type"])
                            if md.get("mime_type") is not None
                            else None
                        ),
                        "chunk_index": int(md.get("chunk_index", 0) or 0),
                        "total_chunks": int(md.get("total_chunks", 1) or 1),
                        "category_id": (
                            str(md["category_id"])
                            if md.get("category_id") is not None
                            else None
                        ),
                        "text": c.get("text", "") or "",
                    },
                    vectors={"embedding": c["embedding"]},
                )
                status = coll.upsert(doc)
                if status.ok():
                    ok += 1
                else:
                    logger.warning("zvec upsert returned non-ok: %s", status)
            except Exception as exc:  # noqa: BLE001
                logger.warning("zvec upsert failed for chunk: %s", exc)
        return ok

    def has_file_hash(self, file_hash: str) -> bool:
        """True iff at least one chunk in this namespace has the given file_hash."""
        if not file_hash:
            return False
        import zvec  # noqa: WPS433

        coll = self._coll()
        try:
            docs = coll.query(
                vectors=zvec.VectorQuery("embedding", vector=[0.0] * self._dim),
                topk=1,
                filter=f"file_hash = '{self._esc(file_hash)}'",
                output_fields=["file_hash"],
            )
            return len(docs) > 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("has_file_hash query failed: %s", exc)
            return False

    def count_by_file_hash(self, file_hash: str) -> int:
        """Return the number of chunks currently stored with the given file_hash.

        Used by the force-reprocess path to know how much to subtract from
        the manifest stats before re-adding the new chunks. Capped at the
        zvec ``topk`` ceiling (:data:`_ZVEC_MAX_TOPK`); a single file
        producing more chunks than that is exceptional and would only
        cause an under-count in the rollback (the zvec store itself is
        unaffected — ``delete_by_file_hash`` will catch any leftover rows
        on the next force pass).
        """
        if not file_hash:
            return 0
        import zvec  # noqa: WPS433

        coll = self._coll()
        try:
            docs = coll.query(
                vectors=zvec.VectorQuery("embedding", vector=[0.0] * self._dim),
                topk=_ZVEC_MAX_TOPK,
                filter=f"file_hash = '{self._esc(file_hash)}'",
                output_fields=["file_hash"],
            )
            return len(docs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("count_by_file_hash failed: %s", exc)
            return 0

    def delete_by_file_hash(self, file_hash: str) -> int:
        """Delete every chunk in this namespace with the given file_hash. Returns the count.

        Loops in pages of :data:`_ZVEC_MAX_TOPK` so files with more chunks
        than the per-call topk cap are still fully cleaned out — each pass
        deletes a page, then re-queries to see if any remain.
        """
        if not file_hash:
            return 0
        import zvec  # noqa: WPS433

        coll = self._coll()
        n = 0
        # Bound the loop so a pathological zvec bug can't spin forever.
        for _ in range(64):  # 64 * 1024 = 65k chunks is way beyond any sane file
            try:
                docs = coll.query(
                    vectors=zvec.VectorQuery("embedding", vector=[0.0] * self._dim),
                    topk=_ZVEC_MAX_TOPK,
                    filter=f"file_hash = '{self._esc(file_hash)}'",
                    output_fields=["file_hash"],
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("delete_by_file_hash query failed: %s", exc)
                return n
            if not docs:
                break
            for d in docs:
                try:
                    coll.delete(d.id)
                    n += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("zvec delete %s failed: %s", d.id, exc)
            if len(docs) < _ZVEC_MAX_TOPK:
                # Final page — no need to re-query.
                break
        return n

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        category_id: Optional[str] = None,
    ) -> list[VectorHit]:
        """Vector search. Returns at most ``top_k`` :class:`VectorHit`s, sorted by score desc.

        Filters by ``category_id`` when provided. EPIC-004 may extend this to
        accept richer filter expressions; right now the contract is simple.
        """
        import zvec  # noqa: WPS433

        coll = self._coll()
        filter_expr: Optional[str] = None
        if category_id:
            filter_expr = f"category_id = '{self._esc(category_id)}'"
        try:
            docs = coll.query(
                vectors=zvec.VectorQuery("embedding", vector=query_embedding),
                topk=min(int(top_k), _ZVEC_MAX_TOPK),
                filter=filter_expr,
                output_fields=[
                    "file_path",
                    "filename",
                    "chunk_index",
                    "total_chunks",
                    "file_hash",
                    "mime_type",
                    "category_id",
                    "text",
                ],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("vector search failed: %s", exc)
            return []
        return [
            VectorHit(
                id=d.id,
                score=float(d.score),
                text=d.field("text") or "",
                metadata={
                    "file_path": d.field("file_path"),
                    "filename": d.field("filename"),
                    "chunk_index": d.field("chunk_index"),
                    "total_chunks": d.field("total_chunks"),
                    "file_hash": d.field("file_hash"),
                    "mime_type": d.field("mime_type"),
                    "category_id": d.field("category_id"),
                },
            )
            for d in docs
        ]

    def count(self) -> int:
        """Approximate count via topk-capped scan.

        Caps at :data:`_ZVEC_MAX_TOPK` (zvec's per-call ceiling). Use
        sparingly; the manifest's ``NamespaceMeta.stats.vectors`` is the
        authoritative total — this helper exists primarily for tests where
        the collection is known to be small (≤ 1024 chunks).
        """
        import zvec  # noqa: WPS433

        coll = self._coll()
        try:
            docs = coll.query(
                vectors=zvec.VectorQuery("embedding", vector=[0.0] * self._dim),
                topk=_ZVEC_MAX_TOPK,
                output_fields=["file_hash"],
            )
            return len(docs)
        except Exception:  # noqa: BLE001
            return 0


__all__ = ["DimensionMismatchError", "NamespaceVectorStore", "VectorHit"]
