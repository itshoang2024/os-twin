import https from 'https';
import { Telegraf, Markup, Context } from 'telegraf';
import { Platform, Connector, ConnectorConfig, ConnectorStatus, HealthCheckResult, SetupStep, ValidationResult } from './base';
import {
  routeCommand,
  routeCallback,
  BotResponse,
  cmdUnknown,
  getCommandsForPlatform,
  getCommandsWithArgsForPlatform,
  getCommandsWithoutArgsForPlatform,
} from '../commands';
import { getSession, getStagedFiles } from '../sessions';
import { askAgent } from '../agent-bridge';
import { flushStagedAttachments, getStagedCount } from '../asset-staging';

function escapeMarkdown(text: string): string {
  return text.replace(/([_*\[\]()`~>#+\-=|{}.!\\])/g, '\\$1');
}

async function safeReply(ctx: Context, text: string): Promise<void> {
  const truncated = text.length > 4000 ? text.slice(0, 4000) + '\n\n_(truncated)_' : text;
  try {
    await ctx.reply(truncated, { parse_mode: 'Markdown' });
  } catch {
    await ctx.reply(escapeMarkdown(truncated), { parse_mode: 'Markdown' });
  }
}

// Force IPv4 — IPv6 to Telegram's servers is unreachable on many networks,
// and Node 20's Happy Eyeballs fallback can stall instead of recovering.
const ipv4Agent = new https.Agent({ keepAlive: true, keepAliveMsecs: 10000, family: 4 });

export class TelegramConnector implements Connector {
  public readonly platform: Platform = 'telegram';
  public status: ConnectorStatus = 'disconnected';
  public bot: Telegraf | null = null;
  private authorizedChats: Set<string> = new Set();
  private pairingCode: string = '';

  public async start(config: ConnectorConfig): Promise<void> {
    const token = config.credentials.token;
    if (!token) {
      this.status = 'error';
      throw new Error('Telegram bot token is missing in credentials');
    }

    this.status = 'connecting';
    this.pairingCode = config.pairing_code || Math.random().toString(16).slice(2, 10);
    this.authorizedChats = new Set(config.authorized_users || []);

    this.bot = new Telegraf(token, { telegram: { agent: ipv4Agent } });

    // ── Authorization middleware ──────────────────────────────────
    this.bot.use(async (ctx, next) => {
      const chatId = String(ctx.chat?.id);
      if (!chatId) return;

      // Always allow /pair
      if ((ctx.message as any)?.text?.startsWith('/pair')) return next();

      // Check authorization (allow if no chats configured yet = first user)
      if (this.authorizedChats.size > 0 && !this.authorizedChats.has(chatId)) {
        await ctx.reply(
          `🔒 *Unauthorized.* This bot is private. Use \`/pair ${this.pairingCode}\` to authorize.`,
          { parse_mode: 'Markdown' }
        );
        return;
      }

      return next();
    });

    // ── /pair command ─────────────────────────────────────────────
    this.bot.command('pair', async (ctx) => {
      const chatId = String(ctx.chat.id);
      const args = ctx.message.text.split(/\s+/).slice(1).join(' ');
      if (args === this.pairingCode) {
        this.authorizedChats.add(chatId);
        // Note: In a real app, we should probably persist this back to config
        await ctx.reply('✅ *Pairing successful!* You are now authorized.', { parse_mode: 'Markdown' });
      } else {
        await ctx.reply('❌ *Invalid pairing code.*', { parse_mode: 'Markdown' });
      }
    });

    // ── Slash commands (no arguments) — driven by COMMAND_REGISTRY
    for (const def of getCommandsWithoutArgsForPlatform(this.platform)) {
      this.bot.command(def.name, async (ctx) => {
        const userId = String(ctx.chat.id);
        const responses = await routeCommand(userId, 'telegram', def.name);
        await this.sendResponses(ctx, responses);
      });
    }

    // Commands with inline arguments — driven by COMMAND_REGISTRY
    for (const def of getCommandsWithArgsForPlatform(this.platform)) {
      const cmdName = def.name;
      this.bot.command(cmdName, async (ctx) => {
        const userId = String(ctx.chat.id);
        const args = ctx.message.text.replace(new RegExp(`^\\/${cmdName}(@\\S+)?`), '').trim();
        const responses = await routeCommand(userId, 'telegram', cmdName, args);
        await this.sendResponses(ctx, responses);
      });
    }

    // ── Callback queries (inline keyboard buttons) ────────────────
    this.bot.on('callback_query', async (ctx) => {
      const cbQuery = ctx.callbackQuery;
      const userId = String((cbQuery as any).message?.chat?.id);
      const data = (cbQuery as any).data as string | undefined;
      if (!userId || !data) return;

      await ctx.answerCbQuery();

      const responses = await routeCallback(userId, 'telegram', data);
      await this.sendResponsesChat(userId, responses);
    });

    // ── Free text ──
    this.bot.on('text', async (ctx) => {
      const userId = String(ctx.chat.id);
      const msgText = ctx.message.text.trim();

      // Skip if it's a registered command (already handled by command handlers above)
      const registeredCmds = new Set(getCommandsForPlatform(this.platform).map(c => c.name));
      const cmdName = msgText.replace(/^\/([a-zA-Z0-9_]+).*/, '$1');
      if (msgText.startsWith('/') && registeredCmds.has(cmdName)) return;

      // Unknown slash command — show fallback menu instead of routing to the LLM
      if (msgText.startsWith('/')) {
        await this.sendResponses(ctx, [cmdUnknown(msgText, 'telegram')]);
        return;
      }
      {
        // Idle: use AI agent with tool-calling (can create plans, check status, etc.)
        try {
          // Include staged file metadata so the agent knows assets are available
          const stagedFiles = getStagedFiles(userId, 'telegram');
          const attachments = stagedFiles.length > 0
            ? stagedFiles.map(f => ({ name: f.name, contentType: f.contentType, sizeBytes: f.sizeBytes }))
            : undefined;
          const result = await askAgent(msgText, { userId, platform: 'telegram', attachments });
          await safeReply(ctx, result.text);
          // Send image attachments as photos
          if (result.attachments?.length) {
            for (const att of result.attachments) {
              await ctx.replyWithPhoto({ source: att.buffer, filename: att.name }).catch(() => {});
            }
          }
        } catch (err: any) {
          console.warn('[TELEGRAM] Agent bridge error:', err.message);
          await ctx.reply('⚠️ Failed to process your request.', { parse_mode: 'Markdown' });
        }
      }

      // After text routing: flush staged attachments if plan now exists
      const updatedSession = getSession(userId, 'telegram');
      if (getStagedCount(userId, 'telegram') > 0 && updatedSession.activePlanId && updatedSession.activePlanId !== 'new') {
        const flushResult = await flushStagedAttachments(userId, 'telegram', updatedSession.activePlanId);
        if (flushResult.saved.length > 0) {
          const names = flushResult.saved.map(a => `\`${a.original_name}\``).join(', ');
          await ctx.reply(`📎 Saved ${flushResult.saved.length} asset(s): ${names}`, { parse_mode: 'Markdown' });
        }
        if (flushResult.failures.length > 0) {
          await ctx.reply(`⚠️ Some assets could not be saved: ${flushResult.failures.join(', ')}`, { parse_mode: 'Markdown' });
        }
      }
    });

    const handleTelegramFiles = async (ctx: Context) => {
      if (!ctx.chat) return;
      const userId = String(ctx.chat.id);
      const msg = ctx.message as any;
      const session = getSession(userId, 'telegram');
      const canSaveNow = session.activePlanId && session.activePlanId !== 'new';

      const files: any[] = [];
      
      const isPhoto = !!msg.photo;
      if (msg.document) {
        files.push(msg.document);
      } else if (msg.photo) {
        // Take the largest photo
        files.push(msg.photo[msg.photo.length - 1]);
      } else if (msg.audio) {
        files.push(msg.audio);
      } else if (msg.voice) {
        files.push(msg.voice);
      }

      if (!files.length) return;

      const downloadable: any[] = [];
      for (const f of files) {
        const fileId = f.file_id;
        const link = await ctx.telegram.getFileLink(fileId);
        const fileName = f.file_name || `file_${fileId.slice(-8)}`;
        // Telegram photos are always JPEG; they don't have mime_type property
        const mimeType = f.mime_type || (isPhoto ? 'image/jpeg' : 'application/octet-stream');
        
        try {
          const res = await fetch(link.href);
          if (!res.ok) continue;
          const buffer = await res.arrayBuffer();
          downloadable.push({
            name: fileName,
            contentType: mimeType,
            data: new Uint8Array(buffer),
          });
        } catch (err) {
          console.warn(`[TELEGRAM] Failed to download ${fileName}:`, err);
        }
      }

      if (downloadable.length > 0) {
        if (canSaveNow) {
          // Plan exists → save immediately
          const { handleFileAttachments } = await import('../commands');
          const responses = await handleFileAttachments(userId, 'telegram', downloadable);
          await this.sendResponses(ctx, responses);
        } else {
          // No plan yet → stage in session buffer
          // Files are already downloaded, put directly into session
          for (const d of downloadable) {
            session.pendingAttachments.push({
              data: d.data,
              name: d.name,
              mimeType: d.contentType || 'application/octet-stream',
              stagedAt: Date.now(),
            });
          }
          const noun = downloadable.length === 1 ? 'file' : 'files';

          // If caption text is provided, route to agent immediately with attachment info
          const caption = (msg.caption || '').trim();
          if (caption) {
            try {
              const attachments = downloadable.map(d => ({ name: d.name, contentType: d.contentType, sizeBytes: d.data.byteLength }));
              const result = await askAgent(caption, { userId, platform: 'telegram', attachments });
              await safeReply(ctx, result.text);
            } catch (err: any) {
              console.warn('[TELEGRAM] Agent bridge error:', err.message);
              await ctx.reply('⚠️ Failed to process your request.', { parse_mode: 'Markdown' });
            }

            // Flush staged attachments if plan was created
            const updatedSession = getSession(userId, 'telegram');
            if (getStagedCount(userId, 'telegram') > 0 && updatedSession.activePlanId && updatedSession.activePlanId !== 'new') {
              const flushResult = await flushStagedAttachments(userId, 'telegram', updatedSession.activePlanId);
              if (flushResult.saved.length > 0) {
                const names = flushResult.saved.map(a => `\`${a.original_name}\``).join(', ');
                await ctx.reply(`📎 Saved ${flushResult.saved.length} asset(s): ${names}`, { parse_mode: 'Markdown' });
              }
            }
          } else {
            await ctx.reply(
              `📎 Holding ${downloadable.length} ${noun}. Send me your idea or use /edit to attach them to a plan.`,
              { parse_mode: 'Markdown' },
            );
          }
        }
      }
    };

    this.bot.on('document', handleTelegramFiles);
    this.bot.on('photo', handleTelegramFiles);
    this.bot.on('audio', handleTelegramFiles);
    this.bot.on('voice', handleTelegramFiles);

    // ── Register command menu with Telegram ───────────────────────
    // Register ALL platform commands with Telegram's autocomplete menu
    await this.bot.telegram.setMyCommands(
      getCommandsForPlatform(this.platform).map(def => ({
        command: def.name,
        description: def.telegramMenu || def.description,
      })),
    ).catch(err => console.warn('[TELEGRAM] Failed to register commands:', err.message));

    // bot.launch() never resolves — it runs the polling loop forever.
    // Fire-and-forget so the connector start() can complete.
    this.bot.launch({ dropPendingUpdates: true })
      .catch(err => console.error('[TELEGRAM] Polling error:', err.message));
    this.status = 'connected';
    console.log(`[TELEGRAM] Connector started. (pairing code: ${this.pairingCode})`);
  }

  public async stop(): Promise<void> {
    if (this.bot) {
      await this.bot.stop();
      this.bot = null;
    }
    this.status = 'disconnected';
  }

  public async healthCheck(): Promise<HealthCheckResult> {
    if (this.status !== 'connected' || !this.bot) {
      return { status: 'unhealthy', message: `Bot is ${this.status}` };
    }
    try {
      await this.bot.telegram.getMe();
      return { status: 'healthy' };
    } catch (error: any) {
      return { status: 'unhealthy', message: error.message };
    }
  }

  public async sendMessage(targetId: string, response: BotResponse): Promise<void> {
    if (!this.bot) throw new Error('Telegram bot not started');
    await this.sendResponsesChat(targetId, [response]);
  }

  public getSetupInstructions(): SetupStep[] {
    return [
      {
        title: 'Create a Bot',
        description: 'Talk to @BotFather on Telegram to create a new bot.',
        instructions: '1. Send /newbot to @BotFather\n2. Follow the prompts to name your bot\n3. Copy the API Token provided.',
      },
      {
        title: 'Configure Token',
        description: 'Add your bot token to the configuration.',
        instructions: 'Paste the token into the "token" field in credentials.',
      }
    ];
  }

  public validateConfig(config: ConnectorConfig): ValidationResult {
    const errors: string[] = [];
    if (!config.credentials.token) {
      errors.push('Missing Telegram bot token');
    }
    return {
      valid: errors.length === 0,
      errors: errors.length > 0 ? errors : undefined,
    };
  }

  private static buildKeyboard(buttons: BotResponse['buttons']) {
    return buttons!.map(row =>
      row.map(btn =>
        btn.url ? Markup.button.url(btn.label, btn.url) : Markup.button.callback(btn.label, btn.callbackData)
      )
    );
  }

  private async sendResponses(ctx: Context, responses: BotResponse[]): Promise<void> {
    for (const resp of responses) {
      const text = resp.text.length > 4000 ? resp.text.slice(0, 4000) + '\n\n_(truncated)_' : resp.text;
      if (resp.buttons && resp.buttons.length) {
        const keyboard = TelegramConnector.buildKeyboard(resp.buttons);
        try {
          await ctx.reply(text, { parse_mode: 'Markdown', ...Markup.inlineKeyboard(keyboard) });
        } catch {
          await ctx.reply(escapeMarkdown(text), { parse_mode: 'Markdown', ...Markup.inlineKeyboard(keyboard) });
        }
      } else {
        await safeReply(ctx, resp.text);
      }
    }
  }

  private async sendResponsesChat(chatId: string, responses: BotResponse[]): Promise<void> {
    if (!this.bot) return;
    for (const resp of responses) {
      const text = resp.text.length > 4000 ? resp.text.slice(0, 4000) + '\n\n_(truncated)_' : resp.text;
      if (resp.buttons && resp.buttons.length) {
        const keyboard = TelegramConnector.buildKeyboard(resp.buttons);
        try {
          await this.bot.telegram.sendMessage(chatId, text, { parse_mode: 'Markdown', ...Markup.inlineKeyboard(keyboard) });
        } catch {
          await this.bot.telegram.sendMessage(chatId, escapeMarkdown(text), { parse_mode: 'Markdown', ...Markup.inlineKeyboard(keyboard) });
        }
      } else {
        try {
          await this.bot.telegram.sendMessage(chatId, text, { parse_mode: 'Markdown' });
        } catch {
          await this.bot.telegram.sendMessage(chatId, escapeMarkdown(text), { parse_mode: 'Markdown' });
        }
      }
    }
  }
}
