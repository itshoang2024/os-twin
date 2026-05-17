/**
 * commands.ts — Shared command implementations for both platforms.
 *
 * Each command returns a response object:
 *   { text, buttons?, file? }
 *
 * Platform adapters translate these into native API calls.
 */

import api, { PlanAsset, ClawhubSkill, RoleInfo } from './api';
import { registry } from './connectors/registry';
import { getSession, clearSession, clearChatHistory, setPlan, setWorkingDir } from './sessions';
import { SlashCommandBuilder } from 'discord.js';

// ── Types ─────────────────────────────────────────────────────────

export interface Button {
  label: string;
  callbackData: string;
  url?: string; // When set, renders as a URL button instead of a callback button
}

export interface BotResponse {
  text: string;
  buttons?: Button[][];
  file?: { path: string; name: string };
}

// ── Command registry (single source of truth) ───────────────────
//
// Every connector imports this to auto-register commands.
// - `arg`: if set, this command accepts a string argument with that name
// - `argRequired`: whether the argument is mandatory (Discord only)
// - `argDescription`: hint text shown to users for the argument
// - `deferReply`: if true, Discord will defer (show "thinking…") before running
// - `discordOnly`: if true, skip registration on Telegram/Slack (voice commands)
// - `telegramMenu`: if set, shows in Telegram's /command quick-list

export interface CommandDef {
  name: string;
  description: string;
  arg?: string;
  argDescription?: string;
  argRequired?: boolean;
  deferReply?: boolean;
  discordOnly?: boolean;
  telegramMenu?: string; // description shown in Telegram's setMyCommands
}

export type CommandPlatform = 'telegram' | 'discord' | 'slack';

export const COMMAND_REGISTRY: CommandDef[] = [
  // ── Plans & AI ──────────────────────────────────────────────────
  { name: 'menu',            description: 'Main Control Center',                                 telegramMenu: '🏢 Main Control Center' },
  { name: 'help',            description: 'Detailed user guide',                                 telegramMenu: '❓ Detailed user guide' },
  { name: 'draft',           description: 'Draft a new Plan with AI',                            arg: 'idea',     argDescription: 'Your project idea',                   deferReply: true, telegramMenu: '📝 Draft a new Plan with AI' },
  { name: 'edit',            description: 'Select a plan to edit with AI',                       deferReply: true },
  { name: 'viewplan',        description: "View a plan's content",                               deferReply: true },
  { name: 'startplan',       description: 'Select and launch a plan',                            deferReply: true },
  { name: 'resume',          description: 'Resume a failed or stopped plan',                     deferReply: true },
  { name: 'assets',          description: 'List assets for the active or selected plan',         deferReply: true },
  { name: 'setdir',          description: 'Set target project directory for new plans',          arg: 'path',     argDescription: 'Absolute path to project directory' },
  { name: 'cancel',          description: 'Exit current editing session' },
  { name: 'clear',           description: 'Clear conversation history with the AI' },
  { name: 'feedback',        description: 'Send feedback to the dashboard',                      arg: 'text',     argDescription: 'Your feedback message',   argRequired: true, deferReply: true },

  // ── Monitoring ──────────────────────────────────────────────────
  { name: 'dashboard',       description: 'Real-time War-Room progress',                         deferReply: true, telegramMenu: '📊 Real-time War-Room progress' },
  { name: 'status',          description: 'List running War-Rooms',                              deferReply: true, telegramMenu: '💻 List running War-Rooms' },
  { name: 'errors',          description: 'Error summary with root causes',                      deferReply: true },
  { name: 'logs',            description: 'View war-room channel messages',                      arg: 'room_id',  argDescription: 'War-room ID (e.g. room-001)',          deferReply: true, telegramMenu: '📜 View war-room logs' },
  { name: 'health',          description: 'System health check',                                 deferReply: true, telegramMenu: '🏥 System health check' },
  { name: 'progress',        description: 'Plan progress bars',                                  deferReply: true },
  { name: 'plans',           description: 'List all project Plans',                             deferReply: true },

  // ── Skills & Roles ──────────────────────────────────────────────
  { name: 'skills',          description: 'View installed AI skills',                            deferReply: true, telegramMenu: '🧠 List AI skills' },
  { name: 'skillsearch',     description: 'Search ClawHub skill marketplace',                    arg: 'query',    argDescription: 'Search query',                         argRequired: true, deferReply: true },
  { name: 'skillinstall',    description: 'Install a skill from ClawHub',                        arg: 'slug',     argDescription: 'Skill slug (e.g. steipete/web-search)', argRequired: true, deferReply: true },
  { name: 'skillremove',     description: 'Remove an installed skill',                           arg: 'name',     argDescription: 'Skill name to remove',                  argRequired: true, deferReply: true },
  { name: 'skillsync',       description: 'Sync skills with dashboard',                          deferReply: true },
  { name: 'roles',           description: 'List all agent roles',                                deferReply: true },

  // ── System ──────────────────────────────────────────────────────
  { name: 'triage',          description: 'Triage a failed war-room',                            arg: 'room_id',  argDescription: 'War-room ID to triage',                 deferReply: true },
  { name: 'clearplans',      description: 'Wipe all plan data',                                  deferReply: true },
  { name: 'new',             description: 'Wipe old War-Room data to start fresh',               deferReply: true },
  { name: 'restart',         description: 'Reboot the Command Center background process',        deferReply: true },
  { name: 'launchdashboard', description: 'Dashboard access info',                               deferReply: true },
  { name: 'preferences',     description: 'Notification preferences',                            deferReply: true },
  { name: 'subscriptions',   description: 'Event subscription toggles',                          deferReply: true },

  // ── Discord-only (voice) ────────────────────────────────────────
  { name: 'join',            description: 'Join your voice channel and stream live audio',       discordOnly: true },
  { name: 'leave',           description: 'Disconnect and save all recordings',                  discordOnly: true },
  { name: 'ping',            description: 'Check bot latency',                                   discordOnly: true },
];

export function getCommandDef(name: string): CommandDef | undefined {
  return COMMAND_REGISTRY.find(c => c.name === name);
}

export function requireCommandDef(name: string): CommandDef {
  const def = getCommandDef(name);
  if (!def) throw new Error(`Command "${name}" is missing from COMMAND_REGISTRY`);
  return def;
}

export function getCommandsForPlatform(platform: CommandPlatform): CommandDef[] {
  return COMMAND_REGISTRY.filter(c => platform === 'discord' || !c.discordOnly);
}

export function getCommandsWithArgsForPlatform(platform: CommandPlatform): CommandDef[] {
  return getCommandsForPlatform(platform).filter(c => c.arg);
}

export function getCommandsWithoutArgsForPlatform(platform: CommandPlatform): CommandDef[] {
  return getCommandsForPlatform(platform).filter(c => !c.arg);
}

export function buildDiscordSlashCommand(def: CommandDef): SlashCommandBuilder {
  const builder = new SlashCommandBuilder()
    .setName(def.name)
    .setDescription(def.description);

  if (def.arg) {
    builder.addStringOption(opt =>
      opt.setName(def.arg!)
        .setDescription(def.argDescription || def.arg!)
        .setRequired(def.argRequired ?? false),
    );
  }

  return builder;
}

