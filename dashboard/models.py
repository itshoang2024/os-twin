from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


class Room(BaseModel):
    room_id: str
    task_ref: str
    status: str
    retries: int
    message_count: int
    last_activity: Optional[str] = None
    task_description: Optional[str] = None
    goal_total: int = 0
    goal_done: int = 0


class Message(BaseModel):
    id: str
    ts: str
    from_: str
    to: str
    type: str
    ref: str
    body: str


class RunRequest(BaseModel):
    plan: str
    plan_id: str
    workspace_isolation: Optional[str] = None
    worktree_root: Optional[str] = None


class ReactionRequest(BaseModel):
    entity_id: str
    user_id: str
    reaction_type: str


class CommentRequest(BaseModel):
    entity_id: str
    user_id: str
    body: str
    parent_id: Optional[str] = None


class TelegramConfigRequest(BaseModel):
    bot_token: str
    chat_id: str


class CreatePlanRequest(BaseModel):
    path: str
    title: str = "Untitled"
    content: Optional[str] = None
    working_dir: Optional[str] = None


class SavePlanRequest(BaseModel):
    content: str
    # "manual_save", "ai_refine", "expansion"
    change_source: str = "manual_save"


class RefineRequest(BaseModel):
    message: str
    plan_content: str = ""
    plan_id: str = ""
    model: str = ""
    chat_history: list = Field(default_factory=list)
    working_dir: str = ""  # Target project directory for this plan
    asset_context: List[Dict[str, Any]] = Field(default_factory=list)
    images: List[Dict[str, Any]] = Field(
        default_factory=list
    )  # [{url: "data:image/...;base64,...", name, contentType}]


class UpdatePlanRoleConfigRequest(BaseModel):
    default_model: str | None = None
    temperature: float | None = None
    timeout_seconds: int | None = None
    cli: str | None = None
    skill_refs: List[str] | None = None
    disabled_skills: List[str] | None = None
    system_prompt_override: str | None = None


class StrategyParameter(BaseModel):
    name: str
    label: str
    value: float | int | str | bool
    type: str  # "int", "float", "bool", "string"


class Strategy(BaseModel):
    id: str
    name: str
    description: str
    status: str  # "active", "inactive"
    parameters: List[StrategyParameter]
    last_run: Optional[str] = None


class Skill(BaseModel):
    name: str
    description: str
    tags: List[str] = Field(default_factory=list)
    trust_level: str = "experimental"
    source: str = "project"
    version: str = "0.1.0"
    category: Optional[str] = None
    score: Optional[float] = None
    applicable_roles: List[str] = Field(default_factory=list)
    content: str = ""
    path: Optional[str] = None
    relative_path: Optional[str] = None
    params: List[Dict[str, Any]] = Field(default_factory=list)
    changelog: List[Dict[str, Any]] = Field(default_factory=list)
    author: Optional[str] = None
    updated_at: Optional[str] = None
    forked_from: Optional[str] = None
    is_draft: bool = False
    enabled: bool = True
    active_epics_count: int = 0


class Role(BaseModel):
    id: str
    name: str
    description: str = ""
    instructions: str = ""
    provider: str  # 'Claude', 'GPT', 'Gemini', 'Custom'
    version: str
    temperature: float = 0.7
    budget_tokens_max: int = 500000
    max_retries: int = 3
    timeout_seconds: int = 300
    skill_refs: List[str] = Field(default_factory=list)
    mcp_refs: List[str] = Field(default_factory=list)
    system_prompt_override: Optional[str] = None
    instance_type: str = "worker"  # 'worker' | 'evaluator'
    created_at: str
    updated_at: str


class CreateRoleRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9 \-_]+$")
    description: str = Field("", max_length=500)
    instructions: str = ""
    provider: str
    version: str
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    budget_tokens_max: int = Field(500000, ge=1000, le=10000000)
    max_retries: int = Field(3, ge=1, le=10)
    timeout_seconds: int = Field(300, ge=60)
    skill_refs: List[str] = Field(default_factory=list)
    mcp_refs: List[str] = Field(default_factory=list)
    instance_type: str = "worker"
    system_prompt_override: Optional[str] = Field(None, max_length=2000)


class SkillSearchResponse(BaseModel):
    skills: List[Skill]
    total: int


class SkillInstallRequest(BaseModel):
    path: str


class SkillSearchRequest(BaseModel):
    query: str
    role: Optional[str] = None
    tags: List[str] = []


class SkillSyncResponse(BaseModel):
    synced_count: int
    added: List[str]
    updated: List[str]
    removed: List[str]


class SkillCreateRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=60)
    description: str = Field(..., min_length=10, max_length=500)
    category: str
    applicable_roles: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    content: str = Field(..., min_length=50)
    is_draft: bool = False


