# Manager Loop — `Start-ManagerLoop.ps1`

> The **brain of Agent OS**. A continuous polling loop that orchestrates autonomous AI agents across parallel war-rooms, routing work through a signal-driven lifecycle state machine.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [V2 Lifecycle State Machine](#v2-lifecycle-state-machine)
- [Signal Processing — `Find-LatestSignal`](#signal-processing--find-latestsignal)
- [Key Functions](#key-functions)
- [Safety Guards](#safety-guards)
- [Deadlock Detection](#deadlock-detection)
- [PLAN-REVIEW Shortcut](#plan-review-shortcut)
- [Release Gate](#release-gate)
- [Configuration](#configuration)
- [Test Coverage](#test-coverage)
- [Known Risks & Mitigations](#known-risks--mitigations)

---

## Overview

`Start-ManagerLoop.ps1` is a **1269-line PowerShell polling loop** that runs continuously until all war-rooms reach a terminal state (`passed`, `failed-final`, or `blocked`) or the process is shut down.

On every iteration (default every 5 seconds), it:

1. Enumerates every `room-*` directory in the war-rooms folder
2. Reads each room's `status`, `lifecycle.json`, and channel messages
3. Decides whether to **transition state**, **spawn an agent**, or **do nothing**
4. Detects and recovers from deadlocks (rooms stuck with no live agents)
5. Checks if all rooms are done and triggers the release pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                      Manager Loop                          │
│                                                             │
│  while (not shutting down):                                 │
│    for each room-* directory:                               │
│      read status, lifecycle.json                            │
│      if pending      → check deps, spawn worker            │
│      if work/review  → check signals, transition or respawn │
│      if decision     → auto-retry or exhaust                │
│      if terminal     → handle release/rescue                │
│    check for deadlocks (stall cycles)                       │
│    check if all rooms passed → release                      │
│    sleep(poll_interval_seconds)                             │
└─────────────────────────────────────────────────────────────┘
```

## Architecture

### Filesystem as the database

The manager uses **no database** — all state is persisted in flat files per room:

| File | Purpose |
|---|---|
| `status` | Current lifecycle state (single line) |
| `lifecycle.json` | V2 state machine definition |
| `config.json` | Room config: assigned role, goals, skill refs |
| `retries` | Number of retry cycles consumed |
| `state_changed_at` | Unix epoch when current state started |
| `crash_respawns` | Consecutive crash-respawn count (safety guard) |
| `deadlock_recoveries` | Total deadlock recovery attempts for this room |
| `audit.log` | Timestamped log of every state transition |
| `channel.jsonl` | JSONL message log (all agent-to-manager comms) |
| `pids/*.pid` | PID files for currently running agents |
| `pids/*.spawned_at` | Spawn lock timestamps (30s grace period) |
| `brief.md` | Original task description for the agent |
| `task-ref` | Task reference ID (e.g., `EPIC-001`, `TASK-001`) |

### Hot-reload

Every 30 seconds, the loop calls `Get-AvailableRoles.ps1` to scan for new role definitions (from `~/.ostwin/roles` and the project's `roles/` directory). This enables **live deployment of new roles** without restarting the manager.

### Concurrency control

The manager tracks `activeCount` — rooms in non-terminal, non-pending states. New rooms are only activated when `activeCount < max_concurrent_rooms` (configurable, default 10).

---

## V2 Lifecycle State Machine

Each room has a `lifecycle.json` that defines a **signal-driven state machine**. The manager doesn't hardcode transitions — it reads them from the lifecycle.

### Default lifecycle

```
pending → developing → review → passed
              ↓ error      ↓ fail
            failed → triage → developing (retry)
            (retries exhausted → failed-final)
```

### State types

| Type | Behavior | Agent spawned? |
|---|---|---|
| `work` | Agent does actual implementation work | Yes |
| `review` | Agent evaluates/reviews prior work | Yes |
| `triage` | Manager classifies failure root cause | No (built-in) |
| `decision` | Auto-transition based on retry count | No (built-in) |
| `terminal` | Final state, no further processing | No |

### Lifecycle JSON structure

```json
{
  "version": 2,
  "initial_state": "developing",
  "max_retries": 3,
  "states": {
    "developing": {
      "role": "engineer",
      "type": "work",
      "signals": {
        "done":  { "target": "review" },
        "error": { "target": "failed", "actions": ["increment_retries"] }
      }
    },
    "review": {
      "role": "qa",
      "type": "review",
      "signals": {
        "pass":     { "target": "passed" },
        "fail":     { "target": "developing", "actions": ["increment_retries", "post_fix"] },
        "escalate": { "target": "triage" },
        "error":    { "target": "failed", "actions": ["increment_retries"] }
      }
    },
    "failed": {
      "type": "decision",
      "auto_transition": true,
      "signals": {
        "retry":   { "target": "developing", "guard": "retries < max_retries" },
        "exhaust": { "target": "failed-final", "guard": "retries >= max_retries" }
      }
    },
    "triage": { "type": "triage", "role": "manager", "signals": { "..." } },
    "passed":       { "type": "terminal" },
    "failed-final": { "type": "terminal" }
  }
}
```

### Dynamic pipeline generation

When a room enters `pending` without a `lifecycle.json`, the manager can **auto-generate** one by:

1. Running `Analyze-TaskRequirements.ps1` to detect required capabilities from the task brief
2. Calling `Resolve-Pipeline.ps1` to build a lifecycle with the right roles (e.g., adding a position-based `review` state for `security-engineer` on security tasks)

---

## Signal Processing — `Find-LatestSignal`

The most critical function in the codebase. It determines which signal (if any) should trigger a state transition.

### Algorithm

```
for each signal_type defined in lifecycle.states[current_state].signals:
    read latest message of that type from channel.jsonl
    if message exists:
        VALIDATE SENDER: message.from must match lifecycle state's role
        VALIDATE TIMING: message.timestamp must be > state_changed_at (strict)
        if both pass → return signal_type
return null (no matching signal)
```

### Sender validation (signal bleed prevention)

Each lifecycle state declares which `role` owns it. Signals from other roles are **rejected**. This prevents a critical bug where a `done` message from `game-engineer` in the `developing` state could bleed through to `game-designer` state and `review` state, causing the room to cascade to `passed` without actual work.

**Example:**
- State `game-designer` has `role: "game-designer"`
- A stale `done` from `game-engineer` is in the channel
- `Find-LatestSignal` rejects it because `game-engineer != game-designer`

### Strict timing (no grace window)

Signals must have timestamp **strictly greater than** `state_changed_at`. Same-second signals are rejected. This prevents stale signals from a previous lifecycle iteration from being re-processed after a state reset.

### Signal actions

When a signal matches, the manager executes its `actions` array before transitioning:

| Action | Effect |
|---|---|
| `increment_retries` | Bumps the `retries` counter file by 1 |
| `post_fix` | Reads the latest fail/error body and posts a `fix` message to the next worker |
| `revise_brief` | Appends triage context to `brief.md` for the next iteration |

---

## Key Functions

### Room management

| Function | Purpose |
|---|---|
| `Write-RoomStatus` | Writes status, updates `state_changed_at`, appends `audit.log`, and cleans up the **previous state's** PID files. On terminal states, nukes all PIDs. |
| `Stop-RoomProcesses` | Kills all processes tracked in `pids/` and removes PID + spawn-lock files |
| `Get-ActiveCount` | Counts rooms in non-terminal, non-pending states |

### Process management

| Function | Purpose |
|---|---|
| `Start-WorkerJob` | Spawns an agent as a background `Start-Job`. Checks spawn lock and PID liveness first. |
| `Write-SpawnLock` | Writes `{role}.spawned_at` with current epoch to create a 30-second spawn grace window |
| `Test-SpawnLock` | Returns `$true` if the spawn lock is within the grace period (default 30s) |

### Triage

| Function | Purpose |
|---|---|
| `Invoke-ManagerTriage` | Classifies failure root cause via keyword matching: `implementation-bug`, `design-issue`, `plan-gap`, or `subcommand-failure:{name}` |
| `Write-TriageContext` | Writes a markdown triage report to `artifacts/triage-context.md` for the next engineer |

### DAG management

| Function | Purpose |
|---|---|
| `Get-CachedDag` | Reads `DAG.json` with mtime-based caching |
| `Set-BlockedDescendants` | BFS from a failed task to mark all downstream dependents as `blocked` |

### Skill resolution

| Function | Purpose |
|---|---|
| `Resolve-RoomSkills` | Queries the dashboard API to find relevant skills for a task, writes `skill_refs` to `config.json`, and copies skill directories into the room |

---

## Safety Guards

The manager implements multiple safety mechanisms to prevent runaway behavior:

### 1. Crash-respawn counter (infinite loop guard)

**Problem:** An agent crashes immediately on spawn (e.g., MCP schema error). No signal is posted. The manager sees no PID and no signal, so it respawns. The agent crashes again. Infinite loop.

**Solution:** A `crash_respawns` file tracks consecutive crash cycles. When it exceeds **3**, the room is marked `failed` instead of respawning.

```
Iteration N:   PID dead, no signal → crash_respawns = 1, respawn
Iteration N+1: PID dead, no signal → crash_respawns = 2, respawn
Iteration N+2: PID dead, no signal → crash_respawns = 3, respawn
Iteration N+3: PID dead, no signal → crash_respawns = 4 > max(3), mark FAILED
```

The counter **resets to 0** on any successful signal transition.

### 2. Spawn lock (duplicate agent guard)

A 30-second grace window (`{role}.spawned_at`) prevents the manager from spawning a duplicate agent while the first one is still initializing (before it writes its PID file).

### 3. Pending signal guard (race condition guard)

Before respawning a dead agent, the manager calls `Find-LatestSignal` a second time. If a signal is pending (agent completed but manager hasn't processed the transition yet), respawn is skipped.

### 4. Sender validation (signal bleed guard)

See [Signal Processing](#signal-processing--find-latestsignal). Prevents a done signal from one role being misattributed to another.

### 5. State timeout

If a room stays in any non-terminal state for longer than `state_timeout_seconds` (default 900s / 15 min), the manager force-restarts it from `initial_state`. Role is re-resolved from the restart state (not the timed-out state — LEAK-6 fix).

### 6. Failed-final rescue

If a room hits `failed-final` but `retries < max_retries` AND there's a fail/error message in the channel, the manager rescues it back to `triage` for another attempt. This handles the case where the `failed -> decision -> failed-final` path fires prematurely.

### 7. One-shot plan approval

`Handle-PlanApproval` (for `PLAN-REVIEW` rooms) is guarded by a `.plan_approved_*` flag file. This prevents the DAG rebuild from firing on every subsequent poll iteration.

---

## Deadlock Detection

If **all active rooms** have no live PIDs for **12 consecutive poll cycles** (~60 seconds), the manager enters deadlock recovery:

1. Skip rooms already in terminal states
2. Skip rooms with pending signals (LEAK-7 fix)
3. Cap deadlock recoveries at 3 per room (then `failed-final`)
4. For recoverable states: increment retries, post fix, restart from `initial_state`

### Known Deadlock Bug (Risk 3)

Deadlock recovery increments retries, which raises the `expected` done-count for the done-count gate. This can make the gate permanently unsatisfiable. See `tests/roles/manager/Deadlock.Tests.ps1` for the full exploitation test.

---

## PLAN-REVIEW Shortcut

When `task-ref` is `PLAN-REVIEW`, the manager runs special shortcut logic **before** the normal signal detection:

1. **Approval detection:**
   - `pass` signal -> approved
   - `plan-approve` signal -> approved
   - `done` with body matching `APPROVED|VERDICT: PASS|plan-approve|signoff` -> approved
2. **Rejection detection:**
   - `fail` signal -> posts `plan-reject` message
   - `done` with body matching `VERDICT: REJECT` -> posts `plan-reject` message

On approval the room transitions to `passed` and `Handle-PlanApproval` fires (rebuilds DAG, unblocks dependent rooms).

---

## Release Gate

When **all rooms** reach `passed`:

1. Run `release/draft.sh` to generate release notes
2. Run `release/signoff.sh` for approval collection
3. If signoff passes -> **RELEASE COMPLETE**, loop exits
4. If signoff fails 3 times -> exits with "pending manual review"

When all rooms are terminal but some failed, the loop exits with a resume command hint.

---

## Configuration

Read from `config.json` at startup:

| Key | Default | Description |
|---|---|---|
| `manager.max_concurrent_rooms` | — | Max rooms in active (non-pending) state |
| `manager.poll_interval_seconds` | — | Sleep between loop iterations |
| `manager.max_engineer_retries` | — | Default max retries (overridden by lifecycle `max_retries`) |
| `manager.state_timeout_seconds` | 900 | Seconds before a state is considered timed out |
| `manager.smart_assignment` | `false` | Enable on-the-fly task analysis for role assignment |
| `manager.dynamic_pipelines` | `true` | Enable on-the-fly lifecycle generation |
| `manager.capability_matching` | `true` | Enable capability-aware triage routing |

---

## Test Coverage

The manager is tested across **5 Pester test suites** with ~190 total test cases. All tests run without live agents — they simulate state by writing directly to the filesystem and channel.

### Test suite map

| File | Tests | Focus |
|---|---|---|
| `Start-ManagerLoop.Tests.ps1` | 87 | V2 lifecycle signals, timing, sender validation, crash guards, spawn locks, PLAN-REVIEW |
| `Orchestration.Tests.ps1` | ~40 | Full message protocol, state machine routing, multi-room concurrency, done-count gate, audit trail |
| `Deadlock.Tests.ps1` | ~15 | Deadlock exploitation: done-counter corruption (Risk 3), QA cascade (Risk 4), stale PIDs (Risk 2), wrong runner (Risk 6) |
| `Redesign.Tests.ps1` | ~2 | Subcommand redesign loop (EPIC-006) |
| `Resolve-RoomSkills.Tests.ps1` | — | Skill resolution via dashboard API |

### Key invariants proven by tests

| Invariant | Test Context |
|---|---|
| Sender validation prevents signal bleed across roles | Signal bleed prevention - room-003 cascade |
| Strict timing rejects stale and same-second signals | Find-LatestSignal - strict timing |
| Crash-respawn counter caps at 3 then marks failed | Crash-respawn counter - guards against infinite crash loops |
| Crash counter resets on successful transition | Crash-respawn counter - reset on successful signal transition |
| Error signal exists on all review states | Review state error signal - evaluator crash handling |
| Error messages use dynamic `$assignedRole`, not hardcoded `"engineer"` | Ephemeral agent error sender identity |
| Spawn lock blocks duplicate spawns within 30s grace | LEAK-9: spawn lock prevents duplicate agents |
| State timeout re-resolves role from restart state | LEAK-6: state timeout re-resolves role |
| Deadlock recovery skips rooms with pending signals | LEAK-7: deadlock recovery must check pending signals |
| Failed-final rescue requires fail/error feedback | LEAK-8: failed-final rescue requires feedback |
| PLAN-REVIEW one-shot flag prevents duplicate approvals | LEAK-5: PLAN-REVIEW shortcut one-shot guard |
| Decision state targets developing (not self-loop) | LEAK-4: decision state does not infinite-loop |

---

## Known Risks & Mitigations

| Risk | Description | Status |
|---|---|---|
| **Risk 3** | Deadlock recovery increments retries -> done-count gate becomes unsatisfiable | Known exploit, tested |
| **Risk 4** | QA deadlock recovery cascades into fixing deadlock (compound of Risk 3) | Known exploit, tested |
| **Risk 6** | Custom lifecycle state with role != `assigned_role` spawns wrong runner | Known exploit, tested |
| **Crash loop** | Agent dies immediately on spawn (MCP error, schema error) - infinite respawn | **Fixed** - crash-respawn counter caps at 3 |
| **Signal bleed** | Done from role A cascades through state owned by role B | **Fixed** - sender validation in `Find-LatestSignal` |
| **Error identity** | `Start-EphemeralAgent.ps1` posted errors as `From "engineer"` - QA errors rejected | **Fixed** - uses `$assignedRole` |
| **Review error signal** | Review states had no `error` signal - crashed QA agent loops forever | **Fixed** - all evaluator states now include `error -> failed` |