export function buildDiscordSlashCommands(defs: CommandDef[] = getCommandsForPlatform('discord')): SlashCommandBuilder[] {
  return defs.map(buildDiscordSlashCommand);
}

// Pre-computed views for compatibility; connectors should use platform helpers above.
export const COMMANDS_WITH_ARGS = getCommandsWithArgsForPlatform('telegram');
export const COMMANDS_NO_ARGS = getCommandsWithoutArgsForPlatform('telegram');
export const ALL_PLATFORM_COMMANDS = getCommandsForPlatform('telegram');
export const TELEGRAM_MENU_COMMANDS = getCommandsForPlatform('telegram').filter(c => c.telegramMenu);
export const DEFERRED_COMMANDS = new Set(COMMAND_REGISTRY.filter(c => c.deferReply).map(c => c.name));

export function isDeferredCommand(name: string): boolean {
  return DEFERRED_COMMANDS.has(name);
}

// ── Response helpers ──────────────────────────────────────────────

function text(t: string): BotResponse {
  return { text: t };
}

function menu(t: string, buttons: Button[][]): BotResponse {
  return { text: t, buttons };
}

function formatBytes(bytes = 0): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ── Menu commands ─────────────────────────────────────────────────

function cmdMenu(): BotResponse {
  return menu('*Main Control Center*\nSelect a category:', [
    [{ label: '📊 Monitoring', callbackData: 'menu:cat:monitoring' }],
    [{ label: '📝 Plans & AI', callbackData: 'menu:cat:plans' }],
    [{ label: '🧠 Skills & Roles', callbackData: 'menu:cat:skills' }],
    [{ label: '⚙️ System', callbackData: 'menu:cat:system' }],
  ]);
}

function _editDistance(a: string, b: string): number {
  const dp: number[][] = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
  for (let i = 0; i <= a.length; i++) dp[i][0] = i;
  for (let j = 0; j <= b.length; j++) dp[0][j] = j;
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      dp[i][j] = a[i - 1] === b[j - 1]
        ? dp[i - 1][j - 1]
        : 1 + Math.min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]);
    }
  }
  return dp[a.length][b.length];
}

/**
 * Build a fallback response for unknown slash commands.
 * Suggests close matches (edit distance ≤ 2) and shows the category menu so
 * the user can pick from defined commands instead of being routed to the LLM.
 */
export function cmdUnknown(input: string, platform: CommandPlatform = 'telegram'): BotResponse {
  const cmdName = input.replace(/^\/([a-zA-Z0-9_]+).*/, '$1');
  const available = getCommandsForPlatform(platform).map(c => c.name);
  const suggestions = available
    .map(n => ({ n, d: _editDistance(n.toLowerCase(), cmdName.toLowerCase()) }))
    .filter(s => s.d <= 2)
    .sort((a, b) => a.d - b.d)
    .slice(0, 5)
    .map(s => s.n);

  const lines = [`⚠️ Unknown command \`/${cmdName}\`.`];
  if (suggestions.length) {
    lines.push('', `Did you mean: ${suggestions.map(s => `\`/${s}\``).join(', ')}?`);
  }
  lines.push('', 'Pick a category below or send /help for the full list.');

  return menu(lines.join('\n'), [
    [{ label: '📊 Monitoring', callbackData: 'menu:cat:monitoring' }],
    [{ label: '📝 Plans & AI', callbackData: 'menu:cat:plans' }],
    [{ label: '🧠 Skills & Roles', callbackData: 'menu:cat:skills' }],
    [{ label: '⚙️ System', callbackData: 'menu:cat:system' }],
  ]);
}

function cmdSubmenuMonitoring(): BotResponse {
  return menu('📊 *Monitoring*\nReal-time War-Room insights:', [
    [{ label: '📊 Dashboard', callbackData: 'cmd:dashboard' }],
    [{ label: '📈 Progress', callbackData: 'cmd:progress' }],
    [{ label: '💻 Status', callbackData: 'cmd:status' }],
    [{ label: '⚠️ Errors', callbackData: 'cmd:errors' }],
    [{ label: '📜 Logs', callbackData: 'cmd:logs' }],
    [{ label: '🏥 Health', callbackData: 'cmd:health' }],
    [{ label: '⬅️ Back', callbackData: 'menu:main' }],
  ]);
}

function cmdSubmenuPlans(): BotResponse {
  return menu('📝 *Plans & AI*\nDraft, view, edit, and launch plans:', [
    [{ label: '✨ Draft New Plan', callbackData: 'cmd:draft_prompt' }],
    [{ label: '👁 View Plan', callbackData: 'cmd:viewplan' }],
    [{ label: '✏️ Edit Plan', callbackData: 'cmd:edit' }],
    [{ label: '🖼 Assets', callbackData: 'cmd:assets' }],
    [{ label: '🚀 Launch Plan', callbackData: 'cmd:startplan' }],
    [{ label: '🔄 Resume Plan', callbackData: 'cmd:resume' }],
    [{ label: '📂 All Plans', callbackData: 'menu:plans' }],
    [{ label: '⬅️ Back', callbackData: 'menu:main' }],
  ]);
}

function cmdSubmenuSkills(): BotResponse {
  return menu('🧠 *Skills & Roles*\nManage AI skills and agent roles:', [
    [{ label: '🧠 Installed Skills', callbackData: 'cmd:skills' }],
    [{ label: '🔍 Search Skills', callbackData: 'cmd:skillsearch_prompt' }],
    [{ label: '🔄 Sync Skills', callbackData: 'cmd:skillsync' }],
    [{ label: '👥 Roles', callbackData: 'cmd:roles' }],
    [{ label: '⬅️ Back', callbackData: 'menu:main' }],
  ]);
}

function cmdSubmenuSystem(): BotResponse {
  return menu('⚙️ *System*\nSystem operations & resources:', [
    [{ label: '🏥 Health', callbackData: 'cmd:health' }],
    [{ label: '🔔 Notifications', callbackData: 'cmd:preferences' }],
    [{ label: '🧹 Clear Plans', callbackData: 'cmd:clearplans' }],
    [{ label: '⬅️ Back', callbackData: 'menu:main' }],
  ]);
}

// ── Monitoring commands ───────────────────────────────────────────

async function cmdDashboard(): Promise<BotResponse> {
  const [{ summary }, baseUrl] = await Promise.all([
    api.getRooms(),
    api.getBaseUrl(),
  ]);
  const total = summary.total || 0;
  const active = (summary.pending || 0)
    + (summary.developing || 0) + (summary.engineering || 0)
    + (summary.review || 0) + (summary.qa_review || 0)
    + (summary.fixing || 0);
  const passed = summary.passed || 0;
  const failed = summary.failed_final || 0;

  const makeBar = (count: number, t: number, len = 12): string => {
    if (t === 0) return '░'.repeat(len);
    const filled = Math.round((count / t) * len);
    return '█'.repeat(filled) + '░'.repeat(len - filled);
  };

  const pctPass = total ? (passed / total * 100).toFixed(1) : '0.0';
  const pctFail = total ? (failed / total * 100).toFixed(1) : '0.0';
  const pctAct = total ? (active / total * 100).toFixed(1) : '0.0';

  return {
    text: `🎛 *OS TWIN COMMAND CENTER* 🎛
_System Status:_ 🟢 *ONLINE*

📊 *WAR-ROOMS OVERVIEW*
\`─────────────────────────────\`
🏃‍♂️ *Active:*   \`${String(active).padEnd(4)}\`
✅ *Passed:*   \`${String(passed).padEnd(4)}\`
❌ *Failed:*   \`${String(failed).padEnd(4)}\`
📦 *Total:*    \`${String(total).padEnd(4)}\`
\`─────────────────────────────\`

📈 *EXECUTION PROGRESS*
✅ \`Passed:\` \`${makeBar(passed, total)}\` \`${pctPass.padStart(5)}%\`
❌ \`Failed:\` \`${makeBar(failed, total)}\` \`${pctFail.padStart(5)}%\`
��‍♂️ \`Active:\` \`${makeBar(active, total)}\` \`${pctAct.padStart(5)}%\``,
    buttons: baseUrl.startsWith('https')
      ? [[{ label: '🔗 Open Dashboard', callbackData: '_', url: baseUrl }]]
      : undefined,
  };
}

