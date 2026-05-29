// ──────────────────────────────────────────────────
// Plan
// ──────────────────────────────────────────────────
export interface Plan {
  plan_id: string;
  title: string;
  goal?: string;
  status?: PlanStatus;
  domain?: Domain;
  epic_count?: number;
  active_epics?: number;
  completed_epics?: number;
  pct_complete?: number;
  critical_path?: { completed: number; total: number };
  escalations?: number;
  roles?: RoleSummary[];
  role_distribution?: Record<string, number>;
  created_at?: string;
  updated_at?: string;
  working_dir?: string;
  // Idea thread that generated this plan (set at promotion time)
  thread_id?: string;
  // Backend-only fields
  content?: string;
  filename?: string;
  meta?: Record<string, unknown>;
}

export type PlanStatus = 'active' | 'draft' | 'completed' | 'archived';
export type Domain = 'software' | 'data' | 'audit' | 'compliance' | 'custom';

// ──────────────────────────────────────────────────
// Epic
// ──────────────────────────────────────────────────
export interface Epic {
  epic_ref: string;
  plan_id: string;
  title: string;
  objective?: string;
  status?: EpicStatus;
  lifecycle_state?: string;
  role?: string;
  tasks?: Task[];
  depends_on?: string[];
  dependents?: string[];
  definition_of_done?: DoDItem[];
  acceptance_criteria?: ACItem[];
  progress?: number;
  retries?: number;
  max_retries?: number;
  timeout_seconds?: number;
  budget_tokens?: { used: number; max: number };
  room_id?: string;
  created_at?: string;
  started_at?: string;
  last_state_change?: string;
  // Backend-only fields  
  body?: string;
  working_dir?: string;
}

// ──────────────────────────────────────────────────
// Plan Asset
// ──────────────────────────────────────────────────
export interface PlanAsset {
  plan_id?: string;
  filename: string;
  original_name: string;
  mime_type: string;
  uploaded_at: string;
  size_bytes?: number;
  path?: string;
  bound_epics?: string[];
  asset_type?: string;
  tags?: string[];
  description?: string;
  binding?: 'plan' | 'epic';
}

export type EpicStatus =
  // V2 lifecycle states (from Resolve-Pipeline.ps1)
  | 'pending' | 'developing' | 'optimize' | 'review'
  | 'triage' | 'failed' | 'passed' | 'failed-final'
  // Bucket for dynamic {role}-review states
  | 'in-review'
  // Legacy aliases (backward compat)
  | 'engineering' | 'review' | 'fixing'
  | 'manager-triage' | 'signoff';

// ──────────────────────────────────────────────────
// Task
// ──────────────────────────────────────────────────
export interface Task {
  task_id: string;
  description: string;
  completed: boolean;
  assigned_role: string;
  status: 'pending' | 'in-progress' | 'done' | 'blocked';
  completed_at?: string;
  completed_by?: string;
}

// ──────────────────────────────────────────────────
// DoD & Acceptance Criteria
// ──────────────────────────────────────────────────
export interface DoDItem {
  id: string;
  text: string;
  verified: boolean;
  verified_by?: string;
  verified_at?: string;
}

export interface ACItem {
  id: string;
  text: string;
  status: 'not-evaluated' | 'pass' | 'fail';
  evaluated_by?: string;
  evaluated_at?: string;
  notes?: string;
}

// ──────────────────────────────────────────────────
// Lifecycle
// ──────────────────────────────────────────────────
export interface LifecycleState {
  name: string;
  type: 'agent' | 'builtin';
  role: string;
  transitions: Record<string, string>;
}

export interface Lifecycle {
  initial_state: string;
  states: Record<string, LifecycleState>;
}

// ──────────────────────────────────────────────────
// Channel Message
// ──────────────────────────────────────────────────
export interface ChannelMessage {
  id: string;
  ts: string;
  from: string;
  to: string;
  type: MessageType;
  ref: string;
  body: string;
  lifecycle_state?: string;
}

