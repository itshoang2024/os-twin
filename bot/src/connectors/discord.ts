import {
  Client,
  GatewayIntentBits,
  Collection,
  ActionRowBuilder,
  ButtonBuilder,
  ButtonStyle,
  ChatInputCommandInteraction,
  Message,
  VoiceState,
  TextChannel,
  REST,
  Routes,
} from 'discord.js';
import fs from 'fs';
import fsp from 'fs/promises';
import path from 'path';
import { EOL } from 'os';

import { Platform, Connector, ConnectorConfig, ConnectorStatus, HealthCheckResult, SetupStep, ValidationResult } from './base';
import {
  routeCommand,
  routeCallback,
  BotResponse,
  Button,
  buildDiscordSlashCommands,
  getCommandDef,
  isDeferredCommand,
  requireCommandDef,
} from '../commands';
import { askAgent } from '../agent-bridge';
import { getSession } from '../sessions';
import { transcribeAndLaunch } from '../audio-transcript';
import { mdConvert, chunk, detectEpicRef, guessAssetType } from './utils';
import api, { PlanAsset } from '../api';
import { stageAttachments, flushStagedAttachments, getStagedCount } from '../asset-staging';

// Voice command imports
import * as pingCommand from '../commands/ping';
import * as joinCommand from '../commands/join';
import * as leaveCommand from '../commands/leave';

export interface VoiceCommand {
  data: { name: string };
  execute: (interaction: ChatInputCommandInteraction) => Promise<any>;
}

interface LogEntry {
  id: string;
  guildId: string;
  channelId: string;
  channelName: string;
  userId: string;
  username: string;
  content: string;
  timestamp: string;
  referencedMessageId?: string;
}

const DISCORD_MSG_LIMIT = 2000;
const LOGS_DIR = path.resolve(__dirname, '../../logs');

export class DiscordConnector implements Connector {
  public readonly platform: Platform = 'discord';
  public status: ConnectorStatus = 'disconnected';
  public client: Client | null = null;
  private voiceCommands: Collection<string, VoiceCommand> = new Collection();
  private allowedChannels: Set<string> | null = null;  // null = all channels

  constructor() {
    if (!fs.existsSync(LOGS_DIR)) fs.mkdirSync(LOGS_DIR, { recursive: true });
    
    const vCmds: Array<{ name: string; command: VoiceCommand }> = [
      { name: 'ping', command: pingCommand },
      { name: 'join', command: joinCommand },
      { name: 'leave', command: leaveCommand },
    ];
    for (const { name, command } of vCmds) {
      const def = requireCommandDef(name);
      if (!def.discordOnly) {
        throw new Error(`Voice command "${name}" must be marked discordOnly in COMMAND_REGISTRY`);
      }
      this.voiceCommands.set(def.name, command);
    }
  }

  public async start(config: ConnectorConfig): Promise<void> {
    const token = config.credentials.token;
    const clientId = config.credentials.client_id;
    const guildId = config.credentials.guild_id;

    if (!token || !clientId) {
      this.status = 'error';
      throw new Error('Discord token or client_id is missing in credentials');
    }

    // Load channel restrictions from settings
    const channels = config.settings?.allowed_channels;
    this.allowedChannels = Array.isArray(channels) && channels.length
      ? new Set(channels.map(String))
      : null;

    if (this.allowedChannels) {
      console.log(`[DISCORD] Channel filter: ${[...this.allowedChannels].join(', ')}`);
    }

    this.status = 'connecting';
    this.client = new Client({
      intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent,
        GatewayIntentBits.GuildVoiceStates,
      ],
    });

