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
import json
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
    BackupNamespaceResponse,
    CreateNamespaceRequest,
    DeleteNamespaceResponse,
    DomainPackInstalledResponse,
    DomainPackListResponse,
    DomainPackOperationResponse,
    DomainPackRequest,
    DomainPackValidateResponse,
    ErrorResponse,
    EnterpriseMapProjectionResponse,
    EnterpriseMapQueryRequest,
    ExplorerOntologyFilters,
    GraphCountsResponse,
    ImportFolderRequest,
    ImportFolderResponse,
    ImportTextRequest,
    ImportTextResponse,
    JobStatusResponse,
    NamespaceJobsResponse,
    OntologyAssistantRequest,
    OntologyAssistantResponse,
    NamespaceMetaResponse,
    OntologyCandidateActionRequest,
    OntologyCandidateBulkRequest,
    OntologyCandidateListResponse,
    OntologyCandidateResponse,
    OntologyFactCreateRequest,
    OntologyFactListResponse,
    OntologyFactPromoteRequest,
    OntologyFactPromoteResponse,
    OntologyFactRelationshipCandidateRequest,
    OntologyFactRelationshipCandidateResponse,
    OntologyFactResponse,
    OntologyFactReviewRequest,
    OntologyProfileDiffRequest,
    OntologyUnitRequest,
    OntologyUnitResponse,
    OntologyProfileDiffResponse,
    OntologyProfileHistoryListResponse,
    OntologyProfileHistoryRecordResponse,
    OntologyProfileRequest,
    OntologyProfileResponse,
    OntologyResetDefaultResponse,
    OntologyReleaseObservabilityResponse,
    OntologySummaryResponse,
    OntologyValidateRequest,
    OntologyValidateResponse,
    TimeSeriesUpsertRequest,
    TimeSeriesResponse,
    TimeSeriesListResponse,
    ObservationEventResponse,
    ObservationEventListResponse,
    QueryRequest,
    QueryResultResponse,
    RefreshNamespaceResponse,
    ResearchIngestJobResponse,
    ResearchIngestRequest,
    ResearchRequest,
    ResearchResponse,
    ResearchSearchRequest,
    ResearchSearchResponse,
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

    if isinstance(exc, KeyError):
        return HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error=str(exc),
                code="NOT_FOUND",
                detail={},
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
        ontology_profile_version=getattr(meta, "ontology_profile_version", None),
    )




def _ontology_unit_to_response(data: dict[str, Any]) -> OntologyUnitResponse:
    """Convert service ontology unit payload to response model."""
    return OntologyUnitResponse(**data)


def _ontology_profile_to_response(data: dict[str, Any]) -> OntologyProfileResponse:
    """Convert service ontology profile payload to response model."""
    return OntologyProfileResponse(**data)


def _ontology_validate_to_response(data: dict[str, Any]) -> OntologyValidateResponse:
    """Convert service ontology validation payload to response model."""
    return OntologyValidateResponse(**data)


def _ontology_summary_to_response(data: dict[str, Any]) -> OntologySummaryResponse:
    """Convert service ontology summary payload to response model."""
    return OntologySummaryResponse(**data)

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



