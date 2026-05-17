import { expect } from 'chai';
import sinon from 'sinon';
import api from '../src/api';
import { askAgent, type AgentResponse } from '../src/agent-bridge';
import { getSession, clearSession } from '../src/sessions';
import { type AttachmentMeta } from '../src/connectors/base';

function mockResponse(text: string, overrides?: Record<string, unknown>) {
  return { text, conversation_id: 'test-conv', actions: [], ...overrides };
}

describe('agent-bridge', () => {
  let sandbox: sinon.SinonSandbox;

  beforeEach(() => {
    sandbox = sinon.createSandbox();
  });

  afterEach(() => {
    sandbox.restore();
  });

  describe('OpenCode API forwarding', () => {
    it('calls api.askOpenCode for non-trivial messages', async () => {
      const askOpenCodeStub = sandbox.stub(api, 'askOpenCode').resolves(
        mockResponse('Here is the status of your plan.'),
      );

      const result = await askAgent('what is the status of plan-001?', {
        userId: 'u1',
        platform: 'discord',
      });

      expect(askOpenCodeStub.calledOnce).to.be.true;
      expect(askOpenCodeStub.firstCall.args[0].message).to.equal('what is the status of plan-001?');
      expect(askOpenCodeStub.firstCall.args[0].conversation_id).to.equal('connector:discord:u1');
      expect(result.text).to.equal('Here is the status of your plan.');
    });

    it('passes user_id and platform in the request', async () => {
      const askOpenCodeStub = sandbox.stub(api, 'askOpenCode').resolves(mockResponse('ok'));

      await askAgent('build me a todo app', { userId: 'user42', platform: 'telegram' });

      expect(askOpenCodeStub.firstCall.args[0].user_id).to.equal('user42');
      expect(askOpenCodeStub.firstCall.args[0].platform).to.equal('telegram');
    });

    it('passes attachments when provided', async () => {
      const askOpenCodeStub = sandbox.stub(api, 'askOpenCode').resolves(mockResponse('ok'));

      await askAgent('build this', {
        userId: 'u1',
        platform: 'discord',
        attachments: [{ name: 'mockup.png', contentType: 'image/png', sizeBytes: 2048 }],
      });

      const callArgs = askOpenCodeStub.firstCall.args[0];
      expect(callArgs.attachments!.length).to.equal(1);
      expect(callArgs.attachments![0].name).to.equal('mockup.png');
    });

    it('passes referencedMessageContent when provided', async () => {
      const askOpenCodeStub = sandbox.stub(api, 'askOpenCode').resolves(mockResponse('ok'));

      await askAgent('yes do that', {
        userId: 'u1',
        platform: 'discord',
        referencedMessageContent: 'What is the status of EPIC-001?',
      });

      expect(askOpenCodeStub.firstCall.args[0].referenced_message_content).to.equal('What is the status of EPIC-001?');
    });

    it('returns error message when api.askOpenCode fails', async () => {
      sandbox.stub(api, 'askOpenCode').rejects(new Error('Connection refused'));

      const result = await askAgent('test question', { userId: 'u1', platform: 'discord' });

      expect(result.text).to.include('Failed to get a response');
    });

    it('returns error when api.askOpenCode returns _error', async () => {
      sandbox.stub(api, 'askOpenCode').resolves(mockResponse('err', { _error: 'session expired' }));

      const result = await askAgent('test question', { userId: 'u1', platform: 'discord' });

      expect(result.text).to.include('OpenCode chat error');
    });
  });

  describe('structured actions from response', () => {
    it('updates session activePlanId when plan_created action received', async () => {
      clearSession('action-u1', 'discord');
      sandbox.stub(api, 'askOpenCode').resolves(mockResponse('Plan created!', {
        actions: [{ type: 'plan_created', plan_id: 'my-cool-plan' }],
      }));

      const result = await askAgent('build me a todo app', { userId: 'action-u1', platform: 'discord' });

      expect(result.text).to.equal('Plan created!');
      const session = getSession('action-u1', 'discord');
      expect(session.activePlanId).to.equal('my-cool-plan');
      clearSession('action-u1', 'discord');
    });
  });

  describe('backward compatibility', () => {
    it('works without ctx parameter (old signature)', async () => {
      sandbox.stub(api, 'askOpenCode').resolves(mockResponse('Hello!'));

      const result = await askAgent('hello');
      expect(result.text).to.be.a('string');
    });

    it('accepts ctx parameter for tool execution', async () => {
      sandbox.stub(api, 'askOpenCode').resolves(mockResponse('ok'));

      const result = await askAgent('hello', { userId: 'u1', platform: 'discord' });
      expect(result.text).to.be.a('string');
    });
  });

  describe('function signature', () => {
    it('askAgent is exported as an async function', () => {
      expect(typeof askAgent).to.equal('function');
    });

    it('returns an object with text property', async () => {
      sandbox.stub(api, 'askOpenCode').resolves(mockResponse('response'));
      const result = await askAgent('test', { userId: 'u1', platform: 'discord' });
      expect(result).to.have.property('text');
    });
  });

  describe('AgentContext interface', () => {
    it('accepts referencedMessageContent', () => {
      const ctx: { userId: string; platform: string; referencedMessageContent?: string } = {
        userId: '806867494702809108',
        platform: 'discord',
        referencedMessageContent: 'What is the status of EPIC-001?',
      };
      expect(ctx.referencedMessageContent).to.equal('What is the status of EPIC-001?');
    });

    it('works without referencedMessageContent (backward compat)', () => {
      const ctx: { userId: string; platform: string; referencedMessageContent?: string } = {
        userId: '806867494702809108',
        platform: 'discord',
      };
      expect(ctx.referencedMessageContent).to.be.undefined;
    });
  });

  describe('attachment context', () => {
    it('AgentContext accepts attachments array', () => {
      const ctx: { userId: string; platform: string; attachments?: AttachmentMeta[] } = {
        userId: 'u1',
        platform: 'discord',
        attachments: [
          { name: 'mockup.png', contentType: 'image/png', sizeBytes: 2048 },
          { name: 'spec.pdf', contentType: 'application/pdf', sizeBytes: 10240 },
        ],
      };
      expect(ctx.attachments).to.have.length(2);
    });
  });
});

