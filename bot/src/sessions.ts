/**
 * sessions.ts — Session manager for both platforms.
 *
 * Sessions are keyed by "platform:userId" to avoid collision.
 * Sessions are persisted to ~/.ostwin/sessions.json so they survive
 * bot restarts.  Binary fields (pendingAttachments) are excluded
 * from persistence — they are transient by nature.
 *
 * Writes are debounced (2 s) to avoid hammering the disk on rapid
 * message bursts.
 */

import { Buffer } from 'buffer';
import fs from 'fs';
import path from 'path';
import os from 'os';

export type SessionMode = 'idle' | 'editing' | 'drafting' | 'awaiting_idea';

export interface ChatMessage {
  role: string;
  content: string;
}

export interface StagedAttachment {
  data: Uint8Array;
  name: string;
  mimeType: string;
  stagedAt: number;
  epicRef?: string;
}

export interface PendingContextEntry {
  command: string;
  result: string;
  timestamp: number;
}

export interface Session {
  userId: string;
  platform: string;
  activePlanId: string | null;
  mode: SessionMode;
  chatHistory: ChatMessage[];
  lastActivity: number;
  workingDir?: string;
  activeEpicRef?: string;
  pendingAttachments: StagedAttachment[];
  pendingContext: PendingContextEntry[];
}

// ---------------------------------------------------------------------------
// Persistence config
// ---------------------------------------------------------------------------

const SESSION_TIMEOUT_MS = 7 * 24 * 60 * 60 * 1000; // 7 days — conversations persist
const PERSIST_DEBOUNCE_MS = 2_000;          // flush at most every 2 s
const SESSIONS_DIR = path.join(os.homedir(), '.ostwin');
const SESSIONS_FILE = path.join(SESSIONS_DIR, 'sessions.json');

/**
 * Serialisable subset of a Session — excludes binary / transient fields.
 */
interface PersistedSession {
  userId: string;
  platform: string;
  activePlanId: string | null;
  mode: SessionMode;
  chatHistory: ChatMessage[];
  lastActivity: number;
  workingDir?: string;
  activeEpicRef?: string;
}

// ---------------------------------------------------------------------------
// In-memory state
// ---------------------------------------------------------------------------

const sessions = new Map<string, Session>();
let _persistTimer: ReturnType<typeof setTimeout> | null = null;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _key(userId: string | number, platform: string): string {
  return `${platform}:${userId}`;
}

function _newSession(userId: string | number, platform: string): Session {
  return {
    userId: String(userId),
    platform,
    activePlanId: null,
    mode: 'idle',
    chatHistory: [],
    lastActivity: Date.now(),
    pendingAttachments: [],
    pendingContext: [],
  };
}

// ---------------------------------------------------------------------------
// Disk persistence — load
// ---------------------------------------------------------------------------

/**
 * Load sessions from disk.  Called once at module init.
 * Expired sessions (older than SESSION_TIMEOUT_MS) are silently discarded.
 */
