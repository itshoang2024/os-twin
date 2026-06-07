import WebSocket from 'ws';
import { ConnectorRegistry } from './connectors/registry';
import {
  ConversationBinding,
  getBindingsForPlan,
  parseConversationTarget,
  updateLastOutboundMessage,
} from './conversation-bindings';
import { logBotDebug, logBotInfo } from './logger';


export type NotificationEvent =
  | 'plan_started'
  | 'epic_passed'
  | 'epic_failed'
  | 'epic_retry'
  | 'plan_completed'
  | 'plan_failed'
  | 'room_created'
  | 'room_status_changed'
  | 'error'
  | 'feedback_needed';

const ORCHESTRATION_NOTIFICATION_EVENTS: Record<string, NotificationEvent> = {
  'plan.run.started': 'plan_started',
  'epic.passed': 'epic_passed',
  'epic.retrying': 'epic_retry',
  'epic.failed': 'epic_failed',
  'plan.run.failed': 'plan_failed',
  'plan.run.completed': 'plan_completed',
  'user.feedback.requested': 'feedback_needed',
  'room.created': 'room_created',
  'room.status.changed': 'room_status_changed',
};

const MAX_SEEN_ORCHESTRATION_EVENTS = 1000;

function normalizeRoomStatus(status = ''): string {
  if (status === 'passed') return 'done';
  if (status === 'failed-final') return 'failed';
  if (status === 'fixing') return 'optimize';
  return status;
}

export class NotificationRouter {
  private ws: WebSocket | null = null;
  private registry: ConnectorRegistry;
  private url: string;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private seenOrchestrationEventIds: string[] = [];
  private seenOrchestrationEventIdSet = new Set<string>();

  constructor(registry: ConnectorRegistry, url: string = 'ws://localhost:3366/api/ws') {
    this.registry = registry;
    this.url = url;
  }

  public start() {
    this.connect();
  }