export type MessageType =
  | 'task' | 'design-guidance' | 'qa-result' | 'escalate'
  | 'plan-approve' | 'plan-reject' | 'done' | 'fix' | 'error';

// ──────────────────────────────────────────────────
// Role & Skill
// ──────────────────────────────────────────────────
export interface Role {
  id: string;
  name: string;
  provider: 'claude' | 'gpt' | 'gemini' | 'custom';
  version: string;
  temperature: number;
  budget_tokens_max: number;
  max_retries: number;
  timeout_seconds: number;
  skill_refs: string[];
  mcp_refs?: string[];
  instance_type: 'worker' | 'evaluator';
  description?: string;
  instructions?: string;
  system_prompt_override?: string;
}

export interface Skill {
  id?: string;
  name: string;
  version: string;
  description: string;
  category: SkillCategory;
  tags?: string[];
  trust_level?: 'experimental' | 'verified' | 'core';
  source?: 'project' | 'user' | 'local';
  applicable_roles: string[];
  usage_count: number;
  instruction_template?: string;
  content?: string;
  is_draft?: boolean;
  author?: string;
  updated_at?: string;
  forked_from?: string;
  score?: number;
  enabled?: boolean;
  changelog?: Array<{ version: string; date: number; changes: string }>;
  active_epics_count?: number;
}

export type SkillCategory =
  | 'implementation' | 'review' | 'testing' | 'writing'
  | 'analysis' | 'compliance' | 'triage';

// ──────────────────────────────────────────────────
// Role Summary (for plan cards)
// ──────────────────────────────────────────────────
export interface RoleSummary {
  name: string;
  initials: string;
  color: string;
}

// ──────────────────────────────────────────────────
// Dashboard Stats
// ──────────────────────────────────────────────────
export interface DashboardStats {
  total_plans: { value: number; trend: Trend };
  active_epics: { value: number; trend: Trend };
  completion_rate: { value: number; trend: Trend };
  escalations: { value: number; trend: Trend };
}

export interface Trend {
  direction: 'up' | 'down' | 'flat';
  delta: number;
}

// ──────────────────────────────────────────────────
// Notification
// ──────────────────────────────────────────────────
export interface Notification {
  id: string;
  ts: string;
  type: 'escalation' | 'completion' | 'failure' | 'info';
  title: string;
  body: string;
  plan_name?: string;
  epic_ref?: string;
  read: boolean;
}

// ──────────────────────────────────────────────────
// DAG (raw shape from /api/plans/{id}/dag)
// ──────────────────────────────────────────────────
export interface DAGNodeRaw {
  room_id: string;
  role: string;
  candidate_roles: string[];
  depends_on: string | string[] | null;
  dependents: string[];
  depth: number;
  on_critical_path: boolean;
}

export interface DAG {
  generated_at: string;
  total_nodes: number;
  max_depth: number;
  nodes: Record<string, DAGNodeRaw>;
  topological_order: string[];
  critical_path: string[];
  critical_path_length: number;
  waves: Record<string, string[]>;
}

// Derived types used internally by DAGViewer for rendering
export interface DAGNode {
  id: string;
  label: string;
  status: EpicStatus;
  x: number;
  y: number;
}

export interface DAGEdge {
  from: string;
  to: string;
  is_critical?: boolean;
}

// ──────────────────────────────────────────────────
// War Room Progress (progress.json)
// ──────────────────────────────────────────────────
export interface WarRoomRoomEntry {
  room_id: string;
  task_ref: string;
  status: string; // 'passed' | 'failed-final' | 'active' | 'pending' | 'blocked'
}

export interface WarRoomProgress {
  updated_at: string;
  total: number;
  passed: number;
  failed: number;
  blocked: number;
  active: number;
  pending: number;
  pct_complete: number;
  critical_path: string | { completed: number; total: number }; // Can be "7/8" or object
  rooms: WarRoomRoomEntry[];
}

// ──────────────────────────────────────────────────
// Audit Log Entry (parsed from audit.log)
// ──────────────────────────────────────────────────
export interface AuditLogEntry {
  timestamp: string;
  type: string; // e.g. 'STATUS'
  from_state: string;
  to_state: string;
}

