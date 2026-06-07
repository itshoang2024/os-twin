import { expect } from 'chai';
import fs from 'fs';
import os from 'os';
import path from 'path';
import {
  isAuthorizedUser,
  persistAuthorizedUser,
  persistPairingCode,
  upsertChannelItem,
} from '../src/connectors/authorization';

describe('connector authorization persistence', () => {
  let dir: string;
  let configPath: string;
  const previousConfigPath = process.env.OSTWIN_CHANNELS_CONFIG_FILE;

  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ostwin-auth-'));
    configPath = path.join(dir, 'channels.json');
    process.env.OSTWIN_CHANNELS_CONFIG_FILE = configPath;
    fs.writeFileSync(configPath, JSON.stringify([
      {
        platform: 'telegram',
        enabled: true,
        credentials: { token: 'redacted' },
        settings: {},
        authorized_users: [],
        pairing_code: 'pairme',
        notification_preferences: { events: [], enabled: true },
      },
    ], null, 2));
  });

  afterEach(() => {
    if (previousConfigPath === undefined) delete process.env.OSTWIN_CHANNELS_CONFIG_FILE;
    else process.env.OSTWIN_CHANNELS_CONFIG_FILE = previousConfigPath;
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it('requires an explicit authorized user instead of allowing empty owner lists', () => {
    expect(isAuthorizedUser([], '123')).to.equal(false);
    expect(isAuthorizedUser(['123'], '123')).to.equal(true);
    expect(isAuthorizedUser(['123'], '456')).to.equal(false);
  });

  it('persists paired Telegram users to channels.json without duplicating', () => {
    persistAuthorizedUser('telegram', '123');
    persistAuthorizedUser('telegram', '123');

    const configs = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
    expect(configs[0].authorized_users).to.deep.equal(['123']);
    expect(configs[0].credentials.token).to.equal('redacted');
  });

  it('persists generated pairing codes so dashboard and logs stay consistent', () => {
    persistPairingCode('telegram', 'generated1');

    const configs = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
    expect(configs[0].pairing_code).to.equal('generated1');
  });

  it('stores channel_items under platform settings for owner notification targets', () => {
    upsertChannelItem('telegram', {
      id: '123',
      kind: 'telegram_chat',
      user_id: '123',
      channel_id: '123',
      conversation_id: 'telegram:chat:123',
      title: 'Owner',
    });

    const configs = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
    expect(configs[0].settings.channel_items).to.have.length(1);
    expect(configs[0].settings.channel_items[0].conversation_id).to.equal('telegram:chat:123');
  });
});