async function cmdStatus(): Promise<BotResponse> {
  const { rooms, error } = await api.getRooms();
  if (error) return text(`⚠️ ${error}`);
  if (!rooms.length) return text('ℹ️ No War-Rooms found.');

  const emoji: Record<string, string> = { passed: '✅', running: '🏃‍♂️', engineering: '🏃‍♂️', developing: '🏃‍♂️', pending: '⏳', review: '👀', qa_review: '👀', fixing: '🔧', 'failed-final': '❌' };
  const lines = ['📋 *War-Rooms Status:*', '`─────────────────────────────`'];
  for (const r of rooms) {
    const e = r.status.includes('fail') ? '❌' : (emoji[r.status] || '❓');
    lines.push(`${e} \`${r.room_id}\` : ${r.status.toUpperCase()} \`[${r.message_count} msgs]\``);
  }
  lines.push('`─────────────────────────────`');
  return text(lines.join('\n'));
}

async function cmdErrors(): Promise<BotResponse> {
  const { rooms, error } = await api.getRooms();
  if (error) return text(`⚠️ ${error}`);
  const failed = rooms.filter(r => r.status.includes('fail'));
  if (!failed.length) return text('✅ System is stable. No active errors.');

  const lines: string[] = [];
  for (const r of failed) {
    lines.push(`⚠️ *${r.room_id}* is ${r.status.toUpperCase()}`);
    const ch = await api.getRoomChannel(r.room_id, 3);
    const msgs = ch?.messages || ch || [];
    if (Array.isArray(msgs)) {
      for (const m of [...msgs].reverse()) {
        if (['fail', 'error'].includes(m.type)) {
          const body = (m.body || '').slice(0, 150).replace(/\n/g, ' ').replace(/[*_`]/g, '');
          lines.push(`  └ ❌ \`${body}...\``);
          break;
        }
      }
    }
  }
  return text(lines.join('\n'));
}

// ── Tier 1: Resume, Logs, Health, Config, Channels ───────────────

async function cmdResumeMenu(): Promise<BotResponse> {
  const { plans } = await api.getPlans();
  const resumable = plans.filter(p => p.status === 'failed' || p.status === 'stopped' || p.status === 'running');
  if (!resumable.length) return text('ℹ️ No plans available to resume. Only failed/stopped plans can be resumed.');
  const buttons = resumable.slice(0, 10).map(p => {
    let title = p.title || p.plan_id;
    if (title.length > 25) title = title.slice(0, 22) + '...';
    return [{ label: `🔄 ${title}`, callbackData: `menu:resume_confirm:${p.plan_id}` }];
  });
  return menu('🔄 *Select a Plan to Resume:*', buttons);
}

async function cmdResumePlan(planId: string): Promise<BotResponse[]> {
  const data = await api.getPlan(planId);
  if (data?._error) return [text(`❌ Plan \`${planId}\` not found.`)];
  const planContent = data.plan?.content || data.content || '';
  const result = await api.resumePlan(planId, planContent);
  if (result?._error) return [text(`❌ Failed to resume plan: ${result._error}`)];
  return [text(`🔄 *Plan Resumed!* \`${planId}\`\n\nExisting war-rooms will be continued. Use /dashboard or /status to monitor progress.`)];
}

async function cmdClearPlans(): Promise<BotResponse> {
  const result = await api.shellCommand('ostwin plan clear --force');
  if (result?._error) return text(`❌ Failed to clear plans: ${result._error}`);
  const output = result?.stdout || '';
  return text(`🧹 *All plans cleared.*\n${output ? `\`\`\`\n${output.slice(0, 500)}\n\`\`\`` : 'Ready to create new plans.'}`);
}

async function cmdLogs(args: string): Promise<BotResponse> {
  const parts = args.trim().split(/\s+/);
  const roomId = parts[0] || '';

  if (!roomId) {
    // Show room selection
    const { rooms } = await api.getRooms();
    if (!rooms.length) return text('ℹ️ No war-rooms found.');
    const buttons = rooms.slice(0, 10).map(r => {
      const emoji = r.status.includes('fail') ? '❌' : r.status === 'passed' ? '✅' : '🏃‍♂️';
      return [{ label: `${emoji} ${r.room_id}`, callbackData: `menu:logs:${r.room_id}` }];
    });
    return menu('📜 *Select a War-Room to view logs:*', buttons);
  }

  const limit = parts[1] ? parseInt(parts[1], 10) || 10 : 10;
  const data = await api.getRoomChannel(roomId, limit);
  if (data?._error) return text(`⚠️ ${data._error}`);

  const msgs = data?.messages || data || [];
  if (!Array.isArray(msgs) || !msgs.length) return text(`📜 No messages in \`${roomId}\`.`);

  const lines = [`📜 *Logs for \`${roomId}\`* (last ${msgs.length}):`];
  for (const m of msgs.slice(-15)) {
    const role = m.from || '?';
    const type = m.type ? `[${m.type}]` : '';
    let body = (m.body || '').slice(0, 120).replace(/\n/g, ' ').replace(/[*_`]/g, '');
    lines.push(`\`${role}\` ${type}: ${body}`);
  }
  if (msgs.length > 15) lines.push(`_…${msgs.length - 15} more messages. Use the dashboard for full logs._`);
  return text(lines.join('\n'));
}

async function cmdHealth(): Promise<BotResponse> {
  const [managerStatus, botStatus] = await Promise.all([
    api.getManagerStatus(),
    api.getBotStatus(),
  ]);

  const mgrRunning = managerStatus?.running ?? false;
  const mgrPid = managerStatus?.pid;
  const botRunning = botStatus?.running ?? false;
  const botPid = botStatus?.pid;
  const botAvail = botStatus?.available ?? false;

  const { rooms, summary } = await api.getRooms();
  const total = summary?.total || 0;
  const passed = summary?.passed || 0;
  const failed = summary?.failed_final || 0;
  const active = total - passed - failed;

  return text(`🏥 *System Health*
\`─────────────────────────────\`
⚙️ *Manager:*     ${mgrRunning ? `🟢 Running (PID ${mgrPid})` : '🔴 Stopped'}
🤖 *Bot:*          ${botRunning ? `🟢 Running (PID ${botPid})` : '🔴 Stopped'}${botAvail ? '' : ' ⚠️ Unavailable'}
📦 *War-Rooms:*    \`${total}\` total, \`${active}\` active, \`${passed}\` passed, \`${failed}\` failed
\`─────────────────────────────\``);
}

// ── Tier 2: Skills management ────────────────────────────────────

async function cmdSkillSearch(args: string): Promise<BotResponse> {
  const query = args.trim();
  if (!query) return text('⚠️ Usage: `/skillsearch <query>`\nExample: `/skillsearch web search`');

  const results = await api.searchSkillsClawhub(query);
  if (!results.length) return text(`ℹ️ No skills found for \`${query}\`.`);

  const lines = [`🔍 *Skill Search: "${query}"*`];
  for (const s of results.slice(0, 15)) {
    const desc = s.description ? ` — ${s.description.slice(0, 80)}` : '';
    const dl = s.downloads ? ` (${s.downloads} downloads)` : '';
    lines.push(`• \`${s.slug || s.name}\`${desc}${dl}`);
  }
  if (results.length > 15) lines.push(`_…${results.length - 15} more results_`);
  lines.push('\n_Install with:_ `/skillinstall <slug>`');
  return text(lines.join('\n'));
}

async function cmdSkillInstall(args: string): Promise<BotResponse> {
  const slug = args.trim();
  if (!slug) return text('⚠️ Usage: `/skillinstall <slug>`\nExample: `/skillinstall steipete/web-search`');

  const result = await api.installSkillClawhub(slug);
  if (result?._error) return text(`❌ Failed to install \`${slug}\`: ${result._error}`);
  return text(`✅ *Skill installed:* \`${slug}\`\n${result?.output ? `\`\`\`\n${String(result.output).slice(0, 500)}\n\`\`\`` : ''}`);
}

async function cmdSkillRemove(args: string): Promise<BotResponse> {
  const name = args.trim();
  if (!name) return text('⚠️ Usage: `/skillremove <name>`');

  const result = await api.removeSkill(name, true);
  if (result?._error) return text(`❌ Failed to remove \`${name}\`: ${result._error}`);
  return text(`✅ *Skill removed:* \`${name}\``);
}

