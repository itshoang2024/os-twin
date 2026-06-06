/**
 * agent-bridge.ts — OpenCode-backed AI agent for connectors.
 *
 * All conversation flows through POST /api/chat which uses an
 * OpenCode server session.  The AI has full memory across turns
 * including tool calls and their results.
 *
 * Memory: OpenCode session is the single source of truth.
 * Local session.chatHistory is NOT maintained here — OpenCode
 * stores the full conversation server-side.
 *
 * Slash command context: routeCommand results are stored in
 * session.pendingContext and injected into the next askAgent() call
 * so the AI knows what the user recently did.
 */

import api from './api';
import { connectorConversationId, draftConversationId } from './conversation-ids';
import { getSession, setMode, setPlan, clearActivePlan, getStagedImages } from './sessions';
import { type AttachmentMeta } from './connectors/base';
import { bindConversation, telegramConversationId } from './conversation-bindings';

// ── Types ───────────────────────────────────────────────────────────────

export interface AgentContext {
  userId: string;
  platform: string;
  conversationId?: string;
  referencedMessageContent?: string;
  attachments?: AttachmentMeta[];
}

export interface AgentResponse {
  text: string;
  planId?: string;
  destinationUrl?: string;
  attachments?: Array<{ buffer: Buffer; name: string }>;
}

function planCreatedDestination(actions?: Array<{ type: string; plan_id?: string; url?: string }>): {
  planId: string;
  destinationUrl: string;
} | null {
  for (const action of actions || []) {
    if (action.type === 'plan_created' && action.plan_id) {
      return {
        planId: action.plan_id,
        destinationUrl: action.url || `/plans/${action.plan_id}`,
      };
    }
  }
  return null;
}

function bindAgentPlan(agentCtx: AgentContext, planId: string): void {
  const conversationId = agentCtx.conversationId || (agentCtx.platform === 'telegram' ? telegramConversationId(agentCtx.userId) : null);
  if (!conversationId || (agentCtx.platform !== 'telegram' && agentCtx.platform !== 'slack')) return;
  try {
    bindConversation({ conversation_id: conversationId, platform: agentCtx.platform as 'telegram' | 'slack', plan_id: planId });
  } catch (err: any) {
    console.warn(`[BINDINGS] Failed to bind agent conversation to ${planId}: ${err.message}`);
  }
}

// ── Trivial message fast-path ───────────────────────────────────────────

const TRIVIAL_PATTERNS = [
  /^(hi|hello|hey|yo|sup)[\s!.?]*$/i,
  /^(thanks|thank you|thx|ty|cheers)[\s!.?]*$/i,
  /^(ok|okay|k|got it|sure|yep|yeah|yes|no|nope|alright)[\s!.?]*$/i,
  /^(good|great|nice|cool|awesome|perfect|wow)[\s!.?]*$/i,
  /^(bye|goodbye|cya|see ya|later)[\s!.?]*$/i,
];

const TRIVIAL_RESPONSES: Record<string, string[]> = {
  greeting: ['Hey! How can I help with your project?', 'Hello! What would you like to do?'],
  thanks: ['You\'re welcome!', 'Glad to help!'],
  ack: ['Got it. Let me know if you need anything else.'],
  positive: ['Glad to hear it! Need anything else?'],
  bye: ['See you later! Your session is still active for 30 minutes.'],
};

function detectTrivial(text: string): string | null {
  const t = text.trim();
  if (t.length > 50) return null;
  if (TRIVIAL_PATTERNS[0].test(t)) return 'greeting';
  if (TRIVIAL_PATTERNS[1].test(t)) return 'thanks';
  if (TRIVIAL_PATTERNS[2].test(t)) return 'ack';
  if (TRIVIAL_PATTERNS[3].test(t)) return 'positive';
  if (TRIVIAL_PATTERNS[4].test(t)) return 'bye';
  return null;
}

// ── Main entry point ────────────────────────────────────────────────────