    this.client.on('interactionCreate', async (interaction) => {
      // Channel restriction: ignore interactions from non-allowed text channels
      const channelId = interaction.channelId;
      if (this.allowedChannels && channelId && !this.allowedChannels.has(channelId)) {
        if (interaction.isRepliable()) {
          await interaction.reply({ content: '⚠️ This bot is restricted to specific channels.', flags: 64 as const }).catch(() => {});
        }
        return;
      }

      if (interaction.isButton()) {
        const userId = String(interaction.user.id);
        const data = interaction.customId;

        await interaction.deferUpdate().catch(() => {});
        const responses = await routeCallback(userId, 'discord', data);
        if (responses.length) {
          await this.sendToChannel(interaction.channel as TextChannel, responses);
        }
        return;
      }

      if (!interaction.isChatInputCommand()) return;

      const commandName = interaction.commandName;
      const voiceCmd = this.voiceCommands.get(commandName);
      if (voiceCmd) {
        // Voice channel restriction: check if the user's voice channel is allowed
        if (this.allowedChannels && (commandName === 'join' || commandName === 'leave')) {
          const member = interaction.member as any;
          const voiceChannelId = member?.voice?.channelId;
          if (voiceChannelId && !this.allowedChannels.has(voiceChannelId)) {
            await interaction.reply({ content: '⚠️ This bot is restricted to specific voice channels.', flags: 64 as const }).catch(() => {});
            return;
          }
        }
        try {
          await voiceCmd.execute(interaction);
        } catch (error) {
          console.error(`[CMD ERROR] ${commandName}:`, error);
          const msg = { content: 'There was an error executing this command!', flags: 64 as const };
          if (interaction.replied || interaction.deferred) {
            await interaction.followUp(msg).catch(() => {});
          } else {
            await interaction.reply(msg).catch(() => {});
          }
        }
        return;
      }

      const userId = String(interaction.user.id);
      if (isDeferredCommand(commandName)) await interaction.deferReply();

      // Extract args from the registry-defined option name
      const cmdDef = getCommandDef(commandName);
      let args = '';
      if (cmdDef?.arg) {
        args = interaction.options.getString(cmdDef.arg) || '';
      }

      const responses = await routeCommand(userId, 'discord', commandName, args);
      await this.sendToInteraction(interaction, responses);
    });

    this.client.on('messageCreate', async (message: Message) => {
      if (message.author.bot) return;
      if (!message.guild) return;
      if (this.allowedChannels && !this.allowedChannels.has(message.channel.id)) return;

      const entry: LogEntry = {
        id: message.id,
        guildId: message.guild.id,
        channelId: message.channel.id,
        channelName: (message.channel as TextChannel).name || 'unknown',
        userId: message.author.id,
        username: message.author.username,
        content: message.content,
        timestamp: message.createdAt.toISOString(),
        referencedMessageId: message.reference?.messageId,
      };

      const logFile = path.join(LOGS_DIR, `${entry.channelName}-${entry.channelId}.jsonl`);
      fsp.appendFile(logFile, JSON.stringify(entry) + EOL)
        .catch(err => console.warn('[LOG] Failed to persist:', err.message));

      const userId = String(message.author.id);
      const session = getSession(userId, 'discord');
      
      // Update activeEpicRef if found in message content
      const msgEpic = detectEpicRef(message.content);
      if (msgEpic) {
        session.activeEpicRef = msgEpic;
      }

      const botUserId = this.client?.user?.id;
      const isMention = !!(botUserId && message.mentions.has(botUserId));
      const attachments = message.attachments ? Array.from(message.attachments.values()) : [];
      

      // ── Handle attachments: save immediately or stage for later ──
      const hasAttachments = attachments.length > 0;
      const canSaveNow = session.activePlanId && session.activePlanId !== 'new';

      if (hasAttachments) {
        if (canSaveNow) {
          // Plan exists → save immediately (existing fast path)
          const assetResponses: BotResponse[] = [];
          const uploadResult = await this.persistAttachments(session.activePlanId!, attachments, message.content, session.activeEpicRef);
          if (uploadResult.saved.length > 0) {
            assetResponses.push({ text: this.formatSavedAssets(session.activePlanId!, uploadResult.saved) });
          }
          if (uploadResult.failures.length > 0) {
            assetResponses.push({ text: this.formatFailedAssets(uploadResult.failures) });
          }
          if (assetResponses.length > 0) {
            await this.sendToChannel(message.channel as TextChannel, assetResponses);
          }
        } else {
          // No plan yet → download from CDN and stage in session buffer
          const epicRef = detectEpicRef(message.content) || session.activeEpicRef;
          console.log(`[DISCORD] Staging ${attachments.length} attachment(s) for user ${userId}`);
          const stageResult = await stageAttachments(userId, 'discord',
            attachments.map(a => ({ url: a.url, name: a.name || 'attachment', contentType: a.contentType })),
            epicRef,
          );
          console.log(`[DISCORD] Stage result:`, { staged: stageResult.staged, failed: stageResult.failed, rejected: stageResult.rejected });

          if (stageResult.rejected) {
            await this.sendToChannel(message.channel as TextChannel, [{
              text: '⚠️ Staged files exceed the 50MB limit. Upload large files via the dashboard.',
            }]);
          } else if (stageResult.staged > 0) {
            const noun = stageResult.staged === 1 ? 'file' : 'files';
            await this.sendToChannel(message.channel as TextChannel, [{
              text: `📎 Holding ${stageResult.staged} ${noun} — processing your request...`,
            }]);
          }
          if (stageResult.failedNames.length > 0) {
            await this.sendToChannel(message.channel as TextChannel, [{
              text: this.formatFailedAssets(stageResult.failedNames.map(n => `${n}: download failed`)),
            }]);
          }
        }
      }

      // ── @mention: route to plan refine when editing, otherwise Q&A ──
      if (isMention) {
        const question = message.content
          .replace(new RegExp(`<@!?${this.client!.user!.id}>`, 'g'), '')
          .trim();

        if (!question && attachments.length === 0) return;

        // All @mentions go through askAgent() — the AI decides whether to
        // refine a plan, check status, or take other actions via tool-calling.
        // Trigger if there's text OR attachments (attachment-only = user wants assets processed)
        if (question || hasAttachments) {
          (message.channel as TextChannel).sendTyping().catch(() => {});

          // Build the prompt — if no text but files attached, describe what was sent
          const agentQuestion = question
            || `I've attached ${attachments.length} file(s): ${attachments.map(a => a.name || 'file').join(', ')}. Please use them to create a plan.`;

          console.log(`🤖 [AGENT] ${entry.username} asked: ${agentQuestion}`);

          // Fetch referenced message content if this is a reply
          let referencedMessageContent: string | undefined;
          if (message.reference?.messageId) {
            try {
              const referencedMsg = await (message.channel as TextChannel).messages.fetch(message.reference.messageId);
              referencedMessageContent = referencedMsg.content;
              console.log(`[DISCORD] Reply context: "${referencedMessageContent?.slice(0, 100)}..."`);
            } catch (err) {
              console.warn(`[DISCORD] Failed to fetch referenced message: ${err}`);
            }
          }

          // Build attachment metadata so the agent knows files are staged
          const attachmentMeta = hasAttachments
            ? attachments.map(a => ({ name: a.name || 'attachment', contentType: a.contentType, sizeBytes: a.size }))
            : undefined;

          try {
            const result = await askAgent(agentQuestion, { 
              userId, 
              platform: 'discord',
              referencedMessageContent,
              attachments: attachmentMeta,
            });

            // Build reply with optional file attachments (e.g. memory graph)
            const discordText = result.text.length > 1900
              ? result.text.slice(0, 1900) + '\n\n*…(truncated)*'
              : result.text;
            const replyOptions: any = { content: discordText };
            if (result.attachments?.length) {
              const { AttachmentBuilder } = await import('discord.js');
              replyOptions.files = result.attachments.map(
                (a) => new AttachmentBuilder(a.buffer, { name: a.name })
              );
            }
            await message.reply(replyOptions);
          } catch (err: any) {
            console.error('❌ [AGENT] Bridge error:', err);
            await message.reply('⚠️ Sorry, I couldn\'t reach the ostwin backend.').catch(() => {});
          }

          // Flush staged attachments if plan was created by the agent
          await this.flushStagedIfReady(userId, message.channel as TextChannel);
        }
        return;
      }

      // Non-mention messages in Discord are not routed to the AI.
      // Users must @mention the bot to interact.
    });