async function cmdSkillSync(): Promise<BotResponse> {
  const result = await api.syncSkills();
  if (result?._error) return text(`❌ Sync failed: ${result._error}`);
  return text(`🔄 *Skills synced.* ${result?.message || ''}`);
}

// ── Tier 2: Roles & Triage ───────────────────────────────────────

async function cmdRoles(): Promise<BotResponse> {
  const roles = await api.getRoles();
  if (!roles.length) return text('ℹ️ No roles found.');

  const lines = ['👥 *Available Roles:*', '`─────────────────────────────`'];
  for (const r of roles.slice(0, 30)) {
    const model = r.default_model ? ` (${r.default_model})` : '';
    const desc = r.description ? ` — ${r.description.slice(0, 60)}` : '';
    lines.push(`• \`${r.name}\`${model}${desc}`);
  }
  if (roles.length > 30) lines.push(`_…${roles.length - 30} more roles_`);
  lines.push('`─────────────────────────────`');
  return text(lines.join('\n'));
}

async function cmdTriage(args: string): Promise<BotResponse> {
  const roomId = args.trim();
  if (!roomId) {
    // Show failed rooms for triage selection
    const { rooms } = await api.getRooms();
    const failed = rooms.filter(r => r.status.includes('fail') || r.status === 'error');
    if (!failed.length) return text('✅ No failed rooms to triage.');
    const buttons = failed.slice(0, 10).map(r => [
      { label: `🔧 ${r.room_id}`, callbackData: `menu:triage:${r.room_id}` },
    ]);
    return menu('🔧 *Select a room to triage:*', buttons);
  }

  const result = await api.roomAction(roomId, 'resume');
  if (result?._error) return text(`❌ Triage failed for \`${roomId}\`: ${result._error}`);
  return text(`🔧 *Triage initiated for \`${roomId}\`*\nAction: resume\nThe room will be re-evaluated by the manager.`);
}

async function cmdLaunchDashboard(): Promise<BotResponse> {
  const [baseUrl, botStatus] = await Promise.all([
    api.getBaseUrl(),
    api.getBotStatus(),
  ]);

  // Dashboard is already running if the bot can reach the API
  const buttons: Button[][] = [];
  if (baseUrl.startsWith('https')) {
    buttons.push([{ label: '🔗 Open Dashboard', callbackData: '_', url: baseUrl }]);
  }

  return {
    text: `🖥 *Dashboard*\n\nThe dashboard is accessible at: \`${baseUrl}\`\n\nIf the dashboard is not running, start it from the CLI with:\n\`ostwin dashboard --background\``,
    buttons: buttons.length ? buttons : undefined,
  };
}

// ── Plan commands ─────────────────────────────────────────────────

async function cmdPlans(): Promise<BotResponse> {
  const [{ plans, error }, baseUrl] = await Promise.all([
    api.getPlans(),
    api.getBaseUrl(),
  ]);
  if (error) return text(`⚠️ ${error}`);
  if (!plans.length) return text('ℹ️ No plans found.');

  const isPublic = baseUrl.startsWith('https');
  const lines = ['📂 *Project Plans:*'];
  const buttons: Button[][] = [];
  for (const p of plans) {
    let title = p.title || p.plan_id;
    if (title.length > 40) title = title.slice(0, 37) + '...';
    lines.push(`• *${title}* (\`${p.plan_id}\`, ${p.status || 'unknown'})`);
    if (isPublic) {
      buttons.push([{ label: `📄 ${title}`, callbackData: '_', url: `${baseUrl}/plans/${p.plan_id}` }]);
    }
  }
  return buttons.length ? { text: lines.join('\n'), buttons } : text(lines.join('\n'));
}

async function cmdSkills(): Promise<BotResponse> {
  const skills = await api.getSkills();
  if (!skills.length) return text('ℹ️ No skills installed.');
  const lines = ['🧠 *Available Skills:*'];
  for (const s of skills.slice(0, 50)) {
    const tags = (s.tags && s.tags.length) ? s.tags.join(', ') : 'General';
    lines.push(`• \`${s.name}\`: [${tags}]`);
  }
  return text(lines.join('\n'));
}

export function cmdHelp(): BotResponse {
  return text(`*OS Twin Command Center — Help Menu*
\`─────────────────────────────\`

*Plans & AI*
  /menu — Main interactive command menu.
  /draft <idea> — Create a new plan from a text prompt.
  /edit — Select a plan to edit and refine with AI.
  /viewplan — Select and read a plan.
  /startplan — Select and launch a plan.
  /resume — Resume a failed or stopped plan.
  /assets — List assets attached to the active or selected plan.
  /setdir <path> — Set the target project directory.
  /cancel — Exit current editing/drafting session.

*Monitoring & Insights*
  /dashboard — Visual UI with real-time progress bars.
  /status — Detailed breakdown of every active War-Room.
  /errors — Root cause of any failed War-Rooms.
  /logs [room_id] — View war-room channel messages.
  /health — System health check.
  /progress — Plan progress bars.

*Skills & Roles*
  /skills — View installed AI skills.
  /skillsearch <query> — Search ClawHub marketplace.
  /skillinstall <slug> — Install a skill from ClawHub.
  /skillremove <name> — Remove an installed skill.
  /skillsync — Sync skills with dashboard.
  /roles — List all agent roles.

*System Operations*
  /plans — List all project plans.
  /triage [room_id] — Triage a failed war-room.
  /clearplans — Wipe all plan data.
  /new — Wipe old War-Room data to start fresh.
  /restart — Reboot the Command Center.
  /launchdashboard — Dashboard access info.`);
}