function _loadFromDisk(): void {
  try {
    if (!fs.existsSync(SESSIONS_FILE)) return;

    const raw = fs.readFileSync(SESSIONS_FILE, 'utf-8');
    const data: Record<string, PersistedSession> = JSON.parse(raw);
    const now = Date.now();
    let loaded = 0;

    for (const [key, persisted] of Object.entries(data)) {
      const session: Session = {
        userId: persisted.userId,
        platform: persisted.platform,
        activePlanId: persisted.activePlanId,
        mode: persisted.mode,
        chatHistory: persisted.chatHistory || [],
        lastActivity: persisted.lastActivity,
        workingDir: persisted.workingDir,
        activeEpicRef: persisted.activeEpicRef,
        pendingAttachments: [],
        pendingContext: [],
      };
      sessions.set(key, session);
      loaded++;
    }

    if (loaded > 0) {
      console.log(`[SESSIONS] Restored ${loaded} session(s) from disk`);
    }
  } catch (err: any) {
    console.warn(`[SESSIONS] Failed to load sessions from disk: ${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// Disk persistence — save (debounced)
// ---------------------------------------------------------------------------

function _serializeForDisk(): Record<string, PersistedSession> {
  const out: Record<string, PersistedSession> = {};

  for (const [key, session] of sessions.entries()) {
    out[key] = {
      userId: session.userId,
      platform: session.platform,
      activePlanId: session.activePlanId,
      mode: session.mode,
      chatHistory: session.chatHistory,
      lastActivity: session.lastActivity,
      workingDir: session.workingDir,
      activeEpicRef: session.activeEpicRef,
    };
  }

  return out;
}

function _flushToDisk(): void {
  try {
    if (!fs.existsSync(SESSIONS_DIR)) {
      fs.mkdirSync(SESSIONS_DIR, { recursive: true });
    }

    const data = _serializeForDisk();

    // Atomic write: write to tmp file then rename
    const tmpFile = SESSIONS_FILE + '.tmp';
    fs.writeFileSync(tmpFile, JSON.stringify(data, null, 2) + '\n', 'utf-8');
    fs.renameSync(tmpFile, SESSIONS_FILE);
  } catch (err: any) {
    console.warn(`[SESSIONS] Failed to persist sessions: ${err.message}`);
  }
}

/**
 * Schedule a debounced write.  Multiple rapid calls within PERSIST_DEBOUNCE_MS
 * are coalesced into a single disk write.
 */
function _schedulePersist(): void {
  if (_persistTimer) return; // already scheduled
  _persistTimer = setTimeout(() => {
    _persistTimer = null;
    _flushToDisk();
  }, PERSIST_DEBOUNCE_MS);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function getSession(userId: string | number, platform = 'telegram'): Session {
  const key = _key(userId, platform);
  let session = sessions.get(key);

  if (session) {
    session.lastActivity = Date.now();
  } else {
    session = _newSession(userId, platform);
    sessions.set(key, session);
  }

  return session;
}

export function clearSession(userId: string | number, platform = 'telegram'): void {
  const key = _key(userId, platform);
  sessions.set(key, _newSession(userId, platform));
  _schedulePersist();
}

export function clearChatHistory(userId: string | number, platform = 'telegram'): void {
  const session = getSession(userId, platform);
  session.chatHistory = [];
  _schedulePersist();
}

export function clearActivePlan(userId: string | number, platform = 'telegram'): void {
  const session = getSession(userId, platform);
  session.activePlanId = null;
  session.activeEpicRef = undefined;
  session.mode = 'idle';
  session.lastActivity = Date.now();
  _schedulePersist();
}

export function clearConversationState(userId: string | number, platform = 'telegram'): void {
  const session = getSession(userId, platform);
  session.activePlanId = null;
  session.activeEpicRef = undefined;
  session.mode = 'idle';
  session.chatHistory = [];
  session.pendingContext = [];
  session.lastActivity = Date.now();
  _schedulePersist();
}

export function setMode(userId: string | number, platform: string, mode: SessionMode): void {
  const session = getSession(userId, platform);
  session.mode = mode;
  session.lastActivity = Date.now();
  _schedulePersist();
}

export function setPlan(userId: string | number, platform: string, planId: string): void {
  const session = getSession(userId, platform);
  session.activePlanId = planId;
  session.lastActivity = Date.now();
  _schedulePersist();
}

export function setWorkingDir(userId: string | number, platform: string, dir: string): void {
  const session = getSession(userId, platform);
  session.workingDir = dir;
  session.lastActivity = Date.now();
  _schedulePersist();
}

/**
 * Persist chat history after a message is added.
 * Call this after pushing to session.chatHistory directly.
 */
export function persistAfterMessage(): void {
  _schedulePersist();
}

/**
 * Force an immediate flush to disk (e.g. on shutdown).
 */
export function flushSessionsSync(): void {
  if (_persistTimer) {
    clearTimeout(_persistTimer);
    _persistTimer = null;
  }
  _flushToDisk();
}

/**
 * Convert staged attachments to image objects for API.
 * Only returns attachments with image/* mime types.
 * Returns data URIs (base64-encoded).
 */
export function getStagedImages(userId: string | number, platform: string): Array<{ url: string; name: string; contentType: string }> {
  const session = getSession(userId, platform);
  const pending = session.pendingAttachments || [];
  return pending
    .filter(a => a.mimeType.startsWith('image/'))
    .map(a => ({
      url: `data:${a.mimeType};base64,${Buffer.from(a.data).toString('base64')}`,
      name: a.name,
      contentType: a.mimeType,
    }));
}

/**
 * Return metadata for ALL staged files (images + documents + any type).
 * Unlike getStagedImages, this does NOT embed base64 data — it only
 * returns lightweight metadata so the agent knows what was attached.
 */
export function getStagedFiles(userId: string | number, platform: string): Array<{ name: string; contentType: string; sizeBytes: number }> {
  const session = getSession(userId, platform);
  const pending = session.pendingAttachments || [];
  return pending.map(a => ({
    name: a.name,
    contentType: a.mimeType,
    sizeBytes: a.data?.byteLength || 0,
  }));
}

// ---------------------------------------------------------------------------
// Init: load persisted sessions on module import
// ---------------------------------------------------------------------------

_loadFromDisk();