    // Register commands
    await this.deployCommands(token, clientId, guildId);

    this.client.once('ready', () => {
      console.log(`[DISCORD] Logged in as ${this.client?.user?.tag}`);
      this.status = 'connected';
    });

    this.client.on('voiceStateUpdate', (oldState: VoiceState, _newState: VoiceState) => {
      const leftChannel = oldState.channel;
      if (!leftChannel) return;

      try {
        const guildId = leftChannel.guild.id;
        const session = joinCommand.sessions.get(guildId);
        if (!session) return;
        if (leftChannel.id !== session.channelId) return;

        const humans = leftChannel.members.filter(m => !m.user.bot).size;
        if (humans === 0) {
          console.log(`📭 [AUTO] All users left ${leftChannel.name} — saving and disconnecting...`);
          joinCommand.cleanupSession(guildId)
            .then(async ({ saved }) => {
              if (saved.length > 0) {
                const guild = leftChannel.guild;
                const textChannel = guild.channels.cache.find(
                  ch => ch.isTextBased() && !ch.isVoiceBased()
                    && (!this.allowedChannels || this.allowedChannels.has(ch.id))
                ) as TextChannel | undefined;

                const send = async (msg: string) => {
                  try { await textChannel?.send(msg); } catch { /* best effort */ }
                };

                const result = await transcribeAndLaunch(saved, send);
                if (result.error) {
                  await send(`⚠️ Voice-to-code: ${result.error}`);
                } else {
                  await send(`🎙→📝→🚀 *Voice-to-Code Complete!*\nPlan \`${result.planId}\` launched. Use /dashboard to monitor.`);
                }
              }
            })
            .catch(err => console.error('[AUTO] Cleanup error:', err.message));
        }
      } catch {
        // Voice commands not available, ignore
      }
    });

