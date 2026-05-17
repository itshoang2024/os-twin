"""Knowledge REST API routes (EPIC-001).

All 9 endpoints:
  - GET    /api/knowledge/namespaces
  - POST   /api/knowledge/namespaces
  - GET    /api/knowledge/namespaces/{namespace}
  - DELETE /api/knowledge/namespaces/{namespace}
  - POST   /api/knowledge/namespaces/{namespace}/import
  - GET    /api/knowledge/namespaces/{namespace}/jobs
  - GET    /api/knowledge/namespaces/{namespace}/jobs/{job_id}
  - POST   /api/knowledge/namespaces/{namespace}/query
  - GET    /api/knowledge/namespaces/{namespace}/graph

All endpoints require authentication via `Depends(get_current_user)`.
Heavy libraries (kuzu, zvec, MarkItDown) are lazy-loaded
inside KnowledgeService methods — importing this module is cheap.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from typing_extensions import Annotated

from dashboard.auth import get_current_user
from dashboard.knowledge.metrics import get_metrics_registry
from dashboard.routes.knowledge_models import (
    CreateNamespaceRequest,
    DeleteNamespaceResponse,
    ErrorResponse,
    GraphCountsResponse,
    ImportFolderRequest,
    ImportFolderResponse,
    ImportTextRequest,
    ImportTextResponse,
    JobStatusResponse,
    NamespaceJobsResponse,
    NamespaceMetaResponse,
    QueryRequest,
    QueryResultResponse,
    RefreshNamespaceResponse,
    BackupNamespaceResponse,
    RestoreNamespaceRequest,
    RetentionPolicyRequest,
    RetentionPolicyResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

# Path deny-list for import_folder (security)
PATH_DENY_LIST = re.compile(r"^/(etc|sys|proc|dev)(/|$)")


# ---------------------------------------------------------------------------
# Lazy service singleton
# ---------------------------------------------------------------------------

_service_instance: Optional[Any] = None
_service_lock = threading.Lock()


def _get_service() -> Any:
    """Lazy singleton for KnowledgeService.

    Imports dashboard.knowledge.service lazily (no kuzu/zvec/MarkItDown
    at module import time) and caches the instance for the lifetime of the process.
    """
    global _service_instance
    if _service_instance is not None:
        return _service_instance
    with _service_lock:
        if _service_instance is not None:
            return _service_instance
        from dashboard.knowledge.service import KnowledgeService

        _service_instance = KnowledgeService()
        return _service_instance


# ---------------------------------------------------------------------------
# Error mapping helper
# ---------------------------------------------------------------------------


def _map_error(exc: Exception) -> HTTPException:
    """Map domain exceptions to HTTP errors with error_code strings.

    Error codes:
      - INVALID_NAMESPACE_ID: 400, namespace name fails ADR-12 regex
      - NAMESPACE_NOT_FOUND: 404, namespace doesn't exist
      - NAMESPACE_EXISTS: 409, create called on existing namespace
      - IMPORT_IN_PROGRESS: 409, concurrent import already running
      - MAX_NAMESPACES_REACHED: 429, namespace quota exceeded
      - INVALID_FOLDER_PATH: 400, path injection attempt or malformed path
      - FOLDER_NOT_FOUND: 404, import path doesn't exist
      - NOT_A_DIRECTORY: 400, import path is not a directory
      - INTERNAL_ERROR: 500, unexpected exception
    """
    # Import exceptions lazily
    from dashboard.knowledge.namespace import (
        InvalidNamespaceIdError,
        NamespaceExistsError,
        NamespaceNotFoundError,
    )
    from dashboard.knowledge.audit import (  # noqa: WPS433
        ImportInProgressError,
        MaxNamespacesReachedError,
    )


    if isinstance(exc, InvalidNamespaceIdError):
        return HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error=str(exc),
                code="INVALID_NAMESPACE_ID",
                detail={"namespace": getattr(exc, "namespace", None)},
            ).model_dump(),
        )

    if isinstance(exc, NamespaceNotFoundError):
        return HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error=str(exc),
                code="NAMESPACE_NOT_FOUND",
                detail={"namespace": getattr(exc, "namespace", None)},
            ).model_dump(),
        )

    if isinstance(exc, NamespaceExistsError):
        return HTTPException(
            status_code=409,
            detail=ErrorResponse(
                error=str(exc),
                code="NAMESPACE_EXISTS",
                detail={"namespace": getattr(exc, "namespace", None)},
            ).model_dump(),
        )

    # EPIC-003: Import already in progress
    if isinstance(exc, ImportInProgressError):
        return HTTPException(
            status_code=409,
            detail=ErrorResponse(
                error=str(exc),
                code="IMPORT_IN_PROGRESS",
                detail={"namespace": exc.namespace, "job_id": exc.job_id},
            ).model_dump(),
        )

    # EPIC-003: Namespace quota exceeded
    if isinstance(exc, MaxNamespacesReachedError):
        return HTTPException(
            status_code=429,
            detail=ErrorResponse(
                error=str(exc),
                code="MAX_NAMESPACES_REACHED",
                detail={"max_count": exc.max_count},
            ).model_dump(),
        )
    if isinstance(exc, FileNotFoundError):
        return HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error=f"Folder not found: {exc}",
                code="FOLDER_NOT_FOUND",
                detail={"path": str(exc)},
            ).model_dump(),
        )

    if isinstance(exc, NotADirectoryError):
        return HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error=f"Not a directory: {exc}",
                code="NOT_A_DIRECTORY",
                detail={"path": str(exc)},
            ).model_dump(),
        )

    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error=str(exc),
                code="INVALID_REQUEST",
                detail={},
            ).model_dump(),
        )

    # Generic internal error
    logger.exception("Unhandled exception in knowledge API: %s", exc)
    return HTTPException(
        status_code=500,
        detail=ErrorResponse(
            error="Internal server error",
            code="INTERNAL_ERROR",
            detail={"message": str(exc)},
        ).model_dump(),
    )


# ---------------------------------------------------------------------------
# Path safety validation
# ---------------------------------------------------------------------------


def _validate_import_path(folder_path: str) -> Path:
    """Validate that folder_path is safe for import.

    Checks:
      - Must be an absolute path
      - Must exist on disk
      - Must be a directory
      - Must not be under /etc, /sys, /proc, or /dev

    Raises:
      - HTTPException with INVALID_FOLDER_PATH for path injection attempts
      - FileNotFoundError for missing paths
      - NotADirectoryError for non-directory paths
    """
    # Check for empty or relative path
    if not folder_path:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="Folder path is required",
                code="INVALID_FOLDER_PATH",
                detail={"path": folder_path},
            ).model_dump(),
        )

    path = Path(folder_path)

    # Check for absolute path
    if not path.is_absolute():
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="Folder path must be absolute",
                code="INVALID_FOLDER_PATH",
                detail={"path": folder_path},
            ).model_dump(),
        )

    # Check for path traversal attempts
    try:
        resolved = path.resolve()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error=f"Invalid path: {exc}",
                code="INVALID_FOLDER_PATH",
                detail={"path": folder_path},
            ).model_dump(),
        )

    # Check deny-list
    if PATH_DENY_LIST.match(str(resolved)):
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="Import from system directories is not allowed",
                code="INVALID_FOLDER_PATH",
                detail={"path": folder_path},
            ).model_dump(),
        )

    # Check existence
    if not path.exists():
        raise FileNotFoundError(folder_path)

    # Check directory
    if not path.is_dir():
        raise NotADirectoryError(folder_path)

    return path


# ---------------------------------------------------------------------------
# Response conversion helpers
# ---------------------------------------------------------------------------


def _get_actor(user: dict) -> str:
    """Extract actor identifier from user dict for audit logging."""
    # Try common fields
    if "email" in user:
        return user["email"]
    if "sub" in user:
        return user["sub"]
    if "username" in user:
        return user["username"]
    if "id" in user:
        return str(user["id"])
    return "anonymous"


def _namespace_meta_to_response(meta: Any) -> NamespaceMetaResponse:
    """Convert NamespaceMeta from dashboard.knowledge to response model."""
    # Handle retention field (EPIC-004)
    retention_data = {}
    if hasattr(meta, "retention") and meta.retention is not None:
        retention_data = {
            "policy": meta.retention.policy,
            "ttl_days": meta.retention.ttl_days,
            "last_swept_at": meta.retention.last_swept_at,
            "auto_delete_when_empty": meta.retention.auto_delete_when_empty,
        }
    
    return NamespaceMetaResponse(
        schema_version=meta.schema_version,
        name=meta.name,
        created_at=meta.created_at,
        updated_at=meta.updated_at,
        language=meta.language,
        description=meta.description,
        embedding_model=meta.embedding_model,
        embedding_dimension=meta.embedding_dimension,
        stats=meta.stats.model_dump(),
        imports=[imp.model_dump() for imp in meta.imports],
        retention=RetentionPolicyResponse(**retention_data),
    )


def _job_status_to_response(status: Any) -> JobStatusResponse:
    """Convert JobStatus from dashboard.knowledge to response model."""
    return JobStatusResponse(
        job_id=status.job_id,
        namespace=status.namespace,
        operation=status.operation,
        state=status.state.value if hasattr(status.state, "value") else str(status.state),
        submitted_at=status.submitted_at,
        started_at=status.started_at,
        finished_at=status.finished_at,
        progress_current=status.progress_current,
        progress_total=status.progress_total,
        message=status.message,
        errors=list(status.errors),
        result=status.result,
    )


def _query_result_to_response(result: Any) -> QueryResultResponse:
    """Convert QueryResult from dashboard.knowledge to response model."""
    return QueryResultResponse(
        query=result.query,
        mode=result.mode,
        namespace=result.namespace,
        chunks=[c.model_dump() for c in result.chunks],
        entities=[e.model_dump() for e in result.entities],
        answer=result.answer,
        citations=[cit.model_dump() for cit in result.citations],
        latency_ms=result.latency_ms,
        warnings=list(result.warnings),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/namespaces",
    response_model=list[NamespaceMetaResponse],
    responses={
        200: {"description": "List of all namespaces"},
        401: {"description": "Authentication required"},
    },
    summary="List all knowledge namespaces",
)
async def list_namespaces(
    user: Annotated[dict, Depends(get_current_user)],
) -> list[NamespaceMetaResponse]:
    """Return a list of all knowledge namespaces.

    Each namespace is a self-contained knowledge base with its own
    vector store, graph database, and metadata.
    """
    try:
        service = _get_service()
        metas = await asyncio.to_thread(service.list_namespaces)
        return [_namespace_meta_to_response(m) for m in metas]
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces",
    response_model=NamespaceMetaResponse,
    status_code=201,
    responses={
        201: {"description": "Namespace created successfully"},
        400: {"description": "Invalid namespace identifier", "model": ErrorResponse},
        401: {"description": "Authentication required"},
        409: {"description": "Namespace already exists", "model": ErrorResponse},
    },
    summary="Create a new knowledge namespace",
)
async def create_namespace(
    request: CreateNamespaceRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> NamespaceMetaResponse:
    """Create a new knowledge namespace.

    The namespace identifier must be:
    - 1-64 characters long
    - Lowercase letters, numbers, hyphens, and underscores only
    - Start with a letter or number
    """
    try:
        actor = _get_actor(user)
        service = _get_service()
        meta = await asyncio.to_thread(
            service.create_namespace,
            request.name,
            language=request.language,
            description=request.description,
            actor=actor,
        )
        return _namespace_meta_to_response(meta)
    except Exception as exc:
        raise _map_error(exc)


@router.get(
    "/namespaces/{namespace}",
    response_model=NamespaceMetaResponse,
    responses={
        200: {"description": "Namespace metadata"},
        400: {"description": "Invalid namespace identifier", "model": ErrorResponse},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Get namespace metadata",
)
async def get_namespace(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> NamespaceMetaResponse:
    """Get metadata for a specific namespace."""
    try:
        service = _get_service()
        meta = await asyncio.to_thread(service.get_namespace, namespace)
        if meta is None:
            from dashboard.knowledge.namespace import NamespaceNotFoundError

            raise NamespaceNotFoundError(namespace)
        return _namespace_meta_to_response(meta)
    except Exception as exc:
        raise _map_error(exc)


@router.delete(
    "/namespaces/{namespace}",
    response_model=DeleteNamespaceResponse,
    responses={
        200: {"description": "Namespace deleted (or didn't exist)"},
        400: {"description": "Invalid namespace identifier", "model": ErrorResponse},
        401: {"description": "Authentication required"},
    },
    summary="Delete a namespace",
)
async def delete_namespace(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> DeleteNamespaceResponse:
    """Delete a namespace and all its data.

    This is idempotent — deleting a non-existent namespace returns
    `{deleted: false}` rather than an error.
    """
    try:
        actor = _get_actor(user)
        service = _get_service()
        deleted = await asyncio.to_thread(service.delete_namespace, namespace, actor=actor)
        return DeleteNamespaceResponse(deleted=deleted, namespace=namespace)
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/import",
    response_model=ImportFolderResponse,
    responses={
        200: {"description": "Import job submitted"},
        400: {"description": "Invalid folder path", "model": ErrorResponse},
        401: {"description": "Authentication required"},
        404: {"description": "Folder not found", "model": ErrorResponse},
    },
    summary="Import a folder into a namespace",
)
async def import_folder(
    namespace: str,
    request: ImportFolderRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> ImportFolderResponse:
    """Import documents from a folder into a namespace.

    The import runs in the background. The response includes a `job_id`
    that can be used to poll the import status.

    The namespace is auto-created if it doesn't exist.

    Security: The folder path must be absolute, exist, be a directory,
    and not be under system directories (/etc, /sys, /proc, /dev).
    """
    try:
        actor = _get_actor(user)
        # Validate path safety BEFORE submitting to service
        _validate_import_path(request.folder_path)

        service = _get_service()
        # import_folder is intentionally sync (returns job_id fast)
        job_id = await asyncio.to_thread(
            service.import_folder,
            namespace,
            request.folder_path,
            request.options,
            actor=actor,
        )
        return ImportFolderResponse(job_id=job_id, namespace=namespace)
    except HTTPException:
        raise
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/import-text",
    response_model=ImportTextResponse,
    responses={
        200: {"description": "Text ingested successfully"},
        400: {"description": "Invalid request", "model": ErrorResponse},
        401: {"description": "Authentication required"},
        409: {"description": "Import already in progress", "model": ErrorResponse},
    },
    summary="Import plain text into a namespace",
)
async def import_text(
    namespace: str,
    request: ImportTextRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> ImportTextResponse:
    """Ingest plain text directly into a namespace.

    Unlike folder import (which runs as a background job), this is
    **synchronous** — the response includes the result directly.
    Suitable for pasting notes, chat excerpts, or other short-form text.

    The namespace is auto-created if it doesn't exist.
    """
    try:
        actor = _get_actor(user)
        service = _get_service()
        result = await asyncio.to_thread(
            service.import_text,
            namespace,
            request.text,
            request.source_label,
            request.options,
            actor=actor,
        )
        return ImportTextResponse(
            namespace=result["namespace"],
            chunks_added=result["chunks_added"],
            entities_added=result["entities_added"],
            relations_added=result["relations_added"],
            elapsed_seconds=result["elapsed_seconds"],
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _map_error(exc)


@router.get(
    "/namespaces/{namespace}/jobs",
    response_model=NamespaceJobsResponse,
    responses={
        200: {"description": "Jobs list with live graph counters for the namespace"},
        400: {"description": "Invalid namespace identifier", "model": ErrorResponse},
        401: {"description": "Authentication required"},
    },
    summary="List jobs for a namespace (with graph stats)",
)
async def list_jobs(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> NamespaceJobsResponse:
    """List all background jobs for a namespace, sorted by submission time (newest first).

    Also returns live entity/chunk/relation counts from the KuzuDB graph
    so the frontend can render namespace health without an extra API call.
    """
    try:
        service = _get_service()
        jobs = await asyncio.to_thread(service.list_jobs, namespace)
        graph_counts = await asyncio.to_thread(service.count_graph_stats, namespace)
        return NamespaceJobsResponse(
            jobs=[_job_status_to_response(j) for j in jobs],
            graph_counts=GraphCountsResponse(**graph_counts),
        )
    except Exception as exc:
        raise _map_error(exc)


@router.get(
    "/namespaces/{namespace}/jobs/{job_id}",
    response_model=JobStatusResponse,
    responses={
        200: {"description": "Job status"},
        400: {"description": "Invalid namespace identifier", "model": ErrorResponse},
        401: {"description": "Authentication required"},
        404: {"description": "Job not found", "model": ErrorResponse},
    },
    summary="Get job status",
)
async def get_job(
    namespace: str,
    job_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> JobStatusResponse:
    """Get the status of a specific background job."""
    try:
        service = _get_service()
        status = await asyncio.to_thread(service.get_job, job_id)
        if status is None:
            raise HTTPException(
                status_code=404,
                detail=ErrorResponse(
                    error=f"Job not found: {job_id}",
                    code="JOB_NOT_FOUND",
                    detail={"job_id": job_id},
                ).model_dump(),
            )
        return _job_status_to_response(status)
    except HTTPException:
        raise
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/query",
    response_model=QueryResultResponse,
    responses={
        200: {"description": "Query results"},
        400: {"description": "Invalid request", "model": ErrorResponse},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Query a namespace",
)
async def query_namespace(
    namespace: str,
    request: QueryRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> QueryResultResponse:
    """Query a knowledge namespace.

    Modes:
    - **raw**: Vector search only (fast, no graph, no LLM)
    - **graph**: Vector search + graph expansion + PageRank
    - **summarized**: Graph mode + LLM-aggregated answer

    Returns chunks, optionally entities, and optionally an LLM-generated answer.
    """
    try:
        actor = _get_actor(user)
        service = _get_service()
        result = await asyncio.to_thread(
            service.query,
            namespace,
            request.query,
            mode=request.mode,
            top_k=request.top_k,
            threshold=request.threshold,
            category=request.category,
            parameter=request.parameter,
            actor=actor,
        )
        return _query_result_to_response(result)
    except Exception as exc:
        raise _map_error(exc)



# ---------------------------------------------------------------------------
# Graph Visualisation Endpoint (EPIC-004)
# ---------------------------------------------------------------------------


@router.post(
    "/namespaces/{namespace}/refresh",
    response_model=RefreshNamespaceResponse,
    responses={
        200: {"description": "Refresh jobs triggered"},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Refresh all imports in a namespace",
)
async def refresh_namespace(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> RefreshNamespaceResponse:
    """Re-trigger all successful imports for the namespace with force=True.

    Useful for re-indexing data after a model change or bug fix.
    Returns a list of job IDs for the triggered background tasks.
    """
    try:
        actor = _get_actor(user)
        service = _get_service()
        job_ids = await asyncio.to_thread(service.refresh_namespace, namespace, actor=actor)
        return RefreshNamespaceResponse(job_ids=job_ids)
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/backup",
    response_model=BackupNamespaceResponse,
    responses={
        200: {"description": "Backup created successfully"},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Backup a namespace",
)
async def backup_namespace(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> BackupNamespaceResponse:
    """Create a compressed archive of the namespace's data.

    Returns the absolute path to the created archive file.
    """
    try:
        service = _get_service()
        archive_path = await asyncio.to_thread(service.backup_namespace, namespace)
        return BackupNamespaceResponse(archive_path=str(archive_path), namespace=namespace)
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/restore",
    response_model=NamespaceMetaResponse,
    responses={
        200: {"description": "Namespace restored successfully"},
        400: {"description": "Invalid backup archive", "model": ErrorResponse},
        401: {"description": "Authentication required"},
        409: {"description": "Namespace already exists", "model": ErrorResponse},
    },
    summary="Restore a namespace from backup",
)
async def restore_namespace(
    namespace: str,
    request: RestoreNamespaceRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> NamespaceMetaResponse:
    """Restore a namespace from a compressed archive.

    If the namespace already exists, `overwrite: true` must be passed in the
    request body to replace it.
    """
    try:
        service = _get_service()
        meta = await asyncio.to_thread(
            service.restore_namespace,
            request.archive_path,
            name=namespace,
            overwrite=request.overwrite
        )
        return _namespace_meta_to_response(meta)
    except Exception as exc:
        raise _map_error(exc)


@router.get(
    "/namespaces/{namespace}/graph",
    responses={
        200: {"description": "Graph data for visualisation"},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Get entity-relation graph for a namespace",
)
async def get_namespace_graph(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
    limit: int = Query(default=200, ge=1, le=5000, description="Max number of nodes to return"),
) -> dict:
    """Get the entity-relation graph for visualization.

    Returns ``{nodes, edges, stats}`` capped at ``limit`` nodes.
    Edges are filtered to those whose endpoints are in the returned node set.
    Empty namespace or no LLM during ingest → empty nodes/edges (not an error).
    """
    try:
        actor = _get_actor(user)
        service = _get_service()
        result = await asyncio.to_thread(
            service.get_graph,
            namespace,
            limit=limit,
            actor=actor,
        )
        return result
    except Exception as exc:
        raise _map_error(exc)


# ---------------------------------------------------------------------------
# Supernova Explorer Endpoints
# ---------------------------------------------------------------------------


class ExplorerExpandRequest(BaseModel):
    """Request body for POST /api/knowledge/namespaces/{namespace}/explorer/expand."""

    node_ids: list[str] = Field(
        ...,
        description="Node IDs to expand from",
        min_length=1,
        max_length=100,
    )
    depth: int = Field(
        default=1,
        description="Number of hops to expand (1-3)",
        ge=1,
        le=3,
    )


class ExplorerSearchRequest(BaseModel):
    """Request body for POST /api/knowledge/namespaces/{namespace}/explorer/search."""

    query: str = Field(
        ...,
        description="Natural language search query",
        min_length=1,
        max_length=2000,
    )
    limit: int = Field(
        default=20,
        description="Max seed results from vector search",
        ge=1,
        le=100,
    )


class ExplorerPathRequest(BaseModel):
    """Request body for POST /api/knowledge/namespaces/{namespace}/explorer/path."""

    source_id: str = Field(..., description="Starting node ID")
    target_id: str = Field(..., description="Ending node ID")


@router.get(
    "/namespaces/{namespace}/explorer/summary",
    summary="Get graph topology summary",
)
async def explorer_summary(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Return lightweight topology stats for the namespace graph.

    Includes entity/chunk/relation counts, label distribution, and degree
    statistics. No node data is returned — this is a cheap overview.
    """
    try:
        service = _get_service()
        return await asyncio.to_thread(service.explorer_summary, namespace)
    except Exception as exc:
        raise _map_error(exc)