// ── System commands ───────────────────────────────────────────────

async function cmdNew(): Promise<BotResponse> {
  const result = await api.shellCommand('rm -rf .war-rooms && mkdir .war-rooms');
  if (result?._error) return text(`❌ Failed to clean War-Rooms: ${result._error}`);
  return text('🧹 *Cleaned up all War-Rooms data.* Ready for a new Plan.');
}

async function cmdRestart(): Promise<BotResponse> {
  const result = await api.stopDashboard();
  if (result?._error) return text(`❌ Failed to restart: ${result._error}`);
  return text('🔄 *Restarting Command Center...*');
}

// ── Plan selection menus ──────────────────────────────────────────

async function _planButtons(prefix: string): Promise<Button[][] | null> {
  const { plans } = await api.getPlans();
  if (!plans.length) return null;
  return plans.slice(0, 10).map(p => {
    let title = p.title || p.plan_id;
    if (title.length > 25) title = title.slice(0, 22) + '...';
    return [{ label: `📄 ${title}`, callbackData: `${prefix}:${p.plan_id}` }];
  });
}

async function cmdViewplanMenu(): Promise<BotResponse> {
  const buttons = await _planButtons('menu:view');
  if (!buttons) return text('ℹ️ No plans found.');
  return menu('👁 *Select a Plan to View:*', buttons);
}

async function cmdEditMenu(): Promise<BotResponse> {
  const buttons = await _planButtons('menu:edit');
  if (!buttons) return text('ℹ️ No plans found. Use /draft <idea> to create one.');
  return menu('✏️ *Select a Plan to Edit:*', buttons);
}

async function cmdStartplanMenu(): Promise<BotResponse> {
  const buttons = await _planButtons('menu:launch_prompt');
  if (!buttons) return text('ℹ️ No plans found. Use /draft <idea> to create one.');
  return menu('🚀 *Select a Plan to Launch:*', buttons);
}

async function cmdAssets(planId: string): Promise<BotResponse> {
  const [assetsRes, epicsRes] = await Promise.all([
    api.getPlanAssets(planId),
    api.getPlanEpics(planId),
  ]);
  
  if (assetsRes.error) return text(`⚠️ ${assetsRes.error}`);
  const assets = assetsRes.assets;
  const epics = epicsRes.epics;

  if (!assets.length && !epics.length) {
    return text(`🖼 *Assets for \`${planId}\`*\nNo assets or epics found.`);
  }

  // Group assets by epic binding
  const planLevel: PlanAsset[] = [];
  const byEpic: Record<string, PlanAsset[]> = {};

  for (const asset of assets) {
    const bound = asset.bound_epics || [];
    if (bound.length === 0) {
      planLevel.push(asset);
    } else {
      for (const epic of bound) {
        if (!byEpic[epic]) byEpic[epic] = [];
        byEpic[epic].push(asset);
      }
    }
  }

  const lines = [`🖼 *Assets for \`${planId}\`*`];

  // Summary line: Include ALL epics even if they have no assets
  const parts = [`Plan-level: ${planLevel.length} file(s)`];
  const allEpicRefs = Array.from(new Set([
    ...epics.map(e => e.task_ref),
    ...Object.keys(byEpic),
  ])).sort();

  for (const ref of allEpicRefs) {
    const count = byEpic[ref] ? byEpic[ref].length : 0;
    const label = count === 0 ? 'no assets' : (count === 1 ? '1 file' : `${count} files`);
    parts.push(`${ref}: ${label}`);
  }
  lines.push(parts.join(' | '));
  lines.push('');

  // Plan-level assets
  if (planLevel.length > 0) {
    lines.push('*Plan-level assets:*');
    for (const asset of planLevel.slice(0, 10)) {
      const typeLabel = asset.asset_type && asset.asset_type !== 'unspecified' ? ` [${asset.asset_type}]` : '';
      lines.push(`• \`${asset.original_name}\` → \`${asset.filename}\`${typeLabel} (${formatBytes(asset.size_bytes)})`);
    }
    if (planLevel.length > 10) lines.push(`  …and ${planLevel.length - 10} more`);
    lines.push('');
  }

  // Per-epic assets
  for (const ref of allEpicRefs) {
    const epicAssets = byEpic[ref];
    if (!epicAssets || epicAssets.length === 0) continue;
    
    lines.push(`*${ref}:*`);
    for (const asset of epicAssets.slice(0, 10)) {
      const typeLabel = asset.asset_type && asset.asset_type !== 'unspecified' ? ` [${asset.asset_type}]` : '';
      lines.push(`• \`${asset.original_name}\` → \`${asset.filename}\`${typeLabel} (${formatBytes(asset.size_bytes)})`);
    }
    if (epicAssets.length > 10) lines.push(`  …and ${epicAssets.length - 10} more`);
    lines.push('');
  }

  // Add bind buttons for assets
  const buttons: Button[][] = [];
  
  // Add "Generate Plan" button if assets exist
  if (assets.length > 0) {
    buttons.push([
      { label: '✨ Generate Plan from Assets', callbackData: `asset:generate_plan:${planId}` },
    ]);
  }
  
  // Show up to 4 assets with bind/unbind buttons (Discord has 5-row limit)
  for (const asset of assets.slice(0, 4)) {
    const shortName = asset.original_name.length > 15 ? asset.original_name.slice(0, 12) + '...' : asset.original_name;
    const row: Button[] = [
      { label: `📎 Bind ${shortName}`, callbackData: `asset:bind_pick:${planId}:${asset.filename}` },
    ];
    if ((asset.bound_epics || []).length > 0) {
      row.push({ label: `🔓 Unbind`, callbackData: `asset:unbind_pick:${planId}:${asset.filename}` });
    }
    buttons.push(row);
  }

  if (buttons.length > 0) {
    return menu(lines.join('\n'), buttons);
  }
  return text(lines.join('\n'));
}

const ASSET_TYPE_OPTIONS = [
  { label: 'Design Mockup', value: 'design-mockup' },
  { label: 'API Spec', value: 'api-spec' },
  { label: 'Test Data', value: 'test-data' },
  { label: 'Reference Doc', value: 'reference-doc' },
  { label: 'Config', value: 'config' },
  { label: 'Other', value: 'other' },
];

async function cmdAssetTypeSelector(planId: string, filename: string): Promise<BotResponse> {
  const buttons: Button[][] = [];
  // 2 buttons per row
  for (let i = 0; i < ASSET_TYPE_OPTIONS.length; i += 2) {
    const row: Button[] = [];
    row.push({
      label: ASSET_TYPE_OPTIONS[i].label,
      callbackData: `asset:set_type:${planId}:${filename}:${ASSET_TYPE_OPTIONS[i].value}`
    });
    if (i + 1 < ASSET_TYPE_OPTIONS.length) {
      row.push({
        label: ASSET_TYPE_OPTIONS[i + 1].label,
        callbackData: `asset:set_type:${planId}:${filename}:${ASSET_TYPE_OPTIONS[i + 1].value}`
      });
    }
    buttons.push(row);
  }
  return menu(`What type is this asset?`, buttons);
}

