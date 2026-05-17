import { PermissionsBitField, ChatInputCommandInteraction, GuildMember } from 'discord.js';
import { joinVoiceChannel, EndBehaviorType, getVoiceConnection, VoiceConnection } from '@discordjs/voice';
import { pipeline, PassThrough } from 'node:stream';
import fs from 'node:fs';
import path from 'node:path';
import prism from 'prism-media';
import { buildDiscordSlashCommand, requireCommandDef } from '../commands';

// ── Recordings directory ────────────────────────────────────────────
const RECORDINGS_DIR = path.resolve(__dirname, '../../recordings');
if (!fs.existsSync(RECORDINGS_DIR)) fs.mkdirSync(RECORDINGS_DIR, { recursive: true });

// ── Types ───────────────────────────────────────────────────────────

interface UserRecording {
  username: string;
  pcmStream?: PassThrough;
  fileStream: fs.WriteStream;
  filePath: string;
}

interface VoiceSession {
  channelId: string;
  connection: VoiceConnection;
  startedAt: string;
  users: Map<string, UserRecording>;
}

// ── State ───────────────────────────────────────────────────────────

/**
 * Per-guild voice session.
 */
export const sessions = new Map<string, VoiceSession>();

/**
 * Live audio streams keyed by `${guildId}:${userId}`.
 * Each value is a PassThrough emitting raw PCM (48 kHz, 16-bit, stereo).
 */
export const activeStreams = new Map<string, PassThrough>();

/**
 * Clean up a guild's voice session — close all streams, save files, disconnect.
 */
export async function cleanupSession(guildId: string): Promise<{ saved: string[] }> {
  const session = sessions.get(guildId);
  if (!session) return { saved: [] };

  const saved: string[] = [];

  for (const [userId, info] of session.users) {
    const streamKey = `${guildId}:${userId}`;

    // End the PassThrough (this also ends the pipeline)
    if (info.pcmStream && !info.pcmStream.destroyed) {
      info.pcmStream.end();
    }

    // Close the file write stream and wait for it to finish
    if (info.fileStream && !info.fileStream.destroyed) {
      await new Promise<void>((resolve) => {
        info.fileStream.end(resolve);
      });
      saved.push(info.filePath);
      console.log(`💾 [SAVE] ${info.username} — ${info.filePath}`);
    }

    activeStreams.delete(streamKey);
  }

  // Disconnect from voice
  const connection = getVoiceConnection(guildId);
  if (connection) connection.destroy();

  sessions.delete(guildId);
  return { saved };
}

// ── Command ─────────────────────────────────────────────────────────

export const data = buildDiscordSlashCommand(requireCommandDef('join'));

export async function execute(interaction: ChatInputCommandInteraction): Promise<any> {
  const member = interaction.member as GuildMember;
  const voiceChannel = member?.voice?.channel;

  if (!voiceChannel) {
    return interaction.reply({ content: 'You must be in a voice channel first!', flags: 64 });
  }

  // Check bot permissions in the voice channel
  const botPermissions = voiceChannel.permissionsFor(interaction.client.user!);
  if (!botPermissions?.has(PermissionsBitField.Flags.Connect) || !botPermissions?.has(PermissionsBitField.Flags.Speak)) {
    return interaction.reply({ content: 'I need **Connect** and **Speak** permissions in that voice channel!', flags: 64 });
  }

  const guildId = voiceChannel.guild.id;

  // Prevent double-join
  if (sessions.has(guildId)) {
    return interaction.reply({ content: "I'm already in a voice channel! Use `/leave` first.", flags: 64 });
  }

  // Defer immediately to avoid Discord's 3-second interaction timeout
  await interaction.deferReply();

  try {
    const connection = joinVoiceChannel({
      channelId: voiceChannel.id,
      guildId,
      adapterCreator: voiceChannel.guild.voiceAdapterCreator,
      selfDeaf: false,
    });

    // Create session
    const session: VoiceSession = {
      channelId: voiceChannel.id,
      connection,
      startedAt: new Date().toISOString(),
      users: new Map(),
    };
    sessions.set(guildId, session);

    await interaction.editReply({
      content: `Joined **${voiceChannel.name}** — streaming & recording live audio. 🎧\nI'll auto-disconnect and save when everyone leaves.`,
    });

    const receiver = connection.receiver;

    receiver.speaking.on('start', (userId: string) => {
      const streamKey = `${guildId}:${userId}`;

      // Skip if we already have an active opus pipeline for this user
      if (activeStreams.has(streamKey)) return;

      const user = interaction.client.users.cache.get(userId);
      const username = user ? user.username : userId;

      // Get or create the persistent file stream for this user's session
      let userInfo = session.users.get(userId);
      if (!userInfo) {
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
        const filePath = path.join(RECORDINGS_DIR, `${username}-${timestamp}.pcm`);
        const fileStream = fs.createWriteStream(filePath, { flags: 'a' });
        userInfo = { username, fileStream, filePath };
        session.users.set(userId, userInfo);
        console.log(`🎙️ [REC] ${username} — recording file created: ${filePath}`);
      }

      // New PassThrough for this speech segment; tee data to the persistent file
      const pcmStream = new PassThrough();
      pcmStream.on('data', (chunk: Buffer) => {
        if (!userInfo!.fileStream.destroyed) userInfo!.fileStream.write(chunk);
      });

      // Mark this user as actively streaming
      activeStreams.set(streamKey, pcmStream);

      const opusStream = receiver.subscribe(userId, {
        end: {
          behavior: EndBehaviorType.AfterSilence,
          duration: 500,
        },
      });

      const decoder = new prism.opus.Decoder({ rate: 48000, channels: 2, frameSize: 960 });

      console.log(`🎙️ [STREAM] ${username} — speaking...`);

      pipeline(opusStream, decoder, pcmStream, (err) => {
        if (err) {
          console.warn(`❌ [STREAM] ${username} — segment error: ${err.message}`);
          if ((err as any).code !== 'ERR_STREAM_PREMATURE_CLOSE' && userInfo!.fileStream && !userInfo!.fileStream.destroyed) {
            userInfo!.fileStream.destroy();
            console.warn(`❌ [STREAM] ${username} — file stream destroyed due to pipeline crash`);
          }
        } else {
          console.log(`🔇 [STREAM] ${username} — paused (file stays open)`);
        }
        // Only remove the active pipeline marker — file stays open for next segment
        activeStreams.delete(streamKey);
      });
    });

  } catch (error) {
    console.error(error);
    try {
      await interaction.editReply({ content: 'Failed to join the voice channel.' });
    } catch { /* interaction may have expired */ }
  }
}
