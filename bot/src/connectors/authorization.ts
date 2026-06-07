import fs from 'fs';
import os from 'os';
import path from 'path';
import { ConnectorConfig, Platform } from './base';

export type AuthorizedPlatform = Extract<Platform, 'telegram' | 'slack'>;

export interface ChannelItem {
  id: string;
  platform: AuthorizedPlatform;
  kind: 'telegram_chat' | 'slack_user' | 'slack_channel';
  user_id?: string;
  channel_id?: string;
  conversation_id?: string;
  title?: string;
  enabled?: boolean;
  registered_events?: string[];
  created_at: string;
  updated_at: string;
}

export interface PersistAuthorizationResult {
  saved: boolean;
  authorized_users: string[];
}

const DEFAULT_CHANNELS_CONFIG_PATH = path.join(os.homedir(), '.ostwin', 'channels.json');

export function getChannelsConfigPath(): string {
  return process.env.OSTWIN_CHANNELS_CONFIG_FILE || DEFAULT_CHANNELS_CONFIG_PATH;
}

export function isAuthorizedUser(authorizedUsers: Iterable<string>, userId?: string | null): boolean {
  if (!userId) return false;
  return new Set(Array.from(authorizedUsers).map(String)).has(String(userId));
}

function readConfigs(configPath = getChannelsConfigPath()): ConnectorConfig[] {
  if (!fs.existsSync(configPath)) return [];
  try {
    const data = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
    return Array.isArray(data) ? data as ConnectorConfig[] : [];
  } catch (err: any) {
    console.warn(`[AUTH] Failed to read channel config ${configPath}: ${err.message}`);
    return [];
  }
}

function writeConfigs(configs: ConnectorConfig[], configPath = getChannelsConfigPath()): void {
  fs.mkdirSync(path.dirname(configPath), { recursive: true });
  const tmp = `${configPath}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(configs, null, 2) + '\n', 'utf-8');
  fs.renameSync(tmp, configPath);
}

function getOrCreateConfig(configs: ConnectorConfig[], platform: AuthorizedPlatform): ConnectorConfig {
  let config = configs.find(c => c.platform === platform);
  if (!config) {
    config = {
      platform,
      enabled: true,
      credentials: {},
      settings: {},
      authorized_users: [],
      pairing_code: '',
      notification_preferences: { events: [], enabled: true },
    };
    configs.push(config);
  }
  config.authorized_users = Array.isArray(config.authorized_users) ? config.authorized_users.map(String) : [];
  config.settings = config.settings || {};
  config.notification_preferences = config.notification_preferences || { events: [], enabled: true };
  return config;
}

export function persistAuthorizedUser(platform: AuthorizedPlatform, userId: string): PersistAuthorizationResult {
  const configs = readConfigs();
  const config = getOrCreateConfig(configs, platform);
  const normalized = String(userId);
  const before = config.authorized_users.length;
  if (!config.authorized_users.includes(normalized)) {
    config.authorized_users.push(normalized);
  }
  writeConfigs(configs);
  return { saved: config.authorized_users.length !== before, authorized_users: config.authorized_users };
}

export function persistPairingCode(platform: AuthorizedPlatform, pairingCode: string): void {
  const configs = readConfigs();
  const config = getOrCreateConfig(configs, platform);
  config.pairing_code = pairingCode;
  writeConfigs(configs);
}

export function upsertChannelItem(platform: AuthorizedPlatform, item: Omit<ChannelItem, 'platform' | 'created_at' | 'updated_at'>): void {
  const configs = readConfigs();
  const config = getOrCreateConfig(configs, platform);
  const now = new Date().toISOString();
  const existingItems = Array.isArray(config.settings.channel_items) ? config.settings.channel_items as ChannelItem[] : [];
  const existing = existingItems.find(channelItem => channelItem.id === item.id);
  const next: ChannelItem = {
    ...(existing || {}),
    ...item,
    platform,
    created_at: existing?.created_at || now,
    updated_at: now,
  };
  config.settings.channel_items = existing
    ? existingItems.map(channelItem => channelItem.id === item.id ? next : channelItem)
    : [...existingItems, next];
  writeConfigs(configs);
}
