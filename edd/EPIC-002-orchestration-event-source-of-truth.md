## EPIC-002: Orchestration Event Source of Truth

Roles: @engineer, @qa

Design and implement the append-only event stream that records orchestration facts before status projections are updated.

### Definition of Done

- [ ] `.agents` has a reusable orchestration event writer module.
- [ ] `Start-Plan.ps1` establishes `plan_id` and `events.jsonl` location for the active plan execution.
- [ ] Event envelope is enforced for every append.
- [ ] Event taxonomy covers plan, epic, room, role, lifecycle, messaging, conversation, and user-control events.
- [ ] Status files and role config JSON remain projections derived from events.
- [ ] Idempotency and replay behavior are documented and testable.

### Acceptance Criteria

- [ ] Every orchestration event includes `plan_id`; a separate run identifier is not part of the v1 event envelope.
- [ ] Every room-scoped event includes `room_id` and `epic_ref`.
- [ ] Runtime failures are represented by events, not synthetic channel messages.
- [ ] Existing `channel.jsonl` remains available for agent context and dashboard channel views.
- [ ] Event append happens before room status, progress, or role status projection updates.
- [ ] Replaying the same `event_id` twice does not duplicate projections or bot notifications.

### Tasks

- [ ] Add `.agents/events/OrchestrationEvents.psm1`.
- [ ] Add `New-OrchestrationEventId`, `Write-OrchestrationEvent`, `Read-OrchestrationEvents`, and `Test-OrchestrationEvent`.
- [ ] Add event-log resolution from `plan_id` and `WarRoomsDir`.
- [ ] Update `Start-Plan.ps1` to create or resume execution context and emit `plan.run.started`.
- [ ] Update `New-WarRoom.ps1` to carry `plan_id` and `events_path` in room config when available.
- [ ] Extend `Write-LifecycleSignal` so channel messages include `plan_id`, `room_id`, and `event_id`.
- [ ] Add Pester tests for valid event append, missing required fields, idempotent duplicate handling, and replay.

### .agents Implementation Plan

### Module layout

Create a PowerShell module:

```text
.agents/events/
  OrchestrationEvents.psm1
  README.md
```

The module owns only event log contracts. It must not spawn roles, update room lifecycle, send dashboard notifications, or call bot code.

#### Event log location

Initial implementation:

```text
<warrooms_dir>/events.jsonl
```

Future-compatible historical location:

```text
~/.ostwin/.agents/executions/<plan_id>/<execution-start-ts>/events.jsonl
```

`Start-Plan.ps1` resolves and exports the effective event log path to manager and role runners through room config or environment. Execution identity is represented by the event log path and the ordered event stream, not by a required envelope field:

| Name | Source | Purpose |
|---|---|---|
| `plan_id` | Existing plan metadata and room config | Stable plan identity |
| `events_path` | Derived from war-rooms dir and execution context | Shared append target |

### Event append behavior

`Write-OrchestrationEvent` must:

1. Validate required fields.
2. Fill `v`, `event_id`, `ts`, and `severity` defaults when omitted.
3. Reject events missing `plan_id`.
4. Reject room-scoped events missing `room_id` or `epic_ref`.
5. Serialize one compact JSON object per line.
6. Append under a file lock or atomic append guard suitable for concurrent role processes.
7. Return the appended event object to the caller.

#### Idempotency

Use `event_id` as the idempotency key. For v1, idempotency can be enforced by checking recent/tail events before append. If the same `event_id` already exists with the same payload hash, return the existing event. If the same `event_id` exists with different content, fail the append and log a contract violation.

#### Projection rule

Any caller that needs to update room `status`, `progress.json`, role config JSON, or dashboard state must append the event first. If append fails, projection update must not happen.

### Orchestration Event Envelope

