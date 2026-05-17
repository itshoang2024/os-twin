"""FastMCP server exposing knowledge-management tools (EPIC-006).

Mounted at ``/api/knowledge/mcp`` in :mod:`dashboard.api`. External MCP
clients (opencode, claude-desktop, custom) can connect, list tools, and
call them.

All tools return JSON-serialisable dicts. Errors come back as
``{"error": "...", "code": "..."}`` — the tool body NEVER raises an
exception, so the MCP transport always sees a well-formed response.

Lazy-import discipline: importing this module must NOT pull in
``kuzu``/``zvec``/``markitdown``/``anthropic``.
The :class:`KnowledgeService` is constructed on the first tool call (or
the first call to :func:`get_mcp_app`), so dashboard cold-boot stays fast.

Performance: all tools are declared ``async`` and wrap the synchronous
KnowledgeService calls in ``asyncio.to_thread()``. This prevents the
streamable-HTTP transport from blocking the event loop while a long-running
embedding, graph query, or LLM call is in progress.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

logger = logging.getLogger(__name__)

# Singleton KnowledgeService — lazy-init on first tool call so module
# import stays cheap (no kuzu / zvec / markitdown /
# anthropic loaded at startup).
_service: Optional[Any] = None
_service_lock = threading.Lock()


def _get_service() -> Any:
    """Return the lazily-constructed singleton :class:`KnowledgeService`.

    Tests reset the singleton by setting ``mcp_server._service = None``
    (e.g. when changing ``OSTWIN_KNOWLEDGE_DIR`` between tests). When the
    env var is set at construction time, we build a :class:`NamespaceManager`
    rooted at that path so each test's isolated tmp dir is honoured —
    without this, the module-level ``KNOWLEDGE_DIR`` (captured once at
    import) would leak between tests.
    """
    global _service
    if _service is not None:
        return _service
    with _service_lock:
        if _service is None:
            import os as _os
            from pathlib import Path as _Path

            from dashboard.knowledge.namespace import NamespaceManager  # noqa: WPS433
            from dashboard.knowledge.service import KnowledgeService  # noqa: WPS433

            override = _os.environ.get("OSTWIN_KNOWLEDGE_DIR")
            if override:
                nm = NamespaceManager(base_dir=_Path(override))
                _service = KnowledgeService(namespace_manager=nm)
            else:
                _service = KnowledgeService()
        return _service


def _err(code: str, msg: str) -> dict:
    """Build the canonical error envelope returned by every tool on failure."""
    return {"error": msg, "code": code}


def _get_mcp_actor() -> str | None:
    """Get the current MCP actor from environment or session context.
    
    The actor is set via:
    - OSTWIN_MCP_ACTOR environment variable (set by the agent runtime)
    - Session header (for HTTP-based MCP clients)
    
    Returns None if no actor is identified (non-curator session).
    """
    import os
    return os.environ.get("OSTWIN_MCP_ACTOR")


def _requires_confirmation() -> bool:
    """Check if the current session requires confirmation for destructive ops.
    
    Returns True if OSTWIN_MCP_ACTOR is set to "knowledge-curator".
    Other actors and anonymous sessions do NOT require confirmation.
    """
    actor = _get_mcp_actor()
    return actor == "knowledge-curator"


# The FastMCP instance — module-level so the @mcp.tool() decorators run at
# import time. The instance itself is cheap (no transport / network setup
# happens until ``get_mcp_app()`` is called).
#
# ``stateless_http=True`` is critical when the streamable-HTTP app is mounted
# as a sub-app inside FastAPI (see ``dashboard/api.py``). The default mode
# uses a long-running session manager whose task group is started by the
# inner app's lifespan — which FastAPI does NOT propagate to mounted
# sub-apps. Without stateless mode, the first POST to ``/api/knowledge/mcp/...``
# crashes with ``RuntimeError: Task group is not initialized``. Stateless mode
# spins up a per-request transport and avoids the problem entirely. Our
# tools are pure functions with no per-session state, so this is safe.
# DNS-rebinding protection: FastMCP auto-enables it when host is the default
# 127.0.0.1, with a default allow-list of {127.0.0.1:*, localhost:*, [::1]:*}.
# This rejects requests with arbitrary Host headers (e.g. ``testserver`` from
# FastAPI's TestClient) with HTTP 421. Since we are mounted inside the
# parent FastAPI application, the parent app is the right layer to enforce
# host policy (via CORS / reverse-proxy / etc.) — pass a permissive
# transport-security settings object so the inner FastMCP transport accepts
# any Host. We still disable DNS-rebinding-protection (the default for
# ``TransportSecuritySettings`` when explicitly constructed without
# ``enable_dns_rebinding_protection=True``).
_mcp_transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=False,
)

# ``streamable_http_path="/"`` makes the FastMCP transport serve at the
# root of its sub-app (so the externally-reachable URL matches the parent
# mount path — ``/api/knowledge/mcp/`` — without a duplicated ``/mcp``
# segment). The default is ``/mcp`` which would push the real endpoint to
# ``/api/knowledge/mcp/mcp`` — confusing for users following the install
# snippet that just says ``/api/knowledge/mcp``.
mcp = FastMCP(
    "ostwin-knowledge",
    stateless_http=True,
    streamable_http_path="/",
    transport_security=_mcp_transport_security,
)


# ---------------------------------------------------------------------------
# Tool: knowledge_list_namespaces
# ---------------------------------------------------------------------------


@mcp.tool()
async def knowledge_list_namespaces() -> dict:
    """List all knowledge namespaces with their stats.

    Returns a dict with key ``namespaces`` containing one entry per
    namespace: ``{name, created_at, updated_at, language, description,
    stats: {files_indexed, chunks, entities, relations, vectors}, imports}``.

    Use when: the user asks "what knowledge bases are available?", or to
    discover namespace ids before querying or importing.

    Example: ``knowledge_list_namespaces()``
    """
    try:
        ks = _get_service()
        items = await asyncio.to_thread(ks.list_namespaces)
        return {"namespaces": [m.model_dump(mode="json") for m in items]}
    except Exception as exc:  # noqa: BLE001
        logger.exception("knowledge_list_namespaces failed")
        return _err("INTERNAL_ERROR", str(exc))


# ---------------------------------------------------------------------------
# Tool: knowledge_create_namespace
# ---------------------------------------------------------------------------


@mcp.tool()
async def knowledge_create_namespace(
    name: str,
    language: str = "English",
    description: str = "",
) -> dict:
    """Create a new knowledge namespace.

    Args:
        name: lowercase alphanumeric + dashes/underscores, 1-64 chars.
            Must start with a letter or digit. Examples: ``project_docs``,
            ``api-reference``, ``client-handbook-2024``.
        language: human language of expected content (default ``"English"``).
            Used by the LLM during entity extraction.
        description: optional free-form description.

    Returns the created NamespaceMeta as a dict, OR
    ``{"error", "code"}`` on failure (codes: ``INVALID_NAMESPACE_ID``,
    ``NAMESPACE_EXISTS``, ``MAX_NAMESPACES_REACHED``, ``INTERNAL_ERROR``).

    Use when: starting a new knowledge base. NOT needed before
    ``knowledge_import_folder`` — that auto-creates the namespace if missing.

    Example: ``knowledge_create_namespace("project_docs", "English",
    "Internal product handbook v3")``
    """
    try:
        ks = _get_service()
        meta = await asyncio.to_thread(
            ks.create_namespace, name, language=language, description=description or None, actor="anonymous"
        )
        return meta.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        from dashboard.knowledge.namespace import (  # noqa: WPS433
            InvalidNamespaceIdError,
            NamespaceExistsError,
        )
        from dashboard.knowledge.audit import (  # noqa: WPS433
            ImportInProgressError,
            MaxNamespacesReachedError,
        )

        if isinstance(exc, InvalidNamespaceIdError):
            return _err("INVALID_NAMESPACE_ID", str(exc))
        if isinstance(exc, NamespaceExistsError):
            return _err("NAMESPACE_EXISTS", str(exc))
        if isinstance(exc, MaxNamespacesReachedError):
            return _err("MAX_NAMESPACES_REACHED", str(exc))
        if isinstance(exc, ImportInProgressError):
            return _err("IMPORT_IN_PROGRESS", str(exc))
        logger.exception("knowledge_create_namespace failed")
        return _err("INTERNAL_ERROR", str(exc))


# ---------------------------------------------------------------------------
# Tool: knowledge_delete_namespace
# ---------------------------------------------------------------------------


@mcp.tool()
async def knowledge_delete_namespace(name: str, confirm: bool = False) -> dict:
    """Delete a knowledge namespace and all its data permanently.

    Args:
        name: Namespace to delete.
        confirm: Required when called by knowledge-curator to prevent accidental
            deletion. Must be explicitly set to True to proceed.

    Returns ``{"deleted": bool}`` — ``false`` if the namespace did not exist
    (no error), ``true`` if it was removed. On unexpected failure returns
    ``{"error", "code": "INTERNAL_ERROR"}``.

    DANGEROUS: this is irreversible. Confirm with the user before calling.

    Example: ``knowledge_delete_namespace("temp_test_kb")``
    Example (curator): ``knowledge_delete_namespace("temp_test_kb", confirm=True)``
    """
    try:
        # EPIC-006: Confirmation gate for knowledge-curator sessions
        if _requires_confirmation() and not confirm:
            return _err(
                "CONFIRMATION_REQUIRED",
                f"knowledge_delete_namespace requires confirm=True when called by knowledge-curator. "
                f"Explicitly set confirm=True to proceed with deleting namespace '{name}'."
            )
        
        ks = _get_service()
        deleted = await asyncio.to_thread(ks.delete_namespace, name, actor="anonymous")
        return {"deleted": deleted}
    except Exception as exc:  # noqa: BLE001
        logger.exception("knowledge_delete_namespace failed")
        return _err("INTERNAL_ERROR", str(exc))


# ---------------------------------------------------------------------------
# Tool: knowledge_import_folder
# ---------------------------------------------------------------------------


@mcp.tool()
async def knowledge_import_folder(
    namespace: str,
    folder_path: str,
    force: bool = False,
) -> dict:
    """Import all supported files from an absolute folder path into a namespace.

    Supported file types: docx, pdf, xlsx, pptx, doc, ppt, xls, html, htm,
    txt, md, csv, json, xml, yaml, yml, rtf, png, jpg, jpeg, gif, bmp, tiff,
    webp. Image OCR uses Anthropic vision (requires ``ANTHROPIC_API_KEY`` in
    the dashboard environment); without the key, images are walked but
    skipped silently with a warning logged per file.

    Args:
        namespace: target namespace. Auto-created if it doesn't exist.
        folder_path: ABSOLUTE local filesystem path to a directory.
            Relative paths are rejected with code ``INVALID_FOLDER_PATH``.
        force: when ``True``, re-process files whose content hash already
            exists in the namespace (default: skip already-indexed files).

    Returns ``{"job_id": str, "status": "submitted", "message": str}`` on
    success, OR ``{"error", "code"}`` on failure (codes:
    ``INVALID_FOLDER_PATH``, ``FOLDER_NOT_FOUND``, ``NOT_A_DIRECTORY``,
    ``INVALID_NAMESPACE_ID``, ``IMPORT_IN_PROGRESS``, ``INTERNAL_ERROR``).

    The import runs in the background — poll
    ``knowledge_get_import_status`` with the returned ``job_id`` to track
    progress through ``pending → running → completed | failed | cancelled``.

    Example: ``knowledge_import_folder("project_docs", "/Users/me/projects/docs")``
    """
    try:
        from pathlib import Path

        p = Path(folder_path)
        if not p.is_absolute():
            return _err(
                "INVALID_FOLDER_PATH",
                f"folder_path must be absolute, got: {folder_path}",
            )
        if not p.exists():
            return _err("FOLDER_NOT_FOUND", f"folder does not exist: {folder_path}")
        if not p.is_dir():
            return _err("NOT_A_DIRECTORY", f"path is not a directory: {folder_path}")
        ks = _get_service()
        job_id = await asyncio.to_thread(
            ks.import_folder, namespace, str(p), options={"force": force}, actor="anonymous"
        )
        return {
            "job_id": job_id,
            "status": "submitted",
            "message": f"Importing {folder_path} into {namespace}",
        }
    except Exception as exc:  # noqa: BLE001
        from dashboard.knowledge.namespace import InvalidNamespaceIdError  # noqa: WPS433
        from dashboard.knowledge.audit import ImportInProgressError  # noqa: WPS433

        if isinstance(exc, InvalidNamespaceIdError):
            return _err("INVALID_NAMESPACE_ID", str(exc))
        if isinstance(exc, ImportInProgressError):
            return _err("IMPORT_IN_PROGRESS", str(exc))
        if isinstance(exc, FileNotFoundError):
            return _err("FOLDER_NOT_FOUND", str(exc))
        if isinstance(exc, NotADirectoryError):
            return _err("NOT_A_DIRECTORY", str(exc))
        logger.exception("knowledge_import_folder failed")
        return _err("INTERNAL_ERROR", str(exc))


# ---------------------------------------------------------------------------
# Tool: knowledge_get_import_status
# ---------------------------------------------------------------------------


@mcp.tool()
async def knowledge_get_import_status(namespace: str, job_id: str) -> dict:
    """Get the status of a knowledge import job.

    Args:
        namespace: namespace where the import was started (informational —
            kept for symmetry with the REST API; the job is looked up by
            ``job_id`` alone).
        job_id: the id returned by :func:`knowledge_import_folder`.

    Returns the JobStatus as a dict (``state``, ``progress_current``,
    ``progress_total``, ``message``, ``errors``, ``result``). ``state`` is
    one of ``pending | running | completed | failed | interrupted |
    cancelled``. On unknown job: ``{"error", "code": "JOB_NOT_FOUND"}``.

    Use after :func:`knowledge_import_folder` to poll progress.

    Example: ``knowledge_get_import_status("project_docs", "abc-123-uuid")``
    """
    try:
        ks = _get_service()
        status = await asyncio.to_thread(ks.get_job, job_id)
        if status is None:
            return _err("JOB_NOT_FOUND", f"no job with id {job_id}")
        return status.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        logger.exception("knowledge_get_import_status failed")
        return _err("INTERNAL_ERROR", str(exc))


# ---------------------------------------------------------------------------
# Tool: knowledge_query
# ---------------------------------------------------------------------------


@mcp.tool()
async def knowledge_import_text(
    namespace: str,
    text: str,
    source_label: str = "inline",
    force: bool = False,
) -> dict:
    """Ingest plain text directly into a knowledge namespace (synchronous).

    Unlike ``knowledge_import_folder`` (which runs as a background job),
    this tool ingests text **synchronously** and returns the result
    immediately — no job polling needed. Perfect for pasting notes,
    chat excerpts, meeting summaries, or other short-form text.

    The text is chunked, embedded, and processed for entity extraction
    exactly like file-based imports. Duplicate text (same content hash)
    is skipped unless ``force=True``.

    Args:
        namespace: target namespace. Auto-created if it doesn't exist.
        text: plain text to ingest (1–100,000 characters).
        source_label: label identifying the text source, used in chunk
            metadata (default ``"inline"``). Examples: ``"meeting-notes"``,
            ``"chat-excerpt"``, ``"user-input"``.
        force: when ``True``, re-ingest even if the same content hash
            already exists in the namespace (default ``False``).

    Returns ``{"namespace": str, "chunks_added": int, "entities_added": int,
    "relations_added": int, "elapsed_seconds": float}`` on success, OR
    ``{"error", "code"}`` on failure (codes: ``EMPTY_TEXT``,
    ``TEXT_TOO_LONG``, ``INVALID_NAMESPACE_ID``, ``IMPORT_IN_PROGRESS``,
    ``INTERNAL_ERROR``).

    Example: ``knowledge_import_text("project_docs", "The authentication
    system uses JWT tokens with 24-hour expiry...", source_label="auth-design")``
    """
    try:
        if not text or not text.strip():
            return _err("EMPTY_TEXT", "text must not be empty")
        if len(text) > 100_000:
            return _err(
                "TEXT_TOO_LONG",
                f"text length {len(text)} exceeds maximum of 100,000 characters",
            )

        ks = _get_service()
        result = await asyncio.to_thread(
            ks.import_text,
            namespace,
            text,
            source_label=source_label,
            options={"force": force},
            actor=_get_mcp_actor() or "anonymous",
        )
        return result
    except Exception as exc:
        from dashboard.knowledge.namespace import InvalidNamespaceIdError  # noqa: WPS433
        from dashboard.knowledge.audit import ImportInProgressError  # noqa: WPS433

        if isinstance(exc, InvalidNamespaceIdError):
            return _err("INVALID_NAMESPACE_ID", str(exc))
        if isinstance(exc, ImportInProgressError):
            return _err("IMPORT_IN_PROGRESS", str(exc))
        logger.exception("knowledge_import_text failed")
        return _err("INTERNAL_ERROR", str(exc))


@mcp.tool()
async def knowledge_query(
    namespace: str,
    query: str,
    mode: str = "raw",
    top_k: int = 10,
) -> dict:
    """Query a knowledge namespace.

    Args:
        namespace: target namespace.
        query: natural-language question or search phrase.
        mode: one of:

            * ``"raw"`` — vector hits only (fast, no LLM).
            * ``"graph"`` — vector + graph neighbours, PageRank-reranked.
            * ``"summarized"`` — graph + LLM-aggregated answer with
              citations (slowest; requires an LLM model and API key configured).

        top_k: max number of chunk hits to return (default 10).

    Returns the QueryResult dict with ``chunks``, ``entities``, optional
    ``answer``, ``citations``, ``latency_ms``, and ``warnings``. On
    namespace-missing: ``{"error", "code": "NAMESPACE_NOT_FOUND"}``. On
    invalid mode: ``{"error", "code": "BAD_REQUEST"}``.

    When no LLM model/API key is configured and ``mode="summarized"``, the
    response includes ``warnings: ["llm_unavailable"]`` and ``answer: null``
    but still returns chunks — never crashes.

    Use ``"raw"`` when you just need relevant snippets; ``"summarized"``
    when you want a synthesised answer with citations.

    Example: ``knowledge_query("project_docs", "How does auth work?",
    mode="summarized", top_k=5)``
    """
    try:
        ks = _get_service()
        result = await asyncio.to_thread(ks.query, namespace, query, mode=mode, top_k=top_k, actor="anonymous")
        return result.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        from dashboard.knowledge.namespace import NamespaceNotFoundError  # noqa: WPS433

        if isinstance(exc, NamespaceNotFoundError):
            return _err("NAMESPACE_NOT_FOUND", str(exc))
        if isinstance(exc, ValueError):
            return _err("BAD_REQUEST", str(exc))
        logger.exception("knowledge_query failed")
        return _err("INTERNAL_ERROR", str(exc))



@mcp.tool()
async def find_notes_by_knowledge_link(
    namespace: str,
    file_hash: str,
    chunk_idx: Optional[int] = None,
) -> dict:
    """Find memory notes that link to a specific knowledge chunk.

    This is part of the Memory ↔ Knowledge Bridge (EPIC-007) that enables
    bidirectional linking between memory notes and knowledge chunks.

    Args:
        namespace: The knowledge namespace to search.
        file_hash: SHA256 hash of the source file.
        chunk_idx: Optional chunk index. If provided, returns notes that link
            to this specific chunk. If None, returns notes that link to ANY
            chunk in the file.

    Returns:
        ``{"note_ids": [...], "count": N}`` on success, OR
        ``{"error", "code": "BRIDGE_DISABLED"}`` if the bridge is not enabled,
        OR ``{"error", "code": "INTERNAL_ERROR"}`` on other failures.

    Example:
        # Find notes linking to a specific chunk
        ``find_notes_by_knowledge_link("docs", "abc123def456", 0)``

        # Find notes linking to any chunk in a file
        ``find_notes_by_knowledge_link("docs", "abc123def456")``
    """
    try:
        from dashboard.knowledge.bridge import (
            BridgeIndex,
            BridgeConfig,
            is_bridge_enabled,
        )
        
        if not is_bridge_enabled():
            return _err(
                "BRIDGE_DISABLED",
                "Memory-Knowledge bridge is not enabled. "
                "Set OSTWIN_KNOWLEDGE_MEMORY_BRIDGE=1 to enable.",
            )
        
        def _do_lookup():
            # Create bridge index instance
            config = BridgeConfig.from_env()
            bridge = BridgeIndex(config=config)
            
            # Perform lookup
            note_ids = bridge.lookup(namespace, file_hash, chunk_idx)
            
            # Close the bridge connection
            bridge.close()
            return note_ids

        note_ids = await asyncio.to_thread(_do_lookup)
        
        return {
            "note_ids": note_ids,
            "count": len(note_ids),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("find_notes_by_knowledge_link failed")
        return _err("INTERNAL_ERROR", str(exc))


# ---------------------------------------------------------------------------
# ASGI app helper
# ---------------------------------------------------------------------------


def get_mcp_app() -> Any:
    """Return the ASGI app for mounting in ``dashboard/api.py``.

    Tries the modern ``streamable_http_app()`` first (mcp[cli] >= 1.1.x),
    falling back to ``sse_app()`` for older releases. The exact attribute
    name has shifted across mcp[cli] versions, so isolating the choice
    here keeps :mod:`dashboard.api` decoupled.

    Note: the underlying ``StreamableHTTPSessionManager`` may only run
    once per instance — if you need a brand-new MCP app (e.g. across
    successive ``TestClient(app)`` contexts inside one process), call
    :func:`reset_mcp_session_manager` first to drop the spent session
    manager so the next ``streamable_http_app()`` creates a fresh one.
    """
    return mcp.streamable_http_app()


def reset_mcp_session_manager() -> None:
    """Drop the FastMCP ``_session_manager`` so the next ASGI app gets a fresh one.

    Required between successive ``TestClient(app)`` lifespan cycles in the
    same process — :class:`mcp.server.streamable_http_manager.StreamableHTTPSessionManager`
    is single-use and raises ``RuntimeError`` on a second ``run()`` call.

    Production (single uvicorn run) never needs this — the lifespan runs
    exactly once. The function is a no-op if the session manager has not
    been created yet.
    """
    if getattr(mcp, "_session_manager", None) is not None:
        mcp._session_manager = None  # type: ignore[attr-defined]


__all__ = [
    "mcp",
    "get_mcp_app",
    "knowledge_list_namespaces",
    "knowledge_create_namespace",
    "knowledge_delete_namespace",
    "knowledge_import_folder",
    "knowledge_import_text",
    "knowledge_get_import_status",
    "knowledge_query",
    # EPIC-007
    "find_notes_by_knowledge_link",
]
