/**
 * deploy-commands.ts — Register Discord slash commands with the API.
 *
 * Run: npx tsx src/deploy-commands.ts
 */

import dotenv from 'dotenv';
import path from 'path';
import os from 'os';
import { REST, Routes } from 'discord.js';
import { buildDiscordSlashCommands } from './commands';

dotenv.config({ path: path.join(os.homedir(), '.ostwin', '.env') });
dotenv.config({ path: path.resolve(__dirname, '../../.env') });

const TOKEN = process.env.DISCORD_TOKEN;
const CLIENT_ID = process.env.DISCORD_CLIENT_ID;
const GUILD_ID = process.env.GUILD_ID;

if (!TOKEN || !CLIENT_ID) {
  console.error('Missing DISCORD_TOKEN or DISCORD_CLIENT_ID in .env');
  process.exit(1);
}

const commands = buildDiscordSlashCommands();

const rest = new REST({ version: '10' }).setToken(TOKEN);

(async () => {
  try {
    console.log(`Registering ${commands.length} commands...`);

    const route = GUILD_ID
      ? Routes.applicationGuildCommands(CLIENT_ID, GUILD_ID)
      : Routes.applicationCommands(CLIENT_ID);

    await rest.put(route, { body: commands.map(c => c.toJSON()) });

    console.log(`✅ Successfully registered ${commands.length} commands${GUILD_ID ? ` to guild ${GUILD_ID}` : ' globally'}.`);
  } catch (error) {
    console.error('Failed to register commands:', error);
  }
})();
