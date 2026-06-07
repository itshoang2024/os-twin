## EPIC-003: Manager Loop Fail-Fast Semantics

Roles: @engineer, @qa

Define and implement how the manager loop handles unrecoverable epic failure, runtime process failure, retry exhaustion, and plan shutdown.

### Definition of Done

- [ ] Failure semantics distinguish semantic QA `fail` from runtime `agent.run.failed`.
- [ ] Role process failure, timeout, and crash-respawn exhaustion emit orchestration events.
- [ ] The fail-fast rule is explicit: one unrecoverable epic failure fails the plan run.
- [ ] The manager emits `epic.failed` and `plan.run.failed` before stopping active rooms.
- [ ] The manager preserves the last failed epic message in the failure event payload when available.
- [ ] `ostwin run` exits with code `1` after making the plan failure visible to the dashboard/bot path.

### Acceptance Criteria

- [ ] If a role exits nonzero, times out, or exhausts crash respawns, the event stream contains a role-run failure event.
- [ ] If retries are exhausted or a manager decision rejects the epic, the event stream contains `epic.failed`.
- [ ] When `epic.failed` is emitted, all other active room processes are stopped.
- [ ] The bot layer receives enough payload to show plan ID, epic ref, room ID, role, summary, and last failed message.
- [ ] A semantic QA `fail` still routes to retry/optimize and does not immediately fail the whole plan.

### Tasks

- [ ] Add event emission around current role status failure detection.
- [ ] Map role timeout to `agent.run.timed_out`.
- [ ] Map nonzero role exit to `agent.run.failed`.
- [ ] Map crash-respawn exhaustion to `agent.run.failed` with `reason: crash_respawn_exhausted`.
- [ ] Map lifecycle retry exhaustion to `lifecycle.retry.exhausted` and `epic.failed`.
- [ ] Map manager reject/final failed room to `epic.failed` and `plan.run.failed`.
- [ ] Define shutdown order: append events, expose/broadcast, stop room processes, update projections, exit nonzero.
- [ ] Document how resume treats an already failed run.

### .agents Implementation Plan

#### Role runner events

Role runners emit events through `Write-OrchestrationEvent`:

| Role runner outcome | Event | Projection |
|---|---|---|
| Process starts | `agent.run.started` | role config `active` |
| Exit code `0` and supported signal | `agent.run.completed`, `channel.message.posted` | role config `completed` |
| Nonzero exit | `agent.run.failed` | role config `failed` |
| Timeout | `agent.run.timed_out` | role config `failed` |
| Unsupported final verdict | `agent.run.failed` with `reason: unsupported_verdict` | role config `failed` |

The role runner must not post lifecycle `error` into `channel.jsonl`. Channel output remains semantic agent communication.

#### Manager loop events

The manager loop emits events around state-machine decisions:

| Manager condition | Event sequence |
|---|---|
| Lifecycle signal accepted | `lifecycle.signal.posted`, `lifecycle.transition.applied`, `room.status.changed` |
| QA semantic fail with retries left | `epic.retrying`, `room.status.changed` |
| Retry exhaustion | `lifecycle.retry.exhausted`, `epic.failed`, `plan.run.failed` |
| Runtime role failure in active state | `epic.failed`, `plan.run.failed` |
| Deadlock recovery exhaustion | `agent.run.failed`, `epic.failed`, `plan.run.failed` |
| All rooms passed | `plan.run.completed` |

#### Last-message capture

When emitting `epic.failed`, the manager should include:

```json
{
  "last_message": {
    "message_id": "latest-relevant-channel-id",
    "type": "fail",
    "from": "qa",
    "body_preview": "first 500 chars",
    "artifact": "artifacts/qa-output.txt"
  }
}
```

If no channel message exists, use the role output artifact preview instead. If neither exists, set `last_message` to `null` and include `payload.reason`.

#### Shutdown order

1. Append the most specific failure event: `agent.run.failed`, `agent.run.timed_out`, or `lifecycle.retry.exhausted`.
2. Append `epic.failed` with `plan_id`, `room_id`, `epic_ref`, role/state, and last available failed message.
3. Append `plan.run.failed` with failed epic summary.
4. Flush the event append and make the event log visible for the dashboard heartbeat tailer.
5. Stop all active room processes.
6. Update status projections.
7. Remove manager PID files.
8. Exit `ostwin run` with code `1`.

### dashboard Implementation Plan

- Treat `epic.failed` and `plan.run.failed` from the event tailer as high-priority broadcasts.
- Update plan and room projections before or alongside broadcast.
- Preserve legacy `room_updated` behavior while consumers migrate, but do not require bot notifications to infer failure from room status.
- Expose enough projection data for dashboard UI to show failed epic, failed role, reason, and artifact path.

### bot Implementation Plan

- `NotificationRouter` handles `orchestration.event`.
- `epic.failed` creates an epic failure notification scoped to the bound conversation.
- `plan.run.failed` creates a plan-level failure notification and should include last failed epic summary.
- Unknown failure reasons fall back to a generic plan-failed message while preserving `plan_id`, `room_id`, and `epic_ref`.

### Failure Semantics

| Situation | Event outcome | Lifecycle signal? | Plan outcome |
|---|---|---|---|
| QA finds implementation defects | `lifecycle.signal.posted` with `fail` | yes | retry or optimize |
| Role process exits nonzero | `agent.run.failed` | no | manager decision |
| Role process times out | `agent.run.timed_out` | no | manager decision |
| Retry limit is exhausted | `lifecycle.retry.exhausted`, `epic.failed` | no | `plan.run.failed` |
| Manager rejects escalated work | `epic.failed` | no | `plan.run.failed` |

### Resume Rule

If the active event log already has `plan.run.failed`, resume must not silently append a contradictory continuation to the same failed execution history. Resume should either:

1. create a fresh execution event log or archive the failed log and emit `plan.run.resumed`, or
2. refuse with a clear message requiring explicit retry/reset.

The default for v1 should be option 2 unless EPIC-002 has implemented explicit event-log archival. This keeps history auditable without reintroducing a separate run identifier.

### Other aspects

Do not reintroduce lifecycle `error` as a signal. The lifecycle graph should remain semantic and manager-owned runtime failures should flow through orchestration events.

depends_on: [EPIC-002]
