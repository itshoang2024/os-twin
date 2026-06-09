"""Request/response Pydantic models for the Knowledge REST API (EPIC-001).

These models wrap the canonical types from `dashboard.knowledge` (NamespaceMeta,
JobStatus, QueryResult) for HTTP transport. They do NOT duplicate fields —
they re-export or compose the canonical types to maintain a single source of
truth.

All models are JSON-serializable (Pydantic v2) and include OpenAPI examples.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Re-exports from dashboard.knowledge (canonical types)
# ---------------------------------------------------------------------------

# These are imported lazily in the routes module to avoid pulling heavy deps
# at import time. We define request/response wrappers here that are cheap.


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------


class CreateNamespaceRequest(BaseModel):
    """Request body for POST /api/knowledge/namespaces."""

    name: str = Field(
        ...,
        description="Namespace identifier (filesystem-safe, URL-safe, 1-64 chars)",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$",
        examples=["docs", "project-alpha", "my_knowledge_base"],
    )
    language: str = Field(
        default="English",
        description="Primary language of the namespace content",
        examples=["English", "French", "Spanish", "German"],
    )
    description: Optional[str] = Field(
        default=None,
        description="Human-readable description of the namespace",
        max_length=500,
        examples=["Technical documentation for the ACME project"],
    )


class ImportFolderRequest(BaseModel):
    """Request body for POST /api/knowledge/namespaces/{namespace}/import."""

    folder_path: str = Field(
        ...,
        description="Absolute path to the folder to import",
        examples=["/home/user/documents/project-docs"],
    )
    options: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional ingestion options (e.g., chunk_size, overlap)",
        examples=[{"chunk_size": 512, "overlap": 50}],
    )


class QueryRequest(BaseModel):
    """Request body for POST /api/knowledge/namespaces/{namespace}/query."""

    query: str = Field(
        ...,
        description="Natural language query text",
        min_length=1,
        max_length=2000,
        examples=["How do I configure the API key?"],
    )
    mode: str = Field(
        default="raw",
        description="Query mode: 'raw' (vector only), 'graph' (vector + graph), 'summarized' (graph + LLM)",
        pattern=r"^(raw|graph|summarized)$",
        examples=["raw", "graph", "summarized"],
    )
    top_k: int = Field(
        default=10,
        description="Maximum number of chunks to return",
        ge=1,
        le=100,
        examples=[10, 20, 50],
    )
    threshold: float = Field(
        default=0.5,
        description="Minimum similarity score (0.0-1.0, higher is better)",
        ge=0.0,
        le=1.0,
        examples=[0.3, 0.5, 0.7],
    )
    category: Optional[str] = Field(
        default=None,
        description="Optional category filter for scoped search",
        examples=["technical", "faq", "reference"],
    )
    parameter: str = Field(
        default="",
        description="Reserved for future use (domain hints)",
        examples=[""],
    )


# ---------------------------------------------------------------------------
# Retention Models (EPIC-004)
# ---------------------------------------------------------------------------


class RetentionPolicyRequest(BaseModel):
    """Request body for PUT /api/knowledge/namespaces/{namespace}/retention."""

    policy: str = Field(
        default="manual",
        description="Retention policy: 'manual' (no auto-cleanup) or 'ttl_days' (auto-delete old imports)",
        pattern=r"^(manual|ttl_days)$",
        examples=["manual", "ttl_days"],
    )
    ttl_days: Optional[int] = Field(
        default=None,
        description="Number of days before imports are auto-deleted (only when policy='ttl_days')",
        ge=1,
        le=3650,  # Max 10 years
        examples=[7, 30, 90],
    )
    auto_delete_when_empty: bool = Field(
        default=False,
        description="Delete namespace when all imports are purged by TTL",
    )


class RetentionPolicyResponse(BaseModel):
    """Response model for retention policy."""

    policy: str = "manual"
    ttl_days: Optional[int] = None
    last_swept_at: Optional[datetime] = None
    auto_delete_when_empty: bool = False


# ---------------------------------------------------------------------------
# Response Models (wrappers around canonical types)
# ---------------------------------------------------------------------------


class DeleteNamespaceResponse(BaseModel):
    """Response for DELETE /api/knowledge/namespaces/{namespace}."""

    deleted: bool = Field(
        ...,
        description="True if the namespace was deleted, False if it didn't exist",
        examples=[True, False],
    )
    namespace: str = Field(
        ...,
        description="The namespace that was targeted for deletion",
        examples=["docs"],
    )


class ImportFolderResponse(BaseModel):
    """Response for POST /api/knowledge/namespaces/{namespace}/import."""

    job_id: str = Field(
        ...,
        description="Unique identifier for the background import job",
        examples=["a1b2c3d4e5f67890"],
    )
    namespace: str = Field(
        ...,
        description="The namespace the import was submitted to",
        examples=["docs"],
    )


class ImportTextRequest(BaseModel):
    """Request body for POST /api/knowledge/namespaces/{namespace}/import-text."""

    text: str = Field(
        ...,
        description="Plain text to ingest directly into the namespace",
        min_length=1,
        max_length=100_000,
        examples=["This is a document about machine learning algorithms."],
    )
    source_label: str = Field(
        default="inline",
        description="Label identifying the text source (used in metadata)",
        max_length=200,
        examples=["inline", "meeting-notes", "chat-excerpt"],
    )
    options: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional ingestion options (e.g., chunk_size, overlap, llm_model)",
        examples=[{"chunk_size": 512, "overlap": 50}],
    )
    category: Optional[str] = Field(
        default=None,
        description="Optional category filter for scoped search",
        examples=["technical", "faq", "reference"],
    )


class ImportTextResponse(BaseModel):
    """Response for POST /api/knowledge/namespaces/{namespace}/import-text."""

    namespace: str = Field(
        ...,
        description="The namespace the text was ingested into",
        examples=["docs"],
    )
    chunks_added: int = Field(
        ...,
        description="Number of chunks created from the text",
        examples=[3],
    )
    entities_added: int = Field(
        ...,
        description="Number of entities extracted from the text",
        examples=[5],
    )
    relations_added: int = Field(
        ...,
        description="Number of relationships extracted from the text",
        examples=[2],
    )
    elapsed_seconds: float = Field(
        ...,
        description="Time taken for ingestion in seconds",
        examples=[0.42],
    )


class RefreshNamespaceResponse(BaseModel):
    """Response for POST /api/knowledge/namespaces/{namespace}/refresh."""

    job_ids: list[str] = Field(
        default_factory=list,
        description="List of job identifiers for the triggered refresh tasks",
    )


class BackupNamespaceResponse(BaseModel):
    """Response for POST /api/knowledge/namespaces/{namespace}/backup."""

    archive_path: str = Field(..., description="Absolute path to the created backup archive")
    namespace: str = Field(..., description="Name of the backed up namespace")


class RestoreNamespaceRequest(BaseModel):
    """Request body for POST /api/knowledge/namespaces/{namespace}/restore."""

    archive_path: str = Field(..., description="Absolute path to the backup archive to restore")
    overwrite: bool = Field(default=False, description="Overwrite existing namespace if True")


class ErrorResponse(BaseModel):
    """Standard error response shape for all knowledge endpoints."""

    error: str = Field(
        ...,
        description="Human-readable error message",
        examples=["Invalid namespace identifier"],
    )
    code: str = Field(
        ...,
        description="Machine-readable error code for programmatic handling",
        examples=[
            "INVALID_NAMESPACE_ID",
            "NAMESPACE_NOT_FOUND",
            "NAMESPACE_EXISTS",
            "INVALID_FOLDER_PATH",
            "FOLDER_NOT_FOUND",
            "NOT_A_DIRECTORY",
            "INTERNAL_ERROR",
        ],
    )
    detail: Optional[dict[str, Any]] = Field(
        default=None,
        description="Additional error context",
        examples=[{"namespace": "Invalid-Name!", "pattern": "^[a-z0-9][a-z0-9_-]{0,63}$"}],
    )


# ---------------------------------------------------------------------------
# Namespace Stats (mirrors NamespaceStats from dashboard.knowledge.namespace)
# ---------------------------------------------------------------------------


class NamespaceStatsResponse(BaseModel):
    """Aggregate counters for a namespace's content."""

    files_indexed: int = Field(default=0, description="Number of files indexed")
    chunks: int = Field(default=0, description="Number of text chunks")
    entities: int = Field(default=0, description="Number of extracted entities")
    relations: int = Field(default=0, description="Number of extracted relations")
    vectors: int = Field(default=0, description="Number of vector embeddings")
    bytes_on_disk: int = Field(default=0, description="Bytes used on disk")


