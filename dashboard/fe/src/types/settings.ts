export type GoogleDeploymentMode = 'gemini' | 'vertex';
export type VertexAuthMode = 'service_account' | 'oauth';
export type ProviderAuthMode = 'api_key' | 'codex_oauth' | 'copilot_oauth' | string;

export type ModelSource = 'models.dev' | 'custom';

export interface ModelInfo {
  id: string;
  label?: string;
  context_window?: string;
  tier?: string;
  mode?: string;  // 'gemini' | 'vertex' for Google models
  provider_id?: string;
  family?: string;
  cost?: { input?: number; output?: number; cache_read?: number; cache_write?: number };
  logo_url?: string;
  reasoning?: boolean;
  tool_call?: boolean;
  attachment?: boolean;
  source?: ModelSource;
}

/** A model entry from the configured models catalog (models.dev or custom) */
export interface ConfiguredModel {
  id: string;
  name: string;
  family: string;
  reasoning: boolean;
  tool_call: boolean;
  attachment: boolean;
  temperature: boolean;
  cost: { input?: number; output?: number; cache_read?: number; cache_write?: number };
  limit: { context?: number; output?: number };
  modalities: { input?: string[]; output?: string[] };
  knowledge: string;
  release_date: string;
  source?: ModelSource;
  /** Set for Google companion models (google-vertex, google-vertex-anthropic).
   *  When present the modelId storage key already contains the companion prefix. */
  companion_provider?: string;
}

/** A provider entry from the configured models catalog */
export interface ConfiguredProvider {
  id: string;
  name: string;
  doc: string;
  api: string;
  npm: string;
  env: string[];
  logo_url: string;
  source: string;
  models: Record<string, ConfiguredModel>;
  /** Allow arbitrary additional fields (makes this structurally compatible
   *  with the ModelSelect providers prop index signature). */
  [key: string]: unknown;
}

/** The full configured_models.json structure */
export interface ConfiguredModelsResponse {
  loaded_at: string;
  source: string;
  configured_provider_ids: string[];
  providers: Record<string, ConfiguredProvider>;
}

/** Provider summary from /api/models/providers */
export interface ProviderSummary {
  id: string;
  name: string;
  logo_url: string;
  model_count: number;
  source: string;
  has_key: boolean;
  doc: string;
}

export interface ProviderSettings {
  api_key_ref?: string;
  base_url?: string;
  org_id?: string;
  enabled: boolean;
  default_model?: string;
  auth_mode?: ProviderAuthMode;
  model_variant?: string;                     // OpenCode --variant for Codex-compatible models
  deployment_mode?: GoogleDeploymentMode;  // Google only
  project_id?: string;                     // Google Vertex only
  vertex_location?: string;                // Google Vertex region (default: global)
  vertex_auth_mode?: VertexAuthMode;       // 'service_account' | 'oauth' (Vertex only)
  enabled_models?: string[];               // empty = all models enabled
  dismissed?: boolean;                     // true if removed from UI
}

export interface ProvidersNamespace {
  openai?: ProviderSettings;
  anthropic?: ProviderSettings;
  google?: ProviderSettings;
  byteplus?: ProviderSettings;
  [key: string]: ProviderSettings | undefined;
}

export interface RoleSettings {
  default_model?: string;
  temperature?: number;
  timeout_seconds?: number;
  max_retries?: number;
  budget_tokens_max?: number;
  system_prompt_override?: string;
  skill_refs?: string[];
  disabled_skills?: string[];
}

export interface RuntimeSettings {
  poll_interval_seconds: number;
  max_concurrent_rooms: number;
  max_engineer_retries: number;
  state_timeout_seconds: number;
  auto_approve_tools: boolean;
  dynamic_pipelines: boolean;
  /** Master agent default model — format: "provider/model_id". Empty = use server default. */
  master_agent_model?: string;
}

export interface AutonomySettings {
  idle_explore_enabled: boolean;
  interval: number;
}

