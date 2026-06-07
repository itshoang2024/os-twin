import { expect } from 'chai';
import sinon from 'sinon';
import { NotificationRouter } from '../src/notifications';
import { registry } from '../src/connectors/registry';
import { Connector } from '../src/connectors/base';
import { bindConversation, resetConversationBindingsForTests } from '../src/conversation-bindings';

describe('NotificationRouter', () => {
  let sandbox: sinon.SinonSandbox;
  let router: NotificationRouter;
  let mockConnector: any;

  beforeEach(() => {
    resetConversationBindingsForTests();
    sandbox = sinon.createSandbox();
    mockConnector = {
      platform: 'telegram',
      status: 'connected',
      sendMessage: sandbox.stub().resolves(),
    };
    sandbox.stub(registry, 'getConnector').returns(mockConnector);
    sandbox.stub(registry, 'getAllConfigs').returns([
      {
        platform: 'telegram',
        enabled: true,
        authorized_users: ['u1'],
        notification_preferences: { events: [], enabled: true },
        credentials: {},
        settings: {},
        pairing_code: '',
      } as any,
    ]);
    sandbox.stub(registry, 'getConfig').returns({
      platform: 'telegram',
      enabled: true,
      authorized_users: ['u1'],
      notification_preferences: { events: [], enabled: true },
      credentials: {},
      settings: {},
      pairing_code: '',
    } as any);
    router = new NotificationRouter(registry);
  });

  afterEach(() => {
    sandbox.restore();
    resetConversationBindingsForTests();
  });

  it('maps room_created to plan_started', async () => {
    bindConversation({ conversation_id: 'telegram:chat:u1', plan_id: 'plan-legacy' });
    const handleEvent = (router as any).handleDashboardEvent.bind(router);
    handleEvent({
      type: 'room_created',
      data: { room: { room_id: 'room-1', task_ref: 'Task 1', plan_id: 'plan-legacy' } },
    });

    // Wait a bit for async routing
    await new Promise(resolve => setTimeout(resolve, 10));

    expect(mockConnector.sendMessage.calledOnce).to.be.true;
    expect(mockConnector.sendMessage.firstCall.args[0]).to.equal('telegram:chat:u1');
    expect(mockConnector.sendMessage.firstCall.args[1].text).to.include('New War-Room Created');
    expect(mockConnector.sendMessage.firstCall.args[1].text).to.include('room-1');
  });

  it('maps room_updated with status done to epic_passed', async () => {
    bindConversation({ conversation_id: 'telegram:chat:u1', plan_id: 'plan-legacy' });
    const handleEvent = (router as any).handleDashboardEvent.bind(router);
    handleEvent({
      type: 'room_updated',
      data: { room: { room_id: 'room-1', status: 'done', plan_id: 'plan-legacy' } },
    });

    await new Promise(resolve => setTimeout(resolve, 10));

    expect(mockConnector.sendMessage.calledOnce).to.be.true;
    expect(mockConnector.sendMessage.firstCall.args[1].text).to.include('EPIC Done');
  });

  it('maps room_updated with status failed to epic_failed', async () => {
    bindConversation({ conversation_id: 'telegram:chat:u1', plan_id: 'plan-legacy' });
    const handleEvent = (router as any).handleDashboardEvent.bind(router);
    handleEvent({
      type: 'room_updated',
      data: { room: { room_id: 'room-1', status: 'failed', plan_id: 'plan-legacy' } },
    });
    await new Promise(resolve => setTimeout(resolve, 10));
    expect(mockConnector.sendMessage.firstCall.args[1].text).to.include('EPIC Failed');
  });

  it('maps room_updated with status optimize to epic_retry', async () => {
    bindConversation({ conversation_id: 'telegram:chat:u1', plan_id: 'plan-legacy' });
    const handleEvent = (router as any).handleDashboardEvent.bind(router);
    handleEvent({
      type: 'room_updated',
      data: { room: { room_id: 'room-1', status: 'optimize', plan_id: 'plan-legacy' } },
    });
    await new Promise(resolve => setTimeout(resolve, 10));
    expect(mockConnector.sendMessage.firstCall.args[1].text).to.include('EPIC Retrying');
  });

  it('maps room_updated with status pending_feedback to feedback_needed', async () => {
    bindConversation({ conversation_id: 'telegram:chat:u1', plan_id: 'plan-legacy' });
    const handleEvent = (router as any).handleDashboardEvent.bind(router);
    handleEvent({
      type: 'room_updated',
      data: { room: { room_id: 'room-1', status: 'pending_feedback', plan_id: 'plan-legacy' } },
    });
    await new Promise(resolve => setTimeout(resolve, 10));
    expect(mockConnector.sendMessage.firstCall.args[1].text).to.include('Feedback Needed');
  });

  it('maps room_updated with status error to error notification', async () => {
    bindConversation({ conversation_id: 'telegram:chat:u1', plan_id: 'plan-legacy' });
    const handleEvent = (router as any).handleDashboardEvent.bind(router);
    handleEvent({
      type: 'room_updated',
      data: { room: { room_id: 'room-1', status: 'error', plan_id: 'plan-legacy' } },
    });
    await new Promise(resolve => setTimeout(resolve, 10));
    expect(mockConnector.sendMessage.firstCall.args[1].text).to.include('System Error');
  });

  it('handles plans_updated (no notification)', async () => {
    const handleEvent = (router as any).handleDashboardEvent.bind(router);
    handleEvent({
      type: 'plans_updated',
      data: {},
    });
    await new Promise(resolve => setTimeout(resolve, 10));
    expect(mockConnector.sendMessage.called).to.be.false;
  });

  it('maps orchestration epic.failed to epic_failed with fail-fast payload details', async () => {
    bindConversation({ conversation_id: 'telegram:chat:u1', plan_id: 'plan-1' });
    const handleEvent = (router as any).handleDashboardEvent.bind(router);
    handleEvent({
      type: 'orchestration.event',
      data: {
        event: {
          event_type: 'epic.failed',
          plan_id: 'plan-1',
          run_id: 'run-1',
          room_id: 'room-3',
          epic_ref: 'EPIC-003',
          role: 'qa',
          summary: 'EPIC failed',
          payload: { reason: 'retry_exhausted' },
          last_message: { body_preview: 'QA found a blocking issue' },
        },
      },
    });
    await new Promise(resolve => setTimeout(resolve, 10));
    expect(mockConnector.sendMessage.calledOnce).to.be.true;
    expect(mockConnector.sendMessage.firstCall.args[0]).to.equal('telegram:chat:u1');
    const text = mockConnector.sendMessage.firstCall.args[1].text;
    expect(text).to.include('EPIC Failed');
    expect(text).to.include('plan-1');
    expect(text).to.include('run-1');
    expect(text).to.include('EPIC-003');
    expect(text).to.include('QA found a blocking issue');
  });

  it('maps orchestration plan.run.failed to plan_failed with failed epic summary', async () => {
    bindConversation({ conversation_id: 'telegram:chat:u1', plan_id: 'plan-2' });
    const handleEvent = (router as any).handleDashboardEvent.bind(router);
    handleEvent({
      type: 'orchestration.event',
      data: {
        event: {
          event_type: 'plan.run.failed',
          plan_id: 'plan-2',
          run_id: 'run-2',
          payload: {
            reason: 'role_run_failed',
            failed_epic: {
              plan_id: 'plan-2',
              run_id: 'run-2',
              room_id: 'room-4',
              epic_ref: 'EPIC-004',
              role: 'engineer',
              last_message: { body_preview: 'Process exited 7' },
            },
          },
        },
      },
    });
    await new Promise(resolve => setTimeout(resolve, 10));
    expect(mockConnector.sendMessage.calledOnce).to.be.true;
    const text = mockConnector.sendMessage.firstCall.args[1].text;
    expect(text).to.include('Plan Failed');
    expect(text).to.include('plan-2');
    expect(text).to.include('run-2');
    expect(text).to.include('EPIC-004');
    expect(text).to.include('Process exited 7');
  });

  it('routes normalized events only to bindings for the matching plan and subscription', async () => {
    bindConversation({ conversation_id: 'telegram:chat:u1', plan_id: 'plan-1', subscriptions: ['plan.run.failed'] });
    bindConversation({ conversation_id: 'telegram:chat:u2', plan_id: 'plan-2', subscriptions: ['plan.run.failed'] });
    bindConversation({ conversation_id: 'telegram:chat:u3', plan_id: 'plan-1', subscriptions: ['epic.failed'] });

    const handleEvent = (router as any).handleDashboardEvent.bind(router);
    handleEvent({ type: 'orchestration.event', data: { event_type: 'plan.run.failed', plan_id: 'plan-1', payload: { reason: 'boom' } } });

    await new Promise(resolve => setTimeout(resolve, 10));
    expect(mockConnector.sendMessage.calledOnce).to.be.true;
    expect(mockConnector.sendMessage.firstCall.args[0]).to.equal('telegram:chat:u1');
  });

  it('maps normalized epic.retrying events to retry notifications', async () => {
    bindConversation({ conversation_id: 'telegram:chat:u1', plan_id: 'plan-retry', subscriptions: ['epic.retrying'] });
    const handleEvent = (router as any).handleDashboardEvent.bind(router);
    handleEvent({
      type: 'orchestration.event',
      data: {
        event_type: 'epic.retrying',
        plan_id: 'plan-retry',
        room_id: 'room-5',
        epic_ref: 'EPIC-005',
        summary: 'Retrying after QA feedback',
        payload: {},
      },
    });

    await new Promise(resolve => setTimeout(resolve, 10));
    expect(mockConnector.sendMessage.calledOnce).to.be.true;
    const text = mockConnector.sendMessage.firstCall.args[1].text;
    expect(text).to.include('EPIC Retry');
    expect(text).to.include('EPIC-005');
    expect(text).to.include('plan-retry');
  });

  it('delivers normalized epic.retrying events to default plan bindings', async () => {
    bindConversation({ conversation_id: 'telegram:chat:u1', plan_id: 'plan-retry-default' });
    const handleEvent = (router as any).handleDashboardEvent.bind(router);
    handleEvent({
      type: 'orchestration.event',
      data: {
        event_type: 'epic.retrying',
        plan_id: 'plan-retry-default',
        room_id: 'room-5',
        epic_ref: 'EPIC-005',
        summary: 'Retrying after QA feedback',
        payload: {},
      },
    });

    await new Promise(resolve => setTimeout(resolve, 10));
    expect(mockConnector.sendMessage.calledOnce).to.be.true;
    expect(mockConnector.sendMessage.firstCall.args[0]).to.equal('telegram:chat:u1');
    expect(mockConnector.sendMessage.firstCall.args[1].text).to.include('EPIC Retry');
  });

  it('supports Slack-shaped bindings through the same routing contract', async () => {
    const slackConnector = { platform: 'slack', status: 'connected', sendMessage: sandbox.stub().resolves({ ts: '123.456' }) };
    (registry.getConnector as sinon.SinonStub).callsFake((platform: string) => platform === 'slack' ? slackConnector : mockConnector);
    bindConversation({ conversation_id: 'slack:team:T1:channel:C1:thread:171.42', plan_id: 'plan-slack', subscriptions: ['user.feedback.requested'] });

    const handleEvent = (router as any).handleDashboardEvent.bind(router);
    handleEvent({ type: 'orchestration.event', data: { event_type: 'user.feedback.requested', plan_id: 'plan-slack', payload: { prompt: 'Need input' } } });

    await new Promise(resolve => setTimeout(resolve, 10));
    expect(slackConnector.sendMessage.calledOnce).to.be.true;
    expect(slackConnector.sendMessage.firstCall.args[0]).to.equal('slack:team:T1:channel:C1:thread:171.42');
  });

  it('ignores unknown normalized orchestration event types without crashing', async () => {
    bindConversation({ conversation_id: 'telegram:chat:u1', plan_id: 'plan-1' });
    const handleEvent = (router as any).handleDashboardEvent.bind(router);
    expect(() => handleEvent({ type: 'orchestration.event', data: { event_type: 'new.unknown', plan_id: 'plan-1' } })).not.to.throw();
    await new Promise(resolve => setTimeout(resolve, 10));
    expect(mockConnector.sendMessage.called).to.be.false;
  });

  it('routes normalized events to bot owners when binding is missing', async () => {
    const handleEvent = (router as any).handleDashboardEvent.bind(router);
    handleEvent({ type: 'orchestration.event', data: { event_type: 'plan.run.failed', plan_id: 'missing-plan' } });
    await new Promise(resolve => setTimeout(resolve, 10));
    expect(mockConnector.sendMessage.calledOnce).to.be.true;
    expect(mockConnector.sendMessage.firstCall.args[0]).to.equal('u1');
    expect(mockConnector.sendMessage.firstCall.args[1].text).to.include('Plan Failed');
  });

  it('ignores duplicate orchestration events with the same event_id', async () => {
    const handleEvent = (router as any).handleDashboardEvent.bind(router);
    const event = {
      type: 'orchestration.event',
      data: {
        event_type: 'plan.run.completed',
        event_id: 'evt-duplicate-plan-completed',
        plan_id: 'missing-plan',
        run_id: 'run-duplicate-plan-completed',
      },
    };

    handleEvent(event);
    handleEvent(event);

    await new Promise(resolve => setTimeout(resolve, 10));
    expect(mockConnector.sendMessage.calledOnce).to.be.true;
    expect(mockConnector.sendMessage.firstCall.args[1].text).to.include('Plan Completed');
  });

  it('routes room.status.changed to bot owners when owner preferences include the canonical room event', async () => {
    sandbox.restore();
    sandbox = sinon.createSandbox();

    const ownerConnector = {
      platform: 'telegram',
      status: 'connected',
      sendMessage: sandbox.stub().resolves(),
    };
    sandbox.stub(registry, 'getConnector').returns(ownerConnector as any);
    sandbox.stub(registry, 'getAllConfigs').returns([
      {
        platform: 'telegram',
        enabled: true,
        authorized_users: ['owner-chat'],
        notification_preferences: { events: ['room.status.changed'], enabled: true },
        credentials: {},
        settings: {},
        pairing_code: '',
      } as any,
    ]);
    sandbox.stub(registry, 'getConfig').returns({
      platform: 'telegram',
      enabled: true,
      authorized_users: ['owner-chat'],
      notification_preferences: { events: ['room.status.changed'], enabled: true },
      credentials: {},
      settings: {},
      pairing_code: '',
    } as any);

    const ownerRouter = new NotificationRouter(registry);
    const handleEvent = (ownerRouter as any).handleDashboardEvent.bind(ownerRouter);
    handleEvent({
      type: 'orchestration.event',
      data: {
        event_type: 'room.status.changed',
        plan_id: 'plan-room-owner',
        run_id: 'run-room-owner',
        room_id: 'room-owner',
        epic_ref: 'EPIC-ROOM',
        payload: {
          previous_status: 'developing',
          status: 'review',
          agent_name: 'manager',
        },
      },
    });

    await new Promise(resolve => setTimeout(resolve, 10));
    expect(ownerConnector.sendMessage.calledOnce).to.be.true;
    expect(ownerConnector.sendMessage.firstCall.args[0]).to.equal('owner-chat');
    expect(ownerConnector.sendMessage.firstCall.args[1].text).to.include('War-Room State Changed');
    expect(ownerConnector.sendMessage.firstCall.args[1].text).to.include('developing');
    expect(ownerConnector.sendMessage.firstCall.args[1].text).to.include('review');
  });

  it('routes owner fallback notifications through registered channel items', async () => {
    sandbox.restore();
    sandbox = sinon.createSandbox();

    const ownerConnector = {
      platform: 'telegram',
      status: 'connected',
      sendMessage: sandbox.stub().resolves(),
    };
    sandbox.stub(registry, 'getConnector').returns(ownerConnector as any);
    sandbox.stub(registry, 'getAllConfigs').returns([
      {
        platform: 'telegram',
        enabled: true,
        authorized_users: ['legacy-owner'],
        notification_preferences: { events: [], enabled: true },
        credentials: {},
        settings: {
          channel_items: [
            {
              id: 'owner-chat',
              kind: 'telegram_chat',
              conversation_id: 'telegram:chat:owner-chat',
              registered_events: ['room.status.changed'],
            },
          ],
        },
        pairing_code: '',
      } as any,
    ]);

    const ownerRouter = new NotificationRouter(registry);
    const handleEvent = (ownerRouter as any).handleDashboardEvent.bind(ownerRouter);
    handleEvent({
      type: 'orchestration.event',
      data: {
        event_type: 'room.status.changed',
        plan_id: 'plan-channel-items',
        run_id: 'run-channel-items',
        room_id: 'room-channel-items',
        epic_ref: 'EPIC-CHANNEL-ITEMS',
        payload: { previous_status: 'developing', status: 'review' },
      },
    });

    await new Promise(resolve => setTimeout(resolve, 10));
    expect(ownerConnector.sendMessage.calledOnce).to.be.true;
    expect(ownerConnector.sendMessage.firstCall.args[0]).to.equal('telegram:chat:owner-chat');
  });

  it('filters owner fallback notifications by channel item registered events', async () => {
    sandbox.restore();
    sandbox = sinon.createSandbox();

    const ownerConnector = {
      platform: 'telegram',
      status: 'connected',
      sendMessage: sandbox.stub().resolves(),
    };
    sandbox.stub(registry, 'getConnector').returns(ownerConnector as any);
    sandbox.stub(registry, 'getAllConfigs').returns([
      {
        platform: 'telegram',
        enabled: true,
        authorized_users: ['legacy-owner'],
        notification_preferences: { events: [], enabled: true },
        credentials: {},
        settings: {
          channel_items: [
            {
              id: 'owner-chat',
              kind: 'telegram_chat',
              conversation_id: 'telegram:chat:owner-chat',
              registered_events: ['epic.failed'],
            },
          ],
        },
        pairing_code: '',
      } as any,
    ]);

    const ownerRouter = new NotificationRouter(registry);
    const handleEvent = (ownerRouter as any).handleDashboardEvent.bind(ownerRouter);
    handleEvent({
      type: 'orchestration.event',
      data: {
        event_type: 'room.status.changed',
        plan_id: 'plan-filtered-channel-items',
        run_id: 'run-filtered-channel-items',
        room_id: 'room-filtered-channel-items',
        epic_ref: 'EPIC-FILTERED-CHANNEL-ITEMS',
        payload: { previous_status: 'developing', status: 'review' },
      },
    });

    await new Promise(resolve => setTimeout(resolve, 10));
    expect(ownerConnector.sendMessage.called).to.be.false;
  });

  it('maps room_removed to plan_completed', async () => {
    bindConversation({ conversation_id: 'telegram:chat:u1', plan_id: 'plan-legacy' });
    const handleEvent = (router as any).handleDashboardEvent.bind(router);
    handleEvent({
      type: 'room_removed',
      data: { room_id: 'room-1', plan_id: 'plan-legacy' },
    });
    await new Promise(resolve => setTimeout(resolve, 10));
    expect(mockConnector.sendMessage.firstCall.args[1].text).to.include('War-Room Removed');
  });

  it('filters notifications based on preferences', async () => {
    sandbox.restore(); // Clear mocks for this test
    sandbox = sinon.createSandbox();
    
    const mockConnector2 = {
      platform: 'telegram',
      status: 'connected',
      sendMessage: sandbox.stub().resolves(),
    };
    sandbox.stub(registry, 'getConnector').returns(mockConnector2 as any);
    sandbox.stub(registry, 'getAllConfigs').returns([
      {
        platform: 'telegram',
        enabled: true,
        authorized_users: ['u1'],
        notification_preferences: { events: ['epic_failed'], enabled: true }, // Only failures
        credentials: {},
        settings: {},
        pairing_code: '',
      } as any,
    ]);
    sandbox.stub(registry, 'getConfig').returns({
      platform: 'telegram',
      enabled: true,
      authorized_users: ['u1'],
      notification_preferences: { events: ['epic_failed'], enabled: true },
      credentials: {},
      settings: {},
      pairing_code: '',
    } as any);

    const router2 = new NotificationRouter(registry);
    const handleEvent = (router2 as any).handleDashboardEvent.bind(router2);
    bindConversation({ conversation_id: 'telegram:chat:u1', plan_id: 'plan-legacy' });

    // This should be filtered out
    handleEvent({
      type: 'room_updated',
      data: { room: { room_id: 'room-1', status: 'done', plan_id: 'plan-legacy' } },
    });

    // This should be delivered
    handleEvent({
      type: 'room_updated',
      data: { room: { room_id: 'room-1', status: 'failed', plan_id: 'plan-legacy' } },
    });

    await new Promise(resolve => setTimeout(resolve, 10));

    expect(mockConnector2.sendMessage.calledOnce).to.be.true;
    expect(mockConnector2.sendMessage.firstCall.args[1].text).to.include('EPIC Failed');
  });

  it('does not send if global enabled is false', async () => {
    sandbox.restore();
    sandbox = sinon.createSandbox();
    
    const mockConnector3 = {
      platform: 'telegram',
      status: 'connected',
      sendMessage: sandbox.stub().resolves(),
    };
    sandbox.stub(registry, 'getConnector').returns(mockConnector3 as any);
    sandbox.stub(registry, 'getAllConfigs').returns([
      {
        platform: 'telegram',
        enabled: true,
        authorized_users: ['u1'],
        notification_preferences: { events: [], enabled: false }, // Disabled globally
        credentials: {},
        settings: {},
        pairing_code: '',
      } as any,
    ]);
    sandbox.stub(registry, 'getConfig').returns({
      platform: 'telegram',
      enabled: true,
      authorized_users: ['u1'],
      notification_preferences: { events: [], enabled: false },
      credentials: {},
      settings: {},
      pairing_code: '',
    } as any);

    const router3 = new NotificationRouter(registry);
    const handleEvent = (router3 as any).handleDashboardEvent.bind(router3);
    bindConversation({ conversation_id: 'telegram:chat:u1', plan_id: 'plan-disabled' });

    handleEvent({
      type: 'room_created',
      data: { room: { room_id: 'room-1', plan_id: 'plan-disabled' } },
    });

    await new Promise(resolve => setTimeout(resolve, 10));
    expect(mockConnector3.sendMessage.called).to.be.false;
  });
});