class ImportRecordResponse(BaseModel):
    """A single import event in the manifest."""

    folder_path: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: str  # "running" | "completed" | "failed" | "interrupted"
    file_count: int = 0
    error_count: int = 0
    job_id: Optional[str] = None


class NamespaceMetaResponse(BaseModel):
    """Manifest metadata for a single namespace.

    Mirrors NamespaceMeta from dashboard.knowledge.namespace for HTTP transport.
    """

    schema_version: int = 2  # Updated to v2 in EPIC-004
    name: str
    created_at: datetime
    updated_at: datetime
    language: str = "English"
    description: Optional[str] = None
    embedding_model: str
    embedding_dimension: int
    stats: NamespaceStatsResponse = Field(default_factory=NamespaceStatsResponse)
    imports: list[ImportRecordResponse] = Field(default_factory=list)
    retention: RetentionPolicyResponse = Field(
        default_factory=RetentionPolicyResponse,
        description="Retention policy for automatic cleanup (EPIC-004)",
    )


# ---------------------------------------------------------------------------
# Job Status (mirrors JobStatus from dashboard.knowledge.jobs)
# ---------------------------------------------------------------------------


class JobStatusResponse(BaseModel):
    """Status of a background job."""

    job_id: str
    namespace: str
    operation: str
    state: str  # "pending" | "running" | "completed" | "failed" | "interrupted" | "cancelled"
    submitted_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    progress_current: int = 0
    progress_total: int = 0
    message: str = ""
    errors: list[str] = Field(default_factory=list)
    result: Optional[dict[str, Any]] = None


