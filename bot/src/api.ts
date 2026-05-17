/**
 * api.ts — Dashboard API client shared by both bots.
 *
 * All bot commands fetch data from the Python dashboard via these helpers.
 */

import config from './config';

// ── Types ─────────────────────────────────────────────────────────

export interface Plan {
  plan_id: string;
  title?: string;
  status?: string;
  epic_count?: number;
  pct_complete?: number;
  content?: string;
}

export interface PlanEpic {
  room_id: string;
  task_ref: string;
  title: string;
  body?: string;
  working_dir?: string;
}

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

export interface Room {
  room_id: string;
  status: string;
  message_count: number;
  epic_ref?: string;
}

export interface RoomMessage {
  from?: string;
  body?: string;
  type?: string;
  room_id?: string;
}

export interface RoomsSummary {
  total?: number;
  passed?: number;
  failed_final?: number;
  pending?: number;
  developing?: number;
  review?: number;
  fixing?: number;
  // Legacy aliases — older deployments report these names; kept so we sum both.
  engineering?: number;
  qa_review?: number;
}

export interface StatsValue {
  value: number;
}

export interface Stats {
  total_plans?: StatsValue;
  active_epics?: StatsValue;
  completion_rate?: StatsValue;
  escalations_pending?: StatsValue;
  _error?: string;
}

export interface Skill {
  name: string;
  tags?: string[];
  description?: string;
  category?: string;
}

export interface ChannelStatus {
  platform: string;
  status: string;
  config?: any;
  health?: { status: string; message?: string };
}

export interface RoleInfo {
  id?: string;
  name: string;
  description?: string;
  version?: string;
  default_model?: string;
}

export interface HealthResult {
  manager: { running: boolean; pid: number | null };
  bot: { running: boolean; pid: number | null; available: boolean };
  config: any;
  error?: string;
}

export interface ClawhubSkill {
  name: string;
  slug: string;
  description?: string;
  author?: string;
  downloads?: number;
  version?: string;
}

export interface PlansResult {
  plans: Plan[];
  count?: number;
  error?: string;
}

export interface RoomsResult {
  rooms: Room[];
  summary: RoomsSummary;
  error?: string;
}

export interface RefineResult {
  plan?: string;
  refined_plan?: string;
  explanation?: string;
  raw_result?: {
    plan_id?: string;
    full_response?: string;
  };
  _error?: string;
}

export interface CreateResult {
  plan_id?: string;
  _error?: string;
}

export interface PlanAssetsResult {
  plan_id?: string;
  assets: PlanAsset[];
  count?: number;
  error?: string;
}

// ── Helpers ───────────────────────────────────────────────────────

function getHeaders(contentType: string | null = 'application/json'): Record<string, string> {
  const h: Record<string, string> = {};
  if (contentType) h['Content-Type'] = contentType;
  if (config.OSTWIN_API_KEY) h['X-API-Key'] = config.OSTWIN_API_KEY;
  return h;
}

export async function fetchBinary(path: string): Promise<Buffer | null> {
  try {
    const res = await fetch(`${config.DASHBOARD_URL}${path}`, {
      headers: getHeaders(null),
    });
    if (!res.ok) return null;
    const arrayBuf = await res.arrayBuffer();
    return Buffer.from(arrayBuf);
  } catch {
    return null;
  }
}

export async function fetchJSON(path: string, options: RequestInit = {}): Promise<any> {
  try {
    const { headers: customHeaders, ...restOptions } = options;
    const res = await fetch(`${config.DASHBOARD_URL}${path}`, {
      ...restOptions,
      headers: customHeaders
        ? { ...getHeaders(null), ...(customHeaders as Record<string, string>) }
        : getHeaders(),
    });
    if (!res.ok) {
      console.warn(`[API] ${path} returned ${res.status}`);
      return { _error: `API returned ${res.status}` };
    }
    const ct = res.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      console.warn(`[API] ${path} returned non-JSON content-type: ${ct}`);
      return { _error: `API returned non-JSON response` };
    }
    return await res.json();
  } catch (err: any) {
    console.warn(`[API] Failed to fetch ${path}: ${err.message}`);
    return { _error: `Dashboard unreachable: ${err.message}` };
  }
}