describe('fast-path classifier', () => {
  let sandbox: sinon.SinonSandbox;

  beforeEach(() => {
    sandbox = sinon.createSandbox();
    clearSession('fast-u1', 'discord');
  });

  afterEach(() => {
    sandbox.restore();
    clearSession('fast-u1', 'discord');
  });

  it('skips API call for greeting messages', async () => {
    const askOpenCodeStub = sandbox.stub(api, 'askOpenCode');

    const result = await askAgent('hello', { userId: 'fast-u1', platform: 'discord' });
    expect(result.text).to.be.a('string');
    expect(result.text.length).to.be.greaterThan(0);
    expect(askOpenCodeStub.called).to.be.false;
  });

  it('skips API call for thanks messages', async () => {
    const askOpenCodeStub = sandbox.stub(api, 'askOpenCode');

    const result = await askAgent('thanks!', { userId: 'fast-u1', platform: 'discord' });
    expect(result.text).to.be.a('string');
    expect(askOpenCodeStub.called).to.be.false;
  });

  it('skips API call for acknowledgments', async () => {
    const askOpenCodeStub = sandbox.stub(api, 'askOpenCode');

    const result = await askAgent('ok', { userId: 'fast-u1', platform: 'discord' });
    expect(result.text).to.be.a('string');
    expect(askOpenCodeStub.called).to.be.false;
  });

  it('skips API call for goodbye messages', async () => {
    const askOpenCodeStub = sandbox.stub(api, 'askOpenCode');

    const result = await askAgent('bye!', { userId: 'fast-u1', platform: 'discord' });
    expect(result.text).to.include('session');
    expect(askOpenCodeStub.called).to.be.false;
  });

  it('does NOT skip API call for long messages', async () => {
    sandbox.stub(api, 'askOpenCode').resolves(mockResponse('ok'));

    const result = await askAgent(
      'hello I want to build a complex system with many features and requirements',
      { userId: 'fast-u1', platform: 'discord' },
    );
    expect(result.text).to.be.a('string');
  });

  it('does NOT skip API call when attachments are present', async () => {
    sandbox.stub(api, 'askOpenCode').resolves(mockResponse('ok'));

    const result = await askAgent('hello', {
      userId: 'fast-u1',
      platform: 'discord',
      attachments: [{ name: 'file.png', contentType: 'image/png', sizeBytes: 1024 }],
    });
    expect(result.text).to.be.a('string');
  });
});

describe('pendingContext injection', () => {
  let sandbox: sinon.SinonSandbox;

  beforeEach(() => {
    sandbox = sinon.createSandbox();
    clearSession('ctx-u1', 'discord');
  });

  afterEach(() => {
    sandbox.restore();
    clearSession('ctx-u1', 'discord');
  });

  it('prepends pendingContext to message when present', async () => {
    const askOpenCodeStub = sandbox.stub(api, 'askOpenCode').resolves(mockResponse('ok'));

    const session = getSession('ctx-u1', 'discord');
    session.pendingContext.push({
      command: 'plans',
      result: 'Plan 1 (draft), Plan 2 (running)',
      timestamp: Date.now(),
    });

    await askAgent('show me more details', { userId: 'ctx-u1', platform: 'discord' });

    const sentMessage = askOpenCodeStub.firstCall.args[0].message;
    expect(sentMessage).to.include('User ran: /plans');
    expect(sentMessage).to.include('Plan 1 (draft)');
    expect(sentMessage).to.include("User's follow-up: show me more details");
    // pendingContext should be cleared after injection
    expect(session.pendingContext).to.have.length(0);
  });
});

describe('AgentResponse type', () => {
  let sandbox: sinon.SinonSandbox;

  beforeEach(() => {
    sandbox = sinon.createSandbox();
  });

  afterEach(() => {
    sandbox.restore();
  });

  it('returns object with text property', async () => {
    sandbox.stub(api, 'askOpenCode').resolves(mockResponse('response'));
    const result = await askAgent('test', { userId: 'u1', platform: 'discord' });
    expect(result).to.have.property('text');
    expect(result.text).to.be.a('string');
  });

  it('returns undefined attachments when none produced', async () => {
    sandbox.stub(api, 'askOpenCode').resolves(mockResponse('response'));
    const result = await askAgent('test', { userId: 'u1', platform: 'discord' });
    expect(result.attachments).to.be.undefined;
  });
});