class SkillUpdateRequest(BaseModel):
    description: Optional[str] = Field(None, min_length=10, max_length=500)
    category: Optional[str] = None
    applicable_roles: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    content: Optional[str] = None
    is_draft: Optional[bool] = None
    enabled: Optional[bool] = None
    major_bump: bool = False
    change_description: Optional[str] = None


class SkillForkRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=60)


class SkillValidateRequest(BaseModel):
    content: str


class SkillValidateResponse(BaseModel):
    valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    markers: List[Dict[str, Any]] = Field(default_factory=list)


class SkillDuplicateCheckRequest(BaseModel):
    name: str


class SkillDuplicateCheckResponse(BaseModel):
    is_duplicate: bool
    similar_skills: List[str] = Field(default_factory=list)


class ProviderSettings(BaseModel):
    api_key_ref: Optional[str] = None
    base_url: Optional[str] = None
    org_id: Optional[str] = None
    enabled: bool = True
    default_model: Optional[str] = None
    auth_mode: Optional[str] = None  # 'api_key' | 'codex_oauth' (OpenAI only)
    model_variant: Optional[str] = None  # OpenCode --variant for Codex-compatible models
    deployment_mode: Optional[str] = None  # 'gemini' | 'vertex' (Google only)
    project_id: Optional[str] = None  # Vertex AI project ID (Google only)
    vertex_location: Optional[str] = None  # Vertex AI region (Google only, default: global)
    vertex_auth_mode: Optional[str] = None  # 'service_account' | 'oauth' (Vertex only, default: service_account)
    enabled_models: List[str] = Field(
        default_factory=list,
        description=("List of allowed model IDs. If empty, all models from this provider are allowed."),
    )
    dismissed: Optional[bool] = False


class ProvidersNamespace(BaseModel):
    model_config = ConfigDict(extra="allow")

    openai: Optional[ProviderSettings] = None
    anthropic: Optional[ProviderSettings] = None
    google: Optional[ProviderSettings] = None
    byteplus: Optional[ProviderSettings] = None
    openai_compatible: Optional[ProviderSettings] = None
    ollama: Optional[ProviderSettings] = None
    custom: Dict[str, ProviderSettings] = Field(default_factory=dict)


class RoleSettings(BaseModel):
    default_model: Optional[str] = None
    temperature: Optional[float] = None
    timeout_seconds: Optional[int] = None
    max_retries: Optional[int] = None
    budget_tokens_max: Optional[int] = None
    system_prompt_override: Optional[str] = None
    skill_refs: List[str] = Field(default_factory=list)
    disabled_skills: List[str] = Field(default_factory=list)
    instance_type: Optional[str] = None


class RuntimeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    poll_interval_seconds: int = Field(default=5, ge=1, le=300)
    max_concurrent_rooms: int = Field(default=10, ge=1, le=10000)
    max_engineer_retries: int = Field(default=3, ge=0, le=100)
    state_timeout_seconds: int = Field(default=900, ge=1, le=86400)
    auto_approve_tools: bool = False
    dynamic_pipelines: bool = True
    # Master agent default model — format: "provider/model_id" or plain "model_id".
    # Empty string means "use the hardcoded default from master_agent.py".
    master_agent_model: str = ""


class MemorySettings(BaseModel):
    """Memory system settings.

    These fields control the memory system's LLM/embedding backend selection,
    search tuning, pool management, and sync behaviour.

    The ``llm_backend`` / ``embedding_backend`` fields use the same vocabulary
    as the AI gateway (``"ollama"``, ``"openai-compatible"``, ``"gemini"``,
    ``"openai"``, ``"anthropic"``, etc.).  When set to ``"openai-compatible"``,
    the companion ``*_compatible_url`` / ``*_compatible_key`` fields provide
    the endpoint URL and optional API key for the custom server.
    """

    model_config = ConfigDict(extra="allow")

    # -- Vector store --
    vector_backend: str = "zvec"  # zvec | chroma

    # -- Behaviour --
    context_aware: bool = True  # include similar memories in LLM analysis
    context_aware_tree: bool = False  # include directory tree in analysis context
    max_links: int = 3  # max links created per note during evolution

    # -- Search tuning --
    similarity_weight: float = 0.8  # weight for cosine similarity vs time decay
    decay_half_life_days: float = 30.0  # older notes rank lower in search

    # -- Sync --
    auto_sync: bool = True  # periodic disk sync
    sync_interval_s: int = 60  # seconds between syncs
    conflict_resolution: str = "last_modified"

    # -- Pool (HTTP transport) --
    pool_idle_timeout_s: int = 300  # kill slot after N seconds idle
    pool_max_instances: int = 10  # max concurrent memory systems
    pool_eviction_policy: str = "lru"  # lru | oldest | none
    pool_sync_interval_s: int = 60  # per-slot sync interval

    # -- LLM (memory-specific processing model) --
    llm_backend: str = ""  # ollama | openai-compatible | gemini | openai | anthropic | …
    llm_model: str = ""  # e.g. llama3.2, google-vertex/gemini-3-flash-preview (empty = use gateway default)
    llm_compatible_url: str = ""  # API endpoint URL (only used when llm_backend="openai-compatible")
    llm_compatible_key: str = ""  # API key (only used when llm_backend="openai-compatible")

    # -- Embedding (memory-specific, overrides knowledge embedding if set) --
    embedding_backend: str = ""  # ollama | openai-compatible | gemini | … (empty = use knowledge config)
    embedding_model: str = ""  # e.g. gemini-embedding-001 (empty = use knowledge config)
    embedding_compatible_url: str = ""  # API endpoint URL (only used when embedding_backend="openai-compatible")
    embedding_compatible_key: str = ""  # API key (only used when embedding_backend="openai-compatible")

    # -- Legacy aliases (kept for backward compat with existing config.json files) --
    embedding_provider: str = ""  # deprecated alias for embedding_backend


