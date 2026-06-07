# War-Rooms: Isolated Execution Units

## Core Concept

A war-room is an isolated filesystem directory where agents collaborate to
complete a single epic. Each war-room is a self-contained process container
with its own message channel, lifecycle state machine, skills, and PID tracking.

War-rooms are the answer to the coordination chaos problem: execution state
(what is this task doing?) is local to the room, while coordination state
(which rooms are blocked on which?) lives in the global DAG.

## Directory Layout

```
.war-rooms/room-001/
  config.json          # Goal contract (DoD, AC, constraints, status)
  brief.md             # Task description for the agent
  channel.jsonl        # JSONL message bus between roles
  lifecycle.json       # State machine definition
  status               # Current state (single word: "pending", "developing", etc.)
  retries              # Retry counter
  done_epoch           # Completion timestamp
  task-ref             # Quick lookup: "EPIC-001"
  TASKS.md             # Work breakdown within the epic
  engineer_001.json    # Per-role instance config (model, timeout, skills)
  qa_001.json          # Another role instance
  pids/                # PID files for running processes
  artifacts/           # Room artifacts such as wrappers, reports, generated files
  contexts/            # Per-role context snapshots
  skills/              # Copied skill files scoped to this room
```

## The Goal Contract (`config.json`)

Every room's `config.json` follows a strict schema
(`.agents/war-rooms/config-schema.json`) and contains:

```json
{
  "room_id": "room-001",
  "task_ref": "EPIC-001",
  "plan_id": "abc123",
  "created_at": "2026-04-01T10:00:00Z",
  "working_dir": "/path/to/project",
  "assignment": {
    "title": "Build Auth Module",
    "description": "...",
    "assigned_role": "engineer",
    "candidate_roles": ["engineer", "qa"],
    "type": "epic"
  },
  "goals": {
    "definition_of_done": [
      "Core logic implemented",
      "Unit test coverage >= 80%"
    ],
    "acceptance_criteria": [
      "Valid JWT returns 200",
      "Expired JWT returns 401"
    ],
    "quality_requirements": {
      "test_coverage_min": 80,
      "lint_clean": true,
      "security_scan_pass": true
    }
  },
  "constraints": {
    "max_retries": 3,
    "timeout_seconds": 900,
    "budget_tokens_max": 500000
  },
  "status": {
    "current": "pending",
    "retries": 0,
    "started_at": null,
    "last_state_change": "2026-04-01T10:00:00Z"
  },
  "skill_refs": ["implement-epic", "create-lifecycle"]
}
```

## The Message Channel (`channel.jsonl`)

All communication between roles within a room flows through `channel.jsonl` --
an append-only JSONL file. Each line is a message:

```json
{"ts": "2026-04-01T10:05:00Z", "from": "manager", "to": "engineer", "type": "task", "ref": "EPIC-001", "body": "..."}
{"ts": "2026-04-01T11:30:00Z", "from": "engineer", "to": "qa", "type": "done", "ref": "EPIC-001", "body": "Implementation complete."}
{"ts": "2026-04-01T11:45:00Z", "from": "qa", "to": "manager", "type": "pass", "ref": "EPIC-001", "body": "All tests passing."}
```

The channel scripts (`.agents/channel/`) provide:
- `Post-Message.ps1` -- append a message
- `Read-Messages.ps1` -- read/filter messages by type, role, or time range
- `Wait-ForMessage.ps1` -- block until a specific message type appears

## Room Creation Flow

1. `Start-Plan.ps1` parses the plan markdown and extracts epics
2. For each epic, `New-WarRoom.ps1` is called with the epic's metadata
3. The room directory is created with all required files
4. Per-role instance configs are generated with model resolution:
   - Priority 1: Plan-specific `{plan_id}.roles.json`
   - Priority 2: Global `.agents/config.json`
   - Priority 3: Role's own `role.json`
   - Priority 4: Default model

## Multi-Agent Collaboration in a Room

Multiple roles can operate within the same war-room. A typical flow:

```
Manager
  |-- spawns --> Engineer (reads brief.md, implements code, posts "done")
  |
  |-- spawns --> QA (reads channel, reviews code, posts "pass" or "fail")
  |
  |-- (if fail) spawns --> Engineer again (reads fail feedback, fixes, posts "done")
```

Each role gets its own instance config file (`{role}_{id}.json`) inside the
room, specifying its model, timeout, and skill_refs. The room's `skills/`
directory contains copies of all skill files relevant to the roles working in
that room.

## Room Isolation Guarantees

| Boundary | Mechanism |
|----------|-----------|
| Message isolation | Each room has its own `channel.jsonl`. No cross-room message leakage. |
| Skill isolation | Skills are copied to `room-*/skills/`. The `AGENT_OS_SKILLS_DIR` env var scopes skill discovery. |
| MCP isolation | Each room gets its own `opencode.json` via `OPENCODE_CONFIG` env var. |
| Process isolation | Each agent runs as a separate OS process tracked by PID files in `pids/`. |
| Memory isolation | Conversation memory is the room's channel. Cross-room knowledge goes through the shared ledger with provenance filtering. |

## Room Teardown

`Remove-WarRoom.ps1` handles cleanup:
1. Kills all tracked PIDs (graceful SIGTERM, then force kill after 2s)
2. Optionally archives `channel.jsonl`, `config.json`, `goal-verification.json`,
   and `audit.log` to `.archives/`
3. Removes the directory

## Concurrency

- Up to 50 rooms run concurrently (configurable: `max_concurrent_rooms`)
- Rooms in the same DAG wave execute in parallel
- No central queue -- the manager loop polls the filesystem every 5 seconds
- Each room is fully independent -- a crash in one room does not affect others

## Monitoring

The dashboard's background task (`dashboard/tasks.py`) polls war-room
directories every second, detects status changes and new messages, and
broadcasts events via SSE to the frontend.

The `Get-WarRoomStatus.ps1` script provides a CLI status dashboard showing
all rooms with their current state, retry count, message count, and goal
completion.

## Key Source Files

| File | Purpose |
|------|---------|
| `.agents/war-rooms/New-WarRoom.ps1` | Create a war-room directory |
| `.agents/war-rooms/Remove-WarRoom.ps1` | Teardown with optional archiving |
| `.agents/war-rooms/Get-WarRoomStatus.ps1` | CLI status dashboard |
| `.agents/war-rooms/config-schema.json` | JSON schema for room config |
| `.agents/war-rooms/Test-GoalCompletion.ps1` | Check if DoD/AC are met |
| `.agents/channel/Post-Message.ps1` | Post to the JSONL channel |
| `.agents/channel/Read-Messages.ps1` | Read/filter channel messages |
| `dashboard/tasks.py` | Background polling for room state changes |
| `dashboard/routes/rooms.py` | REST API for room management |