export type MemoryLLMBackend = 'gemini' | 'openai' | 'ollama' | 'openrouter' | 'sglang' | 'openai-compatible';
export type MemoryEmbeddingBackend = 'gemini' | 'ollama' | 'vertex' | 'openai-compatible';
export type MemoryVectorBackend = 'zvec' | 'chroma';

export interface MemorySettings {
  // Vector store
  vector_backend?: MemoryVectorBackend;
  // Behaviour
  context_aware?: boolean;
  context_aware_tree?: boolean;
  max_links?: number;
  // Search tuning
  similarity_weight?: number;
  decay_half_life_days?: number;
  // Sync
  auto_sync?: boolean;
  sync_interval_s?: number;
  conflict_resolution?: string;
  // Pool (HTTP transport)
  pool_idle_timeout_s?: number;
  pool_max_instances?: number;
  pool_eviction_policy?: string;
  pool_sync_interval_s?: number;
  // LLM (memory-specific processing model)
  llm_backend?: MemoryLLMBackend | '';
  llm_model?: string;
  llm_compatible_url?: string;
  llm_compatible_key?: string;
  // Embedding (memory-specific, overrides knowledge embedding if set)
  embedding_backend?: MemoryEmbeddingBackend | '';
  embedding_model?: string;
  embedding_compatible_url?: string;
  embedding_compatible_key?: string;
  [key: string]: unknown;
}

export interface ChannelPlatformSettings {
  enabled: boolean;
  config?: Record<string, unknown>;
}

export interface ChannelsNamespace {
  telegram?: ChannelPlatformSettings;
  slack?: ChannelPlatformSettings;
  discord?: ChannelPlatformSettings;
  [key: string]: ChannelPlatformSettings | undefined;
}

export interface ObservabilitySettings {
  log_level: 'debug' | 'info' | 'warning' | 'error';
  broadcast_verbosity: 'minimal' | 'normal' | 'verbose';
  trace_enabled: boolean;
}

export interface KnowledgeSettings {
  /** Empty string means "use server default". */
  knowledge_llm_backend: string;
  /** Empty string means "use server default (config.LLM_MODEL / env var)". */
  knowledge_llm_model: string;
  /** OpenAI-compatible LLM config */
  knowledge_llm_compatible_url?: string;
  knowledge_llm_compatible_key?: string;
  /** Empty string means "use server default". */
  knowledge_embedding_backend: MemoryEmbeddingBackend | '';
  /** Empty string means "use server default (config.EMBEDDING_MODEL / env var)". */
  knowledge_embedding_model: string;
  /** OpenAI-compatible embedding config */
  knowledge_embedding_compatible_url?: string;
  knowledge_embedding_compatible_key?: string;
  /** Reflects OSTWIN_EMBEDDING_DIMENSION env var. Read-only in UI. */
  knowledge_embedding_dimension: number;
}

export interface MasterSettings {
  providers: ProvidersNamespace;
  roles: Record<string, RoleSettings>;
  runtime: RuntimeSettings;
  autonomy: AutonomySettings;
  memory: MemorySettings;
  channels: ChannelsNamespace;
  observability: ObservabilitySettings;
  knowledge?: KnowledgeSettings;
}

export interface EffectiveResolution {
  effective: Record<string, Record<string, unknown>>;
  provenance: Record<string, string>;
}

export type SettingsNamespace = 'providers' | 'runtime' | 'memory' | 'knowledge' | 'channels' | 'ai-monitor';

export interface VaultStatus {
  is_set: boolean;
}

export type VaultBackendType =
  | 'auto'
  | 'keychain'
  | 'encrypted_file'
  | 'env'
  | 'hashicorp'
  | 'gcp_secret_mgr';

export interface VaultInfo {
  backend: VaultBackendType;
  healthy: boolean;
  message: string;
  details: Record<string, string>;
}

export interface ProviderTestResult {
  status: 'ok' | 'fail';
  latency_ms: number;
  error?: string;
}

export interface OpenCodeSyncResult {
  synced: string[];
  removed: string[];
  skipped: string[];
  path: string;
  error?: string;
}