@router.get(
    "/namespaces/{namespace}/explorer/seed",
    summary="Get initial graph seed (top PageRank + 1-hop)",
)
async def explorer_seed(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
    top_k: int = Query(default=50, ge=1, le=200, description="Number of top PageRank nodes to seed"),
) -> dict:
    """Load the initial "sky" — top-K PageRank nodes + their 1-hop neighborhood.

    This is the entry point for the Supernova explorer. Returns enough
    data to render the initial graph view, then the client can expand
    on demand.
    """
    try:
        service = _get_service()
        return await asyncio.to_thread(service.explorer_seed, namespace, top_k=top_k)
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/explorer/expand",
    summary="Expand graph from given node IDs",
)
async def explorer_expand(
    namespace: str,
    request: ExplorerExpandRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Expand from a set of node IDs outward by N hops.

    The client sends the IDs of nodes it wants to explore around,
    and the server returns all nodes and edges within the specified
    hop distance.
    """
    try:
        service = _get_service()
        return await asyncio.to_thread(
            service.explorer_expand,
            namespace,
            node_ids=request.node_ids,
            depth=request.depth,
        )
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/explorer/search",
    summary="Vector search + graph expansion",
)
async def explorer_search(
    namespace: str,
    request: ExplorerSearchRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Vector-similarity search over node embeddings + 1-hop context.

    Uses KuzuDB's vector index to find semantically similar entities,
    then expands 1-hop for visual context.
    """
    try:
        service = _get_service()
        return await asyncio.to_thread(
            service.explorer_search,
            namespace,
            query=request.query,
            limit=request.limit,
        )
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/explorer/path",
    summary="Find shortest path between two nodes",
)
async def explorer_path(
    namespace: str,
    request: ExplorerPathRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Find the shortest weighted path between two nodes.

    Uses NetworkX shortest_path with relationship-type weighting.
    Returns the path as a sequence of node IDs plus the connecting edges.
    """
    try:
        service = _get_service()
        return await asyncio.to_thread(
            service.explorer_path,
            namespace,
            source_id=request.source_id,
            target_id=request.target_id,
        )
    except Exception as exc:
        raise _map_error(exc)


@router.get(
    "/namespaces/{namespace}/explorer/node/{node_id}",
    summary="Get full detail for a single node",
)
async def explorer_node_detail(
    namespace: str,
    node_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Full detail for a single node: properties, incident edges, degree stats.

    Returns the node data, all incoming and outgoing edges with peer
    node information, and computed degree statistics.
    """
    try:
        service = _get_service()
        return await asyncio.to_thread(
            service.explorer_node_detail,
            namespace,
            node_id=node_id,
        )
    except Exception as exc:
        raise _map_error(exc)


@router.get(
    "/namespaces/{namespace}/explorer/communities",
    summary="Get Louvain community mapping",
)
async def explorer_communities(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Return the Louvain community mapping for the namespace graph.

    Uses NetworkX Louvain community detection on the entity subgraph.
    Returns:
    - ``community_map``: {entity_id: community_id}
    - ``community_count``: number of communities detected
    - ``community_sizes``: {community_id: member_count}
    """
    try:
        service = _get_service()
        return await asyncio.to_thread(service.explorer_communities, namespace)
    except Exception as exc:
        raise _map_error(exc)


# ---------------------------------------------------------------------------
# Metrics and Health Endpoints (EPIC-005)
# ---------------------------------------------------------------------------


@router.get(
    "/metrics",
    responses={
        200: {"description": "Metrics in JSON or Prometheus format"},
        401: {"description": "Authentication required"},
    },
    summary="Get knowledge service metrics",
)
async def get_metrics(
    request: Request,
    user: Annotated[dict, Depends(get_current_user)],
) -> Any:
    """Get metrics for the knowledge service.

    Content negotiation:
    - Default: JSON format
    - Accept: text/plain → Prometheus text format

    Returns counters, histograms, and gauges for:
    - Ingestion: files_total, bytes_total, latency_seconds
    - Queries: total, errors_total, latency_seconds
    - LLM: calls_total, errors_total, latency_seconds
    - Namespaces: total count, per-namespace disk/vectors/entities
    """
    metrics = get_metrics_registry()
    
    # Check Accept header for Prometheus format
    accept_header = request.headers.get("accept", "")
    if "text/plain" in accept_header:
        return PlainTextResponse(
            content=metrics.export_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )
    
    # Return JSON by default
    return metrics.export_json()


@router.get(
    "/metrics/prometheus",
    response_class=PlainTextResponse,
    responses={
        200: {"description": "Metrics in Prometheus text format", "content": {"text/plain": {}}},
        401: {"description": "Authentication required"},
    },
    summary="Get knowledge service metrics in Prometheus format",
)
async def get_metrics_prometheus(
    user: Annotated[dict, Depends(get_current_user)],
) -> PlainTextResponse:
    """Get metrics in Prometheus text format.

    This endpoint returns metrics in the Prometheus exposition format,
    suitable for scraping by Prometheus servers.
    """
    metrics = get_metrics_registry()
    return PlainTextResponse(
        content=metrics.export_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


class HealthCheckResult(BaseModel):
    """Result of a single health check."""

    status: str = Field(..., description="ok, degraded, or unhealthy")
    message: str = Field(default="", description="Details about the check")
    latency_ms: Optional[float] = Field(default=None, description="Latency of the check in milliseconds")


class HealthResponse(BaseModel):
    """Overall health status response."""

    status: str = Field(..., description="Overall status: ok, degraded, or unhealthy")
    checks: dict[str, HealthCheckResult] = Field(
        default_factory=dict,
        description="Individual check results (storage, embedder, llm)",
    )
    timestamp: str = Field(..., description="ISO timestamp of the health check")


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={
        200: {"description": "Health status"},
        401: {"description": "Authentication required"},
    },
    summary="Get knowledge service health",
)
async def get_health(
    user: Annotated[dict, Depends(get_current_user)],
) -> HealthResponse:
    """Get health status of the knowledge service.

    Checks:
    - **storage**: Whether the knowledge storage directory is writable
    - **embedder**: Whether the embedding model is available
    - **llm**: Whether the LLM is configured with a model and API key

    Status values:
    - **ok**: All checks passed
    - **degraded**: Some checks failed but service is operational
    - **unhealthy**: Critical checks failed, service may not work correctly
    """
    from datetime import datetime, timezone
    import time as time_module
    
    checks: dict[str, HealthCheckResult] = {}
    overall_status = "ok"
    
    # 1. Storage check
    storage_check = await _check_storage()
    checks["storage"] = storage_check
    if storage_check.status == "unhealthy":
        overall_status = "unhealthy"
    elif storage_check.status == "degraded" and overall_status == "ok":
        overall_status = "degraded"
    
    # 2. Embedder check
    embedder_check = await _check_embedder()
    checks["embedder"] = embedder_check
    if embedder_check.status == "unhealthy" and overall_status != "unhealthy":
        overall_status = "degraded"  # Embedder failure is not critical
    
    # 3. LLM check
    llm_check = await _check_llm()
    checks["llm"] = llm_check
    if llm_check.status == "unhealthy" and overall_status != "unhealthy":
        overall_status = "degraded"  # LLM failure is not critical
    
    return HealthResponse(
        status=overall_status,
        checks=checks,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


async def _check_storage() -> HealthCheckResult:
    """Check if storage directory is writable."""
    import time as time_module
    import tempfile
    
    from dashboard.knowledge.config import KNOWLEDGE_DIR
    
    t0 = time_module.perf_counter()
    try:
        # Check if knowledge directory exists and is writable
        knowledge_dir = KNOWLEDGE_DIR
        if not knowledge_dir.exists():
            try:
                knowledge_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return HealthCheckResult(
                    status="unhealthy",
                    message=f"Cannot create knowledge directory: {exc}",
                    latency_ms=(time_module.perf_counter() - t0) * 1000,
                )
        
        # Try to write a temp file
        try:
            test_file = knowledge_dir / ".health_check_test"
            test_file.write_text("test")
            test_file.unlink()
            return HealthCheckResult(
                status="ok",
                message="Storage directory is writable",
                latency_ms=(time_module.perf_counter() - t0) * 1000,
            )
        except OSError as exc:
            # Check if it's a permission error
            if "permission" in str(exc).lower() or "access" in str(exc).lower():
                return HealthCheckResult(
                    status="unhealthy",
                    message=f"Storage directory is not writable: {exc}",
                    latency_ms=(time_module.perf_counter() - t0) * 1000,
                )
            return HealthCheckResult(
                status="degraded",
                message=f"Storage check failed: {exc}",
                latency_ms=(time_module.perf_counter() - t0) * 1000,
            )
    except Exception as exc:
        return HealthCheckResult(
            status="unhealthy",
            message=f"Storage check error: {exc}",
            latency_ms=(time_module.perf_counter() - t0) * 1000,
        )


async def _check_embedder() -> HealthCheckResult:
    """Check if embedding model is available."""
    import time as time_module
    
    t0 = time_module.perf_counter()
    try:
        # Lazy import to avoid loading heavy deps
        from dashboard.knowledge.embeddings import KnowledgeEmbedder  # noqa: WPS433
        
        embedder = KnowledgeEmbedder()
        
        # Try a simple embedding
        try:
            # Use a short test string
            result = embedder.embed_one("health check")
            if result is not None and len(result) > 0:
                return HealthCheckResult(
                    status="ok",
                    message="Embedding model is available",
                    latency_ms=(time_module.perf_counter() - t0) * 1000,
                )
            else:
                return HealthCheckResult(
                    status="degraded",
                    message="Embedding model returned empty result",
                    latency_ms=(time_module.perf_counter() - t0) * 1000,
                )
        except Exception as exc:
            return HealthCheckResult(
                status="unhealthy",
                message=f"Embedding model error: {exc}",
                latency_ms=(time_module.perf_counter() - t0) * 1000,
            )
    except Exception as exc:
        return HealthCheckResult(
            status="unhealthy",
            message=f"Cannot load embedding model: {exc}",
            latency_ms=(time_module.perf_counter() - t0) * 1000,
        )


async def _check_llm() -> HealthCheckResult:
    """Check if LLM is configured and available."""
    import time as time_module
    
    t0 = time_module.perf_counter()
    try:
        from dashboard.knowledge.llm import KnowledgeLLM  # noqa: WPS433
        
        llm = KnowledgeLLM()
        if llm.is_available():
            provider = llm._effective_provider()
            return HealthCheckResult(
                status="ok",
                message=f"LLM configured (model={llm.model}, provider={provider})",
                latency_ms=(time_module.perf_counter() - t0) * 1000,
            )
        else:
            msg = "No LLM model configured" if not llm.model else "No API key for LLM provider"
            return HealthCheckResult(
                status="unhealthy",
                message=msg,
                latency_ms=(time_module.perf_counter() - t0) * 1000,
            )
    except Exception as exc:
        return HealthCheckResult(
            status="unhealthy",
            message=f"LLM check error: {exc}",
            latency_ms=(time_module.perf_counter() - t0) * 1000,
        )




# ---------------------------------------------------------------------------
# Retention Endpoints (EPIC-004)
# ---------------------------------------------------------------------------


@router.put(
    "/namespaces/{namespace}/retention",
    response_model=RetentionPolicyResponse,
    responses={
        200: {"description": "Retention policy updated"},
        400: {"description": "Invalid request", "model": ErrorResponse},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Set retention policy for a namespace",
)
async def set_retention_endpoint(
    namespace: str,
    request: RetentionPolicyRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> RetentionPolicyResponse:
    """Set the retention policy for a namespace.

    Retention policies control automatic cleanup:
    - manual: No automatic cleanup (default)
    - ttl_days: Automatically delete imports older than ttl_days

    When ttl_days is set, the background sweeper will periodically check
    and remove old import records. If all imports are removed and
    auto_delete_when_empty is true, the namespace itself is deleted.
    """
    try:
        service = _get_service()
        
        # Get current manifest
        meta = await asyncio.to_thread(service.get_namespace, namespace)
        if meta is None:
            from dashboard.knowledge.namespace import NamespaceNotFoundError
            raise NamespaceNotFoundError(namespace)
        
        # Update retention policy
        from dashboard.knowledge.namespace import RetentionPolicy
        from datetime import datetime, timezone
        
        retention = RetentionPolicy(
            policy=request.policy,
            ttl_days=request.ttl_days if request.policy == "ttl_days" else None,
            auto_delete_when_empty=request.auto_delete_when_empty,
            last_swept_at=meta.retention.last_swept_at if hasattr(meta, "retention") and meta.retention else None,
        )
        
        # Write updated manifest
        meta.retention = retention
        service._nm.write_manifest(namespace, meta)  # noqa: SLF001
        
        return RetentionPolicyResponse(
            policy=retention.policy,
            ttl_days=retention.ttl_days,
            last_swept_at=retention.last_swept_at,
            auto_delete_when_empty=retention.auto_delete_when_empty,
        )
    except Exception as exc:
        raise _map_error(exc)




__all__ = ["router"]