export async function askAgent(
  question: string,
  ctx?: AgentContext,
): Promise<AgentResponse> {
  const agentCtx: AgentContext = ctx || { userId: 'unknown', platform: 'unknown' };
  const session = getSession(agentCtx.userId, agentCtx.platform);

  const convId = connectorConversationId(agentCtx.platform, agentCtx.userId);

  if (session.mode === 'awaiting_idea') {
    const idea = question.trim();
    if (!idea) {
      return { text: 'Send me the idea for the new plan, or use /cancel to stop drafting.' };
    }

    clearActivePlan(agentCtx.userId, agentCtx.platform);
    setMode(agentCtx.userId, agentCtx.platform, 'idle');

    try {
      const result = await api.askOpenCodeCommand({
        command: 'draft',
        arguments: idea,
        conversation_id: draftConversationId(agentCtx.platform, agentCtx.userId),
        user_id: agentCtx.userId,
        platform: agentCtx.platform,
      });

      if ((result as any)._error) {
        return { text: `⚠️ OpenCode command error: ${(result as any)._error}` };
      }

      const destination = planCreatedDestination(result.actions);
      if (destination) {
        setPlan(agentCtx.userId, agentCtx.platform, destination.planId);
        bindAgentPlan(agentCtx, destination.planId);
      }

      return {
        text: result.text || 'No response.',
        planId: destination?.planId,
        destinationUrl: destination?.destinationUrl,
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      console.error('[BRIDGE] OpenCode draft command error:', message);
      return { text: '⚠️ Failed to draft a new plan.' };
    }
  }

  // Fast-path: skip API call for trivial messages when no active plan
  const hasAttachments = agentCtx.attachments && agentCtx.attachments.length > 0;
  const hasActivePlan = !!(session.activePlanId && session.activePlanId !== 'new');
  const isEditingPlan = session.mode === 'editing' && hasActivePlan;
  if (!hasAttachments && !isEditingPlan) {
    const trivialType = detectTrivial(question);
    if (trivialType) {
      const responses = TRIVIAL_RESPONSES[trivialType] || ['Got it.'];
      const reply = responses[Math.floor(Math.random() * responses.length)];
      return { text: reply };
    }
  }

  // Build the message — inject pending slash command context if present
  let message = question;
  if (session.pendingContext.length > 0) {
    const ctxBlock = session.pendingContext
      .map(c => `[User ran: /${c.command}]\nResult: ${c.result}`)
      .join('\n\n');
    message = `${ctxBlock}\n\nUser's follow-up: ${question}`;
    session.pendingContext = [];
  }

  // Inject active plan context so the OpenCode agent knows which plan to refine
  if (isEditingPlan) {
    message = `[Context: User is editing plan ${session.activePlanId}. Use ostwin_refine_plan with plan_id="${session.activePlanId}" for any modifications.]\n\n${message}`;
  }

  try {
    const stagedImages = getStagedImages(agentCtx.userId, agentCtx.platform);
    const result = await api.askOpenCode({
      message,
      conversation_id: convId,
      user_id: agentCtx.userId,
      platform: agentCtx.platform,
      working_dir: session.workingDir || undefined,
      attachments: agentCtx.attachments?.map(a => ({ name: a.name, contentType: a.contentType || undefined })),
      images: stagedImages.length > 0 ? stagedImages : undefined,
      referenced_message_content: agentCtx.referencedMessageContent,
    });

    if ((result as any)._error) {
      return { text: `⚠️ OpenCode chat error: ${(result as any)._error}` };
    }

    const text = result.text || 'No response.';

    // Use structured actions for reliable session state updates.
    const destination = planCreatedDestination(result.actions);
    if (destination) {
      setPlan(agentCtx.userId, agentCtx.platform, destination.planId);
      bindAgentPlan(agentCtx, destination.planId);
    }

    return {
      text,
      planId: destination?.planId,
      destinationUrl: destination?.destinationUrl,
    };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    console.error('[BRIDGE] OpenCode chat error:', message);
    return { text: '⚠️ Failed to get a response from the AI.' };
  }
}