class GraphCountsResponse(BaseModel):
    """Live counts from the KuzuDB graph for a namespace."""

    entities: int = Field(default=0, description="Number of entity nodes (excluding text_chunk)")
    chunks: int = Field(default=0, description="Number of text_chunk nodes")
    relations: int = Field(default=0, description="Number of relation edges")


class NamespaceJobsResponse(BaseModel):
    """Enriched jobs response — jobs list plus live graph counters.

    The ``graph_counts`` field is populated from a lightweight Cypher
    COUNT query against KuzuDB and reflects the *current* state of the
    graph, not the manifest snapshot.
    """

    jobs: list[JobStatusResponse] = Field(default_factory=list)
    graph_counts: GraphCountsResponse = Field(default_factory=GraphCountsResponse)


# ---------------------------------------------------------------------------
# Query Result (mirrors QueryResult from dashboard.knowledge.query)
# ---------------------------------------------------------------------------


class ChunkHitResponse(BaseModel):
    """A single chunk returned from vector retrieval.

    ``memory_links`` is populated by the Memory-Knowledge bridge
    (OSTWIN_KNOWLEDGE_MEMORY_BRIDGE=1) and contains note IDs from the
    agentic memory store that cite this specific chunk. Empty list when
    the bridge is disabled or unavailable.
    """

    text: str
    score: float
    file_path: str = ""
    filename: str = ""
    chunk_index: int = 0
    total_chunks: int = 1
    file_hash: str = ""
    mime_type: Optional[str] = None
    category_id: Optional[str] = None
    memory_links: list[str] = Field(default_factory=list)


class EntityHitResponse(BaseModel):
    """A single entity returned from graph expansion."""

    id: str
    name: str
    label: str = "entity"
    score: float = 0.0
    description: Optional[str] = None
    category_id: Optional[str] = None


class CitationResponse(BaseModel):
    """A pointer back to the source document for a chunk hit."""

    file: str
    page: Optional[int] = None
    chunk_index: int = 0
    snippet_id: str = ""


class QueryResultResponse(BaseModel):
    """Top-level result for a single query."""

    query: str
    mode: str
    namespace: str
    chunks: list[ChunkHitResponse] = Field(default_factory=list)
    entities: list[EntityHitResponse] = Field(default_factory=list)
    answer: Optional[str] = None
    citations: list[CitationResponse] = Field(default_factory=list)
    latency_ms: int = 0
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Web Research Models
# ---------------------------------------------------------------------------


