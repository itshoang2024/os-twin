"""
OS Twin Vector Log Store — zvec integration layer.

Indexes all war-room channel messages with embeddings for semantic search.
Stores room metadata for fast dashboard lookups (eliminates "UNKNOWN" task-ref).

Usage:
    store = OSTwinStore(Path("/project/.war-rooms"))
    store.ensure_collections()
    store.sync_from_disk()  # backfill existing JSONL
    results = store.search("authentication bug", limit=5)
"""

from __future__ import annotations

import hashlib
import os
import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Optional

import zvec

from datetime import datetime
import uuid_utils

logger = logging.getLogger("zvec_store")

# Embedding dimension — single source of truth from OSTWIN_EMBEDDING_DIM env var.
# Fixed at startup; cannot be changed dynamically to avoid dimension conflicts
# across memory, knowledge, and zvec collections.
from dashboard.llm_client import DEFAULT_EMBEDDING_DIMENSION as EMBEDDING_DIM

OSTWIN_EMBED_MODEL = os.environ.get("OSTWIN_EMBED_MODEL", "leoipulsar/harrier-0.6b")
MESSAGES_COLLECTION = "messages"
METADATA_COLLECTION = "metadata"
PLANS_COLLECTION = "plans_v2"
EPICS_COLLECTION = "epics"
SKILLS_COLLECTION = "skills"
VERSIONS_COLLECTION = "versions"
CHANGES_COLLECTION = "changes"
ROLES_COLLECTION = "roles"


def uuid7() -> str:
    """Generate a spec-compliant UUIDv7 string."""
    return str(uuid_utils.uuid7())


def extract_timestamp_from_uuid7(uid: str) -> datetime:
    """Extract a millisecond-precision datetime from a UUIDv7 string."""
    try:
        u = uuid_utils.UUID(uid)
        # uuid_utils UUIDs have a .timestamp attribute (ms since epoch)
        return datetime.fromtimestamp(u.timestamp / 1000.0)
    except Exception:
        return datetime.fromtimestamp(0)


