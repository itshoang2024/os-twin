# Architecture Overview

## System Components

OSTwin is composed of four major subsystems:

```
+---------------------+     +--------------------+     +------------------+
|    Engine            |     |    Dashboard        |     |    Bot            |
|  (PowerShell)        |<--->|  (Python FastAPI    |<--->| (TypeScript)      |
|                      |     |   + Next.js FE)     |     |  Discord/Telegram |
|  .agents/            |     |  dashboard/         |     |  bot/             |
+---------------------+     +--------------------+     +------------------+
         |
         |  spawns processes, reads/writes filesystem
         v
+---------------------+
|    War-Rooms         |
|  .war-rooms/room-*/  |
|  (filesystem state)  |
+---------------------+
```

### Engine (`.agents/`)

The PowerShell-first orchestration core. Key scripts:

| Script | Purpose |
|--------|---------|
| `plan/Start-Plan.ps1` | Parses PLAN.md, creates war-rooms, builds DAG, starts the manager loop |
| `.agents/roles/_base/Invoke-Agent.ps1` | Universal agent runner -- all roles execute through this single script |
| `roles/_base/Build-SystemPrompt.ps1` | Composes identity + capabilities + quality gates + task context |
| `roles/_base/Resolve-Role.ps1` | 5-tier role discovery chain |
| `roles/_base/Resolve-RoleSkills.ps1` | 3-tier skill resolution with platform/enabled gating |
| `roles/manager/Start-ManagerLoop.ps1` | Polls war-rooms every 5 seconds, spawns workers, manages lifecycle |
| `plan/Build-DependencyGraph.ps1` | Kahn's algorithm for topological sort, critical path, wave computation |
| `war-rooms/New-WarRoom.ps1` | Creates an isolated room directory with config, brief, channel, lifecycle |
| `channel/Post-Message.ps1` | Posts a JSONL message to a war-room's channel |
| `lifecycle/Resolve-Pipeline.ps1` | Generates the lifecycle state machine per room |

### Dashboard (`dashboard/`)

Python FastAPI backend with 15+ route modules and a Next.js 16 frontend.

- **Backend**: Plan CRUD, room status, skill browser, role registry, MCP management,
  WebSocket events, vector search (zvec), plan agent (AI refinement)
- **Frontend**: React 19, Tailwind 4, zustand stores, DAG visualization,
  epic cards, channel viewer, role/skill browsers

### Bot (`bot/`)

TypeScript multi-platform chat bot (Discord, Telegram, Slack) that bridges
user conversations to the dashboard API via WebSocket.

## Filesystem as the Coordination Primitive

OSTwin uses the filesystem -- not a database, not a message queue -- as its
primary coordination layer:

| File | Scope | Purpose |
|------|-------|---------|
| `room-*/config.json` | Per-room | Goal contract (DoD, AC, constraints) |
| `room-*/channel.jsonl` | Per-room | JSONL message bus between roles |
| `room-*/status` | Per-room | Single-word current state |
| `room-*/lifecycle.json` | Per-room | State machine definition |
| `room-*/brief.md` | Per-room | Task description |
| `room-*/pids/` | Per-room | PID tracking for running processes |
| `room-*/artifacts/` | Per-room | Room artifacts such as wrappers, reports, generated files |
| `room-*/skills/` | Per-room | Copied skill files for this room |
| `DAG.json` | Global | Dependency graph across all rooms |
| `progress.json` | Global | Aggregated completion stats |
| `.agents/memory/ledger.jsonl` | Global | Cross-room shared knowledge base |

This design means every room can be inspected with standard tools (`cat`, `jq`,
`tail -f`), debugged by reading files, and recovered after a crash by re-reading
the filesystem state.

## Concurrency Model

- Up to 50 war-rooms run concurrently (configurable via `max_concurrent_rooms`)
- Each room is an independent OS process with its own PID files
- No central queue -- the manager loop polls the filesystem
- Rooms in the same DAG wave execute in parallel
- The filesystem provides natural locking via PID files and atomic writes

## Key Source Locations

| Component | Path |
|-----------|------|
| Engine core | `.agents/` |
| Role definitions | `.agents/roles/` |
| Community roles | `contributes/roles/` (50+) |
| Skill packs | `.agents/skills/` |
| MCP servers | `.agents/mcp/` |
| Plan scripts | `.agents/plan/` |
| War-room management | `.agents/war-rooms/` |
| Dashboard API | `dashboard/` |
| Dashboard frontend | `dashboard/fe/` |
| Bot | `bot/` |
| Tests (Pester) | `.agents/tests/` |
| Tests (Cypress E2E) | `cypress/` |
| Tests (pytest) | `dashboard/tests/` |
