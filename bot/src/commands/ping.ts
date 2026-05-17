import { ChatInputCommandInteraction } from 'discord.js';
import { buildDiscordSlashCommand, requireCommandDef } from '../commands';

export const data = buildDiscordSlashCommand(requireCommandDef('ping'));

export async function execute(interaction: ChatInputCommandInteraction): Promise<void> {
  const sent = await interaction.reply({ content: 'Pinging...', fetchReply: true });
  const latency = sent.createdTimestamp - interaction.createdTimestamp;
  await interaction.editReply(`Pong! Latency is ${latency}ms.`);
}