async function cmdAssetsMenu(userId: string, platform: string): Promise<BotResponse> {
  const session = getSession(userId, platform);
  if (
    session.activePlanId
    && session.activePlanId !== 'new'
  ) {
    return cmdAssets(session.activePlanId);
  }

  const buttons = await _planButtons('menu:assets');
  if (!buttons) return text('ℹ️ No plans found.');
  return menu('🖼 *Select a Plan to View Assets:*', buttons);
}

// ── Plan actions ──────────────────────────────────────────────────

async function cmdViewPlan(planId: string): Promise<BotResponse> {
  const data = await api.getPlan(planId);
  if (data?._error) return text(`❌ Plan \`${planId}\` not found.`);
  let content: string = data.plan?.content || data.content || '';
  if (!content) return text(`📄 *Plan: ${planId}*\n_(no markdown content found)_`);
  if (content.length > 3500) content = content.slice(0, 3500) + '\n...[truncated]';
  return text(`📄 *Plan: ${planId}*\n\`\`\`markdown\n${content}\n\`\`\``);
}

async function cmdStartEditing(userId: string, platform: string, planId: string): Promise<BotResponse> {
  setPlan(userId, platform, planId);

  const convId = `connector:${platform}:${userId}`;
  const result = await api.askOpenCodeCommand({
    command: 'edit',
    arguments: planId,
    conversation_id: convId,
    user_id: userId,
    platform,
  });

  if ((result as any)._error) {
    return text(`✏️ *Active plan set to \`${planId}\`*\n\n⚠️ OpenCode error: ${(result as any)._error}\nType /cancel to deselect.`);
  }

  for (const action of result.actions || []) {
    if (action.type === 'plan_created' && action.plan_id) {
      setPlan(userId, platform, action.plan_id);
    }
  }

  return text(result.text || `✏️ *Editing plan \`${planId}\`*\n\nSend your instructions to refine this plan.`);
}

function cmdPromptLaunch(planId: string): BotResponse {
  return menu(`⚠️ *Confirm Launch*\nAre you sure you want to launch \`${planId}\`? This will wipe the current war-rooms.`, [
    [{ label: '🚀 Launch', callbackData: `menu:launch_confirm:${planId}` }],
    [{ label: '❌ Cancel', callbackData: 'menu:launch_cancel' }],
  ]);
}

async function cmdLaunchPlan(planId: string): Promise<BotResponse[]> {
  const data = await api.getPlan(planId);
  if (data?._error) return [text(`❌ Plan \`${planId}\` not found.`)];
  const planContent = data.plan?.content || data.content || '';
  const result = await api.launchPlan(planId, planContent);
  if (result?._error) return [text(`❌ Failed to launch plan: ${result._error}`)];
  return [text(`🚀 *Plan Launched!* \`${planId}\`\n\nUse /dashboard or /status to monitor progress.`)];
}

// ── AI draft / refine ─────────────────────────────────────────────

// processDraft and handleStatefulText removed — all plan creation
// and refinement now goes through askAgent() (OpenCode-backed) with create_plan / refine_plan tools.

// ── EPIC-003: File attachment handling during plan conversations ──

export async function handleFileAttachments(
  userId: string,
  platform: string,
  files: Array<{ name: string; contentType?: string; data: ArrayBuffer | Uint8Array; epicRef?: string; assetType?: string }>,
): Promise<BotResponse[]> {
  const session = getSession(userId, platform);
  const planId = session.activePlanId;

  if (!planId || planId === 'new') {
    return [text('No active plan. Use `/draft <idea>` or `/edit` first, then upload files.')];
  }

  // FIX-4: Forward epic/type metadata from the first file (all files in a batch share context)
  const firstFile = files[0];
  const metadata = {
    epicRef: firstFile?.epicRef,
    assetType: firstFile?.assetType,
  };

  const result = await api.uploadPlanAssets(planId, files, metadata);
  if (result.error) return [text(`Failed to upload: ${result.error}`)];

  const responses: BotResponse[] = [];
  const names = result.assets.map(a => `\`${a.original_name}\``).join(', ');
  responses.push(text(`✅ *Saved ${result.count} file(s)* to plan \`${planId}\`: ${names}`));

  // EPIC-005: Ask for type selector after upload
  if (result.assets.length > 0) {
    // For batch uploads, we apply the type to the first file and potentially others
    // but the selector UI is best served by picking the first filename as reference.
    const first = result.assets[0];
    const typeMenu = await cmdAssetTypeSelector(planId, first.filename);
    typeMenu.text = `🖼 *Classification Needed*\nWhat is the type of the file(s) you just uploaded?`;
    responses.push(typeMenu);
  }

  return responses;
}

function _generateSlug(idea: string): string {
  const stopWords = new Set(['a', 'an', 'the', 'build', 'create', 'make', 'write', 'i', 'want', 'to', 'for', 'of', 'some']);
  const words = idea.replace(/[^a-zA-Z0-9\s]/g, '').toLowerCase().split(/\s+/);
  const meaningful = words.filter(w => !stopWords.has(w));
  const slug = (meaningful.length ? meaningful : words).slice(0, 3).join('-');
  const hash = Math.random().toString(16).slice(2, 6);
  return slug ? `${slug}-${hash}` : `plan-${hash}`;
}

// ── Notification & Feedback commands ──────────────────────────────

async function cmdFeedback(userId: string, platform: string, args: string): Promise<BotResponse[]> {
  const idea = args.trim();
  if (!idea) {
    return [text('📝 *Feedback:* Please include your feedback message.\nUsage: `/feedback <your feedback>`')];
  }
  
  // Try to find the latest active room for this user to associate feedback with
  const { rooms } = await api.getRooms();
  const latestRoom = (rooms && rooms[0]?.room_id) || 'global';
  
  try {
    await api.postComment(latestRoom, `${platform}:${userId}`, idea);
    return [text('✅ *Feedback received!* Thank you for your input. It has been posted to the dashboard.')];
  } catch (err: any) {
    return [text(`❌ Failed to post feedback: ${err.message}`)];
  }
}

async function cmdPreferences(_userId: string, platform: string): Promise<BotResponse[]> {
  const config = registry.getConfig(platform as any);
  if (!config) return [text('❌ Connector configuration not found.')];

  const prefs = config.notification_preferences || { events: [], enabled: true };
  const status = prefs.enabled ? '🔔 *Enabled*' : '🔕 *Disabled*';
  
  const buttons: Button[][] = [
    [{ 
      label: prefs.enabled ? '🔕 Disable All' : '🔔 Enable All', 
      callbackData: `prefs:toggle_global:${!prefs.enabled}` 
    }],
    [{ label: '🎯 Manage Subscriptions', callbackData: 'cmd:subscriptions' }],
    [{ label: '⬅️ Back', callbackData: 'menu:cat:system' }],
  ];

  return [menu(`⚙️ *Notification Preferences*\n\nStatus: ${status}\n\nYou can toggle global notifications or subscribe to specific events.`, buttons)];
}