class ResearchRequest(BaseModel):
    """Request body for POST /api/knowledge/namespaces/{namespace}/research."""

    query: str = Field(
        ...,
        description="Research query or topic",
        min_length=1,
        max_length=500,
        examples=["pixel art animation techniques 2024"],
    )
    engines: Optional[list[str]] = Field(
        default=None,
        description="SearXNG engines to target (e.g. youtube, github, google)",
        examples=[["google", "youtube"], ["github"]],
    )
    categories: Optional[list[str]] = Field(
        default=None,
        description="SearXNG categories (e.g. videos, it, general, science)",
        examples=[["it", "videos"], ["general"]],
    )
    max_results: int = Field(
        default=10,
        description="Maximum number of search results to fetch and ingest",
        ge=1,
        le=50,
        examples=[10, 20],
    )
    summarize: bool = Field(
        default=True,
        description="Generate an LLM summary of findings",
    )
    language: str = Field(
        default="en",
        description="Search language code",
        min_length=2,
        max_length=5,
        examples=["en", "ja", "de"],
    )


class ResearchSourceResponse(BaseModel):
    """Per-source outcome in research results."""

    url: str
    title: str = ""
    engine: str = ""
    status: str = ""
    chunks_added: int = 0
    error: Optional[str] = None


class ResearchResponse(BaseModel):
    """Response for POST /api/knowledge/namespaces/{namespace}/research."""

    query: str
    namespace: str
    engines_used: list[str] = Field(default_factory=list)
    categories_used: list[str] = Field(default_factory=list)
    sources: list[ResearchSourceResponse] = Field(default_factory=list)
    total_chunks_added: int = 0
    total_entities_added: int = 0
    total_relations_added: int = 0
    summary: Optional[str] = None
    elapsed_seconds: float = 0.0
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Web Research — Two-step async models
# ---------------------------------------------------------------------------


class ResearchSearchRequest(BaseModel):
    """Request body for POST /api/knowledge/namespaces/{namespace}/research/search."""

    query: str = Field(
        ...,
        description="Search query",
        min_length=1,
        max_length=500,
        examples=["pixel art animation techniques 2024"],
    )
    engines: Optional[list[str]] = Field(
        default=None,
        description="SearXNG engines to target",
        examples=[["google", "youtube"], ["github"]],
    )
    categories: Optional[list[str]] = Field(
        default=None,
        description="SearXNG categories",
        examples=[["it", "videos"], ["general"]],
    )
    max_results: int = Field(
        default=10,
        description="Maximum number of search results to return",
        ge=1,
        le=50,
    )
    language: str = Field(
        default="en",
        description="Search language code",
        min_length=2,
        max_length=5,
    )


class SearchResultItemResponse(BaseModel):
    """A single search result preview from SearXNG."""

    title: str
    url: str
    snippet: str = ""
    engine: str = ""
    score: float = 0.0
    thumbnail_url: str = ""
    metadata: dict = Field(default_factory=dict)


class ResearchSearchResponse(BaseModel):
    """Response for POST /api/knowledge/namespaces/{namespace}/research/search."""

    query: str
    engines_used: list[str] = Field(default_factory=list)
    categories_used: list[str] = Field(default_factory=list)
    results: list[SearchResultItemResponse] = Field(default_factory=list)
    elapsed_seconds: float = 0.0
    warnings: list[str] = Field(default_factory=list)


class ResearchIngestItem(BaseModel):
    """A single item selected by the user for ingestion."""

    url: str = Field(..., description="URL to fetch and ingest")
    title: str = Field(default="", description="Title from search result")
    engine: str = Field(default="", description="Source engine")
    snippet: str = Field(default="", description="Search snippet for provenance")


class ResearchIngestRequest(BaseModel):
    """Request body for POST /api/knowledge/namespaces/{namespace}/research/ingest."""

    items: list[ResearchIngestItem] = Field(
        ...,
        description="Selected search results to fetch and ingest",
        min_length=1,
        max_length=50,
    )
    query: str = Field(
        ...,
        description="Original search query (for provenance metadata)",
        min_length=1,
        max_length=500,
    )
    summarize: bool = Field(
        default=True,
        description="Generate an LLM summary after ingestion",
    )
    language: str = Field(
        default="en",
        description="Content language",
        min_length=2,
        max_length=5,
    )


class ResearchIngestJobResponse(BaseModel):
    """Response for POST /api/knowledge/namespaces/{namespace}/research/ingest."""

    job_id: str
    namespace: str
    status: str = "submitted"
    message: str = ""


# ---------------------------------------------------------------------------
# Enterprise Map Projection Contract (EPIC-001)
# ---------------------------------------------------------------------------