    await this.client.login(token);
  }

  public async stop(): Promise<void> {
    if (this.client) {
      this.client.destroy();
      this.client = null;
    }
    this.status = 'disconnected';
  }

  public async healthCheck(): Promise<HealthCheckResult> {
    if (this.status !== 'connected' || !this.client || !this.client.isReady()) {
      return { status: 'unhealthy', message: `Client is ${this.status}` };
    }
    return { status: 'healthy', details: { ping: this.client.ws.ping } };
  }

  public async sendMessage(targetId: string, response: BotResponse): Promise<void> {
    if (!this.client) throw new Error('Discord bot not started');
    if (this.allowedChannels && !this.allowedChannels.has(targetId)) {
      console.warn(`[DISCORD] Blocked sendMessage to non-allowed channel ${targetId}`);
      return;
    }
    const channel = await this.client.channels.fetch(targetId);
    if (channel?.isTextBased()) {
      await this.sendToChannel(channel as TextChannel, [response]);
    } else {
      throw new Error(`Channel ${targetId} is not text-based`);
    }
  }

  public getSetupInstructions(): SetupStep[] {
    return [
      {
        title: 'Create Discord App',
        description: 'Create an application on Discord Developer Portal.',
        instructions: '1. Go to https://discord.com/developers/applications\n2. Click "New Application"\n3. Go to "Bot" section and copy the Token.',
      }
    ];
  }

  public validateConfig(config: ConnectorConfig): ValidationResult {
    const errors: string[] = [];
    if (!config.credentials.token) errors.push('Missing Discord token');
    if (!config.credentials.client_id) errors.push('Missing Discord client_id');
    return {
      valid: errors.length === 0,
      errors: errors.length > 0 ? errors : undefined,
    };
  }

  /**
   * Flush staged attachments if a plan now exists in the session.
   * Optionally sends confirmation/failure messages to the given channel.
   * Returns BotResponse[] for inline use.
   */
  private async flushStagedIfReady(userId: string, channel?: TextChannel): Promise<BotResponse[]> {
    const session = getSession(userId, 'discord');
    const responses: BotResponse[] = [];

    if (getStagedCount(userId, 'discord') > 0 && session.activePlanId && session.activePlanId !== 'new') {
      const flushResult = await flushStagedAttachments(userId, 'discord', session.activePlanId);
      if (flushResult.saved.length > 0) {
        responses.push({ text: this.formatSavedAssets(session.activePlanId, flushResult.saved as PlanAsset[]) });
      }
      if (flushResult.failures.length > 0) {
        responses.push({ text: this.formatFailedAssets(flushResult.failures) });
      }
      if (channel && responses.length > 0) {
        await this.sendToChannel(channel, responses);
      }
    }

    return responses;
  }

  private async persistAttachments(
    planId: string,
    attachments: Array<{ url?: string; name?: string; contentType?: string | null }>,
    messageContent?: string,
    contextEpicRef?: string
  ): Promise<{ saved: PlanAsset[]; failures: string[] }> {
    const failures: string[] = [];
    const downloadable: Array<{ name: string; contentType?: string; data: Uint8Array }> = [];

    // Detect epic ref from current message content or fallback to session context
    const msgEpic = messageContent ? detectEpicRef(messageContent) : undefined;
    const epicRef = msgEpic || contextEpicRef;

    for (const attachment of attachments) {
      const displayName = attachment.name || 'attachment';
      if (!attachment.url) {
        failures.push(`${displayName}: missing download URL`);
        continue;
      }

      try {
        const response = await fetch(attachment.url);
        if (!response.ok) {
          failures.push(`${displayName}: download failed (${response.status})`);
          continue;
        }

        downloadable.push({
          name: displayName,
          contentType: attachment.contentType || response.headers.get('content-type') || undefined,
          data: new Uint8Array(await response.arrayBuffer()),
        });
      } catch (error: any) {
        failures.push(`${displayName}: ${error.message}`);
      }
    }

    if (!downloadable.length) {
      return { saved: [], failures };
    }

    // Guess asset type from the first file in the batch (they usually share context)
    const firstFile = downloadable[0];
    const assetType = guessAssetType(firstFile.name, firstFile.contentType);

    const uploadResult = await api.uploadPlanAssets(planId, downloadable, {
      epicRef,
      assetType,
    });
    if (uploadResult.error) {
      failures.push(uploadResult.error);
      return { saved: [], failures };
    }

    return { saved: uploadResult.assets, failures };
  }

  private formatSavedAssets(planId: string, assets: PlanAsset[]): string {
    const first = assets[0];
    const epicLabel = (first.bound_epics && first.bound_epics.length > 0)
      ? ` for ${first.bound_epics[0]}`
      : '';
    const typeLabel = (first.asset_type && first.asset_type !== 'other')
      ? ` as ${first.asset_type}`
      : '';

    if (assets.length === 1) {
      return `✅ Saved \`${first.original_name}\`${typeLabel}${epicLabel}.`;
    }

    const lines = [`🖼 *Saved ${assets.length} asset(s) to \`${planId}\`${epicLabel}:*`];
    for (const asset of assets.slice(0, 10)) {
      lines.push(`• \`${asset.original_name}\` → \`${asset.filename}\``);
    }
    if (assets.length > 10) {
      lines.push(`…and ${assets.length - 10} more asset(s).`);
    }
    return lines.join('\n');
  }

  private formatFailedAssets(failures: string[]): string {
    const lines = ['⚠️ *Some attachments could not be saved:*'];
    for (const failure of failures.slice(0, 10)) {
      lines.push(`• ${failure}`);
    }
    if (failures.length > 10) {
      lines.push(`…and ${failures.length - 10} more issue(s).`);
    }
    return lines.join('\n');
  }

  private buildButtons(buttons: Button[][]): ActionRowBuilder<ButtonBuilder>[] {
    const rows: ActionRowBuilder<ButtonBuilder>[] = [];
    const dangerPrefixes = ['menu:launch_confirm', 'cmd:restart', 'cmd:new'];
    for (const row of buttons.slice(0, 5)) {
      const actionRow = new ActionRowBuilder<ButtonBuilder>();
      for (const btn of row.slice(0, 5)) {
        let style = ButtonStyle.Primary;
        if (btn.callbackData.includes('Back') || btn.callbackData === 'menu:main') {
          style = ButtonStyle.Secondary;
        } else if (dangerPrefixes.some(p => btn.callbackData.startsWith(p))) {
          style = ButtonStyle.Danger;
        }
        actionRow.addComponents(
          new ButtonBuilder()
            .setCustomId(btn.callbackData)
            .setLabel(btn.label)
            .setStyle(style)
        );
      }
      rows.push(actionRow);
    }
    return rows;
  }

  private async sendToInteraction(interaction: ChatInputCommandInteraction, responses: BotResponse[]): Promise<void> {
    let first = true;
    for (const resp of responses) {
      const convertedText = mdConvert(resp.text || '');
      const components = resp.buttons ? this.buildButtons(resp.buttons) : [];
      const chunksArr = chunk(convertedText, DISCORD_MSG_LIMIT);

      for (let i = 0; i < chunksArr.length; i++) {
        const payload = {
          content: chunksArr[i],
          components: i === 0 ? components : [],
        };

        if (first && !interaction.replied && !interaction.deferred) {
          await interaction.reply(payload);
          first = false;
        } else {
          await interaction.followUp(payload);
        }
      }
    }
  }

  private async sendToChannel(channel: TextChannel, responses: BotResponse[]): Promise<void> {
    for (const resp of responses) {
      const convertedText = mdConvert(resp.text || '');
      const components = resp.buttons ? this.buildButtons(resp.buttons) : [];
      const chunksArr = chunk(convertedText, DISCORD_MSG_LIMIT);
      for (let i = 0; i < chunksArr.length; i++) {
        await channel.send({
          content: chunksArr[i],
          components: i === 0 ? components : [],
        });
      }
    }
  }

  private async deployCommands(token: string, clientId: string, guildId?: string): Promise<void> {
    // Build slash commands from the centralized COMMAND_REGISTRY
    const commands = buildDiscordSlashCommands();

    const rest = new REST({ version: '10' }).setToken(token);
    try {
      console.log(`[DISCORD] Registering ${commands.length} commands...`);
      const route = guildId
        ? Routes.applicationGuildCommands(clientId, guildId)
        : Routes.applicationCommands(clientId);
      await rest.put(route, { body: commands.map(c => c.toJSON()) });
      console.log(`[DISCORD] Successfully registered commands.`);
    } catch (error: any) {
      console.error('[DISCORD] Failed to register commands:', error.message);
    }
  }
}