async function postJSON(path: string, body: unknown): Promise<any> {
  return fetchJSON(path, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

// ── Tunnel / base URL ────────────────────────────────────────────

async function getTunnelStatus(): Promise<{ active: boolean; url: string | null }> {
  const data = await fetchJSON('/api/tunnel/status');
  if (data?._error) return { active: false, url: null };
  return { active: !!data.active, url: data.url || null };
}

export async function getBaseUrl(): Promise<string> {
  const { active, url } = await getTunnelStatus();
  if (active && url) return url.replace(/\/+$/, '');
  return config.DASHBOARD_URL.replace(/\/+$/, '');
}

// ── Plans ─────────────────────────────────────────────────────────

export async function getPlans(): Promise<PlansResult> {
  const data = await fetchJSON('/api/plans');
  if (data?._error) return { error: data._error, plans: [] };
  return { plans: data.plans || [], count: data.count || 0 };
}

export async function getPlan(planId: string): Promise<any> {
  return fetchJSON(`/api/plans/${planId}`);
}

export async function getPlanEpics(planId: string): Promise<{ epics: PlanEpic[]; count: number; error?: string }> {
  const data = await fetchJSON(`/api/plans/${planId}/epics`);
  if (data?._error) return { error: data._error, epics: [], count: 0 };
  return { epics: data.epics || [], count: data.count || 0 };
}

export async function refinePlan(params: {
  message: string;
  planContent?: string;
  planId?: string;
  chatHistory?: Array<{ role: string; content: string }>;
  workingDir?: string;
  assetContext?: PlanAsset[];
  images?: Array<{ url: string; name?: string; contentType?: string }>;
}): Promise<RefineResult> {
  return postJSON('/api/plans/refine', {
    message: params.message,
    plan_content: params.planContent || '',
    plan_id: params.planId || '',
    chat_history: params.chatHistory || [],
    working_dir: params.workingDir || '',
    asset_context: params.assetContext || [],
    images: params.images || [],
  });
}

export async function createPlan(params: {
  title: string;
  content: string;
  workingDir?: string;
}): Promise<CreateResult> {
  return postJSON('/api/plans/create', {
    path: params.workingDir || '.',
    title: params.title,
    content: params.content,
    working_dir: params.workingDir,
  });
}

export async function savePlan(planId: string, content: string): Promise<any> {
  return postJSON(`/api/plans/${planId}/save`, {
    content,
    change_source: 'bot',
  });
}

export async function getPlanAssets(planId: string): Promise<PlanAssetsResult> {
  const data = await fetchJSON(`/api/plans/${planId}/assets`);
  if (data?._error) return { error: data._error, assets: [] };
  return {
    plan_id: data.plan_id,
    assets: data.assets || [],
    count: data.count || 0,
  };
}

export async function uploadPlanAssets(
  planId: string,
  files: Array<{ name: string; contentType?: string; data: ArrayBuffer | Uint8Array }>,
  metadata?: { epicRef?: string; assetType?: string; tags?: string[] },
): Promise<PlanAssetsResult> {
  const form = new FormData();
  for (const file of files) {
    const bytes = file.data instanceof Uint8Array ? file.data : new Uint8Array(file.data);
    const arrayBuffer = new ArrayBuffer(bytes.byteLength);
    new Uint8Array(arrayBuffer).set(bytes);
    const blob = new Blob([arrayBuffer], { type: file.contentType || 'application/octet-stream' });
    form.append('files', blob, file.name);
  }

  // FIX-4: Forward epic/type/tags metadata so assets land on the right epic
  if (metadata?.epicRef) form.append('epic_ref', metadata.epicRef);
  if (metadata?.assetType) form.append('asset_type', metadata.assetType);
  if (metadata?.tags?.length) form.append('tags', metadata.tags.join(','));

  const data = await fetchJSON(`/api/plans/${planId}/assets`, {
    method: 'POST',
    headers: getHeaders(null),
    body: form,
  });
  if (data?._error) return { error: data._error, assets: [] };
  return {
    plan_id: data.plan_id,
    assets: data.assets || [],
    count: data.count || 0,
  };
}

// ── EPIC-002/003: Asset management endpoints ────────────────────

export async function bindAsset(
  planId: string, filename: string, epicRef: string
): Promise<any> {
  return postJSON(`/api/plans/${planId}/assets/${encodeURIComponent(filename)}/bind`, { epic_ref: epicRef });
}

export async function unbindAsset(
  planId: string, filename: string, epicRef: string
): Promise<any> {
  return fetchJSON(`/api/plans/${planId}/assets/${encodeURIComponent(filename)}/bind/${epicRef}`, { method: 'DELETE' });
}

export async function getEpicAssets(planId: string, epicRef: string): Promise<PlanAssetsResult> {
  const data = await fetchJSON(`/api/plans/${planId}/epics/${epicRef}/assets`);
  if (data?._error) return { error: data._error, assets: [] };
  return { plan_id: data.plan_id, assets: data.assets || [], count: data.count || 0 };
}

export async function updateAssetMetadata(
  planId: string, filename: string, updates: { asset_type?: string; tags?: string[]; description?: string }
): Promise<any> {
  return fetchJSON(`/api/plans/${planId}/assets/${encodeURIComponent(filename)}`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
  });
}

export async function generatePlanFromAssets(planId: string): Promise<any> {
  return postJSON(`/api/plans/${planId}/generate-from-assets`, {});
}

export async function launchPlan(planId: string, planContent: string): Promise<any> {
  return postJSON('/api/run', {
    plan: planContent,
    plan_id: planId,
  });
}

// ── Rooms ─────────────────────────────────────────────────────────

export async function getRooms(): Promise<RoomsResult> {
  const data = await fetchJSON('/api/rooms');
  if (data?._error) return { error: data._error, rooms: [], summary: {} };
  return { rooms: data.rooms || [], summary: data.summary || {} };
}

export async function getRoomChannel(roomId: string, limit = 1): Promise<any> {
  return fetchJSON(`/api/rooms/${roomId}/channel?limit=${limit}`);
}

// ── Stats & Search ────────────────────────────────────────────────

export async function getStats(): Promise<Stats> {
  return fetchJSON('/api/stats');
}

export async function getSkills(): Promise<Skill[]> {
  const data = await fetchJSON('/api/skills');
  if (data?._error) return [];
  return Array.isArray(data) ? data : [];
}

export async function semanticSearch(query: string, limit = 5): Promise<any> {
  return fetchJSON(`/api/search?q=${encodeURIComponent(query)}&limit=${limit}`);
}

export async function stopDashboard(): Promise<any> {
  return postJSON('/api/stop', {});
}

export async function shellCommand(command: string): Promise<any> {
  return postJSON('/api/shell', command);
}

export async function postComment(entityId: string, userId: string, body: string, parentId?: string): Promise<any> {
  return postJSON('/api/engagement/comments', {
    entity_id: entityId,
    user_id: userId,
    body,
    parent_id: parentId,
  });
}

export async function getEngagement(entityId: string): Promise<any> {
  return fetchJSON(`/api/engagement/${entityId}`);
}

// ── Resume / Re-launch ───────────────────────────────────────────

export async function resumePlan(planId: string, planContent: string): Promise<any> {
  return postJSON('/api/run', {
    plan: planContent,
    plan_id: planId,
    resume: true,
  });
}

// ── Room actions ─────────────────────────────────────────────────

export async function roomAction(roomId: string, action: string): Promise<any> {
  return postJSON(`/api/rooms/${roomId}/action?action=${encodeURIComponent(action)}`, {});
}

// ── Health & System ──────────────────────────────────────────────

export async function getManagerStatus(): Promise<any> {
  return fetchJSON('/api/status');
}

export async function getBotStatus(): Promise<any> {
  return fetchJSON('/api/bot/status');
}

export async function getConfig(): Promise<any> {
  return fetchJSON('/api/config');
}

export async function getSettings(): Promise<any> {
  return fetchJSON('/api/settings');
}

export async function updateSettings(namespace: string, settings: Record<string, unknown>): Promise<any> {
  return fetchJSON(`/api/settings/${namespace}`, {
    method: 'PUT',
    body: JSON.stringify(settings),
  });
}

// ── Channels ─────────────────────────────────────────────────────

export async function getChannels(): Promise<ChannelStatus[]> {
  const data = await fetchJSON('/api/channels');
  if (data?._error) return [];
  return Array.isArray(data) ? data : [];
}

export async function getChannel(platform: string): Promise<any> {
  return fetchJSON(`/api/channels/${platform}`);
}

export async function testChannel(platform: string): Promise<any> {
  return postJSON(`/api/channels/${platform}/test`, {});
}

export async function connectChannel(platform: string, credentials?: any): Promise<any> {
  return postJSON(`/api/channels/${platform}/connect`, credentials ? { credentials } : {});
}

export async function disconnectChannel(platform: string): Promise<any> {
  return postJSON(`/api/channels/${platform}/disconnect`, {});
}

export async function getChannelPairing(platform: string): Promise<any> {
  return fetchJSON(`/api/channels/${platform}/pairing`);
}

export async function regenerateChannelPairing(platform: string): Promise<any> {
  return postJSON(`/api/channels/${platform}/pairing/regenerate`, {});
}

// ── Skills (extended) ────────────────────────────────────────────

export async function searchSkillsClawhub(query: string, limit = 25): Promise<ClawhubSkill[]> {
  const data = await fetchJSON(`/api/skills/clawhub-search?q=${encodeURIComponent(query)}&limit=${limit}`);
  if (data?._error) return [];
  return Array.isArray(data) ? data : [];
}

export async function installSkillClawhub(skillName: string): Promise<any> {
  return fetchJSON('/api/skills/clawhub-install', {
    method: 'POST',
    headers: { ...getHeaders(), 'X-Confirm-Install': 'true' },
    body: JSON.stringify({ skill_name: skillName }),
  });
}

export async function removeSkill(name: string, force = false): Promise<any> {
  return fetchJSON(`/api/skills/${encodeURIComponent(name)}?force=${force}`, { method: 'DELETE' });
}

export async function syncSkills(): Promise<any> {
  return postJSON('/api/skills/sync', {});
}

// ── Roles ────────────────────────────────────────────────────────

export async function getRoles(): Promise<RoleInfo[]> {
  const data = await fetchJSON('/api/roles');
  if (data?._error) return [];
  return Array.isArray(data) ? data : [];
}

// ── OpenCode Chat (session-backed, full memory) ──────────────────

export interface ToolAction {
  type: string;
  plan_id?: string;
  room_id?: string;
}

export interface ChatResponse {
  text: string;
  conversation_id: string;
  actions?: ToolAction[];
  attachments?: Array<{ name: string; data?: string; type?: string }>;
}

export async function askOpenCode(params: {
  message: string;
  conversation_id?: string;
  user_id?: string;
  platform?: string;
  working_dir?: string;
  attachments?: Array<{ name: string; contentType?: string }>;
  images?: Array<{ url: string; name: string; contentType: string }>;
  referenced_message_content?: string;
}): Promise<ChatResponse> {
  return fetchJSON('/api/chat', {
    method: 'POST',
    body: JSON.stringify({
      message: params.message,
      conversation_id: params.conversation_id,
      user_id: params.user_id || 'unknown',
      platform: params.platform || 'unknown',
      working_dir: params.working_dir,
      attachments: params.attachments,
      images: params.images,
      referenced_message_content: params.referenced_message_content,
    }),
  });
}

export async function askOpenCodeCommand(params: {
  command: string;
  arguments?: string;
  conversation_id?: string;
  user_id?: string;
  platform?: string;
  agent?: string;
}): Promise<ChatResponse> {
  return fetchJSON('/api/chat/command', {
    method: 'POST',
    body: JSON.stringify({
      command: params.command,
      arguments: params.arguments || '',
      conversation_id: params.conversation_id,
      user_id: params.user_id || 'unknown',
      platform: params.platform || 'unknown',
      agent: params.agent || 'ostwin',
    }),
  });
}

export async function endConversation(conversationId: string): Promise<void> {
  await fetchJSON(`/api/chat/${encodeURIComponent(conversationId)}`, {
    method: 'DELETE',
  });
}

// Default export as a mutable object for testability (sinon stubs)
const api = {
  getBaseUrl,
  getPlans,
  getPlan,
  getPlanEpics,
  refinePlan,
  createPlan,
  savePlan,
  getPlanAssets,
  uploadPlanAssets,
  bindAsset,
  unbindAsset,
  getEpicAssets,
  updateAssetMetadata,
  generatePlanFromAssets,
  launchPlan,
  resumePlan,
  roomAction,
  getRooms,
  getRoomChannel,
  getStats,
  getSkills,
  searchSkillsClawhub,
  installSkillClawhub,
  removeSkill,
  syncSkills,
  getRoles,
  getManagerStatus,
  getBotStatus,
  getConfig,
  getSettings,
  updateSettings,
  getChannels,
  getChannel,
  testChannel,
  connectChannel,
  disconnectChannel,
  getChannelPairing,
  regenerateChannelPairing,
  semanticSearch,
  stopDashboard,
  shellCommand,
  postComment,
  getEngagement,
  fetchJSON,
  fetchBinary,
  askOpenCode,
  askOpenCodeCommand,
  endConversation,
};

export default api;
