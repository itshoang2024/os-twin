"""Configuration constants and path helpers for the knowledge package.

All values are env-overridable. No heavy deps imported at module load.

ADR-17: ``SUPPORTED_DOCUMENT_EXTENSIONS`` is the union of the base document
extensions and :data:`IMAGE_EXTENSIONS` so the folder walker picks up images
alongside text documents in a single pass; per-file LLM-vision parsing is
gated separately by ADR-14 (see ``markitdown_reader.py``).
"""

from __future__ import annotations

import os
from pathlib import Path

# --- Core paths -------------------------------------------------------------

KNOWLEDGE_DIR: Path = Path(
    os.environ.get("OSTWIN_KNOWLEDGE_DIR", str(Path.home() / ".ostwin" / "knowledge"))
)

# --- Model defaults ---------------------------------------------------------

EMBEDDING_MODEL: str = os.environ.get(
    "OSTWIN_KNOWLEDGE_EMBED_MODEL", "qwen3-embedding:0.6b"
)
# Embedding dimension is a system-wide constant fixed at startup.
# OSTWIN_EMBEDDING_DIM is the single source of truth — shared by both
# knowledge and memory subsystems.  Cannot be changed dynamically via
# settings to avoid dimension conflicts in vector stores.
from dashboard.llm_client import DEFAULT_EMBEDDING_DIMENSION as EMBEDDING_DIMENSION

# LLM_MODEL has no hardcoded default — user must configure via
# MasterSettings.knowledge.llm_model or OSTWIN_KNOWLEDGE_LLM_MODEL env var.
# When empty, KnowledgeLLM.is_available() returns False (graceful degradation).
LLM_MODEL: str = os.environ.get("OSTWIN_KNOWLEDGE_LLM_MODEL", "llama3.2")

# Provider hints — auto-detected from model name when empty.
# Valid values mirror MemorySettings: "ollama", "openai-compatible", etc.
LLM_PROVIDER: str = os.environ.get("OSTWIN_KNOWLEDGE_LLM_PROVIDER", "ollama")
EMBEDDING_PROVIDER: str = os.environ.get(
    "OSTWIN_KNOWLEDGE_EMBED_PROVIDER", "ollama"
)

# --- Retrieval / graph tunables --------------------------------------------

PAGERANK_SCORE_THRESHOLD: float = float(
    os.environ.get("OSTWIN_KNOWLEDGE_PR_THRESHOLD", "0.001")
)
KUZU_MIGRATE: bool = os.environ.get("OSTWIN_KNOWLEDGE_KUZU_MIGRATE", "1") == "1"

# --- Per-namespace path helpers --------------------------------------------
#
# These module-level helpers are **deprecated** for any code path that needs to
# honour a custom ``base_dir`` (notably tests). They unconditionally root
# everything under :data:`KNOWLEDGE_DIR`, which means a
# :class:`~dashboard.knowledge.namespace.NamespaceManager` constructed with a
# different ``base_dir`` will see its manifest in the right place but its
# vectors / graph in the global location — the bug QA flagged in EPIC-003.
#
# Prefer the **instance methods** on :class:`NamespaceManager`:
#   * ``nm.namespace_dir(ns)``   == ``base / ns``
#   * ``nm.kuzu_db_path(ns)``    == ``base / ns / "graph.db"``
#   * ``nm.vector_dir(ns)``      == ``base / ns / "vectors"``
#   * ``nm.manifest_path(ns)``   == ``base / ns / "manifest.json"``
#
# The functions below remain as a convenience for the (still-correct) default
# case where ``base_dir == KNOWLEDGE_DIR``.


def namespace_dir(namespace: str) -> Path:
    """Return the on-disk directory for a namespace under :data:`KNOWLEDGE_DIR`.

    Deprecated for code that needs to respect a custom ``NamespaceManager.base_dir``;
    use ``NamespaceManager.namespace_dir(ns)`` instead.
    """
    return KNOWLEDGE_DIR / namespace


def kuzu_db_path(namespace: str) -> Path:
    """Return the Kuzu single-file DB path for a namespace.

    Deprecated for code that needs to respect a custom ``NamespaceManager.base_dir``;
    use ``NamespaceManager.kuzu_db_path(ns)`` instead.
    """
    return namespace_dir(namespace) / "graph.db"


def vector_dir(namespace: str) -> Path:
    """Return the per-namespace zvec collection directory.

    The on-disk layout is ``{KNOWLEDGE_DIR}/{namespace}/vectors/`` (was
    ``chroma/`` prior to the EPIC-003 v2 migration to zvec). Deprecated for
    code that needs to respect a custom ``NamespaceManager.base_dir``; use
    ``NamespaceManager.vector_dir(ns)`` instead.
    """
    return namespace_dir(namespace) / "vectors"


def chroma_dir(namespace: str) -> Path:
    """Deprecated alias of :func:`vector_dir`.

    Kept ONLY for backwards-compatibility with one or two test imports that
    have not been updated; new code MUST use :func:`vector_dir` (or, better,
    ``NamespaceManager.vector_dir``). This wrapper still returns the new
    ``vectors/`` path — there is no longer a ``chroma/`` directory anywhere.
    """
    return vector_dir(namespace)


def manifest_path(namespace: str) -> Path:
    """Return the manifest.json path for a namespace.

    Deprecated for code that needs to respect a custom ``NamespaceManager.base_dir``;
    use ``NamespaceManager.manifest_path(ns)`` instead.
    """
    return namespace_dir(namespace) / "manifest.json"


# --- File-type constants (moved from app.utils.constant) -------------------
#
# ADR-17: ``SUPPORTED_DOCUMENT_EXTENSIONS`` is the union of document + image
# extensions so :class:`Ingestor._walk_folder` picks up both kinds in a single
# pass. ADR-14 governs *how* images are parsed (Anthropic vision via
# MarkItDown) — see :mod:`dashboard.knowledge.graph.parsers.markitdown_reader`.
# Without an Anthropic key, image files are still walked but produce empty
# markdown and are skipped with a single warning per file.

_BASE_DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".doc",
    ".ppt",
    ".xls",
    ".html",
    ".htm",
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".rtf",
}

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".tiff",
    ".webp",
}

# Single source of truth for "what gets walked during ingestion" (ADR-17).
SUPPORTED_DOCUMENT_EXTENSIONS = _BASE_DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS

# --- Sliding-window defaults -------------------------------------------------
#
# Used by :class:`SlidingWindowChunker` and
# :class:`VisionSlidingWindowConverter` for page-grouped chunking of
# large documents (PDF, DOCX, etc.).  A "page" is a paragraph-bounded
# segment of approximately ``chunk_size`` characters; ``window_size``
# pages are grouped per window with ``overlap`` pages shared between
# consecutive windows.

SLIDING_WINDOW_SIZE: int = int(
    os.environ.get("OSTWIN_KNOWLEDGE_SLIDING_WINDOW_SIZE", "3")
)
SLIDING_WINDOW_OVERLAP: int = int(
    os.environ.get("OSTWIN_KNOWLEDGE_SLIDING_WINDOW_OVERLAP", "1")
)

# --- Misc -------------------------------------------------------------------

# Garbage-collection ledger file (kept for compat with storage.delete_vector_store)
GARBAGE_COLLECTION_FILE: str = str(KNOWLEDGE_DIR / "_gc.json")