```json
{
  "v": 1,
  "event_id": "evt_01...",
  "event_type": "agent.run.failed",
  "ts": "2026-06-06T00:00:00Z",
  "plan_id": "pt-example",
  "room_id": "room-003",
  "epic_ref": "EPIC-003",
  "role": "qa",
  "state": "review",
  "severity": "error",
  "caused_by": "evt_01...",
  "summary": "QA timed out after 900 seconds.",
  "payload": {
    "exit_code": 1,
    "output_artifact": "artifacts/qa-output.txt"
  },
  "last_message": {
    "message_id": "qa-fail-...",
    "type": "fail",
    "body_preview": "VERDICT: FAIL..."
  }
}
```

Required fields: `v`, `event_id`, `event_type`, `ts`, `plan_id`, `severity`, `summary`, `payload`.

Room-scoped events also require `room_id` and `epic_ref`. Role-scoped events also require `role` and `state`.

### Channel Message Extension

Every `channel.jsonl` row remains a conversation message, but it must carry plan identity so dashboard and bot layers can associate messages with conversations:

```json
{
  "v": 1,
  "id": "qa-fail-...",
  "event_id": "evt_01...",
  "ts": "2026-06-06T00:00:00Z",
  "plan_id": "pt-example",
  "room_id": "room-003",
  "from": "qa",
  "to": "manager",
  "type": "fail",
  "ref": "EPIC-003",
  "body": "VERDICT: FAIL..."
}
```

### Event Taxonomy

| Category | Events |
|---|---|
| Plan authoring | `plan.created`, `plan.updated`, `plan.review.requested`, `plan.review.approved`, `plan.review.rejected`, `plan.dag.built` |
| Plan run | `plan.run.started`, `plan.run.completed`, `plan.run.failed`, `plan.run.cancelled`, `plan.run.paused`, `plan.run.resumed` |
| Epic and room | `room.created`, `room.status.changed`, `epic.started`, `epic.passed`, `epic.failed`, `epic.retrying`, `epic.blocked`, `epic.unblocked` |
| Dependencies | `dependency.created`, `dependency.satisfied`, `dependency.blocked`, `dependency.unblocked` |
| Role assignment | `role.assigned`, `role.reassigned`, `role.resolved`, `role.spawn.requested` |
| Role run | `agent.run.started`, `agent.run.completed`, `agent.run.failed`, `agent.run.timed_out`, `agent.run.respawned` |
| Lifecycle | `lifecycle.signal.posted`, `lifecycle.transition.applied`, `lifecycle.retry.exhausted`, `lifecycle.escalated` |
| Messaging | `channel.message.posted`, `bot.notification.queued`, `bot.notification.sent`, `bot.notification.failed` |
| Conversation | `conversation.bound`, `conversation.unbound`, `conversation.subscription.updated` |
| User control | `user.feedback.requested`, `user.feedback.posted`, `user.plan.cancel_requested`, `user.plan.pause_requested`, `user.plan.resume_requested` |

#### Container Hand-off

| Producer | Event examples | Consumer |
|---|---|---|
| `.agents/Start-Plan.ps1` | `plan.run.started`, `plan.dag.built`, `room.created` | Dashboard EventTailer |
| `.agents/role runners` | `agent.run.started`, `agent.run.completed`, `agent.run.failed`, `channel.message.posted` | Dashboard EventTailer |
| `.agents/manager loop` | `lifecycle.transition.applied`, `epic.failed`, `plan.run.failed`, `plan.run.completed` | Dashboard EventTailer |
| `dashboard` | `bot.notification.failed` when delivery fails and writer is available | Event log and operations |
| `bot` through dashboard | `user.feedback.posted`, `user.plan.cancel_requested`, `user.plan.pause_requested`, `user.plan.resume_requested` | `.agents` manager/control layer |

#### Other aspects

The initial implementation should prefer a simple filesystem event log before adopting a database or external queue. The design should leave room for SQLite or Postgres later without requiring them now.

depends_on: [EPIC-001]