@router.get(
    "/namespaces/{namespace}/ontology/unit",
    response_model=OntologyUnitResponse,
    responses={
        200: {"description": "Ontology unit identity/governance metadata"},
        400: {"description": "Invalid namespace identifier", "model": ErrorResponse},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Get namespace ontology unit",
)
async def get_ontology_unit(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyUnitResponse:
    """Return ontology unit identity/governance metadata without requiring a profile."""
    try:
        service = _get_service()
        data = await asyncio.to_thread(service.get_ontology_unit_response, namespace)
        return _ontology_unit_to_response(data)
    except Exception as exc:
        raise _map_error(exc)


@router.put(
    "/namespaces/{namespace}/ontology/unit",
    response_model=OntologyUnitResponse,
    responses={
        200: {"description": "Ontology unit saved"},
        400: {"description": "Invalid unit payload", "model": ErrorResponse},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Create or update namespace ontology unit",
)
async def put_ontology_unit(
    namespace: str,
    request: OntologyUnitRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyUnitResponse:
    """Persist ontology unit metadata independently from profile publication."""
    try:
        service = _get_service()
        unit = await asyncio.to_thread(service.save_ontology_unit_payload, namespace, request.unit)
        return _ontology_unit_to_response({"namespace": namespace, "unit": unit.model_dump(mode="json"), "unit_exists": True})
    except Exception as exc:
        raise _map_error(exc)


@router.get(
    "/namespaces/{namespace}/ontology/profile",
    response_model=OntologyProfileResponse,
    responses={
        200: {"description": "Active ontology profile or default suggestion metadata"},
        400: {"description": "Invalid namespace identifier", "model": ErrorResponse},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Get namespace ontology profile",
)
async def get_ontology_profile(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyProfileResponse:
    """Return the active ontology profile or deterministic default suggestion metadata."""
    try:
        service = _get_service()
        data = await asyncio.to_thread(service.get_ontology_profile_with_default, namespace)
        return _ontology_profile_to_response(data)
    except Exception as exc:
        raise _map_error(exc)


@router.put(
    "/namespaces/{namespace}/ontology/profile",
    response_model=OntologyProfileResponse,
    responses={
        200: {"description": "Ontology profile saved"},
        400: {"description": "Invalid profile payload", "model": ErrorResponse},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Create or update namespace ontology profile",
)
async def put_ontology_profile(
    namespace: str,
    request: OntologyProfileRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyProfileResponse:
    """Validate and persist an ontology profile for the namespace."""
    try:
        service = _get_service()
        actor = _get_actor(user)
        profile = await asyncio.to_thread(
            service.save_ontology_profile_payload,
            namespace,
            request.profile,
            actor=actor,
            reason=request.reason,
            validation_override=request.validation_override,
        )
        data = {
            "namespace": namespace,
            "profile": profile.model_dump(mode="json"),
            "profile_exists": True,
            "default_suggested": False,
            "default_profile": None,
            "validation_issues": [],
        }
        return _ontology_profile_to_response(data)
    except Exception as exc:
        raise _map_error(exc)


@router.get(
    "/namespaces/{namespace}/ontology/profile/history",
    response_model=OntologyProfileHistoryListResponse,
    summary="List ontology profile history",
)
async def list_ontology_profile_history(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyProfileHistoryListResponse:
    """Return profile version history without embedding full snapshots in each list item."""
    try:
        service = _get_service()
        history = await asyncio.to_thread(service.list_ontology_profile_history, namespace)
        return OntologyProfileHistoryListResponse(
            namespace=namespace,
            history=[OntologyProfileHistoryRecordResponse(**record) for record in history],
        )
    except Exception as exc:
        raise _map_error(exc)


@router.get(
    "/namespaces/{namespace}/ontology/profile/history/{version_or_id}",
    response_model=OntologyProfileHistoryRecordResponse,
    summary="Read ontology profile history record",
)
async def get_ontology_profile_history(
    namespace: str,
    version_or_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyProfileHistoryRecordResponse:
    """Return one immutable profile history record, including its saved snapshot."""
    try:
        service = _get_service()
        record = await asyncio.to_thread(service.get_ontology_profile_history, namespace, version_or_id)
        return OntologyProfileHistoryRecordResponse(**record)
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/ontology/profile/diff",
    response_model=OntologyProfileDiffResponse,
    summary="Diff ontology profile versions or payloads",
)
async def diff_ontology_profile(
    namespace: str,
    request: OntologyProfileDiffRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyProfileDiffResponse:
    """Preview added, removed, and changed ontology definitions without saving."""
    try:
        service = _get_service()
        data = await asyncio.to_thread(
            service.diff_ontology_profiles,
            namespace,
            base_profile=request.base_profile,
            target_profile=request.target_profile,
            base_version=request.base_version,
            target_version=request.target_version,
        )
        return OntologyProfileDiffResponse(**data)
    except Exception as exc:
        raise _map_error(exc)


@router.get(
    "/namespaces/{namespace}/ontology/profile/history/{version_or_id}/preview",
    response_model=OntologyProfileDiffResponse,
    summary="Preview ontology profile rollback",
)
async def preview_ontology_profile_rollback(
    namespace: str,
    version_or_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyProfileDiffResponse:
    """Preview rollback to a historical profile without mutating current storage."""
    try:
        service = _get_service()
        data = await asyncio.to_thread(service.preview_ontology_profile_rollback, namespace, version_or_id)
        return OntologyProfileDiffResponse(**data)
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/ontology/validate",
    response_model=OntologyValidateResponse,
    responses={
        200: {"description": "Validation completed without saving"},
        400: {"description": "Invalid validation payload", "model": ErrorResponse},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Validate ontology payload without saving",
)
async def validate_ontology(
    namespace: str,
    request: OntologyValidateRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyValidateResponse:
    """Validate a profile, node, edge, or pack manifest without mutating storage."""
    try:
        service = _get_service()
        data = await asyncio.to_thread(service.validate_ontology_payload, namespace, request.model_dump())
        return _ontology_validate_to_response(data)
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/ontology/reset-default",
    response_model=OntologyResetDefaultResponse,
    responses={
        200: {"description": "Default ontology profile created or replaced"},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Reset namespace ontology profile to default seed data",
)
async def reset_default_ontology_profile(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyResetDefaultResponse:
    """Create or replace the active ontology profile with deterministic default seed data."""
    try:
        service = _get_service()
        profile, replaced_existing = await asyncio.to_thread(service.reset_default_ontology_profile, namespace)
        return OntologyResetDefaultResponse(
            namespace=namespace,
            profile=profile.model_dump(mode="json"),
            replaced_existing=replaced_existing,
        )
    except Exception as exc:
        raise _map_error(exc)


@router.get(
    "/namespaces/{namespace}/ontology/summary",
    response_model=OntologySummaryResponse,
    responses={
        200: {"description": "Ontology profile summary counters"},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Summarize namespace ontology profile",
)
async def get_ontology_summary(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologySummaryResponse:
    """Return counts for concept types, relation types, aliases, candidates, and issues."""
    try:
        service = _get_service()
        data = await asyncio.to_thread(service.get_ontology_summary, namespace)
        return _ontology_summary_to_response(data)
    except Exception as exc:
        raise _map_error(exc)


@router.get(
    "/namespaces/{namespace}/ontology/release-observability",
    response_model=OntologyReleaseObservabilityResponse,
    responses={
        200: {"description": "Ontology release-gate observability report"},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Report ontology release-gate observability",
)
async def get_ontology_release_observability(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyReleaseObservabilityResponse:
    """Return release-gate health signals across evidence, review, packs, and events."""
    try:
        service = _get_service()
        data = await asyncio.to_thread(service.get_ontology_release_observability, namespace)
        return OntologyReleaseObservabilityResponse(**data)
    except Exception as exc:
        raise _map_error(exc)


def _is_vocabulary_pack_draft_request(message: str) -> bool:
    """Detect the governed pack-draft assistant shortcut requested by the UI."""
    lowered = (message or "").lower()
    return (
        ("draft" in lowered or "proposal" in lowered)
        and ("pack" in lowered or "vocabulary bundle" in lowered or "domain bundle" in lowered)
    )


def _fallback_vocabulary_pack_draft_text(namespace: str, profile_summary: dict[str, Any]) -> str:
    """Return a small structured pack draft when the live assistant is unavailable.

    The response is deliberately advisory and compact. It gives the UI a valid,
    reviewable proposal shape with every EPIC-014 pack-draft section while still
    requiring the normal apply/validate/diff/save governance path before any
    ontology data can change.
    """
    existing_concepts = set(profile_summary.get("concept_types") or [])
    existing_relationships = set(profile_summary.get("relationship_types") or [])
    concept_id = "pack_template_concept" if "pack_template_concept" not in existing_concepts else "pack_template_concept_v2"
    evidence_id = "pack_template_evidence" if "pack_template_evidence" not in existing_concepts else "pack_template_evidence_v2"
    relation_id = "documents" if "documents" not in existing_relationships else "documents_pack_template"
    proposal = {
        "proposed_changes": {
            "concept_types": {
                concept_id: {
                    "id": concept_id,
                    "label": "Pack Template Concept",
                    "abstraction_level": "capability",
                    "default_layer": "pack_template",
                    "description": "Reviewable placeholder concept for a small customer vocabulary bundle draft.",
                    "metadata_schema": {"pack_owner": {"id": "pack_owner", "label": "Pack Owner", "field_type": "string"}},
                    "color": "#2563eb",
                    "shape": "rounded_rectangle",
                    "lifecycle_state": "draft",
                },
                evidence_id: {
                    "id": evidence_id,
                    "label": "Pack Template Evidence",
                    "abstraction_level": "implementation",
                    "default_layer": "pack_template",
                    "description": "Evidence or source artifact used to justify this vocabulary bundle.",
                    "metadata_schema": {"pack_owner": {"id": "pack_owner", "label": "Pack Owner", "field_type": "string"}},
                    "color": "#0f766e",
                    "shape": "document",
                    "lifecycle_state": "draft",
                },
            },
            "relationship_types": {
                relation_id: {
                    "id": relation_id,
                    "label": "Documents",
                    "family": "traceability",
                    "inverse": None,
                    "description": "Connects pack template concepts to evidence before install review.",
                    "allowed_source_types": [evidence_id],
                    "allowed_target_types": [concept_id],
                    "weight": 0.7,
                    "style": "solid",
                    "map_direction": "forward",
                    "is_directed": True,
                    "is_system": False,
                    "lifecycle_state": "draft",
                }
            },
            "layers": {
                "pack_template": {
                    "id": "pack_template",
                    "label": "Pack Template",
                    "order": 90,
                    "description": "Draft-only lane for reviewing candidate vocabulary bundle contents.",
                    "lifecycle_state": "draft",
                }
            },
            "metadata_fields": {
                "pack_owner": {
                    "id": "pack_owner",
                    "label": "Pack Owner",
                    "field_type": "string",
                    "description": "Team or partner accountable for reviewing this vocabulary bundle.",
                    "required": False,
                    "lifecycle_state": "draft",
                }
            },
            "graph_instruction": {
                "default_views": [
                    {"id": "pack_template_review", "label": "Pack Template Review", "lane_dimension": "default_layer", "filters": {}, "description": "Review draft pack contents before governance save."}
                ],
                "concept_type_defaults": {
                    concept_id: {"concept_type": concept_id, "default_layer": "pack_template", "label_template": "{label}", "color": "#2563eb", "shape": "rounded_rectangle"},
                    evidence_id: {"concept_type": evidence_id, "default_layer": "pack_template", "label_template": "{label}", "color": "#0f766e", "shape": "document"},
                },
                "relationship_type_defaults": {
                    relation_id: {"relationship_type": relation_id, "map_direction": "forward", "label_template": "{label}", "color": "#64748b", "weight": 0.7}
                },
                "examples": [
                    {
                        "id": "pack_template_fixture",
                        "description": "Small review fixture for the drafted vocabulary bundle.",
                        "nodes": [{"id": "source_doc", "type": evidence_id}, {"id": "draft_object", "type": concept_id}],
                        "edges": [{"source": "source_doc", "target": "draft_object", "relation_type": relation_id}],
                    }
                ],
            },
            "fixtures": [
                {
                    "id": "pack_template_fixture",
                    "nodes": [{"id": "source_doc", "type": evidence_id}, {"id": "draft_object", "type": concept_id}],
                    "edges": [{"source": "source_doc", "target": "draft_object", "relation_type": relation_id}],
                }
            ],
            "migration_notes": [
                f"Draft vocabulary bundle for namespace {namespace}; review, validate, preview diff, and save before installation.",
                "Generated as a safe fallback because the live assistant was unavailable; treat all sections as advisory.",
            ],
        },
        "rationale": "Small fallback vocabulary bundle proposal for governed review when the assistant backend is unavailable.",
        "evidence_refs": [],
    }
    return (
        "The live ontology assistant is unavailable, so here is a small advisory vocabulary bundle draft that remains review-only. "
        "Apply it to the draft only if it matches the source documents, then validate, preview diff, and save through governance.\n"
        "```json\n"
        f"{json.dumps(proposal, separators=(',', ':'))}\n"
        "```"
    )


_PACK_DRAFT_REQUIRED_SECTIONS = {
    "concept_types",
    "relationship_types",
    "layers",
    "metadata_fields",
    "graph_instruction",
    "fixtures",
    "migration_notes",
}


def _pack_draft_response_is_reviewable(text: str) -> bool:
    """Return True when assistant text contains the UI-required pack proposal envelope."""
    match = re.search(r"```json\s*([\s\S]*?)```", text or "", re.IGNORECASE)
    if not match:
        return False
    try:
        parsed = json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        return False
    if not isinstance(parsed, dict):
        return False
    proposed_changes = parsed.get("proposed_changes")
    if not isinstance(proposed_changes, dict):
        return False
    missing = _PACK_DRAFT_REQUIRED_SECTIONS.difference(proposed_changes.keys())
    if missing:
        return False
    return all(
        isinstance(proposed_changes.get(section), dict)
        for section in ["concept_types", "relationship_types", "layers", "metadata_fields", "graph_instruction"]
    ) and all(
        isinstance(proposed_changes.get(section), list)
        for section in ["fixtures", "migration_notes"]
    )


@router.post(
    "/namespaces/{namespace}/ontology/assistant",
    response_model=OntologyAssistantResponse,
    responses={
        200: {"description": "AI ontology schema design response"},
        400: {"description": "Invalid ontology assistant request", "model": ErrorResponse},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Ask the master agent for ontology schema design help",
)
async def ask_ontology_assistant(
    namespace: str,
    request: OntologyAssistantRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyAssistantResponse:
    """Use the master agent as a governed ontology schema co-builder.

    This endpoint is advisory only. It does not mutate profile storage; callers
    must still validate and save profile changes through the ontology profile
    endpoint.
    """
    try:
        service = _get_service()
        await asyncio.to_thread(service._require_namespace, namespace)
        actor = _get_actor(user)

        from dashboard.llm_client import ChatMessage  # noqa: WPS433
        from dashboard.master_agent import master_chat  # noqa: WPS433

        system_prompt = """\
You are the Ontology Schema Builder inside OS Twin.

You are an advisory conversational co-builder. You may explain, propose, map,
or draft ontology changes, but you must never claim that anything was saved or
approved. The user must explicitly apply proposals to a draft, validate, preview
diff, save, review candidates, or review facts through governed UI controls.

Allowed proposed_changes top-level sections only:
- concept_types: objects keyed by stable lowercase id. ConceptType fields only:
  id, label, abstraction_level, default_layer, description, metadata_schema,
  metadata_fields, color, shape, lifecycle_state.
- relationship_types: objects keyed by stable lowercase id. RelationshipType
  fields only: id, label, family, inverse, description, allowed_source_types,
  allowed_target_types, weight, style, display_style, map_direction,
  is_directed, is_system, lifecycle_state.
- aliases, concept_aliases: string-to-string maps.
- layers, abstraction_levels, metadata_fields, validation_rules,
  graph_instruction, fixtures, migration_notes.
- For vocabulary bundle / pack drafts, include concept_types, relationship_types, layers, metadata_fields, graph_instruction, fixtures, and migration_notes in proposed_changes; these are advisory review payloads only.
- candidate_actions and fact_actions may be proposed as advisory review actions
  only; they are not profile draft patches.

When proposing changes, include one strict fenced JSON block and keep it compact:
```json
{"proposed_changes": {"concept_types": {}}, "rationale": "why", "evidence_refs": []}
```
Use only bounded context supplied below. Do not ask for or reproduce entire raw
documents. Prefer one or two small valid next steps over broad rewrites.
"""
        profile_summary = {
            "profile_id": request.profile.get("profile_id"),
            "version": request.profile.get("version"),
            "status": request.profile.get("status"),
            "concept_types": list((request.profile.get("concept_types") or {}).keys())[:80],
            "relationship_types": list((request.profile.get("relationship_types") or {}).keys())[:80],
            "layers": list((request.profile.get("layers") or {}).keys())[:40],
            "abstraction_levels": list((request.profile.get("abstraction_levels") or {}).keys())[:40],
            "metadata_fields": list((request.profile.get("metadata_fields") or {}).keys())[:80],
            "validation_rule_count": len(request.profile.get("validation_rules") or []),
        }
        selected = request.selected or None
        if isinstance(selected, dict) and "object" in selected:
            selected = {**selected, "object": json.dumps(selected.get("object"), sort_keys=True)[:4000]}
        context = {
            "namespace": namespace,
            "selected": selected,
            "bounded_refs": request.context or {},
            "profile_summary": profile_summary,
            "advisory_only": True,
            "governance_required": ["apply_to_draft", "validate", "preview_diff", "save", "candidate_review", "fact_review"],
        }
        history = [
            ChatMessage(role=msg.role if msg.role in {"user", "assistant"} else "user", content=msg.content)
            for msg in request.history[-8:]
            if msg.content
        ]
        messages = [
            ChatMessage(role="system", content=system_prompt),
            *history,
            ChatMessage(
                role="user",
                content=(
                    "Current ontology context:\n"
                    f"{json.dumps(context, indent=2, sort_keys=True)[:20000]}\n\n"
                    f"User request: {request.message}"
                ),
            ),
        ]
        conversation_id = f"ontology-schema:{namespace}:{actor}"
        is_pack_draft_request = _is_vocabulary_pack_draft_request(request.message)
        try:
            response = await master_chat(messages, conversation_id=conversation_id)
            text = response.content or "No response from ontology assistant."
            if is_pack_draft_request and not _pack_draft_response_is_reviewable(text):
                logger.warning("Ontology assistant returned non-reviewable vocabulary pack draft; returning fallback")
                text = _fallback_vocabulary_pack_draft_text(namespace, profile_summary)
        except Exception:
            if not is_pack_draft_request:
                raise
            logger.exception("Ontology assistant unavailable; returning fallback vocabulary pack draft")
            text = _fallback_vocabulary_pack_draft_text(namespace, profile_summary)
        return OntologyAssistantResponse(
            namespace=namespace,
            conversation_id=conversation_id,
            text=text,
        )
    except Exception as exc:
        raise _map_error(exc)


@router.get(
    "/namespaces/{namespace}/ontology/enterprise-map",
    response_model=EnterpriseMapProjectionResponse,
    responses={
        200: {"description": "Graph-backed ontology projection for enterprise map surfaces"},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Get namespace enterprise map ontology projection",
)
async def get_ontology_enterprise_map(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
    limit: int = Query(default=200, ge=1, le=500, description="Maximum graph nodes to project"),
    filters: str | None = Query(default=None, description="Optional JSON-encoded ExplorerOntologyFilters"),
    group_by: list[str] | None = Query(default=None, description="Optional view-plane grouping fields"),
    color_by: str | None = Query(default=None, description="Optional view-plane color field"),
) -> EnterpriseMapProjectionResponse:
    """Return a bounded graph projection composed with the active ontology profile."""
    try:
        parsed_filters = None
        if filters:
            parsed_filters = ExplorerOntologyFilters.model_validate(json.loads(filters)).to_filter_dict()
        service = _get_service()
        return await asyncio.to_thread(
            service.ontology_enterprise_map,
            namespace,
            limit=limit,
            filters=parsed_filters,
            group_by=group_by,
            color_by=color_by,
        )
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/ontology/enterprise-map/query",
    response_model=EnterpriseMapProjectionResponse,
    responses={
        200: {"description": "Filtered graph-backed ontology projection for enterprise map surfaces"},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Query namespace enterprise map ontology projection",
)
async def query_ontology_enterprise_map(
    namespace: str,
    request: EnterpriseMapQueryRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> EnterpriseMapProjectionResponse:
    """Return the enterprise-map projection with rich filters and view directives."""
    try:
        service = _get_service()
        return await asyncio.to_thread(
            service.ontology_enterprise_map,
            namespace,
            limit=request.limit,
            filters=request.filters.to_filter_dict() if request.filters else None,
            group_by=request.group_by,
            color_by=request.color_by,
        )
    except Exception as exc:
        raise _map_error(exc)


@router.get(
    "/ontology/packs",
    response_model=DomainPackListResponse,
    responses={
        200: {"description": "Available built-in domain packs"},
        401: {"description": "Authentication required"},
    },
    summary="List available ontology domain packs",
)
async def list_available_domain_packs(
    user: Annotated[dict, Depends(get_current_user)],
) -> DomainPackListResponse:
    """Return installable domain pack manifests bundled with the backend."""
    try:
        service = _get_service()
        packs = await asyncio.to_thread(service.list_available_domain_packs)
        return DomainPackListResponse(packs=packs)
    except Exception as exc:
        raise _map_error(exc)


@router.get(
    "/namespaces/{namespace}/ontology/packs",
    response_model=DomainPackInstalledResponse,
    responses={
        200: {"description": "Installed pack state for namespace"},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="List installed domain packs for a namespace",
)
async def list_installed_domain_packs(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> DomainPackInstalledResponse:
    """Return namespace-local domain pack lifecycle state."""
    try:
        service = _get_service()
        data = await asyncio.to_thread(service.list_installed_domain_packs, namespace)
        return DomainPackInstalledResponse(**data)
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/ontology/packs/validate",
    response_model=DomainPackValidateResponse,
    responses={
        200: {"description": "Pack validation preview completed"},
        400: {"description": "Invalid pack or validation conflict", "model": ErrorResponse},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Validate a domain pack install without saving",
)
async def validate_domain_pack(
    namespace: str,
    request: DomainPackRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> DomainPackValidateResponse:
    """Preview compatibility, conflicts, and merged profile without mutating storage."""
    try:
        service = _get_service()
        data = await asyncio.to_thread(service.validate_domain_pack_install, namespace, request.pack_id)
        return DomainPackValidateResponse(**data)
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/ontology/packs/install",
    response_model=DomainPackOperationResponse,
    responses={
        200: {"description": "Domain pack installed or upgraded"},
        400: {"description": "Pack conflict", "model": ErrorResponse},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Install or upgrade a namespace domain pack",
)
async def install_domain_pack(
    namespace: str,
    request: DomainPackRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> DomainPackOperationResponse:
    """Install or upgrade a pack and persist the merged ontology profile/state."""
    try:
        service = _get_service()
        actor = _get_actor(user)
        data = await asyncio.to_thread(service.install_domain_pack, namespace, request.pack_id, actor=actor)
        return DomainPackOperationResponse(**data)
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/ontology/packs/uninstall",
    response_model=DomainPackOperationResponse,
    responses={
        200: {"description": "Domain pack disabled and pack-owned additions removed when safe"},
        400: {"description": "Pack is not installed or cannot be uninstalled", "model": ErrorResponse},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found", "model": ErrorResponse},
    },
    summary="Uninstall a namespace domain pack",
)
async def uninstall_domain_pack(
    namespace: str,
    request: DomainPackRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> DomainPackOperationResponse:
    """Disable a pack and remove pack-owned ontology additions unless retained by another pack."""
    try:
        service = _get_service()
        actor = _get_actor(user)
        data = await asyncio.to_thread(service.uninstall_domain_pack, namespace, request.pack_id, actor=actor)
        return DomainPackOperationResponse(**data)
    except Exception as exc:
        raise _map_error(exc)



@router.get(
    "/namespaces/{namespace}/ontology/observation/events",
    response_model=ObservationEventListResponse,
    summary="List ontology observation events",
)
async def list_observation_events(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
    subject_type: str | None = Query(default=None),
    subject_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
) -> ObservationEventListResponse:
    try:
        service = _get_service()
        events = await asyncio.to_thread(service.list_observation_events, namespace, subject_type=subject_type, subject_id=subject_id, event_type=event_type, start=start, end=end)
        return ObservationEventListResponse(namespace=namespace, events=[ObservationEventResponse(**event) for event in events])
    except Exception as exc:
        raise _map_error(exc)


@router.get(
    "/namespaces/{namespace}/ontology/observation/series",
    response_model=TimeSeriesListResponse,
    summary="List ontology MVP time-series records",
)
async def list_time_series(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
    subject_id: str | None = Query(default=None),
    metric_id: str | None = Query(default=None),
) -> TimeSeriesListResponse:
    try:
        service = _get_service()
        series = await asyncio.to_thread(service.list_time_series, namespace, subject_id=subject_id, metric_id=metric_id)
        return TimeSeriesListResponse(namespace=namespace, series=[TimeSeriesResponse(**item) for item in series])
    except Exception as exc:
        raise _map_error(exc)


@router.put(
    "/namespaces/{namespace}/ontology/observation/series",
    response_model=TimeSeriesResponse,
    summary="Upsert an MVP ontology time-series record",
)
async def upsert_time_series(
    namespace: str,
    request: TimeSeriesUpsertRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> TimeSeriesResponse:
    try:
        service = _get_service()
        actor = _get_actor(user)
        metadata = {**request.metadata, "created_by": actor}
        series = await asyncio.to_thread(service.upsert_time_series, namespace, subject_id=request.subject_id, metric_id=request.metric_id, unit=request.unit, points=request.points, evidence_refs=request.evidence_refs, metadata=metadata)
        return TimeSeriesResponse(**series)
    except Exception as exc:
        raise _map_error(exc)


@router.get(
    "/namespaces/{namespace}/ontology/facts",
    response_model=OntologyFactListResponse,
    summary="List reviewed ontology facts",
)
async def list_ontology_facts(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
    review_state: str | None = Query(default=None),
    source: str | None = Query(default=None),
) -> OntologyFactListResponse:
    try:
        service = _get_service()
        facts = await asyncio.to_thread(service.list_ontology_facts, namespace, review_state=review_state, source=source)
        return OntologyFactListResponse(namespace=namespace, facts=[OntologyFactResponse(**fact) for fact in facts])
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/ontology/facts",
    response_model=OntologyFactResponse,
    summary="Create an assistive ontology fact",
)
async def create_ontology_fact(
    namespace: str,
    request: OntologyFactCreateRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyFactResponse:
    try:
        service = _get_service()
        actor = _get_actor(user)
        metadata = {**request.metadata, "created_by": actor}
        fact = await asyncio.to_thread(
            service.create_ontology_fact,
            namespace,
            statement=request.statement,
            subjects=request.subjects,
            confidence=request.confidence,
            source=request.source,
            evidence_refs=request.evidence_refs,
            provenance_refs=request.provenance_refs,
            suggested_mapping=request.suggested_mapping,
            source_hash=request.source_hash,
            metadata=metadata,
        )
        return OntologyFactResponse(**fact)
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/ontology/facts/{fact_id}/review",
    response_model=OntologyFactResponse,
    summary="Review or reject an ontology fact",
)
async def review_ontology_fact(
    namespace: str,
    fact_id: str,
    request: OntologyFactReviewRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyFactResponse:
    try:
        service = _get_service()
        actor = _get_actor(user)
        fact = await asyncio.to_thread(service.review_ontology_fact, namespace, fact_id, request.review_state, reviewed_by=actor, metadata=request.metadata)
        return OntologyFactResponse(**fact)
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/ontology/facts/{fact_id}/promote-edge",
    response_model=OntologyFactPromoteResponse,
    summary="Promote an approved fact to a typed graph edge",
)
async def promote_ontology_fact_to_edge(
    namespace: str,
    fact_id: str,
    request: OntologyFactPromoteRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyFactPromoteResponse:
    try:
        service = _get_service()
        actor = _get_actor(user)
        edge = await asyncio.to_thread(
            service.promote_ontology_fact_to_edge,
            namespace,
            fact_id,
            relationship_type=request.relationship_type,
            source_id=request.source_id,
            target_id=request.target_id,
            reviewed_by=actor,
        )
        return OntologyFactPromoteResponse(namespace=namespace, edge=edge)
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/ontology/facts/{fact_id}/relationship-candidate",
    response_model=OntologyFactRelationshipCandidateResponse,
    summary="Raise a relationship-type candidate from a fact",
)
async def raise_fact_relationship_candidate(
    namespace: str,
    fact_id: str,
    request: OntologyFactRelationshipCandidateRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyFactRelationshipCandidateResponse:
    try:
        service = _get_service()
        actor = _get_actor(user)
        candidate = await asyncio.to_thread(service.raise_fact_relationship_candidate, namespace, fact_id, relationship_label=request.relationship_label, reviewed_by=actor)
        return OntologyFactRelationshipCandidateResponse(namespace=namespace, candidate=OntologyCandidateResponse(**candidate))
    except Exception as exc:
        raise _map_error(exc)


@router.get(
    "/namespaces/{namespace}/ontology/candidates",
    response_model=OntologyCandidateListResponse,
    summary="List ontology review candidates",
)
async def list_ontology_candidates(
    namespace: str,
    user: Annotated[dict, Depends(get_current_user)],
    status: str | None = Query(default=None),
    candidate_type: str | None = Query(default=None),
) -> OntologyCandidateListResponse:
    try:
        service = _get_service()
        candidates = await asyncio.to_thread(
            service.list_ontology_candidates,
            namespace,
            status=status,
            candidate_type=candidate_type,
        )
        return OntologyCandidateListResponse(
            namespace=namespace,
            candidates=[OntologyCandidateResponse(**candidate) for candidate in candidates],
        )
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/ontology/candidates/{candidate_id}/approve",
    response_model=OntologyCandidateResponse,
    summary="Approve ontology candidate as a new enum",
)
async def approve_ontology_candidate(
    namespace: str,
    candidate_id: str,
    request: OntologyCandidateActionRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyCandidateResponse:
    try:
        service = _get_service()
        actor = _get_actor(user)
        candidate = await asyncio.to_thread(
            service.approve_ontology_candidate,
            namespace,
            candidate_id,
            reviewed_by=actor,
            canonical_id=request.canonical_id,
            payload=request.payload,
        )
        return OntologyCandidateResponse(**candidate)
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/ontology/candidates/{candidate_id}/map",
    response_model=OntologyCandidateResponse,
    summary="Map ontology candidate to an existing enum",
)
async def map_ontology_candidate(
    namespace: str,
    candidate_id: str,
    request: OntologyCandidateActionRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyCandidateResponse:
    try:
        if not request.canonical_id:
            raise ValueError("canonical_id is required")
        service = _get_service()
        actor = _get_actor(user)
        candidate = await asyncio.to_thread(
            service.map_ontology_candidate,
            namespace,
            candidate_id,
            request.canonical_id,
            reviewed_by=actor,
        )
        return OntologyCandidateResponse(**candidate)
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/ontology/candidates/{candidate_id}/reject",
    response_model=OntologyCandidateResponse,
    summary="Reject ontology candidate",
)
async def reject_ontology_candidate(
    namespace: str,
    candidate_id: str,
    request: OntologyCandidateActionRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyCandidateResponse:
    try:
        service = _get_service()
        actor = _get_actor(user)
        candidate = await asyncio.to_thread(
            service.reject_ontology_candidate,
            namespace,
            candidate_id,
            reviewed_by=actor,
            reason=request.reason,
        )
        return OntologyCandidateResponse(**candidate)
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/ontology/candidates/bulk",
    response_model=OntologyCandidateListResponse,
    summary="Bulk review ontology candidates",
)
async def bulk_update_ontology_candidates(
    namespace: str,
    request: OntologyCandidateBulkRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> OntologyCandidateListResponse:
    try:
        service = _get_service()
        actor = _get_actor(user)
        candidates = await asyncio.to_thread(
            service.bulk_update_ontology_candidates,
            namespace,
            request.actions,
            reviewed_by=actor,
        )
        return OntologyCandidateListResponse(
            namespace=namespace,
            candidates=[OntologyCandidateResponse(**candidate) for candidate in candidates],
        )
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
            candidate_count=result.get("candidate_count", 0),
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
        description="Requested hop count; server clamps effective traversal depth to 1-3.",
        ge=1,
    )
    filters: ExplorerOntologyFilters | None = Field(
        default=None,
        description="Optional ontology-aware filters applied to the returned subgraph",
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
    filters: ExplorerOntologyFilters | None = Field(
        default=None,
        description="Optional ontology-aware filters applied to search context",
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
            filters=request.filters.to_filter_dict() if request.filters else None,
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
            filters=request.filters.to_filter_dict() if request.filters else None,
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
    },
    summary="Get knowledge service metrics",
)
async def get_metrics(
    request: Request,
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
    },
    summary="Get knowledge service metrics in Prometheus format",
)
async def get_metrics_prometheus() -> PlainTextResponse:
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
    },
    summary="Get knowledge service health",
)
async def get_health() -> HealthResponse:
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


# ---------------------------------------------------------------------------
# Web Research
# ---------------------------------------------------------------------------


@router.post(
    "/namespaces/{namespace}/research",
    responses={
        200: {"description": "Research results"},
        400: {"description": "Invalid request"},
        401: {"description": "Authentication required"},
        404: {"description": "Namespace not found"},
        409: {"description": "Import already in progress"},
    },
    summary="Research a topic and ingest into namespace",
)
async def research_namespace(
    namespace: str,
    request: ResearchRequest,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Search the web using SearXNG, fetch top pages, and ingest into the namespace.

    Requires the SearXNG service to be available. Auto-creates the namespace
    if it doesn't already exist.
    """
    try:
        actor = _get_actor(user)
        service = _get_service()
        result = await asyncio.to_thread(
            service.research,
            namespace,
            request.query,
            engines=request.engines,
            categories=request.categories,
            max_results=request.max_results,
            summarize=request.summarize,
            language=request.language,
            actor=actor,
        )
        return result
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/research/search",
    responses={
        200: {"description": "Search results preview"},
        400: {"description": "Invalid request"},
        401: {"description": "Authentication required"},
    },
    summary="Search the web and return result previews (no ingestion)",
)
async def research_search(
    namespace: str,
    request: ResearchSearchRequest,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Search the web via SearXNG and return previews for the user to select.

    This is the fast first step of the two-step research flow.
    No content is fetched or ingested — only search metadata is returned.
    """
    try:
        service = _get_service()
        result = await asyncio.to_thread(
            service.search_web,
            request.query,
            engines=request.engines,
            categories=request.categories,
            max_results=request.max_results,
            language=request.language,
        )
        return result
    except Exception as exc:
        raise _map_error(exc)


@router.post(
    "/namespaces/{namespace}/research/ingest",
    responses={
        200: {"description": "Job submitted"},
        400: {"description": "Invalid request"},
        401: {"description": "Authentication required"},
        409: {"description": "Import already in progress"},
    },
    summary="Fetch and ingest selected research URLs (async job)",
)
async def research_ingest(
    namespace: str,
    request: ResearchIngestRequest,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Submit a background job to fetch and ingest selected search results.

    Returns a job_id immediately. Poll via GET /namespaces/{ns}/jobs/{job_id}
    to track progress.
    """
    try:
        actor = _get_actor(user)
        service = _get_service()
        job_id = await asyncio.to_thread(
            service.research_ingest,
            namespace,
            request.query,
            [item.model_dump() for item in request.items],
            summarize=request.summarize,
            language=request.language,
            actor=actor,
        )
        return ResearchIngestJobResponse(
            job_id=job_id,
            namespace=namespace,
            status="submitted",
            message=f"Research ingest job submitted: {len(request.items)} sources",
        )
    except Exception as exc:
        raise _map_error(exc)


__all__ = ["router"]
