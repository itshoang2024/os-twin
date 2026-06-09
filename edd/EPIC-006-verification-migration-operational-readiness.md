## EPIC-006: Verification, Migration, and Operational Readiness

Roles: @engineer, @qa-automation-engineer
Define and execute validation coverage, automated scenario tests, fix loops, migration checks, and operational readiness for the event-driven orchestration design.

### Definition of Done

- [ ] @engineer fixes all defects found while implementing EPIC-001 through EPIC-005.
- [ ] @qa-automation-engineer creates automated scenario coverage for `.agents`, `dashboard`, and `bot`.
- [ ] Test scenarios cover happy path, semantic QA failure, runtime failure, retry exhaustion, bot broadcast, resume, malformed events, and stale bindings.
- [ ] Migration guidance explains how current room status and role config projections coexist with events.
- [ ] Operational guidance covers event log inspection, failed broadcast investigation, cursor reset, and stale binding cleanup.
- [ ] Observability guidance names the minimum counters and logs required for production confidence.

### Acceptance Criteria

- [ ] Tests prove that one unrecoverable failed epic causes plan failure and nonzero run exit.
- [ ] Tests prove semantic QA `fail` retries or optimizes without immediately failing the plan.
- [ ] Tests prove every emitted event has `plan_id` and `run_id`.
- [ ] Tests prove every room-scoped event has `room_id` and `epic_ref`.
- [ ] Tests prove channel messages carry plan/run identity after the migration.
- [ ] Tests prove dashboard tailer broadcasts normalized `orchestration.event` payloads.
- [ ] Tests prove bot routing uses conversation bindings and not only global notification preferences.
- [ ] Tests prove old channel history remains readable.
- [ ] Tests prove dashboard and bot can handle unknown event types without crashing.
- [ ] Tests prove malformed or partial JSONL rows do not break the tailer.

### Tasks

- [ ] Add Pester coverage for event append, required fields, manager failure handling, and fail-fast exit.
- [ ] Add Pester coverage that semantic lifecycle `fail` still routes to retry/optimize.
- [ ] Add pytest coverage for dashboard `EventTailer`, cursor movement, malformed JSONL, duplicate `event_id`, projection updates, and normalized broadcast.
- [ ] Add bot tests for Telegram conversation binding, Slack-shaped binding, event filtering, unknown events, and failure notification routing.
- [ ] Add an end-to-end dry-run fixture that writes events through `.agents`, tails them through dashboard, and routes them through a mocked bot connector.
- [ ] Add replay/projection smoke test from `events.jsonl`.
- [ ] Add runbook section for inspecting event logs and recovering stuck projections.
- [ ] @engineer fixes all implementation issues found by @qa-automation-engineer and reruns the affected tests.
- [ ] @qa signs off only after all scenario tests pass or remaining failures are explicitly marked unrelated baseline noise.

### Test Ownership

| Owner | Responsibility |
|---|---|
| @engineer | Implement tests near touched code, fix failing implementation, keep contracts aligned with docs |
| @qa-automation-engineer | Build cross-container automated scenarios, mock external Telegram/Slack delivery, capture evidence |
| @qa | Review test quality and ensure acceptance criteria are covered |
| @sre-lead | Review operational checks, logs, cursor recovery, and failure observability |
| @principal-engineer | Verify architecture conformance and no source-of-truth drift |

### Scenario Matrix

| ID | Scenario | Containers | Expected result | Test type |
|---|---|---|---|---|
| S01 | Plan run starts | `.agents`, `dashboard` | `plan.run.started` appended and projected | Pester + pytest |
| S02 | Room is created | `.agents`, `dashboard` | `room.created` event and room projection exist | Pester + pytest |
| S03 | Role completes successfully | `.agents`, `dashboard` | `agent.run.completed`, channel message, and projection update | Pester |
| S04 | Semantic QA `fail` | `.agents` | lifecycle retry/optimize path, no `plan.run.failed` | Pester |
| S05 | Role exits nonzero | `.agents`, `dashboard`, `bot` | `agent.run.failed`, `epic.failed`, `plan.run.failed`, bot receives failure | Pester + pytest + bot test |
| S06 | Role timeout | `.agents`, `dashboard`, `bot` | `agent.run.timed_out`, fail-fast broadcast, exit `1` | Pester + pytest + bot test |
| S07 | Retry exhaustion | `.agents`, `dashboard`, `bot` | `lifecycle.retry.exhausted`, `epic.failed`, `plan.run.failed` | Pester + integration |
| S08 | Last failed message exists | `.agents`, `bot` | failure notification includes `last_message.body_preview` | Pester + bot test |
| S09 | Missing last message | `.agents`, `bot` | failure notification falls back to artifact/reason | Pester + bot test |
| S10 | Dashboard tailer sees new event | `dashboard` | cursor advances and normalized event broadcasts | pytest |
| S11 | Dashboard tailer restarts | `dashboard` | already-seen `event_id` does not rebroadcast | pytest |
| S12 | Partial JSONL row | `dashboard` | cursor waits before partial row and retries | pytest |
| S13 | Invalid JSONL row | `dashboard` | warning logged, no crash, next valid event still processed | pytest |
| S14 | Duplicate `event_id` | `.agents`, `dashboard` | no duplicate projection or notification | Pester + pytest |
| S15 | Telegram binding exists | `bot` | event routes only to bound Telegram conversation | bot unit test |
| S16 | Slack-shaped binding exists | `bot` | event routes through Slack binding contract with mocked connector | bot unit test |
| S17 | Binding missing | `bot` | no global broadcast; event logged as unrouted | bot unit test |
| S18 | Unknown event type | `dashboard`, `bot` | event is logged/ignored without crash | pytest + bot unit test |
| S19 | User cancel request | `bot`, `dashboard`, `.agents` | `user.plan.cancel_requested` appended with plan/run identity | integration |
| S20 | Resume failed plan | `.agents`, `dashboard`, `bot` | new `run_id` or explicit refusal according to EPIC-003 rule | integration |

