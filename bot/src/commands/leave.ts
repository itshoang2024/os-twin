import { ChatInputCommandInteraction, TextChannel } from 'discord.js';
import { getVoiceConnection } from '@discordjs/voice';
import path from 'node:path';
import { cleanupSession } from './join';
import { transcribeAndLaunch } from '../audio-transcript';
import { buildDiscordSlashCommand, requireCommandDef } from '../commands';

export const data = buildDiscordSlashCommand(requireCommandDef('leave'));

export async function execute(interaction: ChatInputCommandInteraction): Promise<any> {
  const guildId = interaction.guildId!;
  const connection = getVoiceConnection(guildId);

  if (!connection) {
    return interaction.reply({ content: "I'm not in a voice channel!", flags: 64 });
  }

  await interaction.deferReply();

  const { saved } = await cleanupSession(guildId);

  const fileList = saved.length
    ? saved.map(f => `\`${path.basename(f)}\``).join(', ')
    : 'No audio was recorded.';

  console.log(`👋 [LEAVE] Disconnected from guild ${guildId}, saved ${saved.length} file(s)`);
  await interaction.editReply({
    content: `Disconnected and saved recordings. 👋\n📁 ${fileList}`,
  });

  // Auto-pipeline: transcribe → plan → launch
  if (saved.length > 0) {
    const channel = interaction.channel as TextChannel | null;

    const send = async (msg: string) => {
      try { await channel?.send(msg); } catch { /* best effort */ }
    };

    const result = await transcribeAndLaunch(saved, send);

    if (result.error) {
      await send(`⚠️ Voice-to-code pipeline: ${result.error}`);
    } else {
      let summary = `🎙→📝→🚀 *Voice-to-Code Complete!*\n\nPlan \`${result.planId}\` launched.`;
      summary += `\nUse /dashboard or /status to monitor progress.`;

      if (result.transcription.length < 1500) {
        summary += `\n\n*Transcription:*\n${result.transcription}`;
      }
      await send(summary);
    }
  }
}