  public stop() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.ws) {
      this.ws.terminate();
      this.ws = null;
    }
  }

  private connect() {
    console.log(`[NOTIFICATIONS] Connecting to dashboard WebSocket: ${this.url}`);
    this.ws = new WebSocket(this.url);

    this.ws.on('open', () => {
      console.log('[NOTIFICATIONS] Connected to dashboard');
    });

    this.ws.on('message', (data) => {
      try {
        const event = JSON.parse(data.toString());
        logBotDebug('[NOTIFICATIONS] Dashboard event received', {
          type: event?.type || event?.event || 'unknown',
          event_type: event?.data?.event_type || event?.data?.event?.event_type,
          event_id: event?.data?.event_id || event?.data?.event?.event_id,
          plan_id: event?.data?.plan_id || event?.data?.event?.plan_id || event?.data?.room?.plan_id,
        });
        this.handleDashboardEvent(event);
      } catch (err) {
        console.error('[NOTIFICATIONS] Failed to parse event:', err);
      }
    });

    this.ws.on('close', () => {
      console.log('[NOTIFICATIONS] Connection closed, reconnecting in 5s...');
      this.scheduleReconnect();
    });

    this.ws.on('error', (err) => {
      console.error('[NOTIFICATIONS] WebSocket error:', err.message);
    });
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => this.connect(), 5000);
  }

  private handleDashboardEvent(event: any) {
    const { type, data } = event;
    let notification: NotificationEvent | null = null;
    let messageBody = '';
    let roomId = data?.room?.room_id || data?.room_id;

    switch (type) {
      case 'orchestration.event': {
        const evt = data?.event || data;
        const payload = evt?.payload || {};
        const eventType = evt?.event_type;
        if (!eventType) {
          console.warn('[NOTIFICATIONS] Ignoring orchestration.event without event_type');
          return;
        }
        const failedEpic = payload.failed_epic || {};
        const epicRef = evt?.epic_ref || failedEpic.epic_ref || payload.epic_ref || 'unknown epic';
        roomId = evt?.room_id || failedEpic.room_id || payload.room_id || roomId;
        const planId = evt?.plan_id || payload.plan_id || failedEpic.plan_id;
        const runId = evt?.run_id || payload.run_id || failedEpic.run_id || 'unknown run';
        if (!planId) {
          console.warn(`[NOTIFICATIONS] Ignoring orchestration.event ${eventType} without plan_id`);
          return;
        }
        if (!this.markOrchestrationEventSeen(evt?.event_id)) {
          logBotDebug('[NOTIFICATIONS] Duplicate orchestration event ignored', {
            event_type: eventType,
            event_id: evt?.event_id,
            plan_id: planId,
            run_id: runId,
          });
          return;
        }
        logBotInfo('[NOTIFICATIONS] Orchestration event accepted', {
          event_type: eventType,
          event_id: evt?.event_id,
          plan_id: planId,
          run_id: runId,
          room_id: roomId,
          epic_ref: epicRef,
        });
        const role = evt?.role || failedEpic.role || payload.role || payload.agent_name || 'unknown role';
        const reason = evt?.summary || payload.summary || payload.reason || 'unknown reason';
        const lastMessage = evt?.last_message || payload.last_message || failedEpic.last_message;
        const preview = this.formatLastMessage(lastMessage);
        notification = ORCHESTRATION_NOTIFICATION_EVENTS[eventType] || null;

        if (eventType === 'epic.failed') {
          messageBody = `❌ *EPIC Failed:* \`${epicRef}\`\nPlan: \`${planId}\`\nRun: \`${runId}\`\nRoom: \`${roomId}\`\nRole: \`${role}\`\nReason: ${reason}${preview}`;
        } else if (eventType === 'plan.run.failed') {
          messageBody = `🛑 *Plan Failed:* \`${planId}\`\nRun: \`${runId}\`\nFailed epic: \`${epicRef}\`\nRoom: \`${roomId}\`\nRole: \`${role}\`\nReason: ${reason}${preview}`;
        } else if (eventType === 'epic.passed') {
          messageBody = `✅ *EPIC Done:* \`${epicRef}\`\nPlan: \`${planId}\`\nRun: \`${runId}\`\nRoom: \`${roomId}\`${preview}`;
        } else if (eventType === 'epic.retrying') {
          messageBody = `🔄 *EPIC Retry:* \`${epicRef}\`\nPlan: \`${planId}\`\nRun: \`${runId}\`\nRoom: \`${roomId || 'unknown room'}\`\n${evt?.summary || payload.reason || 'Retrying after feedback or failure.'}${preview}`;
        } else if (eventType === 'user.feedback.requested') {
          messageBody = `🤔 *Feedback Needed*\nPlan: \`${planId}\`\nRun: \`${runId}\`\nRoom: \`${roomId || 'unknown room'}\`\n${evt?.summary || payload.prompt || 'Please provide input to proceed.'}${preview}`;
        } else if (eventType === 'plan.run.completed') {
          messageBody = `🏁 *Plan Completed:* \`${planId}\`\nRun: \`${runId}\`${preview}`;
        } else if (eventType === 'plan.run.started') {
          messageBody = `🚀 *Plan Started:* \`${planId}\`\nRun: \`${runId}\`${preview}`;
        } else if (eventType === 'room.created') {
          const agentName = payload.agent_name || role;
          messageBody = `🏗️ *War-Room Created:* \`${epicRef}\`\nPlan: \`${planId}\`\nRun: \`${runId}\`\nRoom: \`${roomId || 'unknown room'}\`\nAgent: \`${agentName}\`${preview}`;
        } else if (eventType === 'room.status.changed') {
          const previousStatus = normalizeRoomStatus(evt?.previous_status || payload.previous_status || 'unknown');
          const nextStatus = normalizeRoomStatus(evt?.status || payload.status || 'unknown');
          const agentName = payload.agent_name || role;
          messageBody = `🔁 *War-Room State Changed:* \`${epicRef}\`\nPlan: \`${planId}\`\nRun: \`${runId}\`\nRoom: \`${roomId || 'unknown room'}\`\nAgent: \`${agentName}\`\nStatus: \`${previousStatus}\` → \`${nextStatus}\`${preview}`;
        } else {
          console.warn(`[NOTIFICATIONS] Unknown orchestration.event type ignored: ${eventType}`);
          return;
        }
        this.routePlanScopedNotification({ eventType, event: notification, text: messageBody, planId, epicRef, roomId });
        return;
      }

      case 'room_created':
        notification = 'plan_started';
        messageBody = `🚀 *New War-Room Created:* \`${roomId}\`\nTask: ${data.room.task_ref || 'Initial Setup'}`;
        break;

      case 'room_updated':
        const status = normalizeRoomStatus(data.room.status);
        if (status === 'done') {
          notification = 'epic_passed';
          messageBody = `✅ *EPIC Done:* \`${roomId}\`\nAll tasks completed successfully.`;
        } else if (status === 'failed') {
          notification = 'epic_failed';
          messageBody = `❌ *EPIC Failed:* \`${roomId}\`\nInvestigation required.`;
        } else if (status === 'optimize') {
          notification = 'epic_retry';
          messageBody = `🔄 *EPIC Retrying:* \`${roomId}\`\nAddressing QA feedback.`;
        } else if (status === 'pending_feedback') {
          notification = 'feedback_needed';
          messageBody = `🤔 *Feedback Needed:* \`${roomId}\`\nPlease provide input to proceed.`;
        } else if (status === 'error') {
          notification = 'error';
          messageBody = `⚠️ *System Error:* \`${roomId}\`\nCheck logs for details.`;
        }
        break;

      case 'room_removed':
        notification = 'plan_completed';
        messageBody = `🏁 *War-Room Removed:* \`${roomId}\`\nCleaned up successfully.`;
        break;

      case 'plans_updated':
        // Optional: Notify if a whole plan is completed
        break;
    }

    if (notification && messageBody) {
      const legacyPlanId = data?.plan_id || data?.room?.plan_id;
      if (legacyPlanId) {
        this.routePlanScopedNotification({
          eventType: this.legacyEventType(notification),
          event: notification,
          text: messageBody,
          planId: legacyPlanId,
          epicRef: data?.epic_ref || data?.room?.task_ref,
          roomId,
        });
      } else {
        console.warn(`[NOTIFICATIONS] Ignoring ${type} without plan_id; not broadcasting plan event globally`);
      }
    }
  }

  private legacyEventType(event: NotificationEvent): string {
    switch (event) {
      case 'plan_started': return 'plan.run.started';
      case 'plan_completed': return 'plan.run.completed';
      case 'plan_failed': return 'plan.run.failed';
      case 'room_created': return 'room.created';
      case 'room_status_changed': return 'room.status.changed';
      case 'epic_passed': return 'epic.passed';
      case 'epic_failed': return 'epic.failed';
      case 'epic_retry': return 'epic.retrying';
      case 'feedback_needed': return 'user.feedback.requested';
      case 'error': return 'system.error';
      default: return event;
    }
  }

  private async routeNotification(event: NotificationEvent, text: string) {
    const configs = this.registry.getAllConfigs();

    for (const config of configs) {
      if (!config.enabled) continue;

      const prefs = config.notification_preferences;
      if (!prefs.enabled) continue;

      // If events list is empty, treat as "all enabled" or check specific mapping
      if (prefs.events.length > 0 && !prefs.events.includes(event)) {
        continue;
      }

      const connector = this.registry.getConnector(config.platform);
      if (connector && connector.status === 'connected') {
        for (const userId of config.authorized_users) {
          try {
            await connector.sendMessage(userId, { text });
          } catch (err) {
            console.error(`[NOTIFICATIONS] Failed to send to ${config.platform}:${userId}:`, err);
          }
        }
      }
    }
  }

  private async routeOwnerNotification(params: { eventType: string; event: NotificationEvent; text: string; planId?: string }) {
    const configs = this.registry.getAllConfigs();

    for (const config of configs) {
      if (!config.enabled) continue;

      const prefs = config.notification_preferences;
      if (!prefs.enabled) {
        logBotDebug('[NOTIFICATIONS] Owner preferences disabled delivery', {
          platform: config.platform,
          event_type: params.eventType,
          plan_id: params.planId,
        });
        continue;
      }

      if (prefs.events.length > 0 && !prefs.events.includes(params.event) && !prefs.events.includes(params.eventType)) {
        logBotDebug('[NOTIFICATIONS] Owner preferences filtered delivery', {
          platform: config.platform,
          event_type: params.eventType,
          semantic_event: params.event,
          allowed_events: prefs.events,
        });
        continue;
      }

      const connector = this.registry.getConnector(config.platform);
      if (!connector || connector.status !== 'connected') {
        logBotDebug('[NOTIFICATIONS] Owner connector unavailable for delivery', {
          platform: config.platform,
          connector_status: connector?.status || 'missing',
        });
        continue;
      }

      const channelItems = Array.isArray(config.settings?.channel_items) ? config.settings.channel_items : [];
      const targets = channelItems.length > 0
        ? Array.from(new Set(channelItems
            .filter((item: any) => item.enabled !== false)
            .filter((item: any) => {
              if (!Array.isArray(item.registered_events)) return true;
              return item.registered_events.includes(params.event) || item.registered_events.includes(params.eventType);
            })
            .map((item: any) => String(item.conversation_id || item.channel_id || item.user_id || item.id))
            .filter(Boolean)))
        : (config.authorized_users || []);

      for (const userId of targets) {
        try {
          logBotInfo('[NOTIFICATIONS] Sending owner notification', {
            platform: config.platform,
            user_id: userId,
            event_type: params.eventType,
            plan_id: params.planId,
          });
          await connector.sendMessage(userId, { text: params.text });
        } catch (err) {
          console.error(`[NOTIFICATIONS] Failed to send owner notification to ${config.platform}:${userId}:`, err);
        }
      }
    }
  }

  private async routePlanScopedNotification(params: {
    eventType: string;
    event: NotificationEvent;
    text: string;
    planId: string;
    epicRef?: string;
    roomId?: string;
  }) {
    const bindings = getBindingsForPlan(params.planId);
    logBotDebug('[NOTIFICATIONS] Resolving plan bindings', {
      plan_id: params.planId,
      event_type: params.eventType,
      binding_count: bindings.length,
    });
    if (bindings.length === 0) {
      console.warn(`[NOTIFICATIONS] No conversation binding for plan_id=${params.planId}; routing event ${params.eventType} to configured bot owners`);
      await this.routeOwnerNotification({ eventType: params.eventType, event: params.event, text: params.text, planId: params.planId });
      return;
    }

    for (const binding of bindings) {
      if (!this.bindingMatches(binding, params)) {
        logBotDebug('[NOTIFICATIONS] Binding skipped by filter', {
          conversation_id: binding.conversation_id,
          plan_id: binding.plan_id,
          event_type: params.eventType,
          epic_ref: params.epicRef,
          room_id: params.roomId,
        });
        continue;
      }
      const target = parseConversationTarget(binding.conversation_id);
      if (!target) {
        console.warn(`[NOTIFICATIONS] Invalid bound conversation_id ignored: ${binding.conversation_id}`);
        continue;
      }

      const config = this.registry.getConfig(binding.platform as any);
      if (config && config.notification_preferences) {
        const prefs = config.notification_preferences;
        if (!prefs.enabled) {
          logBotDebug('[NOTIFICATIONS] Connector preferences disabled delivery', {
            platform: binding.platform,
            conversation_id: binding.conversation_id,
            event_type: params.eventType,
          });
          continue;
        }
        if (prefs.events.length > 0 && !prefs.events.includes(params.event) && !prefs.events.includes(params.eventType)) {
          logBotDebug('[NOTIFICATIONS] Connector preferences filtered delivery', {
            platform: binding.platform,
            conversation_id: binding.conversation_id,
            event_type: params.eventType,
            semantic_event: params.event,
            allowed_events: prefs.events,
          });
          continue;
        }
      }

      const connector = this.registry.getConnector(binding.platform as any);
      if (!connector || connector.status !== 'connected') {
        logBotDebug('[NOTIFICATIONS] Connector unavailable for delivery', {
          platform: binding.platform,
          conversation_id: binding.conversation_id,
          connector_status: connector?.status || 'missing',
        });
        continue;
      }

      try {
        logBotInfo('[NOTIFICATIONS] Sending connector notification', {
          platform: binding.platform,
          conversation_id: binding.conversation_id,
          event_type: params.eventType,
          plan_id: params.planId,
        });
        const result = await connector.sendMessage(binding.conversation_id, { text: params.text }) as any;
        const messageId = typeof result === 'string' ? result : (result?.message_id || result?.ts);
        if (messageId) updateLastOutboundMessage(binding.conversation_id, String(messageId));
      } catch (err) {
        console.error(`[NOTIFICATIONS] Failed to send to ${binding.conversation_id}:`, err);
      }
    }
  }

  private bindingMatches(binding: ConversationBinding, params: { eventType: string; event: NotificationEvent; epicRef?: string; roomId?: string }): boolean {
    if (binding.epic_ref && params.epicRef && binding.epic_ref !== params.epicRef) return false;
    if (binding.room_id && params.roomId && binding.room_id !== params.roomId) return false;
    const subscriptions = binding.subscriptions || [];
    if (subscriptions.length > 0 && !subscriptions.includes(params.eventType) && !subscriptions.includes(params.event)) return false;
    return true;
  }

  private formatLastMessage(lastMessage: any): string {
    if (!lastMessage?.body_preview) return '';
    const sender = lastMessage.from ? ` from ${lastMessage.from}` : '';
    const type = lastMessage.type ? ` (${lastMessage.type})` : '';
    return `\n\nLast message${sender}${type}:\n${lastMessage.body_preview}`;
  }

  private markOrchestrationEventSeen(eventId: unknown): boolean {
    if (!eventId) return true;
    const normalized = String(eventId);
    if (this.seenOrchestrationEventIdSet.has(normalized)) return false;

    this.seenOrchestrationEventIdSet.add(normalized);
    this.seenOrchestrationEventIds.push(normalized);
    if (this.seenOrchestrationEventIds.length > MAX_SEEN_ORCHESTRATION_EVENTS) {
      const evicted = this.seenOrchestrationEventIds.shift();
      if (evicted) this.seenOrchestrationEventIdSet.delete(evicted);
    }
    return true;
  }
}