async function cmdSubscriptions(_userId: string, platform: string): Promise<BotResponse[]> {
  const config = registry.getConfig(platform as any);
  if (!config) return [text('❌ Connector configuration not found.')];

  const prefs = config.notification_preferences || { events: [], enabled: true };
  const events: { id: string; label: string }[] = [
    { id: 'plan_started', label: '🚀 Plan Started' },
    { id: 'epic_passed', label: '✅ EPIC Passed' },
    { id: 'epic_failed', label: '❌ EPIC Failed' },
    { id: 'epic_retry', label: '🔄 EPIC Retry' },
    { id: 'feedback_needed', label: '🤔 Feedback Needed' },
    { id: 'error', label: '⚠️ Errors' },
  ];

  const buttons: Button[][] = events.map(e => {
    const isSubscribed = prefs.events.includes(e.id);
    return [{
      label: `${isSubscribed ? '✅' : '⬜️'} ${e.label}`,
      callbackData: `prefs:toggle_event:${e.id}`
    }];
  });

  buttons.push([{ label: '⬅️ Back', callbackData: 'cmd:preferences' }]);

  return [menu('🎯 *Event Subscriptions*\nSelect which events you want to be notified about:', buttons)];
}

async function cmdProgress(): Promise<BotResponse[]> {
  const { plans } = await api.getPlans();
  const activePlans = plans ? plans.filter(p => p.status !== 'completed' && p.status !== 'failed') : [];
  
  if (activePlans.length === 0) {
    return [text('ℹ️ No active plans found.')];
  }

  const progressLines = activePlans.map(p => {
    const pct = p.pct_complete || 0;
    const bar = '█'.repeat(Math.floor(pct / 10)) + '░'.repeat(10 - Math.floor(pct / 10));
    return `*${p.title || p.plan_id}*\n\`${bar}\` ${pct}%\nStatus: ${p.status}`;
  });

  return [text(`📈 *Current Progress*\n\n${progressLines.join('\n\n')}`)];
}

async function handleToggleGlobal(userId: string, platform: string, enabled: boolean): Promise<BotResponse[]> {
  const config = registry.getConfig(platform as any);
  const prefs = config?.notification_preferences || { events: [], enabled: true };
  await registry.updateConfig(platform as any, {
    notification_preferences: { ...prefs, enabled }
  });
  return cmdPreferences(userId, platform);
}

async function handleToggleEvent(userId: string, platform: string, eventId: string): Promise<BotResponse[]> {
  const config = registry.getConfig(platform as any);
  if (!config) return [];

  const prefs = config.notification_preferences || { events: [], enabled: true };
  let newEvents = [...prefs.events];
  
  if (newEvents.includes(eventId)) {
    newEvents = newEvents.filter(e => e !== eventId);
  } else {
    newEvents.push(eventId);
  }

  await registry.updateConfig(platform as any, {
    notification_preferences: { ...prefs, events: newEvents }
  });
  
  return cmdSubscriptions(userId, platform);
}

// ── Unified router ────────────────────────────────────────────────

// Commands whose execution already flows through the OpenCode session
// (either via askAgent or via api.askOpenCodeCommand). Their results live
// in the server-side session history already, so pushing them to
// pendingContext would replay the same content as a fake user message on
// the next askAgent() call and the model would see it as a duplicate.
const OPENCODE_BACKED_COMMANDS = new Set(['draft', 'edit']);

export async function routeCommand(userId: string, platform: string, command: string, args = ''): Promise<BotResponse[]> {
  const responses = await _routeCommandInner(userId, platform, command, args);

  // Store result in pendingContext so the next askAgent() call can inject
  // it as context for the OpenCode session. Skip for OpenCode-backed
  // commands and session-resetting commands.
  const session = getSession(userId, platform);
  const resultText = responses.map(r => r.text).join('\n').slice(0, 500);
  const skip = command === 'clear' || command === 'cancel' || OPENCODE_BACKED_COMMANDS.has(command);
  if (resultText && !skip) {
    session.pendingContext.push({
      command: `${command} ${args}`.trim(),
      result: resultText,
      timestamp: Date.now(),
    });
    if (session.pendingContext.length > 5) session.pendingContext.shift();
  }

  return responses;
}

async function _routeCommandInner(userId: string, platform: string, command: string, args = ''): Promise<BotResponse[]> {
  switch (command) {
    case 'menu':        return [cmdMenu()];
    case 'help':        return [cmdHelp()];
    case 'dashboard':   return [await cmdDashboard()];
    case 'status':      return [await cmdStatus()];
    case 'plans':       return [await cmdPlans()];
    case 'errors':      return [await cmdErrors()];
    case 'skills':      return [await cmdSkills()];
    case 'new':         return [await cmdNew()];
    case 'restart':     return [await cmdRestart()];
    case 'cancel':
      clearSession(userId, platform);
      return [text('🛑 Session cleared. Active plan deselected.')];
    case 'clear': {
      const session = getSession(userId, platform);
      session.pendingContext = [];
      const convId = `connector:${platform}:${userId}`;
      api.endConversation(convId).catch(err => console.warn('[CLEAR] Failed to end OpenCode session:', err));
      return [text('🧹 Conversation history cleared. The AI will start fresh.')];
    }
    case 'setdir': {
      const dir = args.trim();
      if (!dir) {
        const saved = registry.getConfig(platform as any)?.settings?.working_dir;
        const current = saved || '(default — dashboard project root)';
        return [text(`📂 *Current working directory:* \`${current}\`\n\nUsage: \`/setdir /path/to/project\``)];
      }
      // Persist to session + connector config (survives restarts)
      setWorkingDir(userId, platform, dir);
      await registry.updateConfig(platform as any, {
        settings: { ...registry.getConfig(platform as any)?.settings, working_dir: dir },
      });
      return [text(`📂 *Working directory set to:* \`${dir}\`\n\nAll new plans will target this directory.`)];
    }
    case 'draft': {
      const idea = args.trim();
      if (!idea) {
        return [text('✨ Usage: `/draft <your idea>`\nExample: `/draft build a todo app with authentication`\n\nOr just `@os-twin build me a todo app` — the AI will handle it.')];
      }
      // Run /draft as a real OpenCode slash command. The server resolves
      // .opencode/commands/draft.md (with $ARGUMENTS = idea) and invokes
      // the ostwin agent, which calls ostwin_create_plan. No fabricated
      // user message is injected into the session history.
      const convId = `connector:${platform}:${userId}`;
      const result = await api.askOpenCodeCommand({
        command: 'draft',
        arguments: idea,
        conversation_id: convId,
        user_id: userId,
        platform,
      });
      if ((result as any)._error) {
        return [text(`⚠️ OpenCode command error: ${(result as any)._error}`)];
      }
      // Mirror askAgent's action handling so activePlanId gets set.
      for (const action of result.actions || []) {
        if (action.type === 'plan_created' && action.plan_id) {
          setPlan(userId, platform, action.plan_id);
        }
      }
      return [text(result.text || 'No response.')];
    }
    case 'edit':        return [await cmdEditMenu()];
    case 'assets':      return [await cmdAssetsMenu(userId, platform)];
    case 'startplan':   return [await cmdStartplanMenu()];
    case 'viewplan':    return [await cmdViewplanMenu()];
    case 'feedback':    return await cmdFeedback(userId, platform, args);
    case 'preferences': return await cmdPreferences(userId, platform);
    case 'subscriptions': return await cmdSubscriptions(userId, platform);
    case 'progress':    return await cmdProgress();

    // ── Tier 1 commands ─────────────────────────────────────────
    case 'resume':          return [await cmdResumeMenu()];
    case 'clearplans':      return [await cmdClearPlans()];
    case 'logs':            return [await cmdLogs(args)];
    case 'health':          return [await cmdHealth()];
    // ── Tier 2 commands ─────────────────────────────────────────
    case 'skillsearch':     return [await cmdSkillSearch(args)];
    case 'skillinstall':    return [await cmdSkillInstall(args)];
    case 'skillremove':     return [await cmdSkillRemove(args)];
    case 'skillsync':       return [await cmdSkillSync()];
    case 'roles':           return [await cmdRoles()];
    case 'triage':          return [await cmdTriage(args)];
    case 'launchdashboard': return [await cmdLaunchDashboard()];

    default:            return [text('⚠️ Unknown command. Type /help for a list of commands.')];
  }
}

