---
title: What is OSTwin?
description: An introduction to OSTwin — the role operating system for composable AI engineering teams.
sidebar:
  order: 1
---

OSTwin is an **operating system for AI agents**. It takes a markdown plan, decomposes it into a dependency graph of epics, spins up isolated war-rooms, and orchestrates role-based agents to execute each epic — all without writing a single line of agent code.

## The Problem

Building with AI agents today means fighting three unsolved problems:

| Problem | What happens | OSTwin's answer |
|---------|-------------|-----------------|
| **Agent sprawl** | Every task gets a new bespoke agent. Config drifts. Nothing is reusable. | Roles + Skills compose agents from portable building blocks |
| **Context explosion** | Agents share one massive context. Prompt pollution kills quality. | War-rooms isolate each epic's context, memory, and tools |
| **No isolation** | One agent's bad tool call corrupts another's state. No blast radius control. | MCP servers are scoped per war-room. Filesystem boundaries enforced |

Most multi-agent systems treat agents as long-running processes with hardcoded capabilities. OSTwin inverts this: agents are **ephemeral sessions** assembled on demand from composable building blocks. The building blocks are portable, the sessions are disposable, and the coordination is filesystem-native.

The composition chain is the heart of the design:

```text
Plan -> Epics -> War-Rooms -> Roles -> Skills -> Artifacts
```

A plan defines the outcome. Epics divide that outcome into executable promises. Each epic becomes one war-room. The war-room launches the roles named by the epic, and each role receives only the skills that make sense for that room. Downstream epics inherit useful outputs through the DAG and shared memory, but they still run with their own role instances, tools, channel, lifecycle, and skill set.

## Three Axes of Agent Identity

OSTwin defines every agent through three orthogonal axes. This is the core abstraction that makes the system composable:

```
          Identity (WHO)
              │
              │   role.json + ROLE.md
              │   personality, constraints, style
              │
              ├──────────── Expertise (WHAT)
              │             │
              │             │   SKILL.md files
              │             │   domain knowledge, workflows
              │             │   loaded on demand
              │
              └──────────── Execution (HOW)
                            │
                            │   MCP servers
                            │   scoped tool access
                            │   isolated per war-room
```

**Identity** is stable — an architect role always reasons like an architect. **Expertise** is swappable — the same architect can load Unity skills or web skills. **Execution** is isolated — each war-room gets its own filesystem boundary, lifecycle, message channel, memory view, and tool sandbox.

## Core Flow

Every OSTwin run follows the same pipeline:

```
PLAN.md → Parse → DAG → Schedule Waves → Spawn War-Rooms → Execute → Report
                   │         │                  │
                   │    Topological sort    Each room gets:
                   │    into parallel       - channel.jsonl
                   │    waves               - skills/
                   │                        - status file
                   ▼                        - artifacts/
              Dependencies                  - lifecycle.json
              between epics                 - optional worktree
```

1. The **Engine** parses your `PLAN.md` into structured epics.
2. A **DAG** resolves the logical flow between epics and sorts them into execution waves.
3. Each epic gets a **War-Room**: an isolated team room with its own channel, lifecycle, artifacts, memory view, and optional Git worktree.
4. **Agents** are composed at runtime from roles, relevant skills, and scoped MCP tools, then execute inside their war-room.
5. A **lifecycle state machine** governs each room's progress: work, review, retry, triage, and final `done` or `failed` outcome.

## Flow Concepts

The DAG is the plan's delivery map. It is not just a visual dependency chart; it tells the manager which epics can run in parallel, which epics must wait for upstream outputs, and which downstream rooms should be blocked if an upstream dependency cannot be completed. A DAG edge means "this room needs that room's result before it can safely start."

An epic is a team, not a single prompt. When OSTwin starts an epic, it creates a war-room where the assigned roles collaborate under the manager. The engineer may implement, QA may review, an architect or specialist may advise, and the manager coordinates the handoffs. When roles disagree or a review fails, the manager routes the conflict through retry or triage, weighs the evidence in the room channel, and decides whether to fix, revise, block descendants, or continue.

The flow also keeps code and assets inside the delivery path. In room-worktree isolation, each epic works in its own Git worktree. When a room reaches a successful terminal outcome, its code changes, generated assets, research reports, and other durable artifacts can be committed on that room branch and integrated before dependent epics begin. Downstream teams then inherit real repository state, not just a chat summary.

During epic ramp-up, OSTwin resolves the team's expertise before work begins. Role defaults, plan-level skill references, room-level needs, and discovered task keywords are merged into a skill set for that room. The agent sees a lean skill index first, then loads full skill instructions on demand, so a backend epic, UI epic, audit epic, or deep-research epic can all use the same role identity with different runtime expertise.

Because role identity and skill expertise are separate, two epics can use the
same role differently. `engineer` can be a backend implementer in EPIC-002, a
frontend maintainer in EPIC-003, and a release fixer in EPIC-004 simply by
changing the skills resolved for that room.

## Key Design Decisions

:::note[Why these choices?]
Every design decision in OSTwin optimizes for one thing: **letting AI agents collaborate reliably at scale without custom code**.
:::

- **Filesystem coordination** — JSONL channels, JSON status files, markdown plans. No database required. Git-friendly. Every agent can read/write with basic file I/O.
- **Scale on depth, not width** — Instead of many shallow agents, OSTwin uses fewer stable roles with deeper, room-specific skill resolution.
- **Config over code** — Agents are defined by `role.json` + `ROLE.md` + `SKILL.md`, not Python classes. Non-engineers can modify agent behavior.
- **Ephemeral agents** — No persistent agent processes. Each session is composed fresh from its role, skills, and tools. No state leaks between runs.

## System Components

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Engine** | Local orchestration runtime | Parses plans, builds DAG, orchestrates war-rooms, manages lifecycle |
| **Dashboard** | FastAPI + Next.js | Real-time monitoring, plan status, war-room inspection, memory search |
| **Bot** | TypeScript | Conversational interface for plan management and agent interaction |
| **MCP Servers** | Python (FastAPI) | Tool providers scoped per war-room — filesystem, memory, channel ops |
| **Skills** | Markdown (`SKILL.md`) | Portable domain expertise loaded into agent context on demand |
| **Roles** | JSON + Markdown | Agent identity definitions — personality, constraints, allowed skills |

## What OSTwin is NOT

- **Not an agent framework** — You don't write agents. You write plans and roles.
- **Not a prompt chain** — Agents make autonomous decisions within their war-room scope.
- **Not a wrapper around one LLM** — Provider-agnostic. Works with Anthropic, OpenAI, Google, or local models.
- **Not a chatbot** — There is no conversational loop. Plans go in, artifacts come out.

## Who is OSTwin For?

- **Teams using AI for software engineering** — automate entire feature development cycles
- **Platform engineers** — build internal tooling around composable agent primitives
- **AI researchers** — experiment with multi-agent coordination without framework lock-in
- **Solo developers** — get an entire engineering team (architect, engineer, QA) from a single plan file

:::tip
The fastest way to start is the [Quick Start](/getting-started/quick-start/). It gets you from install to `plan.md`, then shows the create/run flow.
:::

## Next Steps

Ready to install? Head to [Installation](/getting-started/installation/) to get OSTwin running locally.