### Test Implementation Plan

#### .agents Pester

Suggested tests:

```text
.agents/tests/events/OrchestrationEvents.Tests.ps1
.agents/tests/roles/manager/EventDrivenFailure.Tests.ps1
.agents/tests/roles/_base/LifecycleSignalEvent.Tests.ps1
```

Coverage:

- `Write-OrchestrationEvent` validates required fields.
- Event append is one JSON object per line.
- Duplicate `event_id` is idempotent.
- `Write-LifecycleSignal` stamps channel rows with `plan_id`, `run_id`, `room_id`, and `event_id`.
- Manager emits fail-fast events before room process shutdown.
- Manager exits nonzero on unrecoverable plan failure.

#### dashboard pytest

Suggested tests:

```text
dashboard/tests/test_orchestration_events.py
dashboard/tests/test_orchestration_event_tailer.py
dashboard/tests/test_orchestration_event_broadcast.py
```

Coverage:

- EventTailer cursor starts at correct offset.
- Complete lines are processed; partial trailing lines are retried.
- Invalid JSON and invalid envelopes are skipped with warnings.
- Duplicate `event_id` does not rebroadcast.
- Projection update maps `epic.failed` and `plan.run.failed` correctly.
- WebSocket/SSE broadcast shape is `{ "type": "orchestration.event", "data": event }`.

#### bot tests

Suggested tests:

```text
bot/test/conversation-bindings.test.ts
bot/test/notifications-orchestration.test.ts
bot/test/user-control-events.test.ts
```

Coverage:

- Binding is created when a plan is selected/launched.
- Resume updates `run_id`.
- Telegram and Slack-shaped bindings use the same routing logic.
- Event subscription filters work.
- Missing binding does not broadcast globally.
- Unknown events do not crash the router.
- Failure notification includes plan ID, run ID, epic ref, room ID, summary, and last message preview.

### Fix Loop

1. @qa-automation-engineer runs targeted tests for the EPIC being verified.
2. Failures are classified as implementation bug, test bug, environment issue, or existing baseline noise.
3. @engineer fixes implementation bugs and test bugs in the touched scope.
4. @qa-automation-engineer reruns the failed scenario plus adjacent scenarios.
5. @qa verifies acceptance criteria and signs off.
6. @principal-engineer reviews any contract changes that affect prior EPICs.

No EPIC is considered complete until its tests pass and the final EPIC-006 scenario matrix has no untriaged failures.

### Migration Guidance

| Existing artifact | Migration role |
|---|---|
| Room `status` | Remains fast projection; no longer source of truth for audit |
| Role config JSON | Remains role-run projection; no longer only failure record |
| `channel.jsonl` | Remains conversation context; gains plan/run fields |
| Dashboard frontend events | Continue through compatibility adapter |
| Bot notification preferences | Continue as filters, but route through plan-scoped bindings |

### Operational Checks

- [ ] Event log can be tailed and parsed as JSONL.
- [ ] Event replay can rebuild plan and room status projections.
- [ ] Failed bot delivery is visible as `bot.notification.failed` when supported.
- [ ] Stale conversation bindings can be listed and removed.
- [ ] Unknown event types are logged and ignored by consumers that do not support them.
- [ ] Dashboard tailer logs cursor resets and malformed event rows.
- [ ] Runbook explains how to compare `events.jsonl`, room status, dashboard projection, and bot delivery logs.

### Other aspects

Treat generated local config and runtime files as environment-specific. Verification should focus on deterministic contracts and targeted regression tests before broad repo-wide checks.

depends_on: [EPIC-003, EPIC-004, EPIC-005]
