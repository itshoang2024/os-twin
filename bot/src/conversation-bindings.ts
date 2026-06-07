import fs from 'fs';
import path from 'path';
import os from 'os';

export type BindingPlatform = 'telegram' | 'slack';

export interface ConversationBinding {
  conversation_id: string;
  platform: BindingPlatform;
  plan_id: string;
  subscriptions: string[];
  last_outbound_message_id?: string;
  epic_ref?: string;
  room_id?: string;
  created_at: string;
  updated_at: string;
}

export interface BindConversationInput {
  conversation_id: string;
  platform?: BindingPlatform;
  plan_id: string;
  subscriptions?: string[];
  last_outbound_message_id?: string;
  epic_ref?: string;
  room_id?: string;
}

export interface ConversationTarget {
  platform: BindingPlatform;
  targetId: string;
  threadId?: string;
}

export const DEFAULT_PLAN_SUBSCRIPTIONS = [
  'plan.run.started',
  'plan.run.completed',
  'plan.run.failed',
  'epic.passed',
  'epic.failed',
  'epic.retrying',
  'room.created',
  'room.status.changed',
  'system.error',
  'user.feedback.requested',
];

const DEFAULT_BINDINGS_FILE = path.join(os.homedir(), '.ostwin', 'conversation-bindings.json');
let bindingsFile = process.env.OSTWIN_CONVERSATION_BINDINGS_FILE || DEFAULT_BINDINGS_FILE;
let bindings = new Map<string, ConversationBinding>();

export function telegramConversationId(chatId: string | number, threadId?: string | number): string {
  const base = `telegram:chat:${chatId}`;
  return threadId === undefined || threadId === null ? base : `${base}:thread:${threadId}`;
}

export function slackConversationId(teamId: string, channelId: string, threadTs?: string): string {
  const base = `slack:team:${teamId}:channel:${channelId}`;
  return threadTs ? `${base}:thread:${threadTs}` : base;
}

export function inferBindingPlatform(conversationId: string): BindingPlatform | null {
  if (conversationId.startsWith('telegram:')) return 'telegram';
  if (conversationId.startsWith('slack:')) return 'slack';
  return null;
}

export function parseConversationTarget(conversationId: string): ConversationTarget | null {
  const telegram = conversationId.match(/^telegram:chat:([^:]+)(?::thread:([^:]+))?$/);
  if (telegram) return { platform: 'telegram', targetId: telegram[1], threadId: telegram[2] };

  const slack = conversationId.match(/^slack:team:([^:]+):channel:([^:]+)(?::thread:([^:]+))?$/);
  if (slack) return { platform: 'slack', targetId: slack[2], threadId: slack[3] };

  return null;
}

export function validateConversationId(conversationId: string): boolean {
  return parseConversationTarget(conversationId) !== null;
}

function nowIso(): string {
  return new Date().toISOString();
}

function loadBindings(): void {
  try {
    if (!fs.existsSync(bindingsFile)) return;
    const raw = fs.readFileSync(bindingsFile, 'utf-8');
    const data: ConversationBinding[] = JSON.parse(raw);
    bindings = new Map(data.map(binding => [binding.conversation_id, binding]));
  } catch (err: any) {
    console.warn(`[BINDINGS] Failed to load conversation bindings: ${err.message}`);
    bindings = new Map();
  }
}

function saveBindings(): void {
  try {
    fs.mkdirSync(path.dirname(bindingsFile), { recursive: true });
    const tmpFile = `${bindingsFile}.tmp`;
    const ordered = Array.from(bindings.values()).sort((a, b) => a.conversation_id.localeCompare(b.conversation_id));
    fs.writeFileSync(tmpFile, JSON.stringify(ordered, null, 2) + '\n', 'utf-8');
    fs.renameSync(tmpFile, bindingsFile);
  } catch (err: any) {
    console.warn(`[BINDINGS] Failed to persist conversation bindings: ${err.message}`);
  }
}

export function bindConversation(input: BindConversationInput): ConversationBinding {
  const target = parseConversationTarget(input.conversation_id);
  if (!target) throw new Error(`Invalid conversation_id: ${input.conversation_id}`);

  const platform = input.platform || target.platform;
  if (platform !== target.platform) {
    throw new Error(`conversation_id platform ${target.platform} does not match ${platform}`);
  }

  const existing = bindings.get(input.conversation_id);
  const timestamp = nowIso();
  const binding: ConversationBinding = {
    conversation_id: input.conversation_id,
    platform,
    plan_id: input.plan_id,
    subscriptions: input.subscriptions || existing?.subscriptions || DEFAULT_PLAN_SUBSCRIPTIONS,
    last_outbound_message_id: input.last_outbound_message_id ?? existing?.last_outbound_message_id,
    epic_ref: input.epic_ref ?? existing?.epic_ref,
    room_id: input.room_id ?? existing?.room_id,
    created_at: existing?.created_at || timestamp,
    updated_at: timestamp,
  };
  bindings.set(binding.conversation_id, binding);
  saveBindings();
  return binding;
}

export function unbindConversation(conversationId: string): boolean {
  const removed = bindings.delete(conversationId);
  if (removed) saveBindings();
  return removed;
}

export function getBindingsForPlan(planId: string): ConversationBinding[] {
  return Array.from(bindings.values()).filter(binding => binding.plan_id === planId);
}

export function getActiveBinding(conversationId: string): ConversationBinding | null {
  return bindings.get(conversationId) || null;
}

export function updateLastOutboundMessage(conversationId: string, messageId: string): void {
  const binding = bindings.get(conversationId);
  if (!binding) return;
  binding.last_outbound_message_id = messageId;
  binding.updated_at = nowIso();
  saveBindings();
}

export function resetConversationBindingsForTests(filePath?: string): void {
  bindingsFile = filePath || DEFAULT_BINDINGS_FILE;
  bindings = new Map();
  if (filePath && fs.existsSync(filePath)) fs.rmSync(filePath, { force: true });
}

loadBindings();