// ──────────────────────────────────────────────────
// Agent Instance (e.g. architect_001.json)
// ──────────────────────────────────────────────────
export interface AgentInstance {
  role: string;
  instance_id: string;
  instance_type: string;
  display_name: string;
  model: string;
  assigned_at: string;
  status: string; // 'completed' | 'running' | 'failed'
  config_override: Record<string, unknown>;
}

// ──────────────────────────────────────────────────
// Files & Git
// ──────────────────────────────────────────────────

export interface FileEntry {
  name: string;
  type: 'file' | 'directory';
  size?: number;
  extension?: string;
  children_count?: number;
}

export interface FileTreeNode {
  name: string;
  type: 'file' | 'directory';
  path: string;
  size?: number;
  extension?: string;
  children_count?: number;
  children?: FileTreeNode[];
}

export interface FileContentResponse {
  path: string;
  content: string | null;
  encoding: 'utf-8' | 'base64' | null;
  size: number;
  mime_type: string;
  truncated: boolean;
  download_url: string;
}

export interface GitFileChange {
  path: string;
  status: string; // e.g. "M", "A", "??"
}

export interface GitCommitSummary {
  hash: string;
  author: string;
  timestamp: number;
  subject: string;
}

export interface FileChanges {
  git_enabled: boolean;
  status: string[]; // git status --porcelain raw lines
  recent_commits: GitCommitSummary[];
  error?: string;
}

// ──────────────────────────────────────────────────
// War Room Config (config.json)
// ──────────────────────────────────────────────────
export interface WarRoomConfig {
  room_id: string;
  task_ref: string;
  plan_id: string;
  depends_on: string[];
  created_at: string;
  working_dir: string;
  assignment: {
    title: string;
    description: string;
    assigned_role: string;
    candidate_roles: string[];
    type: string;
  };
  goals: {
    definition_of_done: string[];
    acceptance_criteria: string[];
    quality_requirements: {
      test_coverage_min: number;
      lint_clean: boolean;
      security_scan_pass: boolean;
    };
  };
  constraints: {
    max_retries: number;
    timeout_seconds: number;
    budget_tokens_max: number;
  };
  status: {
    current: string;
    retries: number;
    started_at: string | null;
    last_state_change: string;
  };
  skill_refs: string[];
}

// ──────────────────────────────────────────────────
// Plan Version
// ──────────────────────────────────────────────────
export interface PlanVersion {
  id: string;
  plan_id: string;
  version: number;
  title: string;
  epic_count: number;
  created_at: string;
  change_source: string;
  content?: string;
}

// ──────────────────────────────────────────────────
// Change Event (Unified History)
// ──────────────────────────────────────────────────
export interface ChangeEvent {
  id: string;
  plan_id: string;
  timestamp: string;
  type: 'plan_version' | 'asset_change';
  source: 'zvec' | 'git' | 'file_watcher';

  // For plan_version
  version?: number;
  title?: string;
  change_source?: string;

  // For asset_change (git/file)
  change_type?: string;
  file_path?: string;
  diff_summary?: string;
  author?: string;
  message?: string;
  files?: string[];
  is_uncommitted?: boolean;
}

// ──────────────────────────────────────────────────
// Model
// ──────────────────────────────────────────────────
export interface Model {
  id: string;
  name: string;
  provider: 'claude' | 'gpt' | 'gemini' | 'custom';
  context_window: number;
  cost_per_1m_tokens: number;
}

// ──────────────────────────────────────────────────
// Planning Thread & Message (Ideas / Brainstorming)
// ──────────────────────────────────────────────────
export interface PlanningThread {
  id: string;
  title: string | null;
  status: 'active' | 'promoted' | 'archived';
  plan_id: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ImageAttachment {
  url: string;
  name: string;
  type: string;
}

export interface PlanningMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  images?: ImageAttachment[];
}

// ──────────────────────────────────────────────────
// Settings (EPIC-004)
// ──────────────────────────────────────────────────
export * from './settings';