JsonScalar = Union[str, int, float, bool, None]
JsonObject = dict[str, Union[JsonScalar, list[JsonScalar], dict[str, JsonScalar]]]
FilterValue = Union[list[str], "ExplorerOntologyFilterClause"]


class StrictRequestModel(BaseModel):
    """Base model for governed request contracts; unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid")


class TimeRangeResponse(StrictRequestModel):
    """Optional time range attached to map nodes/edges."""

    start: Optional[str] = None
    end: Optional[str] = None


class ExplorerOntologyFilterClause(StrictRequestModel):
    """Include/exclude filter clause for one enterprise-map facet."""

    values: list[str] = Field(default_factory=list)
    mode: Literal["include", "exclude"] = "include"


class ExplorerOntologyFilters(StrictRequestModel):
    """Strict ontology filters accepted by enterprise-map and explorer expand."""

    layer: Optional[FilterValue] = None
    abstraction_level: Optional[FilterValue] = None
    concept_type: Optional[FilterValue] = None
    relationship_family: Optional[FilterValue] = None
    relationship_type: Optional[FilterValue] = None
    pack_id: Optional[FilterValue] = None
    lifecycle_state: Optional[FilterValue] = None
    owner: Optional[FilterValue] = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    def to_filter_dict(self) -> dict[str, object]:
        """Return a compact dict with unset/empty filters removed."""

        data = self.model_dump(exclude_none=True)
        if not data.get("metadata"):
            data.pop("metadata", None)
        return data


class EnterpriseMapQueryRequest(StrictRequestModel):
    """Rich enterprise-map read body for filtered/view-directed POST queries."""

    limit: int = Field(default=200, ge=1, le=500)
    filters: Optional[ExplorerOntologyFilters] = None
    group_by: Optional[list[str]] = None
    color_by: Optional[str] = None


class EnterpriseMapOntologyPathResponse(BaseModel):
    """Ontology path breadcrumbs for a projected node."""

    concept_type: Optional[str] = None
    abstraction_level: Optional[str] = None
    layer: Optional[str] = None
    pack_id: Optional[str] = None


class EnterpriseMapNodeResponse(BaseModel):
    """Single node in the governed enterprise-map visual projection."""

    id: str
    label: str = "entity"
    name: str
    score: float = 1.0
    properties: JsonObject = Field(default_factory=dict)
    concept_type: Optional[str] = None
    concept_label: Optional[str] = None
    abstraction_level: Optional[str] = None
    layer: Optional[str] = None
    pack_id: Optional[str] = None
    family: Optional[str] = None
    review_state: Optional[str] = None
    lifecycle_state: Optional[str] = None
    validation_issues: list[str] = Field(default_factory=list)
    external_ref: Optional[str] = None
    provenance_refs: list[str] = Field(default_factory=list)
    ontology_path: Optional[EnterpriseMapOntologyPathResponse] = None
    map_group: Optional[str] = None
    color: Optional[str] = None
    shape: Optional[str] = None
    event_count: Optional[int] = None
    active_event_count: Optional[int] = None
    time_range: Optional[TimeRangeResponse] = None
    series_refs: list[str] = Field(default_factory=list)
    flow_refs: list[str] = Field(default_factory=list)
    simulation_refs: list[str] = Field(default_factory=list)
    state: Optional[str] = None
    simulation_state: Optional[str] = None
    state_machine_ref: Optional[str] = None
    state_color: Optional[str] = None
    phase: Optional[str] = None
    track: Optional[str] = None
    priority: Optional[Union[str, int]] = None
    effort: Optional[Union[str, int]] = None
    prerequisites: list[str] = Field(default_factory=list)
    acceptance: Optional[Union[list[str], str]] = None


class EnterpriseMapEdgeResponse(BaseModel):
    """Single edge in the governed enterprise-map visual projection."""

    source: str
    target: str
    label: str = "RELATES"
    weight: float = 1.0
    properties: JsonObject = Field(default_factory=dict)
    relationship_type: Optional[str] = None
    relationship_family: Optional[str] = None
    family: Optional[str] = None
    review_state: Optional[str] = None
    validation_issues: list[str] = Field(default_factory=list)
    external_ref: Optional[str] = None
    provenance_refs: list[str] = Field(default_factory=list)
    color: Optional[str] = None
    event_count: Optional[int] = None
    active_event_count: Optional[int] = None
    time_range: Optional[TimeRangeResponse] = None
    series_refs: list[str] = Field(default_factory=list)
    flow_refs: list[str] = Field(default_factory=list)
    simulation_refs: list[str] = Field(default_factory=list)
    state: Optional[str] = None
    simulation_state: Optional[str] = None
    state_machine_ref: Optional[str] = None
    state_color: Optional[str] = None
    phase: Optional[str] = None
    track: Optional[str] = None
    priority: Optional[Union[str, int]] = None
    effort: Optional[Union[str, int]] = None
    prerequisites: list[str] = Field(default_factory=list)
    acceptance: Optional[Union[list[str], str]] = None


class EnterpriseMapLayerResponse(BaseModel):
    id: str
    label: str
    order: int = 0


class EnterpriseMapAbstractionLevelResponse(BaseModel):
    id: str
    label: str
    order: int = 0


class EnterpriseMapStatsResponse(BaseModel):
    source_node_count: int = 0
    source_edge_count: int = 0
    node_count: int = 0
    edge_count: int = 0
    ontology_candidate_count: int = 0
    validation_issue_count: int = 0
    event_count: int = 0
    active_event_count: int = 0
    truncated: bool = False
    depth_requested: Optional[int] = None
    depth_effective: Optional[int] = None
    node_cap: Optional[int] = None


class EnterpriseMapMetaResponse(BaseModel):
    profile_id: Optional[str] = None
    namespace: str = ""
    generated_at: str = ""
    map_state: Literal["live", "empty"] = "empty"
    map_source_kind: Literal["knowledge_graph", "none"] = "none"
    source_node_count: int = 0
    source_edge_count: int = 0
    applied_filters: dict[str, object] = Field(default_factory=dict)
    applied_group_by: list[str] = Field(default_factory=list)
    applied_color_by: str = "type"
    truncated: bool = False
    depth_requested: Optional[int] = None
    depth_effective: Optional[int] = None
    node_cap: Optional[int] = None
    node_limit: Optional[int] = None
    edge_limit: Optional[int] = None
    event_limit: Optional[int] = None
    next_cursor: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    feature_flags: dict[str, bool] = Field(default_factory=dict)


class EnterpriseMapProjectionResponse(BaseModel):
    nodes: list[EnterpriseMapNodeResponse] = Field(default_factory=list)
    edges: list[EnterpriseMapEdgeResponse] = Field(default_factory=list)
    layers: list[EnterpriseMapLayerResponse] = Field(default_factory=list)
    abstraction_levels: list[EnterpriseMapAbstractionLevelResponse] = Field(default_factory=list)
    stats: EnterpriseMapStatsResponse = Field(default_factory=EnterpriseMapStatsResponse)
    meta: EnterpriseMapMetaResponse = Field(default_factory=EnterpriseMapMetaResponse)


__all__ = [
    # Requests
    "CreateNamespaceRequest",
    "ImportFolderRequest",
    "QueryRequest",
    "RestoreNamespaceRequest",
    "RetentionPolicyRequest",  # EPIC-004
    "ResearchRequest",
    "ResearchSearchRequest",
    "ResearchIngestItem",
    "ResearchIngestRequest",
    "TimeRangeResponse",
    "ExplorerOntologyFilterClause",
    "ExplorerOntologyFilters",
    "EnterpriseMapQueryRequest",
    "EnterpriseMapNodeResponse",
    "EnterpriseMapEdgeResponse",
    "EnterpriseMapMetaResponse",
    "EnterpriseMapStatsResponse",
    "EnterpriseMapProjectionResponse",
    "EnterpriseMapLayerResponse",
    "EnterpriseMapAbstractionLevelResponse",
    "EnterpriseMapOntologyPathResponse",
    # Responses
    "DeleteNamespaceResponse",
    "ImportFolderResponse",
    "BackupNamespaceResponse",
    "ErrorResponse",
    "NamespaceStatsResponse",
    "ImportRecordResponse",
    "NamespaceMetaResponse",
    "JobStatusResponse",
    "GraphCountsResponse",
    "NamespaceJobsResponse",
    "ChunkHitResponse",
    "EntityHitResponse",
    "CitationResponse",
    "QueryResultResponse",
    "RefreshNamespaceResponse",
    "RetentionPolicyResponse",  # EPIC-004
    "ResearchResponse",
    "ResearchSourceResponse",
    "ResearchSearchResponse",
    "SearchResultItemResponse",
    "ResearchIngestJobResponse",
]