export async function routeCallback(userId: string, platform: string, callbackData: string): Promise<BotResponse[]> {
  if (callbackData === 'menu:plans')             return [await cmdPlans()];
  if (callbackData === 'menu:cat:monitoring')     return [cmdSubmenuMonitoring()];
  if (callbackData === 'menu:cat:plans')          return [cmdSubmenuPlans()];
  if (callbackData === 'menu:cat:skills')         return [cmdSubmenuSkills()];
  if (callbackData === 'menu:cat:system')         return [cmdSubmenuSystem()];
  if (callbackData === 'menu:main')               return [cmdMenu()];
  if (callbackData === 'menu:launch_cancel')      return [text('🛑 Launch cancelled.')];

  if (callbackData === 'cmd:draft_prompt')
    return [text('✨ Send /draft <your idea> to create a new plan.')];

  if (callbackData === 'cmd:skillsearch_prompt')
    return [text('🔍 Send `/skillsearch <query>` to search the ClawHub marketplace.')];

  if (callbackData.startsWith('cmd:')) {
    const cmd = callbackData.slice(4);
    return routeCommand(userId, platform, cmd);
  }

  if (callbackData.startsWith('menu:view:')) {
    const planId = callbackData.split(':')[2];
    return [await cmdViewPlan(planId)];
  }
  if (callbackData.startsWith('menu:assets:')) {
    const planId = callbackData.split(':')[2];
    return [await cmdAssets(planId)];
  }
  if (callbackData.startsWith('menu:edit:')) {
    const planId = callbackData.split(':')[2];
    return [await cmdStartEditing(userId, platform, planId)];
  }
  if (callbackData.startsWith('menu:launch_prompt:')) {
    const planId = callbackData.split(':')[2];
    return [cmdPromptLaunch(planId)];
  }
  if (callbackData.startsWith('menu:launch_confirm:')) {
    const planId = callbackData.split(':')[2];
    return cmdLaunchPlan(planId);
  }

  if (callbackData.startsWith('prefs:toggle_global:')) {
    const enabled = callbackData.split(':')[2] === 'true';
    return await handleToggleGlobal(userId, platform, enabled);
  }
  if (callbackData.startsWith('prefs:toggle_event:')) {
    const eventId = callbackData.split(':')[2];
    return await handleToggleEvent(userId, platform, eventId);
  }

  // EPIC-005: Asset management callbacks
  if (callbackData.startsWith('asset:bind_pick:')) {
    // asset:bind_pick:<planId>:<filename> — show epic picker
    const parts = callbackData.split(':');
    const planId = parts[2];
    const filename = parts[3];
    const { epics, error } = await api.getPlanEpics(planId);
    if (error) return [text(`⚠️ ${error}`)];
    if (!epics.length) return [text('No epics found in this plan. Define some epics in the plan markdown first.')];
    
    const buttons: Button[][] = epics.map(e => [
      { label: `${e.task_ref}: ${e.title}`, callbackData: `asset:bind:${planId}:${filename}:${e.task_ref}` },
    ]);
    return [menu(`Bind \`${filename}\` to which epic?`, buttons)];
  }
  if (callbackData.startsWith('asset:bind:')) {
    const parts = callbackData.split(':');
    const planId = parts[2];
    const filename = parts[3];
    const epicRef = parts[4];
    const result = await api.bindAsset(planId, filename, epicRef);
    if (result?._error) return [text(`Failed: ${result._error}`)];
    return [text(`Bound \`${filename}\` to ${epicRef}.`)];
  }
  if (callbackData.startsWith('asset:unbind_pick:')) {
    const parts = callbackData.split(':');
    const planId = parts[2];
    const filename = parts[3];
    const { assets } = await api.getPlanAssets(planId);
    const asset = assets.find(a => a.filename === filename);
    const epics = asset?.bound_epics || [];
    if (!epics.length) return [text('This asset is not bound to any epic.')];
    const buttons: Button[][] = epics.map(epic => [
      { label: `Unbind from ${epic}`, callbackData: `asset:unbind:${planId}:${filename}:${epic}` },
    ]);
    return [menu(`Unbind \`${filename}\` from which epic?`, buttons)];
  }
  if (callbackData.startsWith('asset:unbind:')) {
    const parts = callbackData.split(':');
    const planId = parts[2];
    const filename = parts[3];
    const epicRef = parts[4];
    const result = await api.unbindAsset(planId, filename, epicRef);
    if (result?._error) return [text(`Failed: ${result._error}`)];
    return [text(`Unbound \`${filename}\` from ${epicRef}.`)];
  }
  if (callbackData.startsWith('asset:set_type:')) {
    const parts = callbackData.split(':');
    const planId = parts[2];
    const filename = parts[3];
    const assetType = parts[4];
    const result = await api.updateAssetMetadata(planId, filename, { asset_type: assetType });
    if (result?._error) return [text(`Failed: ${result._error}`)];
    return [text(`Set type of \`${filename}\` to ${assetType}.`)];
  }
  // ── Resume, Logs, Triage callbacks ──
  if (callbackData.startsWith('menu:resume_confirm:')) {
    const planId = callbackData.split(':')[2];
    return cmdResumePlan(planId);
  }
  if (callbackData.startsWith('menu:logs:')) {
    const roomId = callbackData.split(':')[2];
    return [await cmdLogs(roomId)];
  }
  if (callbackData.startsWith('menu:triage:')) {
    const roomId = callbackData.split(':')[2];
    return [await cmdTriage(roomId)];
  }

  if (callbackData.startsWith('asset:generate_plan:')) {
    const parts = callbackData.split(':');
    const planId = parts[2];
    
    // Show immediate feedback - return a message that will be sent
    // The actual API call happens here, but we give immediate feedback
    
    try {
      const result = await api.generatePlanFromAssets(planId);
      
      if (result?._error) {
        return [text(`❌ *Generation failed*\n\nError: ${result._error}`)];
      }
      
      if (result.status === 'generated') {
        return [text(
          `✅ *Plan generated successfully!*\n\n` +
          `🤖 The AI has analyzed your ${result.explanation ? 'assets' : 'uploaded files'} and created a structured plan.\n\n` +
          `📝 Next steps:\n` +
          `• Use \`/edit ${planId}\` to review and refine it\n` +
          `• Use \`/launch ${planId}\` to start execution\n\n` +
          `${result.explanation ? `**AI Explanation:** ${result.explanation}` : ''}`
        )];
      }
      
      return [text(`⚠️ Unexpected response from AI. Please try again.`)];
    } catch (error: any) {
      return [text(`❌ *Generation failed*\n\nError: ${error.message || 'Unknown error'}`)];
    }
  }

  return [];
}