class ChannelPlatformSettings(BaseModel):
    enabled: bool = True
    config: Dict[str, Any] = Field(default_factory=dict)


class ChannelsNamespace(BaseModel):
    telegram: Optional[ChannelPlatformSettings] = None
    slack: Optional[ChannelPlatformSettings] = None
    discord: Optional[ChannelPlatformSettings] = None
    custom: Dict[str, ChannelPlatformSettings] = Field(default_factory=dict)


class AutonomySettings(BaseModel):
    idle_explore_enabled: bool = False
    interval: int = 3600


class ObservabilitySettings(BaseModel):
    log_level: str = "INFO"
    broadcast_verbosity: str = "normal"
    otel_enabled: bool = False


class KnowledgeSettings(BaseModel):
    """Knowledge service runtime settings (ADR-15).

    Overrides the env-var defaults baked into ``dashboard/knowledge/config.py``.
    Resolution precedence is ``MasterSettings.knowledge`` > env var >
    hardcoded default — see :class:`KnowledgeService.__init__`.

    All fields are prefixed with ``knowledge_`` to explicitly declare the
    settings namespace and avoid field-name collisions across namespaces.

    Empty strings mean "no override; use the env-var / hardcoded default".
    ``knowledge_embedding_dimension`` is read-only — fixed at startup from
    ``OSTWIN_EMBEDDING_DIM`` env var.  Changing it dynamically would cause
    dimension conflicts between memory and knowledge vector collections.

    When ``knowledge_llm_backend`` or ``knowledge_embedding_backend`` is set to
    ``"openai-compatible"``, the companion ``*_compatible_url`` / ``*_compatible_key``
    fields provide the endpoint URL and optional API key for the custom server.
    """

    model_config = ConfigDict(extra="allow")

    # -- LLM --
    knowledge_llm_backend: str = ""  # empty = use config.LLM_PROVIDER
    knowledge_llm_model: str = ""  # empty = use config.LLM_MODEL
    knowledge_llm_compatible_url: str = ""  # API endpoint URL (only when backend="openai-compatible")
    knowledge_llm_compatible_key: str = ""  # API key (only when backend="openai-compatible")
    # -- Embedding --
    knowledge_embedding_backend: str = ""  # empty = use config.EMBEDDING_PROVIDER
    knowledge_embedding_model: str = ""  # empty = use config.EMBEDDING_MODEL
    knowledge_embedding_compatible_url: str = ""  # API endpoint URL (only when backend="openai-compatible")
    knowledge_embedding_compatible_key: str = ""  # API key (only when backend="openai-compatible")
    knowledge_embedding_dimension: int = 1024  # read-only: reflects OSTWIN_EMBEDDING_DIM

    def model_post_init(self, __context) -> None:
        """Override embedding dimension with the fixed env-var value."""
        from dashboard.llm_client import DEFAULT_EMBEDDING_DIMENSION

        self.knowledge_embedding_dimension = DEFAULT_EMBEDDING_DIMENSION


class AISettings(BaseModel):
    """AI gateway settings — per-purpose model overrides."""

    completion_model: str = ""
    knowledge_model: str = ""
    memory_model: str = ""
    cloud_embedding_model: str = ""
    local_embedding_model: str = ""
    timeout_seconds: int = 120
    max_retries: int = 2


class MasterSettings(BaseModel):
    providers: ProvidersNamespace = Field(default_factory=ProvidersNamespace)
    roles: Dict[str, RoleSettings] = Field(default_factory=dict)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    channels: ChannelsNamespace = Field(default_factory=ChannelsNamespace)
    autonomy: AutonomySettings = Field(default_factory=AutonomySettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    knowledge: KnowledgeSettings = Field(default_factory=KnowledgeSettings)
    ai: AISettings = Field(default_factory=AISettings)


class EffectiveResolution(BaseModel):
    effective: Dict[str, Any]
    provenance: Dict[str, str]
