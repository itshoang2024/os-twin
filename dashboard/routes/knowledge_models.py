"""Request/response Pydantic models for the Knowledge REST API (EPIC-001).

These models wrap the canonical types from `dashboard.knowledge` (NamespaceMeta,
JobStatus, QueryResult) for HTTP transport. They do NOT duplicate fields —
they re-export or compose the canonical types to maintain a single source of
truth.

All models are JSON-serializable (Pydantic v2) and include OpenAPI examples.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


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
# Ontology Profile Models (EPIC-003)
# ---------------------------------------------------------------------------


class OntologyUnitRequest(BaseModel):
    """Request body for PUT /api/knowledge/namespaces/{namespace}/ontology/unit."""

    unit: dict[str, Any] = Field(
        ...,
        description="OntologyUnit JSON payload to validate and persist. The namespace must match the path.",
        examples=[{"namespace": "docs", "active_profile_id": None, "name": "Audit Process Ontology"}],
    )


class OntologyUnitResponse(BaseModel):
    """Response for ontology unit lookup and writes."""

    namespace: str = Field(..., description="Namespace for the ontology unit")
    unit: Optional[dict[str, Any]] = Field(default=None, description="Ontology unit JSON, if one exists")
    unit_exists: bool = Field(..., description="True when ontology/unit.json exists or legacy synthesis succeeded")


class OntologyProfileRequest(BaseModel):
    """Request body for PUT /api/knowledge/namespaces/{namespace}/ontology/profile."""

    profile: dict[str, Any] = Field(
        ...,
        description="OntologyProfile JSON payload to validate and persist. The namespace must match the path.",
        examples=[{"profile_id": "enterprise_feature_map", "namespace": "docs", "version": "1.0.0"}],
    )
    reason: str = Field(default="Profile saved through API", description="Human reason recorded in profile history")
    validation_override: Optional[dict[str, Any]] = Field(
        default=None,
        description="Required metadata when migration safety detects a dangerous ontology change.",
    )


class OntologyValidationIssueResponse(BaseModel):
    """Structured ontology validation issue."""

    severity: str = Field(..., description="Issue severity: info, warning, or error")
    code: str = Field(..., description="Machine-readable validation issue code")
    path: str = Field(..., description="Path within the submitted subject that triggered the issue")
    message: str = Field(..., description="Human-readable validation message")
    suggested_fix: str = Field(default="", description="Suggested remediation")
    subject: str = Field(default="edge", description="Validated subject: profile, node, edge, or pack")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional issue metadata")


class OntologyProfileResponse(BaseModel):
    """Response for ontology profile lookup and writes."""

    namespace: str = Field(..., description="Namespace for the ontology profile")
    profile: Optional[dict[str, Any]] = Field(default=None, description="Active ontology profile JSON, if one exists")
    profile_exists: bool = Field(..., description="True when an active profile is persisted")
    default_suggested: bool = Field(
        default=False,
        description="True when no active profile exists and default_profile contains seed metadata",
    )
    default_profile: Optional[dict[str, Any]] = Field(
        default=None,
        description="Deterministic default profile suggestion for legacy namespaces without a saved profile",
    )
    validation_issues: list[OntologyValidationIssueResponse] = Field(default_factory=list)




class OntologyProfileDiffRequest(BaseModel):
    """Request body for side-effect-free ontology profile diff previews."""

    base_profile: Optional[dict[str, Any]] = None
    target_profile: Optional[dict[str, Any]] = None
    base_version: Optional[str] = None
    target_version: Optional[str] = None


class OntologyProfileDiffResponse(BaseModel):
    namespace: str
    base_version: Optional[str] = None
    target_version: Optional[str] = None
    history_id: Optional[str] = None
    diff: dict[str, Any]
    migration_issues: list[dict[str, Any]] = Field(default_factory=list)
    would_mutate: bool = False


class OntologyProfileHistoryRecordResponse(BaseModel):
    id: str
    namespace: str
    actor: str
    timestamp: datetime
    reason: str
    previous_version: Optional[str] = None
    new_version: str
    changed_paths: list[str] = Field(default_factory=list)
    diff: dict[str, Any] = Field(default_factory=dict)
    migration_issues: list[dict[str, Any]] = Field(default_factory=list)
    validation_override: Optional[dict[str, Any]] = None
    migration_entries: list[dict[str, Any]] = Field(default_factory=list)
    profile: Optional[dict[str, Any]] = None


class OntologyProfileHistoryListResponse(BaseModel):
    namespace: str
    history: list[OntologyProfileHistoryRecordResponse] = Field(default_factory=list)


class OntologyValidateRequest(BaseModel):
    """Request body for POST /api/knowledge/namespaces/{namespace}/ontology/validate."""

    subject: Literal["profile", "node", "edge", "pack"] = Field(
        ...,
        description="Type of object to validate without saving",
        examples=["profile", "edge"],
    )
    profile: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional profile payload to validate or to use as validation context",
    )
    node: Optional[dict[str, Any]] = Field(default=None, description="Node payload with a type/concept_type field")
    edge: Optional[dict[str, Any]] = Field(
        default=None,
        description="Edge payload with relation/source/target type fields",
    )
    nodes: list[dict[str, Any]] = Field(default_factory=list, description="Node pack payloads")
    edges: list[dict[str, Any]] = Field(default_factory=list, description="Edge pack payloads")


class OntologyValidateResponse(BaseModel):
    """Response for side-effect-free ontology validation."""

    namespace: str
    subject: str
    valid: bool = Field(..., description="False when any validation issue has severity=error")
    issues: list[OntologyValidationIssueResponse] = Field(default_factory=list)


class OntologyResetDefaultResponse(BaseModel):
    """Response for POST /api/knowledge/namespaces/{namespace}/ontology/reset-default."""

    namespace: str
    profile: dict[str, Any]
    replaced_existing: bool = Field(..., description="True when an existing profile was replaced")


class OntologySummaryResponse(BaseModel):
    """Summary counters for a namespace ontology profile."""

    namespace: str
    profile_exists: bool
    profile_id: Optional[str] = None
    version: Optional[str] = None
    concept_type_count: int = 0
    relation_type_count: int = 0
    alias_count: int = 0
    candidate_count: int = 0
    validation_issue_count: int = 0
    validation_issues: list[OntologyValidationIssueResponse] = Field(default_factory=list)


class OntologyReleaseObservabilityResponse(BaseModel):
    """Release-gate health report for the ontology lifecycle."""

    namespace: str
    generated_at: str
    profile: dict[str, Any] = Field(default_factory=dict)
    candidates: dict[str, Any] = Field(default_factory=dict)
    facts: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    observations: dict[str, Any] = Field(default_factory=dict)
    assistant: dict[str, Any] = Field(default_factory=dict)
    packs: dict[str, Any] = Field(default_factory=dict)
    release_blockers: list[dict[str, Any]] = Field(default_factory=list)
    release_ready: bool = False


# ---------------------------------------------------------------------------
# Enterprise Map Projection Models (EPIC-009)
# ---------------------------------------------------------------------------


class EnterpriseMapOntologyPathResponse(BaseModel):
    """Ontology coordinates attached to an enterprise map node."""

    layer: Optional[str] = None
    abstraction_level: Optional[str] = None
    concept_type: Optional[str] = None
    pack_id: Optional[str] = None
    lifecycle_state: Optional[str] = None


class EnterpriseMapNodeResponse(BaseModel):
    """Ontology-aware node returned by /ontology/enterprise-map."""

    id: str
    label: Optional[str] = None
    name: Optional[str] = None
    score: float = 1.0
    properties: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    concept_type: Optional[str] = None
    concept_label: Optional[str] = None
    concept_color: Optional[str] = None
    concept_shape: Optional[str] = None
    abstraction_level: Optional[str] = None
    abstraction_label: Optional[str] = None
    layer_id: Optional[str] = None
    layer_label: Optional[str] = None
    layer_order: Optional[int] = None
    pack_id: Optional[str] = None
    lifecycle_state: Optional[str] = None
    review_state: Optional[str] = None
    confidence: Optional[float] = None
    provenance_refs: list[str] = Field(default_factory=list)
    external_ref: Optional[dict[str, Any]] = None
    owner: Optional[str] = None
    description: Optional[str] = None
    map_group: Optional[str] = None
    data_store: Optional[str] = None
    sync_mode: Optional[str] = None
    quality_state: Optional[str] = None
    candidate_state: Optional[str] = None
    event_count: Optional[Any] = None
    active_event_count: Optional[Any] = None
    time_range: Optional[Any] = None
    series_refs: Optional[Any] = None
    flow_refs: Optional[Any] = None
    state: Optional[Any] = None
    simulation_state: Optional[Any] = None
    simulation_refs: Optional[Any] = None
    state_machine_ref: Optional[Any] = None
    state_color: Optional[Any] = None
    phase: Optional[Any] = None
    track: Optional[Any] = None
    priority: Optional[Any] = None
    effort: Optional[Any] = None
    prerequisites: Optional[Any] = None
    acceptance: Optional[Any] = None
    ontology_path: EnterpriseMapOntologyPathResponse = Field(default_factory=EnterpriseMapOntologyPathResponse)
    validation_issues: list[dict[str, Any]] = Field(default_factory=list)


class EnterpriseMapEdgeResponse(BaseModel):
    """Ontology-aware relationship returned by /ontology/enterprise-map."""

    id: Optional[str] = None
    source: str
    target: str
    label: Optional[str] = None
    weight: float = 1.0
    properties: dict[str, Any] = Field(default_factory=dict)
    relationship_type: Optional[str] = None
    family: Optional[str] = None
    display_label: Optional[str] = None
    inverse_label: Optional[str] = None
    style: Optional[str] = None
    color: Optional[str] = None
    dash: Optional[str] = None
    map_source: Optional[str] = None
    map_target: Optional[str] = None
    map_direction: Optional[str] = None
    map_group: Optional[str] = None
    review_state: Optional[str] = None
    confidence: Optional[float] = None
    provenance_refs: list[str] = Field(default_factory=list)
    external_ref: Optional[dict[str, Any]] = None
    candidate_state: Optional[str] = None
    event_count: Optional[Any] = None
    active_event_count: Optional[Any] = None
    time_range: Optional[Any] = None
    series_refs: Optional[Any] = None
    flow_refs: Optional[Any] = None
    state: Optional[Any] = None
    simulation_state: Optional[Any] = None
    simulation_refs: Optional[Any] = None
    state_machine_ref: Optional[Any] = None
    state_color: Optional[Any] = None
    phase: Optional[Any] = None
    track: Optional[Any] = None
    priority: Optional[Any] = None
    effort: Optional[Any] = None
    prerequisites: Optional[Any] = None
    acceptance: Optional[Any] = None
    is_candidate: bool = False
    validation_issues: list[dict[str, Any]] = Field(default_factory=list)


class EnterpriseMapLayerResponse(BaseModel):
    """Layer lane returned by the enterprise map projection."""

    id: str
    label: str
    order: int = 999
    description: str = ""
    lifecycle_state: str = "active"
    count: int = 0


class EnterpriseMapAbstractionLevelResponse(BaseModel):
    """Abstraction level metadata returned by the enterprise map projection."""

    id: str
    label: str
    order: Optional[int] = None
    description: str = ""


class EnterpriseMapStatsResponse(BaseModel):
    """Projection counters and large-graph safety metadata."""

    node_count: int = 0
    edge_count: int = 0
    layer_count: int = 0
    concept_type_count: int = 0
    relationship_type_count: int = 0
    candidate_edge_count: int = 0
    validation_issue_count: int = 0
    source_node_count: Optional[int] = None
    source_edge_count: Optional[int] = None
    ontology_candidate_count: Optional[int] = None
    event_count: int = 0
    active_event_count: int = 0
    flow_count: int = 0
    state_machine_count: int = 0
    simulation_scenario_count: int = 0
    limit: Optional[int] = None
    filtered: bool = False


class EnterpriseMapMetaResponse(BaseModel):
    """Namespace/profile metadata for the enterprise map projection."""

    ontology_profile: Optional[dict[str, Any]] = None
    profile_exists: bool = False
    ontology_candidate_count: int = 0
    graph_instruction: dict[str, Any] = Field(default_factory=dict)
    time_window: dict[str, Any] = Field(default_factory=dict)
    observation_series_backend: str = "inline-json-mvp"
    analysis: dict[str, Any] = Field(default_factory=dict)


class EnterpriseMapProjectionResponse(BaseModel):
    """Typed response model for /api/knowledge/namespaces/{namespace}/ontology/enterprise-map."""

    nodes: list[EnterpriseMapNodeResponse] = Field(default_factory=list)
    edges: list[EnterpriseMapEdgeResponse] = Field(default_factory=list)
    layers: list[EnterpriseMapLayerResponse] = Field(default_factory=list)
    abstraction_levels: list[EnterpriseMapAbstractionLevelResponse] = Field(default_factory=list)
    concept_type_counts: dict[str, int] = Field(default_factory=dict)
    relationship_type_counts: dict[str, int] = Field(default_factory=dict)
    relationship_family_counts: dict[str, int] = Field(default_factory=dict)
    stats: EnterpriseMapStatsResponse = Field(default_factory=EnterpriseMapStatsResponse)
    meta: EnterpriseMapMetaResponse = Field(default_factory=EnterpriseMapMetaResponse)


# ---------------------------------------------------------------------------
# Domain Pack Models (EPIC-005)
# ---------------------------------------------------------------------------


class DomainPackRequest(BaseModel):
    """Request body for domain pack operations."""

    pack_id: str = Field(..., description="Domain pack identifier", examples=["financial-services"])


class DomainPackManifestResponse(BaseModel):
    """Installable domain pack manifest."""

    pack_id: str
    name: str
    version: str
    compatible_profile_versions: list[str] = Field(default_factory=list)
    concept_types: dict[str, Any] = Field(default_factory=dict)
    relationship_types: dict[str, Any] = Field(default_factory=dict)
    layers: dict[str, Any] = Field(default_factory=dict)
    abstraction_levels: dict[str, Any] = Field(default_factory=dict)
    aliases: dict[str, str] = Field(default_factory=dict)
    metadata_fields: dict[str, Any] = Field(default_factory=dict)
    validation_rules: list[dict[str, Any]] = Field(default_factory=list)
    graph_instruction: dict[str, Any] = Field(default_factory=dict)
    time_window: dict[str, Any] = Field(default_factory=dict)
    observation_series_backend: str = "inline-json-mvp"
    analysis: dict[str, Any] = Field(default_factory=dict)
    fixtures: list[dict[str, Any]] = Field(default_factory=list)
    migration_notes: list[str] = Field(default_factory=list)


class DomainPackListResponse(BaseModel):
    """Response for available domain packs."""

    packs: list[DomainPackManifestResponse] = Field(default_factory=list)


class DomainPackInstalledResponse(BaseModel):
    """Response for installed domain pack namespace state."""

    namespace: str
    schema_version: int = 1
    installed_packs: dict[str, Any] = Field(default_factory=dict)


class DomainPackValidateResponse(BaseModel):
    """Side-effect-free pack validation response."""

    namespace: str
    pack_id: str
    valid: bool
    issues: list[OntologyValidationIssueResponse] = Field(default_factory=list)
    profile: Optional[dict[str, Any]] = None
    manifest: Optional[DomainPackManifestResponse] = None


class DomainPackOperationResponse(BaseModel):
    """Pack install/uninstall operation response."""

    namespace: str
    pack_id: str
    action: str
    installed: bool
    profile: dict[str, Any]
    state: DomainPackInstalledResponse
    issues: list[OntologyValidationIssueResponse] = Field(default_factory=list)


class OntologyCandidateActionRequest(BaseModel):
    """Review action for an ontology candidate."""

    canonical_id: Optional[str] = Field(default=None, description="Canonical enum id for approve/map actions")
    payload: dict[str, Any] = Field(default_factory=dict, description="Optional enum metadata for approval")
    reason: str = Field(default="", description="Optional rejection reason")


class OntologyCandidateBulkRequest(BaseModel):
    """Bulk candidate review actions."""

    actions: list[dict[str, Any]] = Field(default_factory=list)


class OntologyCandidateResponse(BaseModel):
    id: str
    namespace: str
    candidate_type: str
    source: str
    original_label: str
    normalized_label: str = ""
    suggested_canonical: Optional[str] = None
    confidence: float
    sample_text: str
    status: str
    source_hash: str = ""
    proposed_payload: dict[str, Any] = Field(default_factory=dict)
    source_evidence_ref: Optional[str] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OntologyCandidateListResponse(BaseModel):
    namespace: str
    candidates: list[OntologyCandidateResponse] = Field(default_factory=list)


class FactSubjectResponse(BaseModel):
    kind: str
    id: str
    label: str = ""
    concept_type: Optional[str] = None


class SuggestedRelationshipMappingResponse(BaseModel):
    relationship_type: Optional[str] = None
    source_id: Optional[str] = None
    target_id: Optional[str] = None
    source_kind: str = "node"
    target_kind: str = "node"
    direction: str = "forward"
    confidence: Optional[float] = None


class OntologyFactResponse(BaseModel):
    id: str
    namespace: str
    statement: str
    subjects: list[FactSubjectResponse] = Field(default_factory=list)
    subject_ids: list[str] = Field(default_factory=list)
    confidence: float
    review_state: str
    source: str
    evidence_refs: list[str] = Field(default_factory=list)
    provenance_refs: list[str] = Field(default_factory=list)
    suggested_mapping: Optional[SuggestedRelationshipMappingResponse] = None
    source_hash: str = ""
    promoted_edge_id: Optional[str] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OntologyFactListResponse(BaseModel):
    namespace: str
    facts: list[OntologyFactResponse] = Field(default_factory=list)


class OntologyFactCreateRequest(BaseModel):
    statement: str = Field(..., min_length=1, max_length=2000)
    subjects: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: Literal["extraction", "assistant", "manual"] = "assistant"
    evidence_refs: list[str] = Field(default_factory=list)
    provenance_refs: list[str] = Field(default_factory=list)
    suggested_mapping: Optional[dict[str, Any]] = None
    source_hash: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class OntologyFactReviewRequest(BaseModel):
    review_state: Literal["draft", "assistive", "reviewed", "approved", "rejected"]
    metadata: dict[str, Any] = Field(default_factory=dict)


class OntologyFactPromoteRequest(BaseModel):
    relationship_type: Optional[str] = None
    source_id: Optional[str] = None
    target_id: Optional[str] = None


class OntologyFactRelationshipCandidateRequest(BaseModel):
    relationship_label: str = Field(..., min_length=1, max_length=120)


class OntologyFactPromoteResponse(BaseModel):
    namespace: str
    edge: dict[str, Any]


class OntologyFactRelationshipCandidateResponse(BaseModel):
    namespace: str
    candidate: OntologyCandidateResponse


class ObservationEventResponse(BaseModel):
    id: str
    namespace: str
    event_type: str
    subject_type: str
    subject_id: str
    occurred_at: datetime
    actor: Optional[str] = None
    value: Optional[Any] = None
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ObservationEventListResponse(BaseModel):
    namespace: str
    events: list[ObservationEventResponse] = Field(default_factory=list)


class TimeSeriesPointResponse(BaseModel):
    timestamp: datetime
    value: float
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TimeSeriesResponse(BaseModel):
    id: str
    namespace: str
    subject_id: str
    metric_id: str
    unit: str = "count"
    points: list[TimeSeriesPointResponse] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class TimeSeriesListResponse(BaseModel):
    namespace: str
    series: list[TimeSeriesResponse] = Field(default_factory=list)


class TimeSeriesUpsertRequest(BaseModel):
    subject_id: str = Field(..., min_length=1)
    metric_id: str = Field(..., min_length=1)
    unit: str = "count"
    points: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OntologyAssistantMessageRequest(BaseModel):
    """Prior chat turn sent to the ontology assistant."""

    role: str
    content: str


class OntologyAssistantRequest(BaseModel):
    """Request body for AI-assisted ontology schema design."""

    message: str = Field(..., description="User instruction for schema design")
    profile: dict[str, Any] = Field(..., description="Current draft ontology profile")
    selected: Optional[dict[str, Any]] = Field(default=None, description="Selected schema graph element")
    context: Optional[dict[str, Any]] = Field(default=None, description="Bounded candidate, evidence, fact, pack, or namespace refs")
    history: list[OntologyAssistantMessageRequest] = Field(default_factory=list)


class OntologyAssistantResponse(BaseModel):
    """Text response from the ontology schema assistant."""

    namespace: str
    conversation_id: str
    text: str


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
    candidate_count: int = Field(
        default=0,
        description="Number of ontology review candidates emitted during ingestion",
        examples=[1],
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
    ontology_profile_version: Optional[str] = Field(
        default=None,
        description="Active ontology profile version for this namespace, or null for legacy namespaces",
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


__all__ = [
    # Requests
    "CreateNamespaceRequest",
    "ImportFolderRequest",
    "QueryRequest",
    "RestoreNamespaceRequest",
    "RetentionPolicyRequest",  # EPIC-004
    "OntologyProfileRequest",
    "OntologyValidateRequest",
    "OntologyAssistantRequest",
    "ResearchRequest",
    "ResearchSearchRequest",
    "ResearchIngestItem",
    "ResearchIngestRequest",
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
    "OntologyValidationIssueResponse",
    "OntologyUnitRequest",
    "OntologyUnitResponse",
    "OntologyProfileResponse",
    "OntologyValidateResponse",
    "OntologyResetDefaultResponse",
    "OntologySummaryResponse",
    "OntologyAssistantResponse",
    "EnterpriseMapOntologyPathResponse",
    "EnterpriseMapNodeResponse",
    "EnterpriseMapEdgeResponse",
    "EnterpriseMapLayerResponse",
    "EnterpriseMapAbstractionLevelResponse",
    "EnterpriseMapStatsResponse",
    "EnterpriseMapMetaResponse",
    "EnterpriseMapProjectionResponse",
    "TimeSeriesUpsertRequest",
    "TimeSeriesListResponse",
    "TimeSeriesResponse",
    "ObservationEventListResponse",
    "ObservationEventResponse",
    "ResearchResponse",
    "ResearchSourceResponse",
    "ResearchSearchResponse",
    "SearchResultItemResponse",
    "ResearchIngestJobResponse",
]
