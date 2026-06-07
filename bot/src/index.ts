/**
 * index.ts — Entry point for the unified OS Twin bot.
 *
 * Refactored to use ConnectorRegistry for a plugin-driven lifecycle.
 */

// Node 20+ "Happy Eyeballs" tries IPv6 first; if IPv6 is unreachable
// the fallback to IPv4 can stall.  Force IPv4-first for reliability.
import dns from 'dns';
dns.setDefaultResultOrder('ipv4first');

import './logger';

// config.ts loads .env from the project root — import it first
import './config';
import config from './config';
import { registry } from './connectors/registry';
import { TelegramConnector } from './connectors/telegram';
import { DiscordConnector } from './connectors/discord';
import { SlackConnector } from './connectors/slack';
import { ConnectorConfig } from './connectors/base';
import { NotificationRouter } from './notifications';
import { flushSessionsSync } from './sessions';

function dashboardWebSocketUrl(dashboardUrl: string): string {
  const base = dashboardUrl.replace(/\/$/, '');
  if (base.startsWith('https://')) return `${base.replace(/^https:\/\//, 'wss://')}/api/ws`;
  if (base.startsWith('http://')) return `${base.replace(/^http:\/\//, 'ws://')}/api/ws`;
  return 'ws://localhost:3366/api/ws';
}

console.log('╔═══════════════════════════════════╗');
console.log('║   OS Twin — Unified Bot Gateway   ║');
console.log('╚═══════════════════════════════════╝');

async function main() {
  const notificationRouter = new NotificationRouter(registry, dashboardWebSocketUrl(config.DASHBOARD_URL));

  const tgConnector = new TelegramConnector();
  const dcConnector = new DiscordConnector();
  const slackConnector = new SlackConnector();

  // Register built-in connectors
  registry.register(tgConnector);
  registry.register(dcConnector);
  registry.register(slackConnector);

  // Load configs from ~/.ostwin/channels.json
  await registry.loadConfigs();

  // Seed default configs from .env if missing in registry
  const tgConfig = registry.getConfig('telegram');
  if (!tgConfig && config.TELEGRAM_BOT_TOKEN) {
    console.log('[REGISTRY] Seeding Telegram config from .env...');
    const defaultTg: ConnectorConfig = {
      platform: 'telegram',
      enabled: true,
      credentials: { token: config.TELEGRAM_BOT_TOKEN },
      settings: {},
      authorized_users: process.env.TELEGRAM_CHAT_ID ? [process.env.TELEGRAM_CHAT_ID] : [],
      pairing_code: process.env.TELEGRAM_PAIRING_CODE || '',
      notification_preferences: { events: [], enabled: true },
    };
    await registry.updateConfig('telegram', defaultTg);
  }

  const dcConfig = registry.getConfig('discord');
  const dcAllowedChannels = process.env.DISCORD_ALLOWED_CHANNELS
    ? process.env.DISCORD_ALLOWED_CHANNELS.split(',').map(s => s.trim()).filter(Boolean)
    : [];
  if (!dcConfig && config.DISCORD_TOKEN) {
    console.log('[REGISTRY] Seeding Discord config from .env...');
    const defaultDc: ConnectorConfig = {
      platform: 'discord',
      enabled: true,
      credentials: {
        token: config.DISCORD_TOKEN,
        client_id: config.DISCORD_CLIENT_ID,
        guild_id: config.GUILD_ID,
      },
      settings: { allowed_channels: dcAllowedChannels },
      authorized_users: [],
      pairing_code: '',
      notification_preferences: { events: [], enabled: true },
    };
    await registry.updateConfig('discord', defaultDc);
  } else if (dcConfig && dcAllowedChannels.length) {
    // Always sync channel restrictions from .env — they take priority
    await registry.updateConfig('discord', {
      settings: { ...dcConfig.settings, allowed_channels: dcAllowedChannels },
    });
  }

  const slackConfig = registry.getConfig('slack');
  if (!slackConfig && config.SLACK_BOT_TOKEN) {
    console.log('[REGISTRY] Seeding Slack config from .env...');
    const defaultSlack: ConnectorConfig = {
      platform: 'slack',
      enabled: true,
      credentials: {
        token: config.SLACK_BOT_TOKEN,
        appToken: config.SLACK_APP_TOKEN,
        signingSecret: config.SLACK_SIGNING_SECRET,
      },
      settings: {},
      authorized_users: [],
      pairing_code: '',
      notification_preferences: { events: [], enabled: true },
    };
    await registry.updateConfig('slack', defaultSlack);
  }

  // Start all enabled connectors
  await registry.startAll();

  // Start notification router
  notificationRouter.start();

  // Graceful stop
  const shutdown = async () => {
    console.log('\n[REGISTRY] Shutting down all connectors...');
    flushSessionsSync();
    notificationRouter.stop();
    await registry.stopAll();
    process.exit(0);
  };

  process.once('SIGINT', shutdown);
  process.once('SIGTERM', shutdown);
}

main().catch(err => {
  console.error('[INDEX] Fatal startup error:', err);
  process.exit(1);
});
