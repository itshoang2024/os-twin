## EPIC-004: Plan-Scoped Messages and Conversation Binding

Roles: @engineer, @qa-automation-engineer

Define and implement how Telegram and Slack conversations bind to a plan, and how bot notifications route by `plan_id`.

### Definition of Done

- [ ] Conversation binding contract is implemented in the bot container.
- [ ] Telegram conversation ID shape is supported.
- [ ] Slack conversation ID shape is supported by the same contract, even if Slack delivery remains behind current connector readiness.
- [ ] Bot routing rules are implemented for notifications and user feedback.
- [ ] Every bot-visible orchestration message is plan-scoped.
- [ ] Bot no longer broadcasts plan events only through global authorized user lists.

### Acceptance Criteria

- [ ] A Telegram user can start or follow a plan and receive only events for that bound plan.
- [ ] A Slack thread can bind to the same `plan_id` and receive equivalent events.
- [ ] If a user asks about a plan in an existing conversation, the bot can determine `plan_id` from binding before falling back to explicit user input.
- [ ] Bot notification preferences can filter by event type without losing plan context.
- [ ] Unknown `orchestration.event` types are logged and ignored without crashing.

### Tasks

- [ ] Add `ConversationBinding` types and persistence.
- [ ] Add binding helpers: `bindConversation`, `unbindConversation`, `getBindingsForPlan`, `getActiveBinding`.
- [ ] Update plan create/launch/resume command flows to create or update bindings.
- [ ] Update `NotificationRouter` to route `orchestration.event` by `plan_id` with optional event-type, epic, and room filters.
- [ ] Document and implement stale/missing binding behavior.
- [ ] Add bot tests for Telegram binding, Slack-shaped binding, event filtering, and unknown events.

### bot Implementation Plan

#### Suggested files

```text
bot/src/conversation-bindings.ts
bot/src/notifications.ts
bot/src/sessions.ts
bot/src/commands.ts
bot/src/agent-bridge.ts
bot/test/conversation-bindings.test.ts
bot/test/notifications-orchestration.test.ts
```

#### Conversation binding contract

```json
{
  "conversation_id": "telegram:chat:12345",
  "platform": "telegram",
  "plan_id": "pt-example",
  "subscriptions": [
    "plan.run.failed",
    "epic.failed",
    "user.feedback.requested"
  ],
  "last_outbound_message_id": "123",
  "created_at": "2026-06-06T00:00:00Z",
  "updated_at": "2026-06-06T00:00:00Z"
}
```

Persist bindings in `~/.ostwin/conversation-bindings.json` or extend `~/.ostwin/sessions.json` with a `bindings` field. Prefer a separate `conversation-bindings.json` for v1 so routing state is not mixed with chat history.

#### Conversation ID shapes

| Platform | Conversation ID |
|---|---|
| Telegram chat | `telegram:chat:<chat_id>` |
| Telegram topic/thread | `telegram:chat:<chat_id>:thread:<thread_id>` |
| Slack channel thread | `slack:team:<team_id>:channel:<channel_id>:thread:<thread_ts>` |
| Slack channel fallback | `slack:team:<team_id>:channel:<channel_id>` |

#### Binding lifecycle

| Input | Resolution |
|---|---|
| User creates a plan in chat | Bind conversation to new `plan_id` |
| User launches a plan | Bind or update conversation to launched `plan_id` |
| User resumes a plan | Keep `plan_id`; if the prior execution failed, follow EPIC-003 resume/reset rules |
| User selects/follows a plan | Bind conversation with default subscriptions |
| Event arrives from dashboard | Route by `plan_id`, optional epic/room filters, and subscription list |
| Binding is missing | Do not broadcast globally; log missing binding and keep event available through dashboard |

#### Notification routing

`NotificationRouter.handleDashboardEvent` should support both:

1. legacy dashboard payloads such as `room_created` or `room_updated`, and
2. normalized event payloads:

```json
{
  "type": "orchestration.event",
  "data": {
    "event_type": "plan.run.failed",
    "plan_id": "pt-example"
  }
}
```

For normalized events, routing must:

1. validate `data.plan_id`;
2. find bindings by `plan_id`;
3. filter by optional binding fields such as `epic_ref` or `room_id` when present;
4. filter by subscription list;
5. send via the connector matching the binding platform;
6. update `last_outbound_message_id` when the connector returns one.

#### User-control events

Bot commands should route user controls through dashboard APIs so `.agents` can append them as events:

| User action | Event |
|---|---|
| Pause plan | `user.plan.pause_requested` |
| Resume plan | `user.plan.resume_requested` |
| Cancel plan | `user.plan.cancel_requested` |
| Provide feedback | `user.feedback.posted` |

### dashboard Implementation Plan

- Provide APIs for bot to bind/unbind or list plan conversation bindings if binding state is centralized later.
- For v1, bot-local binding is acceptable, but dashboard broadcasts must always include `plan_id`.
- Dashboard should not broadcast plan events globally when the bot has no binding.

### .agents Implementation Plan

- User-control events that come from bot through dashboard must append to `events.jsonl`.
- Manager loop should consume supported user-control events in later implementation phases.
- Unsupported user-control events should be logged as ignored with `event_id`.

### Other aspects

Telegram is the first implementation target. Slack should use the same contract so the design does not need to change when Slack control is enabled.

depends_on: [EPIC-003]
