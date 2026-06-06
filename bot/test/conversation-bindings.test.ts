import { expect } from 'chai';
import fs from 'fs';
import os from 'os';
import path from 'path';
import {
  bindConversation,
  DEFAULT_PLAN_SUBSCRIPTIONS,
  getActiveBinding,
  getBindingsForPlan,
  parseConversationTarget,
  resetConversationBindingsForTests,
  slackConversationId,
  telegramConversationId,
  unbindConversation,
} from '../src/conversation-bindings';

describe('conversation-bindings', () => {
  let filePath: string;

  beforeEach(() => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ostwin-bindings-'));
    filePath = path.join(dir, 'conversation-bindings.json');
    resetConversationBindingsForTests(filePath);
  });

  afterEach(() => {
    resetConversationBindingsForTests(filePath);
  });

  it('supports Telegram chat and topic conversation IDs', () => {
    expect(telegramConversationId('12345')).to.equal('telegram:chat:12345');
    expect(telegramConversationId('12345', '99')).to.equal('telegram:chat:12345:thread:99');
    expect(parseConversationTarget('telegram:chat:12345:thread:99')).to.deep.equal({
      platform: 'telegram',
      targetId: '12345',
      threadId: '99',
    });
  });

  it('supports Slack channel and thread conversation IDs', () => {
    expect(slackConversationId('T1', 'C1')).to.equal('slack:team:T1:channel:C1');
    expect(slackConversationId('T1', 'C1', '171.42')).to.equal('slack:team:T1:channel:C1:thread:171.42');
    expect(parseConversationTarget('slack:team:T1:channel:C1:thread:171.42')).to.deep.equal({
      platform: 'slack',
      targetId: 'C1',
      threadId: '171.42',
    });
  });

  it('binds, updates, lists, and unbinds a plan conversation', () => {
    const binding = bindConversation({
      conversation_id: 'telegram:chat:12345',
      plan_id: 'pt-example',
      subscriptions: ['plan.run.failed'],
    });

    expect(binding.platform).to.equal('telegram');
    expect(getActiveBinding('telegram:chat:12345')?.plan_id).to.equal('pt-example');
    expect(getBindingsForPlan('pt-example')).to.have.length(1);

    bindConversation({ conversation_id: 'telegram:chat:12345', plan_id: 'pt-new' });
    expect(getBindingsForPlan('pt-example')).to.have.length(0);
    expect(getBindingsForPlan('pt-new')).to.have.length(1);
    expect(unbindConversation('telegram:chat:12345')).to.equal(true);
    expect(getActiveBinding('telegram:chat:12345')).to.equal(null);
  });

  it('rejects invalid conversation IDs', () => {
    expect(() => bindConversation({ conversation_id: 'telegram:12345', plan_id: 'pt-example' })).to.throw('Invalid conversation_id');
  });

  it('defaults to normalized retry and legacy system error subscriptions', () => {
    expect(DEFAULT_PLAN_SUBSCRIPTIONS).to.include('epic.retrying');
    expect(DEFAULT_PLAN_SUBSCRIPTIONS).to.not.include('epic.retry');
    expect(DEFAULT_PLAN_SUBSCRIPTIONS).to.include('system.error');

    const binding = bindConversation({
      conversation_id: 'telegram:chat:defaults',
      plan_id: 'pt-defaults',
    });

    expect(binding.subscriptions).to.include('epic.retrying');
    expect(binding.subscriptions).to.include('system.error');
  });
});
