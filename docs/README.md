# OSTwin Documentation

OSTwin is a zero-agent operating system for composable AI engineering teams.
It scales on **skill depth**, not agent count.

## The Composability Story

OSTwin starts with a human-readable **Plan**. A plan describes the goal, then
breaks that goal into **Epics** connected by a dependency **DAG**. Each epic is
the smallest independently executable promise: it has an objective, a Definition
of Done, acceptance criteria, dependencies, and the **Roles** needed to complete
it.

When the plan runs, every epic becomes an isolated **War-Room**. The war-room is
where composition becomes concrete:

- The **Epic** defines the mission and the dependency boundary.
- The **Roles** define who should reason about the mission: architect,
  engineer, QA, auditor, reporter, or a custom specialist.
- The **Skills** define what those roles know how to do for this specific room.
- The **War-Room** scopes execution, messages, tools, lifecycle, memory, and
  artifacts so one epic cannot leak state into another.

This means OSTwin does not grow by creating more permanent agents. It grows by
recombining smaller primitives. The same `engineer` role can work on a backend
epic with API-testing skills, a dashboard epic with frontend skills, or a
release epic with packaging skills. The role keeps its identity; the skills
change with the epic.

## How Roles and Skills Move Across Epics

A plan can assign different role-and-skill combinations to each epic:

```markdown
### EPIC-001 -- Design Auth Architecture
Roles: architect, security-auditor
depends_on: []

### EPIC-002 -- Implement Auth API
Roles: backend-engineer, qa
depends_on: ["EPIC-001"]

### EPIC-003 -- Document Release Notes
Roles: reporter, technical-writer
depends_on: ["EPIC-002"]
```

At runtime, OSTwin resolves each role, merges the relevant `skill_refs`, copies
those skill files into that epic's war-room, and launches the same universal
runner. Downstream epics receive predecessor outputs through the DAG and shared
memory ledger, but they still execute in their own room with their own role
instances and skill set.

That is the core design: **Plans compose Epics. Epics compose Roles. Roles
compose Skills. War-Rooms isolate each composition.**

## The Five Pillars

OSTwin separates three axes that other frameworks fuse:

| Axis | Artifact | Question it answers |
|------|----------|---------------------|
| Identity | `role.json` + `ROLE.md` | *Who am I?* |
| Expertise | `SKILL.md` files | *What do I know?* |
| Execution | `war-room/` directory + scoped tools | *Where do I run?* |

These axes are composed independently through five architectural pillars:

| # | Pillar | Doc |
|---|--------|-----|
| 1 | [The Zero-Agent Pattern](roles-and-zero-agent.md) | Roles are config, not code. One universal runner serves all roles. |
| 2 | [Skills as Atomic Expertise](skills.md) | Skills are `SKILL.md` files discovered at runtime, not baked into prompts. |
| 3 | [MCP Isolation Per Role](mcp-isolation.md) | Tools are scoped per role and per room, saving tokens and reducing blast radius. |
| 4 | [War-Rooms: Isolated Execution](war-rooms.md) | Each epic runs in a self-contained directory with its own channel, lifecycle, and PID tracking. |
| 5 | [Layered Memory](memory.md) | Conversation, code artifacts, and shared ledger -- each bounded. |

## Additional Systems

| System | Doc |
|--------|-----|
| [Agentic Memory MCP](agentic-memory.md) | Semantic knowledge base with auto-linking, tagging, and vector search. |

## Execution Model

| Topic | Doc |
|-------|-----|
| [Plans, Epics, and the DAG](plan-epic-dag.md) | How plans are defined, how epics declare DoD/AC/Tasks, how the dependency graph controls ordering. |
| [Epic Lifecycle](lifecycle.md) | State machine, transitions, retries, and escalation. |
| [Architecture Overview](architecture-overview.md) | System-level view: engine, dashboard, bot, and how they connect. |
