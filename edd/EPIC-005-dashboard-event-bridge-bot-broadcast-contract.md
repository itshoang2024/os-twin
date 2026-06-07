## EPIC-005: Dashboard Event Bridge and Bot Broadcast Contract

Roles: @engineer, @qa-automation-engineer

Define and implement the dashboard bridge that tails orchestration events and broadcasts a normalized event envelope to the bot layer.

### Definition of Done

- [ ] Dashboard has an `EventTailer` heartbeat task for `events.jsonl`.
- [ ] Dashboard-to-bot event shape is implemented as `{ "type": "orchestration.event", "data": event }`.
- [ ] Event tailing has cursor semantics: event log path, byte offset, last event ID, and last seen mtime.
- [ ] Dashboard projection behavior is implemented for plan and room status.
- [ ] Backward compatibility with existing dashboard frontend event shapes is documented and preserved.
- [ ] Bot notification behavior is documented for failure, retry, pass, completion, and feedback-required events.

### Acceptance Criteria

- [ ] Dashboard does not force bot consumers to infer event type from mixed `{ event, ...data }` payloads.
- [ ] Bot receives the same normalized envelope for Telegram and Slack.
- [ ] Plan failure notifications include a short summary and linkable identifiers.
- [ ] Existing dashboard room and plan views can continue to work from status projections.
- [ ] Event tailer restart does not rebroadcast already seen events in the same dashboard process.
- [ ] If an event log is truncated or rotated, the tailer resets safely and logs the reset.

### Tasks

- [ ] Add `dashboard/orchestration_events.py` with event parsing, validation, cursor, and projection helpers.
- [ ] Add an `EventTailer` background task in `dashboard/tasks.py`.
- [ ] Wire `EventTailer` into startup alongside existing room polling.
- [ ] Add normalized `broadcaster.broadcast_orchestration_event(event)` or equivalent.
- [ ] Keep compatibility adapter for existing frontend events.
- [ ] Update bot notification mapping from event taxonomy to connector messages.
- [ ] Add pytest coverage for event tailing, cursor movement, malformed JSONL rows, and normalized broadcast.

### dashboard Implementation Plan

#### Suggested files

```text
dashboard/orchestration_events.py
dashboard/tasks.py
dashboard/global_state.py
dashboard/ws_router.py
dashboard/tests/test_orchestration_events.py
dashboard/tests/test_orchestration_event_broadcast.py
```

#### EventTailer heartbeat

The tailer runs as a background task. It discovers plan execution event logs, reads from the last cursor, validates JSONL rows, updates projections, and broadcasts normalized events.

Cursor shape:

```json
{
  "events_path": "/path/to/.war-rooms/events.jsonl",
  "byte_offset": 12345,
  "last_event_id": "evt_01...",
  "last_mtime": 1780000000.0
}
```

Heartbeat behavior:

1. Every interval, discover active event logs from plan metadata and active war-room dirs.
2. For each event log, seek to `byte_offset`.
3. Read complete lines only.
4. Parse JSON rows.
5. Skip duplicate `event_id` values already seen in memory.
6. Validate required envelope fields.
7. Update projections.
8. Broadcast normalized event.
9. Advance cursor only after projection and broadcast handoff succeeds.

Initial interval: 1 second. This matches current dashboard room polling behavior and can be tuned later.

#### Malformed and partial rows

| Row condition | Behavior |
|---|---|
| Blank line | Skip |
| Partial trailing line | Leave cursor before partial line and retry next heartbeat |
| Invalid JSON | Log warning, emit no broadcast, advance cursor only if line is complete |
| Missing required fields | Log warning, emit no broadcast, advance cursor |
| Duplicate `event_id` | Skip broadcast and projection |
| File shrank | Reset cursor to `0`, clear per-file offset, keep global seen-event IDs |

#### Projection updates

The dashboard projection layer should update read models from event types:

| Event | Projection |
|---|---|
| `plan.run.started` | plan lifecycle running |
| `room.created` | room metadata exists |
| `room.status.changed` | room status |
| `epic.passed` | epic status passed |
| `epic.retrying` | epic status retrying/fixing |
| `epic.failed` | epic status failed |
| `plan.run.failed` | plan lifecycle failed |
| `plan.run.completed` | plan lifecycle completed |

Existing status-file polling remains as a compatibility fallback while event-derived projections roll out.

### Broadcast Envelope

```json
{
  "type": "orchestration.event",
  "data": {
    "v": 1,
    "event_id": "evt_01...",
    "event_type": "epic.failed",
    "ts": "2026-06-06T00:00:00Z",
    "plan_id": "pt-example",
    "room_id": "room-003",
    "epic_ref": "EPIC-003",
    "severity": "error",
    "summary": "EPIC-003 failed after QA timeout.",
    "payload": {}
  }
}
```

### Compatibility Adapter

The dashboard currently broadcasts legacy shapes for frontend consumers. Keep those during migration:

| Event-derived state | Legacy compatibility message |
|---|---|
| `room.created` | `room_created` |
| `room.status.changed` | `room_updated` |
| `epic.passed` | `room_updated` with status `passed` |
| `epic.failed` | `room_updated` with status `failed` or `failed-final` |
| `plan.run.completed` | `plans_updated` |
| `plan.run.failed` | `plans_updated` |

The bot should prefer `orchestration.event`; legacy events remain for UI/backward compatibility.

### Notification Mapping

| Orchestration event | Bot notification |
|---|---|
| `plan.run.started` | Plan started |
| `epic.passed` | Epic passed |
| `epic.retrying` | Epic retry |
| `epic.failed` | Epic failed |
| `plan.run.failed` | Plan failed |
| `plan.run.completed` | Plan completed |
| `user.feedback.requested` | Feedback needed |

### .agents Implementation Plan

- `.agents` must append events before updating projections so the dashboard tailer can treat events as truth.
- `.agents` should avoid writing bot-specific payloads. It writes orchestration facts only.
- `.agents` can optionally emit `bot.notification.failed` only when dashboard/bot report delivery failures through a supported control path.

### bot Implementation Plan

- Bot keeps its existing long-lived WebSocket connection.
- Bot handles `type: orchestration.event` before legacy event cases.
- Bot ignores unknown orchestration event types after logging them.
- Bot routes by conversation binding, not by global authorized user list.

### Other aspects

The dashboard is a transport and projection layer, not the event source of truth. Bot notification failures should be represented as `bot.notification.failed` events when the event writer is available.

depends_on: [EPIC-002, EPIC-004]