class OSTwinStore:
    """In-process vector store for OS Twin logs and metadata."""

    def __init__(self, warrooms_dir: Path, agents_dir: Path | None = None, embedder=None):
        self.warrooms_dir = warrooms_dir
        self.agents_dir = agents_dir  # .agents/ directory (for plans etc.)
        self._embedder = embedder  # Optional KnowledgeEmbedder (lazy-created if None)
        self._embedding_dim = EMBEDDING_DIM  # Per-instance; updated when model loads
        # Global zvec store at ~/.config/ostwin/.zvec
        env_zvec_dir = os.environ.get("OSTWIN_ZVEC_DIR")
        if env_zvec_dir:
            zvec_real_dir = Path(env_zvec_dir)
        else:
            zvec_real_dir = Path.home() / ".config" / "ostwin" / ".zvec"
        zvec_real_dir.mkdir(parents=True, exist_ok=True)

        # Handle paths with spaces (zvec library regex limitation)
        if " " in str(zvec_real_dir):
            import tempfile
            import hashlib

            # Create a stable symlink in /tmp based on the project path hash
            path_hash = hashlib.md5(str(zvec_real_dir).encode()).hexdigest()[:8]
            tmp_dir = Path(tempfile.gettempdir()) / f"ostwin_zvec_{path_hash}"

            try:
                # Need to use string paths for os.readlink/os.symlink for compatibility
                zvec_path_str = str(zvec_real_dir.absolute())
                tmp_path_str = str(tmp_dir.absolute())

                if tmp_dir.exists() or tmp_dir.is_symlink():
                    try:
                        if os.readlink(tmp_path_str) == zvec_path_str:
                            pass  # already correct
                        else:
                            os.remove(tmp_path_str)
                            os.symlink(zvec_path_str, tmp_path_str)
                    except (OSError, ValueError):
                        # Not a symlink or other error, try to replace it
                        if tmp_dir.is_dir():
                            import shutil

                            shutil.rmtree(tmp_path_str)
                        else:
                            os.remove(tmp_path_str)
                        os.symlink(zvec_path_str, tmp_path_str)
                else:
                    os.symlink(zvec_path_str, tmp_path_str)

                self.zvec_dir = tmp_dir
                logger.info(
                    "Using zvec symlink for path with spaces: %s -> %s",
                    tmp_dir,
                    zvec_real_dir,
                )
            except Exception as e:
                logger.warning(
                    "Failed to create zvec symlink: %s. Falling back to original path.",
                    e,
                )
                self.zvec_dir = zvec_real_dir
        else:
            self.zvec_dir = zvec_real_dir

        self._messages: Optional[zvec.Collection] = None
        self._metadata: Optional[zvec.Collection] = None
        self._plans: Optional[zvec.Collection] = None
        self._epics: Optional[zvec.Collection] = None
        self._skills: Optional[zvec.Collection] = None
        self._versions: Optional[zvec.Collection] = None
        self._changes: Optional[zvec.Collection] = None
        self._roles: Optional[zvec.Collection] = None
        self._embed_fn = None
        self._embed_available: Optional[bool] = None

        # Embedding cache — survives zvec collection rebuilds
        self._embed_cache_path = self.zvec_dir / "embedding_cache.json"
        self._embed_cache: dict[str, list[float]] = {}
        self._load_embed_cache()

    # ── Collections ────────────────────────────────────────────────────

    def ensure_collections(self) -> None:
        """Create or open all collections."""
        zvec.init(log_level=zvec.LogLevel.WARN)
        # Ensure model is loaded and _embedding_dim is set before opening
        self._get_embed_fn()
        # Dimension is fixed from OSTWIN_EMBEDDING_DIM; no dynamic mutation.
        self._embedding_dim = EMBEDDING_DIM
        # Check for migrations first
        self.migrate_collections()
        self._messages = self._open_or_create_messages()
        self._metadata = self._open_or_create_metadata()
        self._plans = self._open_or_create_plans()
        self._epics = self._open_or_create_epics()
        self._skills = self._open_or_create_skills()
        self._versions = self._open_or_create_versions()
        self._changes = self._open_or_create_changes()
        self._roles = self._open_or_create_roles()
        logger.info("zvec collections ready at %s", self.zvec_dir)

    def migrate_collections(self) -> dict:
        """Check all collections and migrate if time_id is missing."""
        stats = {"migrated": [], "skipped": [], "errors": []}

        collections = [
            (MESSAGES_COLLECTION, self._open_or_create_messages),
            (METADATA_COLLECTION, self._open_or_create_metadata),
            (PLANS_COLLECTION, self._open_or_create_plans),
            (EPICS_COLLECTION, self._open_or_create_epics),
            (SKILLS_COLLECTION, self._open_or_create_skills),
            (VERSIONS_COLLECTION, self._open_or_create_versions),
            (CHANGES_COLLECTION, self._open_or_create_changes),
            (ROLES_COLLECTION, self._open_or_create_roles),
        ]

        import shutil

        for name, opener in collections:
            path = self.zvec_dir / name
            if not path.exists():
                continue

            try:
                col = zvec.open(str(path))
                schema = col.schema
                has_time_id = any(f.name == "time_id" for f in schema.fields)
                has_enabled = any(f.name == "enabled" for f in schema.fields)
                has_instance_type = any(f.name == "instance_type" for f in schema.fields)

                # Check vector dimension mismatch (Harrier migration).
                # zvec exposes `schema.vectors` as either a list of VectorSchema
                # or a single VectorSchema object depending on version. Handle
                # both shapes and capture the current dim for later logging.
                dim_mismatch = False
                current_dim: Optional[int] = None
                vectors = schema.vectors
                if isinstance(vectors, list) and len(vectors) > 0:
                    current_dim = vectors[0].dimension
                elif hasattr(vectors, "dimension"):
                    current_dim = vectors.dimension
                if current_dim is not None and current_dim != EMBEDDING_DIM:
                    dim_mismatch = True

                # To be safe, we need the collection to be closed.
                # In current zvec, dropping the ref usually works.
                col = None

                needs_enabled = name == SKILLS_COLLECTION and not has_enabled
                needs_instance_type = name == ROLES_COLLECTION and not has_instance_type
                if not has_time_id or dim_mismatch or needs_enabled or needs_instance_type:
                    reasons = []
                    if dim_mismatch:
                        reasons.append(f"dim {current_dim} → {EMBEDDING_DIM}")
                    if not has_time_id:
                        reasons.append("missing time_id")
                    if needs_enabled:
                        reasons.append("missing enabled")
                    if needs_instance_type:
                        reasons.append("missing instance_type")
                    logger.info("Migrating collection %s (%s)", name, ", ".join(reasons))
                    shutil.rmtree(str(path))
                    stats["migrated"].append(name)
                else:
                    stats["skipped"].append(name)
            except Exception as e:
                logger.warning("Failed to check/migrate collection %s: %s", name, e)
                stats["errors"].append(f"{name}: {str(e)}")
                # If we couldn't even read the schema, the collection is
                # likely from an incompatible zvec version. Nuke it so the
                # subsequent _open_or_create call rebuilds it with the
                # current schema. Better to lose the index than to leave
                # the dashboard stuck in a permanent re-index loop.
                try:
                    shutil.rmtree(str(path))
                    logger.info("Removed unreadable collection %s — will rebuild", name)
                    stats["migrated"].append(name)
                except Exception as rm_err:
                    logger.error("Failed to remove unreadable collection %s: %s", name, rm_err)

        if stats["migrated"]:
            logger.info("Collections migrated: %s", ", ".join(stats["migrated"]))

        return stats

    def _open_or_create_messages(self) -> zvec.Collection:
        path = str(self.zvec_dir / MESSAGES_COLLECTION)
        try:
            return zvec.open(path)
        except Exception:
            schema = zvec.CollectionSchema(
                name=MESSAGES_COLLECTION,
                fields=[
                    zvec.FieldSchema(
                        "time_id",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "room_id",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "from_role",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "to_role",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "msg_type",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema("ref", zvec.DataType.STRING, index_param=zvec.InvertIndexParam()),
                    zvec.FieldSchema("ts", zvec.DataType.STRING, index_param=zvec.InvertIndexParam()),
                    zvec.FieldSchema("body", zvec.DataType.STRING),
                ],
                vectors=zvec.VectorSchema(
                    "embedding",
                    zvec.DataType.VECTOR_FP32,
                    EMBEDDING_DIM,
                    index_param=zvec.HnswIndexParam(
                        metric_type=zvec.MetricType.COSINE,
                        m=16,
                        ef_construction=200,
                    ),
                ),
            )
            return zvec.create_and_open(path=path, schema=schema)

    def _open_or_create_metadata(self) -> zvec.Collection:
        path = str(self.zvec_dir / METADATA_COLLECTION)
        try:
            return zvec.open(path)
        except Exception:
            schema = zvec.CollectionSchema(
                name=METADATA_COLLECTION,
                fields=[
                    zvec.FieldSchema(
                        "time_id",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "task_ref",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "status",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema("retries", zvec.DataType.INT32),
                    zvec.FieldSchema("message_count", zvec.DataType.INT32),
                    zvec.FieldSchema("last_activity", zvec.DataType.STRING, nullable=True),
                    zvec.FieldSchema("task_description", zvec.DataType.STRING, nullable=True),
                ],
                vectors=zvec.VectorSchema(
                    "embedding",
                    zvec.DataType.VECTOR_FP32,
                    EMBEDDING_DIM,
                    index_param=zvec.HnswIndexParam(
                        metric_type=zvec.MetricType.COSINE,
                        m=16,
                        ef_construction=200,
                    ),
                ),
            )
            return zvec.create_and_open(path=path, schema=schema)

    def _open_or_create_plans(self) -> zvec.Collection:
        path = str(self.zvec_dir / PLANS_COLLECTION)
        try:
            return zvec.open(path)
        except Exception:
            schema = zvec.CollectionSchema(
                name=PLANS_COLLECTION,
                fields=[
                    zvec.FieldSchema(
                        "time_id",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "title",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema("content", zvec.DataType.STRING),
                    zvec.FieldSchema(
                        "status",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema("epic_count", zvec.DataType.INT32),
                    zvec.FieldSchema(
                        "created_at",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema("filename", zvec.DataType.STRING, nullable=True),
                    zvec.FieldSchema("file_mtime", zvec.DataType.DOUBLE, nullable=True),
                ],
                vectors=zvec.VectorSchema(
                    "embedding",
                    zvec.DataType.VECTOR_FP32,
                    EMBEDDING_DIM,
                    index_param=zvec.HnswIndexParam(
                        metric_type=zvec.MetricType.COSINE,
                        m=16,
                        ef_construction=200,
                    ),
                ),
            )
            return zvec.create_and_open(path=path, schema=schema)

    def _open_or_create_epics(self) -> zvec.Collection:
        path = str(self.zvec_dir / EPICS_COLLECTION)
        try:
            return zvec.open(path)
        except Exception:
            schema = zvec.CollectionSchema(
                name=EPICS_COLLECTION,
                fields=[
                    zvec.FieldSchema(
                        "time_id",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "epic_ref",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "plan_id",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "title",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema("body", zvec.DataType.STRING),
                    zvec.FieldSchema(
                        "room_id",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "status",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema("working_dir", zvec.DataType.STRING, nullable=True),
                ],
                vectors=zvec.VectorSchema(
                    "embedding",
                    zvec.DataType.VECTOR_FP32,
                    EMBEDDING_DIM,
                    index_param=zvec.HnswIndexParam(
                        metric_type=zvec.MetricType.COSINE,
                        m=16,
                        ef_construction=200,
                    ),
                ),
            )
            return zvec.create_and_open(path=path, schema=schema)

    def _open_or_create_skills(self) -> zvec.Collection:
        path = str(self.zvec_dir / SKILLS_COLLECTION)
        try:
            return zvec.open(path)
        except Exception:
            schema = zvec.CollectionSchema(
                name=SKILLS_COLLECTION,
                fields=[
                    zvec.FieldSchema(
                        "time_id",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "name",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema("description", zvec.DataType.STRING),
                    zvec.FieldSchema(
                        "tags",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema("path", zvec.DataType.STRING),
                    zvec.FieldSchema(
                        "relative_path",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "trust_level",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "source",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema("content", zvec.DataType.STRING),
                    zvec.FieldSchema(
                        "version",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "category",
                        zvec.DataType.STRING,
                        nullable=True,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema("applicable_roles", zvec.DataType.STRING),
                    zvec.FieldSchema("params", zvec.DataType.STRING),
                    zvec.FieldSchema("changelog", zvec.DataType.STRING),
                    zvec.FieldSchema("author", zvec.DataType.STRING, nullable=True),
                    zvec.FieldSchema("forked_from", zvec.DataType.STRING, nullable=True),
                    zvec.FieldSchema("is_draft", zvec.DataType.INT32),
                    zvec.FieldSchema("enabled", zvec.DataType.INT32),
                ],
                vectors=zvec.VectorSchema(
                    "embedding",
                    zvec.DataType.VECTOR_FP32,
                    EMBEDDING_DIM,
                    index_param=zvec.HnswIndexParam(
                        metric_type=zvec.MetricType.COSINE,
                        m=16,
                        ef_construction=200,
                    ),
                ),
            )
            return zvec.create_and_open(path=path, schema=schema)

    def _open_or_create_versions(self) -> zvec.Collection:
        path = str(self.zvec_dir / VERSIONS_COLLECTION)
        try:
            return zvec.open(path)
        except Exception:
            schema = zvec.CollectionSchema(
                name=VERSIONS_COLLECTION,
                fields=[
                    zvec.FieldSchema(
                        "time_id",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "plan_id",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "version",
                        zvec.DataType.INT32,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema("title", zvec.DataType.STRING),
                    zvec.FieldSchema("content", zvec.DataType.STRING),
                    zvec.FieldSchema("epic_count", zvec.DataType.INT32),
                    zvec.FieldSchema("change_source", zvec.DataType.STRING),
                    zvec.FieldSchema("created_at", zvec.DataType.STRING),
                ],
                vectors=zvec.VectorSchema(
                    "embedding",
                    zvec.DataType.VECTOR_FP32,
                    EMBEDDING_DIM,
                    index_param=zvec.HnswIndexParam(
                        metric_type=zvec.MetricType.COSINE,
                        m=16,
                        ef_construction=200,
                    ),
                ),
            )
            return zvec.create_and_open(path=path, schema=schema)

    def _open_or_create_changes(self) -> zvec.Collection:
        path = str(self.zvec_dir / CHANGES_COLLECTION)
        try:
            return zvec.open(path)
        except Exception:
            schema = zvec.CollectionSchema(
                name=CHANGES_COLLECTION,
                fields=[
                    zvec.FieldSchema(
                        "time_id",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "plan_id",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "timestamp",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "change_type",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema("file_path", zvec.DataType.STRING),
                    zvec.FieldSchema("diff_summary", zvec.DataType.STRING),
                    zvec.FieldSchema(
                        "source",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                ],
                vectors=zvec.VectorSchema(
                    "embedding",
                    zvec.DataType.VECTOR_FP32,
                    EMBEDDING_DIM,
                    index_param=zvec.HnswIndexParam(
                        metric_type=zvec.MetricType.COSINE,
                        m=16,
                        ef_construction=200,
                    ),
                ),
            )
            return zvec.create_and_open(path=path, schema=schema)

    def _open_or_create_roles(self) -> zvec.Collection:
        path = str(self.zvec_dir / ROLES_COLLECTION)
        try:
            return zvec.open(path)
        except Exception:
            schema = zvec.CollectionSchema(
                name=ROLES_COLLECTION,
                fields=[
                    zvec.FieldSchema(
                        "time_id",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "role_id",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "name",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema("description", zvec.DataType.STRING),
                    zvec.FieldSchema(
                        "provider",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema(
                        "version",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema("temperature", zvec.DataType.STRING),
                    zvec.FieldSchema("budget_tokens_max", zvec.DataType.STRING),
                    zvec.FieldSchema("max_retries", zvec.DataType.STRING),
                    zvec.FieldSchema("timeout_seconds", zvec.DataType.STRING),
                    zvec.FieldSchema("skill_refs", zvec.DataType.STRING),
                    zvec.FieldSchema("system_prompt_override", zvec.DataType.STRING, nullable=True),
                    zvec.FieldSchema(
                        "instance_type",
                        zvec.DataType.STRING,
                        index_param=zvec.InvertIndexParam(),
                    ),
                    zvec.FieldSchema("created_at", zvec.DataType.STRING),
                    zvec.FieldSchema("updated_at", zvec.DataType.STRING),
                ],
                vectors=zvec.VectorSchema(
                    "embedding",
                    zvec.DataType.VECTOR_FP32,
                    EMBEDDING_DIM,
                    index_param=zvec.HnswIndexParam(
                        metric_type=zvec.MetricType.COSINE,
                        m=16,
                        ef_construction=200,
                    ),
                ),
            )
            return zvec.create_and_open(path=path, schema=schema)

    # ── Embedding ──────────────────────────────────────────────────────

    def _get_embed_fn(self):
        """Lazy-load embedding via KnowledgeEmbedder.

        Uses the same embedding stack as the knowledge graph
        (dashboard/knowledge/embeddings.py), injected or lazy-created.
        Returns an object with .encode() and .get_sentence_embedding_dimension().
        """
        if self._embed_available is False:
            return None
        if self._embed_fn is not None:
            return self._embed_fn
        try:
            if self._embedder is None:
                from dashboard.knowledge.embeddings import KnowledgeEmbedder

                self._embedder = KnowledgeEmbedder()  # uses MasterSettings > env > default

            import numpy as np

            embedder = self._embedder
            logger.info("Loading embedding model via KnowledgeEmbedder: %s", embedder.model_name)

            class _EmbedProxy:
                """Wraps KnowledgeEmbedder for zvec's encode/dimension API."""

                def __init__(self, ke):
                    self._ke = ke
                    self._dim = None

                def encode(self, texts, convert_to_numpy=False, show_progress_bar=False):
                    if isinstance(texts, str):
                        texts = [texts]
                    vecs = self._ke.embed(texts)
                    if convert_to_numpy:
                        return np.array(vecs)
                    return vecs

                def get_sentence_embedding_dimension(self):
                    if self._dim is None:
                        self._dim = self._ke.dimension()
                    return self._dim

            self._embed_fn = _EmbedProxy(embedder)

            # Use the fixed system-wide dimension (OSTWIN_EMBEDDING_DIM).
            # Do NOT use the model's native dimension — all vectors must
            # share the same dimension to avoid collection conflicts.
            self._embedding_dim = EMBEDDING_DIM

            self._embed_available = True
            logger.info("Embedding model loaded via KnowledgeEmbedder (dim=%d)", self._embedding_dim)
            return self._embed_fn
        except Exception as e:
            logger.warning("Embedding unavailable: %s. Vector search disabled.", e)
            self._embed_available = False
            return None

    def _embed_text(self, text: str, is_query: bool = False) -> list[float] | None:
        fn = self._get_embed_fn()
        if fn is None:
            return None
        if not text or not isinstance(text, str) or not text.strip():
            return None

        # Add instruction prefix for queries (Harrier requirement)
        if is_query:
            text = f"Instruct: Retrieve semantically similar text\nQuery: {text}"

        # Truncate very long messages for embedding
        truncated = text[:2000] if len(text) > 2000 else text
        try:
            # zvec's embedding adapter expects an array-like result here.
            embedding = fn.encode(truncated, convert_to_numpy=True)
            return embedding.tolist()
        except Exception as e:
            logger.debug("Embedding failed for text: %s", e)
            return None

    def _embed_texts_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Embed multiple texts in a single model call, with disk cache.

        Cached embeddings are loaded from ~/.config/ostwin/.zvec/embedding_cache.json
        so they survive zvec collection rebuilds. Only uncached texts hit the model.
        """
        results: list[list[float] | None] = [None] * len(texts)
        uncached_texts = []
        uncached_indices = []

        for i, t in enumerate(texts):
            if not t or not isinstance(t, str) or not t.strip():
                continue
            key = hashlib.md5(t[:2000].encode("utf-8", errors="replace")).hexdigest()
            cached = self._embed_cache.get(key)
            if cached is not None:
                results[i] = cached
            else:
                uncached_texts.append(t[:2000])
                uncached_indices.append((i, key))

        if uncached_texts:
            fn = self._get_embed_fn()
            if fn is not None:
                try:
                    logger.info(
                        "Embedding %d texts (%d from cache)",
                        len(uncached_texts),
                        len(texts) - len(uncached_texts),
                    )
                    embeddings = fn.encode(uncached_texts, convert_to_numpy=True, show_progress_bar=False)
                    for (idx, key), emb in zip(uncached_indices, embeddings):
                        vec = emb.tolist()
                        results[idx] = vec
                        self._embed_cache[key] = vec
                except Exception as e:
                    logger.debug("Batch embedding failed: %s", e)
            self._save_embed_cache()

        return results

    def _load_embed_cache(self):
        """Load embedding cache from disk."""
        try:
            if self._embed_cache_path.exists():
                with open(self._embed_cache_path, "r") as f:
                    self._embed_cache = json.load(f)
                logger.info(
                    "Loaded %d cached embeddings from %s",
                    len(self._embed_cache),
                    self._embed_cache_path,
                )
        except Exception as e:
            logger.debug("Failed to load embedding cache: %s", e)
            self._embed_cache = {}

    def _save_embed_cache(self):
        """Persist embedding cache to disk."""
        try:
            with open(self._embed_cache_path, "w") as f:
                json.dump(self._embed_cache, f)
        except Exception as e:
            logger.debug("Failed to save embedding cache: %s", e)

    # ── Text Sanitization ──────────────────────────────────────────────

    @staticmethod
    def _sanitize_text(text: str) -> str:
        """Sanitize text for zvec storage.

        Preserves common Unicode punctuation (em-dashes, smart quotes, etc.)
        by translating them to ASCII equivalents, and strips only truly
        problematic characters (emoji, control chars, etc.).
        """
        if not text:
            return text
        # Map common Unicode punctuation to ASCII equivalents
        replacements = {
            "\u2014": "--",  # em-dash
            "\u2013": "-",  # en-dash
            "\u2015": "--",  # horizontal bar
            "\u2018": "'",  # left single quote
            "\u2019": "'",  # right single quote
            "\u201c": '"',  # left double quote
            "\u201d": '"',  # right double quote
            "\u2026": "...",  # ellipsis
            "\u00a0": " ",  # non-breaking space
            "\u2022": "*",  # bullet
            "\u00b7": "*",  # middle dot
            "\u2011": "-",  # non-breaking hyphen
            "\u2010": "-",  # hyphen
            "\u2212": "-",  # minus sign
            "\u00ab": "<<",  # left guillemet
            "\u00bb": ">>",  # right guillemet
            "\u2039": "<",  # single left guillemet
            "\u203a": ">",  # single right guillemet
        }
        for uc, ascii_eq in replacements.items():
            text = text.replace(uc, ascii_eq)
        # For remaining non-ASCII: try NFKD normalization then drop unsupported
        result = []
        for ch in text:
            if ord(ch) < 128:
                result.append(ch)
            else:
                decomposed = unicodedata.normalize("NFKD", ch)
                ascii_part = decomposed.encode("ascii", errors="ignore").decode("ascii")
                if ascii_part:
                    result.append(ascii_part)
                # else: character is dropped (emoji, CJK, etc.)
        return "".join(result)

    # ── Message Indexing ───────────────────────────────────────────────

    def index_message(self, room_id: str, msg: dict) -> bool:
        """Index a single channel message. Returns True on success."""
        if self._messages is None:
            return False
        msg_id = msg.get("id", "")
        if not msg_id:
            return False

        body = str(msg.get("body", ""))
        # Sanitize: zvec C++ layer can't handle some Unicode chars (emoji etc.)
        body_clean = self._sanitize_text(body)
        embedding = self._embed_text(body, is_query=False)

        # zvec requires the vector field — use zero vector as fallback
        if embedding is None:
            embedding = [0.0] * EMBEDDING_DIM

        doc = zvec.Doc(
            id=str(msg_id),
            fields={
                "time_id": uuid7(),
                "room_id": str(room_id),
                "from_role": str(msg.get("from", "")),
                "to_role": str(msg.get("to", "")),
                "msg_type": str(msg.get("type", "")),
                "ref": str(msg.get("ref", "")),
                "ts": str(msg.get("ts", "")),
                "body": body_clean,
            },
            vectors={"embedding": embedding},
        )

        try:
            status = self._messages.upsert(doc)
            return status.ok()
        except Exception as e:
            logger.warning("Failed to index message %s: %s", msg_id, e)
            return False

    def index_messages_batch(self, room_id: str, msgs: list[dict]) -> int:
        """Index multiple messages. Returns count of successfully indexed."""
        count = 0
        for msg in msgs:
            if self.index_message(room_id, msg):
                count += 1
        return count

    # ── Room Metadata ──────────────────────────────────────────────────

    def upsert_room_metadata(self, room_id: str, data: dict) -> bool:
        """Store or update room metadata snapshot."""
        if self._metadata is None:
            return False

        task_desc = data.get("task_description", "")
        embedding = self._embed_text(task_desc, is_query=False)
        if embedding is None:
            embedding = [0.0] * EMBEDDING_DIM

        doc = zvec.Doc(
            id=room_id,
            fields={
                "time_id": uuid7(),
                "task_ref": data.get("task_ref", "UNKNOWN"),
                "status": data.get("status", "unknown"),
                "retries": data.get("retries", 0),
                "message_count": data.get("message_count", 0),
                "last_activity": data.get("last_activity", ""),
                "task_description": task_desc,
            },
            vectors={"embedding": embedding},
        )

        status = self._metadata.upsert(doc)
        return status.ok()

    def get_room_metadata(self, room_id: str) -> dict | None:
        """Fetch room metadata by room_id. Returns None if not found."""
        if self._metadata is None:
            return None
        try:
            result = self._metadata.fetch(room_id)
            if room_id not in result:
                return None
            doc = result[room_id]
            return {
                "time_id": doc.field("time_id"),
                "room_id": room_id,
                "task_ref": doc.field("task_ref"),
                "status": doc.field("status"),
                "retries": doc.field("retries"),
                "message_count": doc.field("message_count"),
                "last_activity": doc.field("last_activity"),
                "task_description": doc.field("task_description"),
            }
        except Exception:
            return None

    def get_all_rooms_metadata(self, order_by_time: bool = False) -> list[dict]:
        """Fetch all room metadata. Returns list of dicts."""
        if self._metadata is None:
            return []
        results = []
        # Query all rooms by scanning — metadata collection is small
        for room_dir in sorted(self.warrooms_dir.glob("room-*")):
            if room_dir.is_dir():
                meta = self.get_room_metadata(room_dir.name)
                if meta:
                    results.append(meta)
        if order_by_time:
            results.sort(key=lambda x: x.get("time_id", ""), reverse=True)
        return results

    # ── Plan & Epic Indexing ─────────────────────────────────────────────

    def index_plan(
        self,
        plan_id: str,
        title: str,
        content: str,
        epic_count: int,
        filename: str = "",
        status: str = "launched",
        created_at: str = "",
        file_mtime: float = 0.0,
    ) -> bool:
        """Index a plan document. Returns True on success."""
        if self._plans is None:
            return False

        content_clean = self._sanitize_text(content)
        embedding = self._embed_text(f"{title} {content_clean[:1000]}", is_query=False)
        if embedding is None:
            embedding = [0.0] * EMBEDDING_DIM

        doc = zvec.Doc(
            id=plan_id,
            fields={
                "time_id": uuid7(),
                "title": title,
                "content": content_clean,
                "status": status,
                "epic_count": epic_count,
                "created_at": created_at or "",
                "filename": filename or "",
                "file_mtime": float(file_mtime or 0.0),
            },
            vectors={"embedding": embedding},
        )
        try:
            s = self._plans.upsert(doc)
            self._plans.flush()
            return s.ok()
        except Exception as e:
            logger.warning("Failed to index plan %s: %s", plan_id, e)
            return False

    def delete_plan(self, plan_id: str) -> bool:
        """Delete a plan from the zvec index by plan_id. Returns True on success."""
        if self._plans is None:
            return False
        try:
            self._plans.delete(plan_id)
            self._plans.flush()
            return True
        except Exception as e:
            logger.warning("Failed to delete plan %s: %s", plan_id, e)
            return False

    def index_epic(
        self,
        epic_ref: str,
        plan_id: str,
        title: str,
        body: str,
        room_id: str,
        working_dir: str = ".",
        status: str = "pending",
    ) -> bool:
        """Index a single Epic from a plan. Returns True on success."""
        if self._epics is None:
            return False

        body_clean = self._sanitize_text(body)
        embed_text = f"{epic_ref} {title} {body_clean[:1000]}"
        embedding = self._embed_text(embed_text, is_query=False)
        if embedding is None:
            embedding = [0.0] * EMBEDDING_DIM

        doc = zvec.Doc(
            id=f"{plan_id}--{epic_ref}",
            fields={
                "time_id": uuid7(),
                "epic_ref": epic_ref,
                "plan_id": plan_id,
                "title": title,
                "body": body_clean,
                "room_id": room_id,
                "status": status,
                "working_dir": working_dir or ".",
            },
            vectors={"embedding": embedding},
        )
        try:
            s = self._epics.upsert(doc)
            self._epics.flush()
            return s.ok()
        except Exception as e:
            logger.warning("Failed to index epic %s: %s", epic_ref, e)
            return False

    def update_epic_status(self, plan_id: str, epic_ref: str, status: str) -> bool:
        """Update an epic's status (syncs from war-room status)."""
        if self._epics is None:
            return False
        doc_id = f"{plan_id}--{epic_ref}"
        try:
            result = self._epics.fetch(doc_id)
            if doc_id not in result:
                return False
            existing = result[doc_id]
            # Re-upsert with updated status
            doc = zvec.Doc(
                id=doc_id,
                fields={
                    "time_id": uuid7(),
                    "epic_ref": existing.field("epic_ref"),
                    "plan_id": existing.field("plan_id"),
                    "title": existing.field("title"),
                    "body": existing.field("body"),
                    "room_id": existing.field("room_id"),
                    "status": status,
                    "working_dir": existing.field("working_dir"),
                },
                vectors={"embedding": [0.0] * EMBEDDING_DIM},  # reuse placeholder
            )
            s = self._epics.upsert(doc)
            self._epics.flush()
            return s.ok()
        except Exception as e:
            logger.warning("Failed to update epic status %s: %s", doc_id, e)
            return False

    def get_plan(self, plan_id: str) -> dict | None:
        """Fetch a single plan by ID."""
        if self._plans is None:
            return None
        try:
            result = self._plans.fetch(plan_id)
            if plan_id not in result:
                return None
            doc = result[plan_id]
            return {
                "time_id": doc.field("time_id"),
                "plan_id": plan_id,
                "title": doc.field("title"),
                "content": doc.field("content"),
                "status": doc.field("status"),
                "epic_count": doc.field("epic_count"),
                "created_at": doc.field("created_at"),
                "filename": doc.field("filename"),
                "file_mtime": doc.field("file_mtime") or 0.0,
            }
        except Exception:
            return None

    def get_all_plans(self, order_by_time: bool = False) -> list[dict]:
        """Fetch all plans. Returns list sorted by created_at desc or time_id."""
        if self._plans is None:
            return []
        results = []
        # Scan plans directory on disk to discover plan IDs
        plans_dir = self._plans_dir()
        if not plans_dir.exists():
            return results
        for f in sorted(plans_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            plan_id = f.stem
            plan = self.get_plan(plan_id)
            if plan:
                results.append(plan)
        if order_by_time:
            results.sort(key=lambda x: x.get("time_id", ""), reverse=True)
        return results

    def get_epics_for_plan(self, plan_id: str) -> list[dict]:
        """Get all epics belonging to a plan."""
        if self._epics is None:
            return []
        results = []
        # Use vector query with filter (any vector, just for filtering)
        try:
            docs = self._epics.query(
                vectors=zvec.VectorQuery("embedding", vector=[0.0] * EMBEDDING_DIM),
                topk=50,
                filter=f"plan_id = '{plan_id}'",
                output_fields=[
                    "time_id",
                    "epic_ref",
                    "plan_id",
                    "title",
                    "body",
                    "room_id",
                    "status",
                    "working_dir",
                ],
            )
            for doc in docs:
                results.append(
                    {
                        "id": doc.id,
                        "time_id": doc.field("time_id"),
                        "epic_ref": doc.field("epic_ref"),
                        "plan_id": doc.field("plan_id"),
                        "title": doc.field("title"),
                        "body": doc.field("body"),
                        "room_id": doc.field("room_id"),
                        "status": doc.field("status"),
                        "working_dir": doc.field("working_dir"),
                    }
                )
        except Exception as e:
            logger.warning("Failed to get epics for plan %s: %s", plan_id, e)
        return results

    # ── Plan History & Asset Change Tracking ────────────────────────────

    def save_plan_version(
        self,
        plan_id: str,
        content: str,
        title: str,
        epic_count: int,
        change_source: str = "manual_save",
    ) -> bool:
        """Store a version snapshot of a plan's .md content."""
        if self._versions is None:
            return False

        # Find the next version number
        existing = self.get_plan_versions(plan_id)
        next_version = (max(v["version"] for v in existing) + 1) if existing else 1

        from datetime import datetime, timezone

        created_at = datetime.now(timezone.utc).isoformat()
        content_clean = self._sanitize_text(content)

        doc_id = f"{plan_id}-v{next_version}"
        embedding = self._embed_text(f"{title} {content_clean[:1000]}", is_query=False)
        if embedding is None:
            embedding = [0.0] * EMBEDDING_DIM

        doc = zvec.Doc(
            id=doc_id,
            fields={
                "time_id": uuid7(),
                "plan_id": plan_id,
                "version": int(next_version),
                "title": title,
                "content": content_clean,
                "epic_count": int(epic_count),
                "change_source": change_source,
                "created_at": created_at,
            },
            vectors={"embedding": embedding},
        )
        try:
            s = self._versions.upsert(doc)
            self._versions.flush()
            return s.ok()
        except Exception as e:
            logger.warning("Failed to save plan version %s: %s", doc_id, e)
            return False

    def get_plan_versions(self, plan_id: str) -> list[dict]:
        """Fetch all version headers for a plan (metadata only)."""
        if self._versions is None:
            return []
        try:
            # Note: Using manual filtering as zvec filter sometimes behaves unexpectedly in-process
            docs = self._versions.query(
                vectors=zvec.VectorQuery("embedding", vector=[0.0] * EMBEDDING_DIM),
                topk=1000,
                output_fields=[
                    "time_id",
                    "plan_id",
                    "version",
                    "title",
                    "epic_count",
                    "change_source",
                    "created_at",
                ],
            )
            results = []
            for doc in docs:
                try:
                    if doc.field("plan_id") == plan_id:
                        results.append(
                            {
                                "id": doc.id,
                                "time_id": doc.field("time_id"),
                                "version": doc.field("version"),
                                "title": doc.field("title"),
                                "epic_count": doc.field("epic_count"),
                                "change_source": doc.field("change_source"),
                                "created_at": doc.field("created_at"),
                            }
                        )
                except Exception:
                    continue
            return sorted(results, key=lambda x: x["version"], reverse=True)
        except Exception as e:
            logger.warning("Failed to get versions for plan %s: %s", plan_id, e)
            return []

    def get_plan_version(self, plan_id: str, version: int) -> dict | None:
        """Fetch a specific version with full content."""
        if self._versions is None:
            return None
        doc_id = f"{plan_id}-v{version}"
        try:
            result = self._versions.fetch(doc_id)
            if doc_id not in result:
                return None
            doc = result[doc_id]
            return {
                "id": doc_id,
                "time_id": doc.field("time_id"),
                "plan_id": doc.field("plan_id"),
                "version": doc.field("version"),
                "title": doc.field("title"),
                "content": doc.field("content"),
                "epic_count": doc.field("epic_count"),
                "change_source": doc.field("change_source"),
                "created_at": doc.field("created_at"),
            }
        except Exception:
            return None

    def save_change_event(
        self,
        plan_id: str,
        change_type: str,
        file_path: str,
        diff_summary: str = "",
        source: str = "git",
    ) -> str | None:
        """Record an asset mutation event."""
        if self._changes is None:
            return None

        import hashlib
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()

        # Unique ID for the change event
        event_id = hashlib.sha256(f"{plan_id}:{now}:{file_path}".encode()).hexdigest()[:12]

        # Embedding for change event
        embedding = self._embed_text(f"{change_type} {file_path} {diff_summary[:500]}", is_query=False)
        if embedding is None:
            embedding = [0.0] * EMBEDDING_DIM

        doc = zvec.Doc(
            id=event_id,
            fields={
                "time_id": uuid7(),
                "plan_id": plan_id,
                "timestamp": now,
                "change_type": change_type,
                "file_path": str(file_path),
                "diff_summary": diff_summary,
                "source": source,
            },
            vectors={"embedding": embedding},
        )
        try:
            s = self._changes.upsert(doc)
            self._changes.flush()
            return event_id if s.ok() else None
        except Exception as e:
            logger.warning("Failed to save change event: %s", e)
            return None

    def get_changes_for_plan(self, plan_id: str, limit: int = 50) -> list[dict]:
        """Retrieve recent change events for a plan."""
        if self._changes is None:
            return []
        try:
            # Note: Using manual filtering as zvec filter sometimes behaves unexpectedly in-process
            docs = self._changes.query(
                vectors=zvec.VectorQuery("embedding", vector=[0.0] * EMBEDDING_DIM),
                topk=1000,
                output_fields=[
                    "time_id",
                    "plan_id",
                    "timestamp",
                    "change_type",
                    "file_path",
                    "diff_summary",
                    "source",
                ],
            )
            results = []
            for doc in docs:
                try:
                    if doc.field("plan_id") == plan_id:
                        results.append(
                            {
                                "id": doc.id,
                                "time_id": doc.field("time_id"),
                                "plan_id": plan_id,
                                "timestamp": doc.field("timestamp"),
                                "change_type": doc.field("change_type"),
                                "file_path": doc.field("file_path"),
                                "diff_summary": doc.field("diff_summary"),
                                "source": doc.field("source"),
                            }
                        )
                except Exception:
                    continue
            # Sort by timestamp desc and apply limit
            return sorted(results, key=lambda x: x["timestamp"], reverse=True)[:limit]
        except Exception as e:
            logger.warning("Failed to get changes for plan %s: %s", plan_id, e)
            return []

    def get_change_event(self, change_id: str) -> dict | None:
        """Fetch a specific change event by ID."""
        if self._changes is None:
            return None
        try:
            result = self._changes.fetch(change_id)
            if change_id not in result:
                return None
            doc = result[change_id]
            return {
                "id": change_id,
                "time_id": doc.field("time_id"),
                "plan_id": doc.field("plan_id"),
                "timestamp": doc.field("timestamp"),
                "change_type": doc.field("change_type"),
                "file_path": doc.field("file_path"),
                "diff_summary": doc.field("diff_summary"),
                "source": doc.field("source"),
            }
        except Exception:
            return None

    def search_plans(self, query: str, limit: int = 10, order_by_time: bool = False) -> list[dict]:
        """Semantic search across plans."""
        if self._plans is None:
            return []
        embedding = self._embed_text(query, is_query=True)
        if embedding is None:
            return []
        try:
            docs = self._plans.query(
                vectors=zvec.VectorQuery("embedding", vector=embedding),
                topk=limit,
                output_fields=[
                    "time_id",
                    "title",
                    "status",
                    "epic_count",
                    "created_at",
                    "filename",
                    "file_mtime",
                ],
            )
            results = [
                {
                    "plan_id": doc.id,
                    "time_id": doc.field("time_id"),
                    "score": doc.score,
                    "title": doc.field("title"),
                    "status": doc.field("status"),
                    "epic_count": doc.field("epic_count"),
                    "created_at": doc.field("created_at"),
                    "filename": doc.field("filename"),
                    "file_mtime": doc.field("file_mtime") or 0.0,
                }
                for doc in docs
            ]
            if order_by_time:
                results.sort(key=lambda x: x.get("time_id", ""), reverse=True)
            return results
        except Exception as e:
            logger.error("Plan search failed: %s", e)
            return []

    def search_epics(
        self,
        query: str,
        plan_id: str | None = None,
        limit: int = 20,
        order_by_time: bool = False,
    ) -> list[dict]:
        """Semantic search across epics."""
        if self._epics is None:
            return []
        embedding = self._embed_text(query, is_query=True)
        if embedding is None:
            return []
        filter_str = f"plan_id = '{plan_id}'" if plan_id else None
        try:
            docs = self._epics.query(
                vectors=zvec.VectorQuery("embedding", vector=embedding),
                topk=limit,
                filter=filter_str,
                output_fields=[
                    "time_id",
                    "epic_ref",
                    "plan_id",
                    "title",
                    "body",
                    "room_id",
                    "status",
                    "working_dir",
                ],
            )
            results = [
                {
                    "id": doc.id,
                    "time_id": doc.field("time_id"),
                    "score": doc.score,
                    "epic_ref": doc.field("epic_ref"),
                    "plan_id": doc.field("plan_id"),
                    "title": doc.field("title"),
                    "body": doc.field("body"),
                    "room_id": doc.field("room_id"),
                    "status": doc.field("status"),
                }
                for doc in docs
            ]
            if order_by_time:
                results.sort(key=lambda x: x.get("time_id", ""), reverse=True)
            return results
        except Exception as e:
            logger.error("Epic search failed: %s", e)
            return []

    # ── Skill Indexing & Search ────────────────────────────────────────

    @staticmethod
    def _skill_doc_id(name: str) -> str:
        """Sanitize a skill name into a zvec-safe doc ID (alphanumeric + hyphens)."""
        return re.sub(r"[^a-z0-9-]", "-", name.strip().lower()).strip("-")

    def index_skill(
        self,
        name: str,
        description: str,
        tags: list[str],
        path: str,
        relative_path: str = "",
        trust_level: str = "experimental",
        source: str = "project",
        content: str = "",
        version: str = "0.1.0",
        category: str | None = None,
        applicable_roles: list[str] = [],
        params: list[dict] = [],
        changelog: list[dict] = [],
        author: str | None = None,
        forked_from: str | None = None,
        is_draft: bool = False,
        enabled: bool = True,
    ) -> bool:
        """Index or update a skill. Returns True on success."""
        if self._skills is None:
            return False

        content_clean = self._sanitize_text(content)
        desc_clean = self._sanitize_text(description)
        tags_str = ",".join(tags) if tags else ""
        roles_str = ",".join(applicable_roles) if applicable_roles else ""
        params_json = json.dumps(params)
        changelog_json = json.dumps(changelog)

        embed_text = f"{name} {desc_clean} {tags_str} {content_clean[:1000]}"
        embedding = self._embed_text(embed_text, is_query=False)
        if embedding is None:
            embedding = [0.0] * EMBEDDING_DIM

        doc = zvec.Doc(
            id=self._skill_doc_id(name),
            fields={
                "time_id": uuid7(),
                "name": name,
                "description": desc_clean,
                "tags": tags_str,
                "path": str(path),
                "relative_path": relative_path or "",
                "trust_level": trust_level,
                "source": source,
                "content": content_clean,
                "version": version,
                "category": category,
                "applicable_roles": roles_str,
                "params": params_json,
                "changelog": changelog_json,
                "author": author,
                "forked_from": forked_from,
                "is_draft": 1 if is_draft else 0,
                "enabled": 1 if enabled else 0,
            },
            vectors={"embedding": embedding},
        )
        try:
            s = self._skills.upsert(doc)
            self._skills.flush()
            return s.ok()
        except Exception as e:
            logger.warning("Failed to index skill %s: %s", name, e)
            return False

    def _map_skill_doc(self, doc: zvec.Doc) -> dict:
        """Helper to map a skill zvec doc to a standard skill dict."""
        tags_str = doc.field("tags")
        tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []
        roles_str = doc.field("applicable_roles")
        roles = [r.strip() for r in roles_str.split(",") if r.strip()] if roles_str else []
        try:
            params = json.loads(doc.field("params"))
        except Exception:
            params = []
        try:
            changelog = json.loads(doc.field("changelog"))
        except Exception:
            changelog = []

        return {
            "time_id": doc.field("time_id"),
            "name": doc.field("name"),
            "description": doc.field("description"),
            "tags": tags,
            "path": doc.field("path"),
            "relative_path": doc.field("relative_path"),
            "trust_level": doc.field("trust_level"),
            "source": doc.field("source"),
            "content": doc.field("content"),
            "version": doc.field("version"),
            "category": doc.field("category"),
            "applicable_roles": roles,
            "params": params,
            "changelog": changelog,
            "author": doc.field("author"),
            "forked_from": doc.field("forked_from"),
            "is_draft": bool(doc.field("is_draft")),
            "enabled": bool(doc.field("enabled")) if doc.field("enabled") is not None else True,
        }

    def get_skill(self, name: str) -> dict | None:
        """Fetch a single skill by name. Returns None if not found."""
        if self._skills is None:
            return None
        try:
            doc_id = self._skill_doc_id(name)
            result = self._skills.fetch(doc_id)
            if doc_id not in result:
                return None
            return self._map_skill_doc(result[doc_id])
        except Exception:
            return None

    def get_all_skills(self, limit: int = 100, order_by_time: bool = False) -> list[dict]:
        """Fetch all indexed skills. Returns list of dicts."""
        if self._skills is None:
            return []
        try:
            # Use a zero-vector query to retrieve all docs up to limit
            docs = self._skills.query(
                vectors=zvec.VectorQuery("embedding", vector=[0.0] * EMBEDDING_DIM),
                topk=limit,
                output_fields=[
                    "time_id",
                    "name",
                    "description",
                    "tags",
                    "path",
                    "relative_path",
                    "trust_level",
                    "source",
                    "content",
                    "version",
                    "category",
                    "applicable_roles",
                    "params",
                    "changelog",
                    "author",
                    "forked_from",
                    "is_draft",
                    "enabled",
                ],
            )
            results = [self._map_skill_doc(doc) for doc in docs]
            if order_by_time:
                # Sort by time_id descending (newest first)
                results.sort(key=lambda x: x.get("time_id", ""), reverse=True)
            return results
        except Exception as e:
            logger.error("get_all_skills failed: %s", e)
            return []

    def search_skills(self, query: str, limit: int = 20, order_by_time: bool = False) -> list[dict]:
        """Semantic search across indexed skills. Returns ranked results."""
        if self._skills is None:
            return []
        embedding = self._embed_text(query, is_query=True)
        if embedding is None:
            return []
        try:
            docs = self._skills.query(
                vectors=zvec.VectorQuery("embedding", vector=embedding),
                topk=limit,
                output_fields=[
                    "time_id",
                    "name",
                    "description",
                    "tags",
                    "path",
                    "relative_path",
                    "trust_level",
                    "source",
                    "content",
                    "version",
                    "category",
                    "applicable_roles",
                    "params",
                    "changelog",
                    "author",
                    "forked_from",
                    "is_draft",
                    "enabled",
                ],
            )
            results = []
            for doc in docs:
                skill = self._map_skill_doc(doc)
                skill["score"] = float(doc.score)
                results.append(skill)
            if order_by_time:
                # Sort by time_id descending (newest first)
                results.sort(key=lambda x: x.get("time_id", ""), reverse=True)
            return results
        except Exception as e:
            logger.error("Skill search failed: %s", e)
            return []

    def delete_skill(self, name: str) -> bool:
        """Delete a skill by name. Returns True on success."""
        if self._skills is None:
            return False
        try:
            self._skills.delete(name)
            self._skills.flush()
            return True
        except Exception as e:
            logger.warning("Failed to delete skill %s: %s", name, e)
            return False

    def sync_skills(self, skills_dirs: list) -> dict:
        """Synchronize skills collection with SKILL.md files on disk.

        Handles additions, updates, and removals.
        Returns dict with synced_count, added, updated, removed.
        """
        from dashboard.api_utils import parse_skill_md

        added = []
        updated = []
        removed = []
        synced_count = 0

        # 1. Collect current skills from disk
        disk_skills: dict[str, dict] = {}
        for sdir in skills_dirs:
            sdir_path = Path(sdir) if not isinstance(sdir, Path) else sdir
            if not sdir_path.exists():
                continue
            for skill_md in sdir_path.rglob("SKILL.md"):
                skill_data = parse_skill_md(skill_md.parent)
                if skill_data:
                    disk_skills[skill_data["name"]] = skill_data

        # 2. Fetch all indexed skill names
        try:
            indexed_skills = self.get_all_skills(limit=1000)
            indexed_names = {s["name"] for s in indexed_skills}
        except Exception:
            indexed_names = set()

        # 3. Filter to only skills that actually changed
        to_index: list[tuple[str, dict, bool]] = []  # (name, data, is_new)
        for name, data in disk_skills.items():
            existing = self.get_skill(name)
            content_bytes = data["content"].encode("ascii", errors="replace")
            content_ascii = content_bytes.decode("ascii")
            if existing and existing.get("content") == content_ascii:
                continue
            to_index.append((name, data, existing is None))

        # 4. Batch-embed all changed skills in one model call
        if to_index:
            embed_texts = []
            for _, data, _ in to_index:
                desc_clean = self._sanitize_text(data["description"])
                content_clean = self._sanitize_text(data["content"])
                tags_str = ",".join(data.get("tags", []))
                embed_texts.append(f"{data['name']} {desc_clean} {tags_str} {content_clean[:1000]}")

            logger.info("Batch-embedding %d skills...", len(embed_texts))
            embeddings = self._embed_texts_batch(embed_texts)

            for (name, data, is_new), embedding in zip(to_index, embeddings):
                if embedding is None:
                    embedding = [0.0] * EMBEDDING_DIM

                doc = zvec.Doc(
                    id=self._skill_doc_id(name),
                    fields={
                        "time_id": uuid7(),
                        "name": name,
                        "description": self._sanitize_text(data["description"]),
                        "tags": ",".join(data.get("tags", [])),
                        "path": str(data["path"]),
                        "relative_path": data.get("relative_path", ""),
                        "trust_level": data.get("trust_level", "experimental"),
                        "source": data["source"],
                        "content": self._sanitize_text(data["content"]),
                        "version": data.get("version", "0.1.0"),
                        "category": data.get("category"),
                        "applicable_roles": ",".join(data.get("applicable_roles", [])),
                        "params": json.dumps(data.get("params", [])),
                        "changelog": json.dumps(data.get("changelog", [])),
                        "author": data.get("author"),
                        "forked_from": data.get("forked_from"),
                        "is_draft": 1 if data.get("is_draft", False) else 0,
                        "enabled": 1,
                    },
                    vectors={"embedding": embedding},
                )
                try:
                    self._skills.upsert(doc)
                    synced_count += 1
                    if is_new:
                        added.append(name)
                    else:
                        updated.append(name)
                except Exception as e:
                    logger.debug("Failed to upsert skill %s: %s", name, e)

        # 5. Handle removals — skills deleted from disk
        disk_names = set(disk_skills.keys())
        for name in indexed_names:
            if name not in disk_names:
                if self.delete_skill(name):
                    removed.append(name)

        # Optimize index after bulk operations
        if self._skills:
            try:
                self._skills.optimize()
            except Exception:
                pass

        logger.info(
            "Skills sync: %d synced, %d added, %d updated, %d removed",
            synced_count,
            len(added),
            len(updated),
            len(removed),
        )
        return {
            "synced_count": synced_count,
            "added": added,
            "updated": updated,
            "removed": removed,
        }

    # ── Role Indexing & Search ─────────────────────────────────────────

    def index_role(
        self,
        role_id: str,
        name: str,
        description: str = "",
        provider: str = "",
        version: str = "",
        temperature: float = 0.7,
        budget_tokens_max: int = 500000,
        max_retries: int = 3,
        timeout_seconds: int = 300,
        skill_refs: list[str] | None = None,
        instance_type: str = "worker",
        system_prompt_override: str | None = None,
        created_at: str = "",
        updated_at: str = "",
    ) -> bool:
        """Index or update a role. Returns True on success."""
        if self._roles is None:
            return False

        skill_refs = skill_refs or []
        skill_refs_str = ",".join(skill_refs)
        desc_clean = self._sanitize_text(description)
        inst_type_clean = self._sanitize_text(instance_type)

        embed_text = f"{name} {provider} {desc_clean} {skill_refs_str} {inst_type_clean}"
        embedding = self._embed_text(embed_text, is_query=False)
        if embedding is None:
            embedding = [0.0] * EMBEDDING_DIM

        doc = zvec.Doc(
            id=role_id,
            fields={
                "time_id": uuid7(),
                "role_id": role_id,
                "name": name,
                "description": desc_clean,
                "provider": provider,
                "version": version,
                "temperature": str(temperature),
                "budget_tokens_max": str(budget_tokens_max),
                "max_retries": str(max_retries),
                "timeout_seconds": str(timeout_seconds),
                "skill_refs": skill_refs_str,
                "instance_type": inst_type_clean,
                "system_prompt_override": system_prompt_override,
                "created_at": created_at,
                "updated_at": updated_at,
            },
            vectors={"embedding": embedding},
        )
        try:
            s = self._roles.upsert(doc)
            self._roles.flush()
            return s.ok()
        except Exception as e:
            logger.warning("Failed to index role %s: %s", role_id, e)
            return False

    def _map_role_doc(self, doc: zvec.Doc) -> dict:
        """Helper to map a role zvec doc to a standard role dict."""
        skill_refs_str = doc.field("skill_refs")
        skill_refs = [s.strip() for s in skill_refs_str.split(",") if s.strip()] if skill_refs_str else []

        temp_str = doc.field("temperature")
        try:
            temperature = float(temp_str)
        except (ValueError, TypeError):
            temperature = 0.7

        budget_str = doc.field("budget_tokens_max")
        try:
            budget_tokens_max = int(budget_str)
        except (ValueError, TypeError):
            budget_tokens_max = 500000

        retries_str = doc.field("max_retries")
        try:
            max_retries = int(retries_str)
        except (ValueError, TypeError):
            max_retries = 3

        timeout_str = doc.field("timeout_seconds")
        try:
            timeout_seconds = int(timeout_str)
        except (ValueError, TypeError):
            timeout_seconds = 300

        return {
            "time_id": doc.field("time_id"),
            "id": doc.field("role_id"),
            "name": doc.field("name"),
            "description": doc.field("description"),
            "provider": doc.field("provider"),
            "version": doc.field("version"),
            "temperature": temperature,
            "budget_tokens_max": budget_tokens_max,
            "max_retries": max_retries,
            "timeout_seconds": timeout_seconds,
            "skill_refs": skill_refs,
            "instance_type": doc.field("instance_type") or "worker",
            "system_prompt_override": doc.field("system_prompt_override"),
            "created_at": doc.field("created_at"),
            "updated_at": doc.field("updated_at"),
        }

    def get_role(self, role_id: str) -> dict | None:
        """Fetch a single role by ID. Returns None if not found."""
        if self._roles is None:
            return None
        try:
            result = self._roles.fetch(role_id)
            if role_id not in result:
                return None
            return self._map_role_doc(result[role_id])
        except Exception:
            return None

    def get_all_roles(self, limit: int = 100, order_by_time: bool = False) -> list[dict]:
        """Fetch all indexed roles. Returns list of dicts."""
        if self._roles is None:
            return []
        try:
            docs = self._roles.query(
                vectors=zvec.VectorQuery("embedding", vector=[0.0] * EMBEDDING_DIM),
                topk=limit,
                output_fields=[
                    "time_id",
                    "role_id",
                    "name",
                    "description",
                    "provider",
                    "version",
                    "temperature",
                    "budget_tokens_max",
                    "max_retries",
                    "timeout_seconds",
                    "skill_refs",
                    "system_prompt_override",
                    "created_at",
                    "updated_at",
                ],
            )
            results = [self._map_role_doc(doc) for doc in docs]
            if order_by_time:
                results.sort(key=lambda x: x.get("time_id", ""), reverse=True)
            return results
        except Exception as e:
            logger.error("get_all_roles failed: %s", e)
            return []

    def search_roles(self, query: str, limit: int = 20, order_by_time: bool = False) -> list[dict]:
        """Semantic search across indexed roles. Returns ranked results."""
        if self._roles is None:
            return []
        embedding = self._embed_text(query, is_query=True)
        if embedding is None:
            return []
        try:
            docs = self._roles.query(
                vectors=zvec.VectorQuery("embedding", vector=embedding),
                topk=limit,
                output_fields=[
                    "time_id",
                    "role_id",
                    "name",
                    "description",
                    "provider",
                    "version",
                    "temperature",
                    "budget_tokens_max",
                    "max_retries",
                    "timeout_seconds",
                    "skill_refs",
                    "system_prompt_override",
                    "created_at",
                    "updated_at",
                ],
            )
            results = []
            for doc in docs:
                role = self._map_role_doc(doc)
                role["score"] = float(doc.score)
                results.append(role)
            if order_by_time:
                results.sort(key=lambda x: x.get("time_id", ""), reverse=True)
            return results
        except Exception as e:
            logger.error("Role search failed: %s", e)
            return []

    def delete_role(self, role_id: str) -> bool:
        """Delete a role by ID. Returns True on success."""
        if self._roles is None:
            return False
        try:
            self._roles.delete(role_id)
            self._roles.flush()
            return True
        except Exception as e:
            logger.warning("Failed to delete role %s: %s", role_id, e)
            return False

    def sync_roles(self, roles_dir: Path) -> dict:
        """Synchronize roles collection with config/registry on disk.

        Handles additions, updates, and removals.
        Returns dict with synced_count, added, updated, removed.
        """
        added = []
        updated = []
        removed = []
        synced_count = 0

        roles_dir = Path(roles_dir) if not isinstance(roles_dir, Path) else roles_dir

        # 1. Read roles from disk (config.json or registry.json fallback)
        disk_roles: dict[str, dict] = {}
        config_file = roles_dir / "config.json"
        registry_file = roles_dir / "registry.json"

        if config_file.exists():
            try:
                data = json.loads(config_file.read_text())
                for r in data:
                    role_id = r.get("id", "")
                    if role_id:
                        disk_roles[role_id] = r
            except Exception as e:
                logger.warning("Failed to read roles config.json: %s", e)
        elif registry_file.exists():
            try:
                data = json.loads(registry_file.read_text())
                for r in data.get("roles", []):
                    role_name = r.get("name", "")
                    role_id = r.get("id", f"registry-{role_name}")
                    if role_id:
                        disk_roles[role_id] = {**r, "id": role_id}
            except Exception as e:
                logger.warning("Failed to read roles registry.json: %s", e)

        if not disk_roles:
            logger.info("No roles found on disk — skipping sync")
            return {"synced_count": 0, "added": [], "updated": [], "removed": []}

        # 2. Fetch all indexed role IDs
        try:
            indexed_roles = self.get_all_roles(limit=1000)
            indexed_ids = {r["id"] for r in indexed_roles}
        except Exception:
            indexed_ids = set()

        # 3. Handle additions and updates
        for role_id, data in disk_roles.items():
            existing = self.get_role(role_id)
            if existing and existing.get("updated_at") == data.get("updated_at", ""):
                continue

            if self.index_role(
                role_id=role_id,
                name=data.get("name", ""),
                description=data.get("description", ""),
                provider=data.get("provider", ""),
                version=data.get("version", ""),
                temperature=float(data.get("temperature", 0.7)),
                budget_tokens_max=int(data.get("budget_tokens_max", 500000)),
                max_retries=int(data.get("max_retries", 3)),
                timeout_seconds=int(data.get("timeout_seconds", 300)),
                skill_refs=data.get("skill_refs", []),
                system_prompt_override=data.get("system_prompt_override"),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
            ):
                synced_count += 1
                if not existing:
                    added.append(role_id)
                else:
                    updated.append(role_id)

        # 4. Handle removals — roles deleted from disk
        disk_ids = set(disk_roles.keys())
        for role_id in indexed_ids:
            if role_id not in disk_ids:
                if self.delete_role(role_id):
                    removed.append(role_id)

        if self._roles:
            try:
                self._roles.optimize()
            except Exception:
                pass

        logger.info(
            "Roles sync: %d synced, %d added, %d updated, %d removed",
            synced_count,
            len(added),
            len(updated),
            len(removed),
        )
        return {
            "synced_count": synced_count,
            "added": added,
            "updated": updated,
            "removed": removed,
        }

    # ── Search ─────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        room_id: str | None = None,
        msg_type: str | None = None,
        limit: int = 20,
        order_by_time: bool = False,
    ) -> list[dict]:
        """Semantic search across indexed messages. Returns ranked results."""
        if self._messages is None:
            return []

        embedding = self._embed_text(query, is_query=True)
        if embedding is None:
            return []

        # Build filter expression
        filters = []
        if room_id:
            filters.append(f"room_id = '{room_id}'")
        if msg_type:
            filters.append(f"msg_type = '{msg_type}'")
        filter_str = " AND ".join(filters) if filters else None

        try:
            docs = self._messages.query(
                vectors=zvec.VectorQuery("embedding", vector=embedding),
                topk=limit,
                filter=filter_str,
                output_fields=[
                    "time_id",
                    "room_id",
                    "from_role",
                    "to_role",
                    "msg_type",
                    "ref",
                    "ts",
                    "body",
                ],
            )

            results = []
            for doc in docs:
                results.append(
                    {
                        "id": doc.id,
                        "time_id": doc.field("time_id"),
                        "score": doc.score,
                        "room_id": doc.field("room_id"),
                        "from": doc.field("from_role"),
                        "to": doc.field("to_role"),
                        "type": doc.field("msg_type"),
                        "ref": doc.field("ref"),
                        "ts": doc.field("ts"),
                        "body": doc.field("body"),
                    }
                )
            if order_by_time:
                results.sort(key=lambda x: x.get("time_id", ""), reverse=True)
            return results
        except Exception as e:
            logger.error("Search failed: %s", e)
            return []

    # ── Disk Sync ──────────────────────────────────────────────────────

    def sync_from_disk(self) -> int:
        """
        Backfill zvec from all channel.jsonl files on disk.
        Idempotent — uses message ID as primary key (upsert).
        Also syncs room metadata from room files.
        Returns total messages indexed.
        """
        total = 0
        if not self.warrooms_dir.exists():
            return 0

        for room_dir in sorted(self.warrooms_dir.glob("room-*")):
            if not room_dir.is_dir():
                continue
            room_id = room_dir.name

            # Sync channel messages
            channel_file = room_dir / "channel.jsonl"
            if channel_file.exists():
                msgs = []
                for line in channel_file.read_text().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msgs.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                total += self.index_messages_batch(room_id, msgs)

            # Sync room metadata from files
            task_ref = self._read_file(room_dir / "task-ref")
            if not task_ref:
                # Fallback: extract from TASKS.md
                tasks_md = room_dir / "TASKS.md"
                if tasks_md.exists():
                    header = tasks_md.read_text().split("\n", 1)[0]
                    m = re.search(r"(EPIC-\d+|TASK-\d+)", header)
                    if m:
                        task_ref = m.group(1)
            if not task_ref:
                # Fallback: derive from room-id
                m = re.match(r"room-(\d+)", room_id)
                task_ref = f"EPIC-{m.group(1)}" if m else "UNKNOWN"

            status = self._read_file(room_dir / "status") or "unknown"
            retries_str = self._read_file(room_dir / "retries") or "0"
            retries = int(retries_str) if retries_str.isdigit() else 0

            # Read description from brief.md or TASKS.md
            desc = None
            if (room_dir / "brief.md").exists():
                desc = (room_dir / "brief.md").read_text()
            elif (room_dir / "TASKS.md").exists():
                desc = (room_dir / "TASKS.md").read_text()

            channel_file = room_dir / "channel.jsonl"
            msg_count = 0
            last_activity = None
            if channel_file.exists():
                lines = [l for l in channel_file.read_text().splitlines() if l.strip()]
                msg_count = len(lines)
                if lines:
                    try:
                        last_msg = json.loads(lines[-1])
                        last_activity = last_msg.get("ts", "")
                    except json.JSONDecodeError:
                        pass

            self.upsert_room_metadata(
                room_id,
                {
                    "task_ref": task_ref,
                    "status": status,
                    "retries": retries,
                    "message_count": msg_count,
                    "last_activity": last_activity or "",
                    "task_description": desc or "",
                },
            )

        # Sync plans from disk
        plans_synced = self._sync_plans_from_disk()

        if self._messages:
            self._messages.flush()
            # Build HNSW index for search after bulk insert
            try:
                self._messages.optimize()
            except Exception as e:
                logger.warning("optimize failed: %s", e)
        if self._metadata:
            self._metadata.flush()
        if self._plans:
            self._plans.flush()
            try:
                self._plans.optimize()
            except Exception:
                pass
        if self._epics:
            self._epics.flush()
            try:
                self._epics.optimize()
            except Exception:
                pass
        if self._versions:
            self._versions.flush()
        if self._changes:
            self._changes.flush()

        logger.info("zvec sync complete: %d messages, %d plans indexed", total, plans_synced)
        return total

    def _sync_plans_from_disk(self) -> int:
        """Backfill plans collection from .agents/plans/*.md files on disk."""
        plans_dir = self._plans_dir()
        if not plans_dir.exists():
            return 0

        count = 0
        for plan_file in sorted(plans_dir.glob("*.md")):
            plan_id = plan_file.stem
            if plan_id == "PLAN.template":
                continue

            try:
                content = plan_file.read_text()
            except FileNotFoundError:
                continue
            if not content.strip():
                continue

            # Extract title from "# Plan: ..." header
            title_match = re.search(r"^# (?:Plan|PLAN):\s*(.+)", content, re.MULTILINE)
            title = title_match.group(1).strip() if title_match else plan_id

            # Extract epics/tasks
            epics = self._parse_plan_epics(content, plan_id)

            # Determine status from war-rooms (if rooms exist, it was launched)
            status = (
                "launched"
                if any((self.warrooms_dir / f"room-{i + 1:03d}").exists() for i in range(len(epics)))
                else "stored"
            )

            # Use file mtime as created_at
            from datetime import datetime, timezone

            mtime = plan_file.stat().st_mtime
            created_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()

            self.index_plan(
                plan_id=plan_id,
                title=title,
                content=content,
                epic_count=len(epics),
                filename=plan_file.name,
                status=status,
                created_at=created_at,
            )

            # Index each epic
            for epic in epics:
                # Try to sync status from war-room
                room_dir = self.warrooms_dir / epic["room_id"]
                epic_status = "pending"
                if room_dir.exists():
                    s = self._read_file(room_dir / "status")
                    if s:
                        epic_status = s

                self.index_epic(
                    epic_ref=epic["task_ref"],
                    plan_id=plan_id,
                    title=epic["title"],
                    body=epic["body"],
                    room_id=epic["room_id"],
                    working_dir=epic.get("working_dir", "."),
                    status=epic_status,
                )

            count += 1

        return count

    @staticmethod
    def _parse_plan_epics(content: str, plan_id: str) -> list[dict]:
        """Parse a plan markdown into a list of epic/task dicts."""
        # Extract working dir
        config_match = re.search(r"working_dir:\s*(.+)", content)
        working_dir = config_match.group(1).strip() if config_match else "."

        # Detect format
        has_epics_colon = bool(re.search(r"^#{2,3} Epic:", content, re.MULTILINE))
        has_epics_bare = bool(re.search(r"^#{2,3} EPIC-\d+", content, re.MULTILINE))
        has_tasks = bool(re.search(r"^#{2,3} Tasks?:", content, re.MULTILINE))

        if has_epics_colon:
            # "## Epic: EPIC-001 — Title" format
            split_pattern = r"^#{2,3} Epic:\s*"
            ref_pattern = r"(EPIC-\d+)\s*[—\-:]\s*(.*)"
            default_prefix = "EPIC"
        elif has_epics_bare:
            # "### EPIC-001 — Title" format (no "Epic:" prefix)
            split_pattern = r"^#{2,3} (?=EPIC-\d+)"
            ref_pattern = r"(EPIC-\d+)\s*[—\-:]\s*(.*)"
            default_prefix = "EPIC"
        elif has_tasks:
            split_pattern = r"^#{2,3} Tasks?:\s*"
            ref_pattern = r"(TASK-\d+)\s*[—\-:]\s*(.*)"
            default_prefix = "TASK"
        else:
            return []

        items = []
        parts = re.split(split_pattern, content, flags=re.MULTILINE)

        for i, part in enumerate(parts[1:], 1):
            lines = part.strip().split("\n")
            header = lines[0].strip()

            ref_match = re.match(ref_pattern, header)
            if ref_match:
                item_ref = ref_match.group(1)
                item_title = ref_match.group(2).strip()
            else:
                item_ref = f"{default_prefix}-{i:03d}"
                item_title = header

            item_body = "\n".join(lines[1:]).strip()
            room_id = f"room-{i:03d}"

            depends_on = []
            m_deps = re.search(r"depends_on:\s*\[(.*?)\]", item_body)
            if m_deps:
                deps_str = m_deps.group(1)
                depends_on = [d.strip() for d in deps_str.split(",") if d.strip()]

            items.append(
                {
                    "room_id": room_id,
                    "task_ref": item_ref,
                    "epic_ref": item_ref,
                    "title": item_title,
                    "body": item_body,
                    "working_dir": working_dir,
                    "depends_on": depends_on,
                    "status": "pending",
                }
            )

        return items

    def close(self) -> None:
        """Flush and close collections."""
        if self._messages:
            self._messages.flush()
        if self._metadata:
            self._metadata.flush()
        if self._plans:
            self._plans.flush()
        if self._epics:
            self._epics.flush()
        if self._skills:
            self._skills.flush()
        if self._versions:
            self._versions.flush()
        if self._changes:
            self._changes.flush()
        if self._roles:
            self._roles.flush()

    # ── Helpers ─────────────────────────────────────────────────────────

    def _plans_dir(self) -> Path:
        """Always use the global plans store (~/.ostwin/.agents/plans/)."""
        global_store = Path.home() / ".ostwin" / ".agents" / "plans"
        if global_store.exists():
            return global_store
        if self.agents_dir:
            return self.agents_dir / "plans"
        # Fallback: try common locations
        for candidate in [
            self.warrooms_dir.parent / ".agents" / "plans",
            self.warrooms_dir.parent.parent / ".agents" / "plans",
        ]:
            if candidate.exists():
                return candidate
        return self.warrooms_dir.parent / ".agents" / "plans"

    @staticmethod
    def _read_file(path: Path) -> str | None:
        try:
            return path.read_text().strip() if path.exists() else None
        except Exception:
            return None
