---
title: Agentic Engineering Playbook
description: A field guide for prompt structure, context engineering, role/evaluator workflows, and EPIC quality.
sidebar:
  order: 2
---

**Build Agents That Actually Ship.**

A field guide for engineers working in an AI-first SDLC. Every section maps a concept to how it changes the way you write prompts, design contexts, and structure epics — because in agentic systems, **your planning is your code**.

---

## 00. The SOLID Plan Flow

A SOLID plan is not a task list. It is a two-phase conversion system:

1. **Align product truth.**
2. **Design the system, then distribute the work.**

The first phase protects the team from building the wrong thing. The second phase protects the team from building the right thing in a messy, untestable way.

### Phase 1: Product Truth Alignment

Start from the business standpoint and force the product management team to turn intent into a clear markdown contract before any agent begins implementation.

The product contract should answer:

* **Business outcome**: what measurable result changes if this ships?
* **Customer or user**: whose workflow, pain, risk, or opportunity is being served?
* **Product decision**: what experience, policy, or capability is being committed?
* **Success metrics**: which product, operational, or financial signals prove value?
* **Scope and non-goals**: what is in, what is out, and what must not be changed?
* **User journeys**: which happy path, edge cases, empty states, and failure states matter?
* **Acceptance criteria**: what must be true for product, QA, and stakeholders to accept the work?

Recommended markdown artifacts:

```text
PRODUCT.md              # Business outcome, users, value, constraints
JOURNEYS.md             # User journeys, states, edge cases, service moments
ACCEPTANCE-CRITERIA.md  # Given/When/Then checks from the product standpoint
SCOPE.md                # In scope, out of scope, assumptions, risks
```

Exit gate: product, design, and business owners can read the markdown and agree on the same outcome without extra explanation.

### Phase 2: System Design & Distributed Execution

After product truth is aligned, translate it into system design. This is where the team decides how the product promise becomes data, components, APIs, services, state transitions, tests, and operational behavior.

The system design contract should cover:

* **C4 model**: context, containers, components, and the boundaries between them.
* **Data modeling**: entities, relationships, ownership, lifecycle, migrations, and retention.
* **API and event contracts**: commands, queries, events, payloads, errors, idempotency, and versioning.
* **Workflow and state**: state machines, permissions, queues, background jobs, and failure recovery.
* **Non-functional requirements**: security, privacy, latency, reliability, observability, cost, and accessibility.
* **Rollout plan**: feature flags, migration order, backwards compatibility, rollback, and support readiness.

Recommended markdown artifacts:

```text
SYSTEM-DESIGN.md  # Architecture narrative and major decisions
C4.md             # Context, container, component diagrams
DATA-MODEL.md     # Entities, ownership, lifecycle, migration plan
CONTRACTS.md      # APIs, events, permissions, errors, compatibility
PLAN.md           # Epics, dependencies, roles, acceptance gates
```

Exit gate: every epic can be assigned to an agent team with a clear product outcome, a system boundary, owned artifacts, test evidence, and a dependency position in the delivery graph.

<!--
### Split Epics by Outcome

Do not split epics into frontend, backend, database, and test workstreams. Split them by **the outcome a user or operator can verify**.

A strong epic owns one customer-visible improvement or one enabling platform capability. It may touch UI, APIs, data, tests, and docs, but it should still have one owner, one boundary, and one acceptance test.
-->

---

## 01. The Pyramid Principle

Borrowed from consulting, the **Pyramid Principle** is the most important thinking structure for anyone writing prompts, EPICs, or technical specs for AI agents. The rule is simple: *lead with your conclusion, then prove it*.

An LLM processes your prompt top-to-bottom and must hold all prior context in its attention window. If the conclusion is at the bottom, the agent has already made decisions before it knows what you want.

### The Three Pyramid Rules

| Rule | Meaning | In Practice |
| --- | --- | --- |
| **BLUF** | Bottom Line Up Front | First sentence = the task/decision |
| **MECE** | Mutually Exclusive, Collectively Exhaustive | No overlap in acceptance criteria; no gaps |
| **Rule of 3** | Group support into ≤3 clusters | Max 3 goals per EPIC phase, 3 AC per Story |

> **The Pyramid Principle is the foundation of every other concept in this handbook.** EPICs lead with the outcome. Prompts lead with the task. Context files lead with the current state. Master this, and everything else becomes cleaner.

---

## 02. Prompt-Driven Context

In classical software, your source code *is* the product. In agentic systems, **your context is the source code**. What you give the agent completely determines what it builds.

**Core Principle:** The quality of the AI's output is entirely a function of the quality of its input context. There is no "prompt magic." There is only context quality.

### What "Context" Means in This System

* **CONTEXT.md**: The agent's memory. Tech stack, current phase, blockers, routing tags. Re-read at every session start.
* **PLAN.md**: The Supervisor's spec. Phase goals, tasks per role, AC, DoD. The source of truth.
* **SKILL.md**: Capability instruction files. Loaded on-demand via MCP.
* **TODO.md**: Engineer's append-only log. Release notes per version.

> **If you find yourself correcting an agent mid-task, you have a context problem, not a model problem.** Go back and improve the PLAN.md before the next cycle.

---

## 03. Context Engineering

Context Engineering is designing the information environment for an agent's mind. A poorly-structured context produces hallucinations and out-of-scope changes.

### The Four Properties of Good Context

1. **Bounded**: One context per feature. No cross-feature contamination.
2. **Current**: CONTEXT.md reflects *actual* current state, not intended state.
3. **Append-only**: History is never deleted. Agents read the full chain of decisions.
4. **Role-scoped**: Each agent owns exactly one file. Reads others' as read-only.

### CONTEXT.md Format — Required Fields

```yaml
# CONTEXT.md — {Feature Name}
Project:          {repo name}
Tech stack:       TypeScript, Postgres 15, Redis, Next.js 14
Routing tags:     [backend], [frontend]
Current phase:    Phase 2
Last completed:   v1d (Phase 1 — auth scaffolding)
Current blocker:  none
Architecture decisions:
  - JWT stored in httpOnly cookie (not localStorage)
  - Prisma ORM, no raw SQL
Phase summary:
  Phase 1 — Auth scaffolding (DONE)
  Phase 2 — Payment flow (ACTIVE)
  Phase 3 — Notifications (PENDING)
Agent assignments:
  Supervisor: Claude
  Engineer:   Cursor / Claude Code
  QA:         Claude (separate session)
```

---

## 04. MCP & Skills

**MCP (Model Context Protocol)** connects AI agents to tools and data dynamically. **Skills** (`SKILL.md` files) sit on top of MCP, instructing an agent *how* to use those tools.

### Skill File Design Rules

* **Lead with trigger conditions** — when to use this skill, when not to.
* **Include a worked example** — agents learn from demonstration.
* **State constraints explicitly** — what the skill must never do.
* **Version your skills** — changes break running agents.
* **Keep skills single-purpose** — one SKILL.md per domain.

### MCP Server Scoping — Role-Based Access

Not every agent needs every tool.

* **Supervisor**: filesystem (read), ROOM bus
* **Engineer**: filesystem (rw), shell, git, DB
* **QA**: filesystem (read), test runner, ROOM bus
* **DevOps**: cloud CLI, registry, ROOM bus

---

## 05. Roles: Worker & Evaluator

The fundamental unit of agentic collaboration is the **Worker / Evaluator pair**. One agent produces; another validates.
**Self-review is a cognitive trap for both humans and LLMs.**

### Worker Agent (Engineer)

* **CLAIM** before starting any task
* **WORKING heartbeat** every ~5 min on long tasks
* Write **TODO.md Release Notes FIRST**, then post RELEASE event
* Wait for QA response via `--wait-for BUG,DELIVER`
* Max 3 BUG cycles, then post BLOCKED and escalate

### Evaluator Agent (QA)

* **REVIEWING** before starting review (prevents duplicate QA)
* Read **TODO.md Release Notes** before testing
* Write **QA.md bug table FIRST**, then post BUG event
* Test against **PLAN.md AC**, not personal preference

> QA never invents requirements. Scope creep kills velocity.

---

## 06. English as the Embedding Layer

When writing context consumed by an LLM — **write in English**.

* **Training data density**: ~70–80% of most LLM pretraining corpora is English.
* **Token efficiency**: 1 English word ≈ 1–1.5 tokens (vs. 2-4 tokens for other languages).
* **Instruction following**: Highest benchmark scores.
* **Code alignment**: Code is written in English; context matches code natively.

All PLAN.md, CONTEXT.md, SKILL.md, AC, and DoD must be written in **English**. User-facing content can be localized.

---

## 07. Domain-Driven Design & TDD for Agents

### Domain-Driven Design (DDD)

* **Ubiquitous Language**: A shared vocabulary between engineers, agents, and domain experts.
* **Bounded Context**: Each feature context folder = one bounded context.
* **Aggregates**: Group related entities that change together.
* **Domain Events**: ROOM.jsonl is your event bus (`RELEASE`, `BUG`, `DELIVER`).

### Test-Driven Development (TDD) for Agent Tasks

Supervisor writes Acceptance Criteria (the "test") in PLAN.md → Engineer implements until AC passes → QA runs AC as literal test cases → DELIVER only when all AC are green.

**GIVEN / WHEN / THEN is the lingua franca of AC.**

```text
AC-1: GIVEN valid userId and cartId
      WHEN  PaymentSession.create() is called
      THEN  returns a unique SessionId AND persists to DB
```

---

## 08. The EPIC Planning Standard

The EPIC is the primary source of truth for a deliverable slice. It is the bridge between product intent, system design, and agent execution.

A world-class epic is:

* **Outcome-led**: it starts with the value or system capability that will exist after completion.
* **Product-grounded**: it links back to the business goal, user journey, and acceptance criteria.
* **Architecture-aware**: it names the system boundary, data model impact, contracts, and operational constraints.
* **Lean**: it is small enough for one focused agent team to build, review, fix, and verify.
* **Testable**: QA can prove the outcome from the epic text without inventing requirements.
* **Observable**: completion produces artifacts, test evidence, and room events that can be audited.

### The Canonical EPIC Format

```markdown
## EPIC-001 - {Outcome Statement}
Roles:        @engineer, @qa, @devops
depends_on:   [EPIC-000]
routing:      [frontend], [backend], [data], [qa]

### Product Intent
Business outcome: {measurable value or risk reduction}
User/customer:    {primary actor or stakeholder}
Product decision: {the behavior, policy, or experience being committed}
Source docs:      PRODUCT.md, JOURNEYS.md, ACCEPTANCE-CRITERIA.md

### System Design
C4 boundary:      {context/container/component touched by this epic}
Data model:       {entities, ownership, migrations, retention}
Contracts:        {APIs, events, permissions, errors, compatibility}
NFRs:             {security, performance, observability, accessibility}

### Execution Scope
IN:
- {specific capability, behavior, or system change}

OUT:
- {adjacent work intentionally excluded}

### Definition of Done
- [ ] All Acceptance Criteria pass (QA verified)
- [ ] No HIGH or CRITICAL bugs open
- [ ] Product acceptance evidence attached
- [ ] System design deltas documented
- [ ] Unit/integration/e2e coverage matches risk
- [ ] CONTEXT.md updated to reflect completion
- [ ] Rollout, rollback, and observability notes are complete

### Acceptance Criteria
- [ ] AC-1: GIVEN {precondition} WHEN {action} THEN {expected result}
- [ ] AC-2: GIVEN {precondition} WHEN {action} THEN {expected result}
- [ ] AC-3: GIVEN {failure or edge case} WHEN {action} THEN {safe behavior}

### Tasks
- [ ] Task 1: {product-visible behavior} — [routing-tag]
- [ ] Task 2: {data/model/contract change} — [routing-tag]
- [ ] Task 3: {verification and observability evidence} — [routing-tag]

### Agent Team Flow
1. @engineer implements from Product Intent + System Design.
2. @qa validates AC, edge cases, and regression risk.
3. @devops or @sre verifies rollout, telemetry, and recovery when needed.
4. Manager closes only after artifacts, evidence, and room state agree.
```

### EPIC Quality Checklist

* Has a unique `EPIC-{NNN}` ID.
* Outcome statement is one sentence (BLUF).
* Roles are explicitly listed.
* IN/OUT scope is explicit.
* Product intent links back to business outcome and user journey.
* System design names C4 boundary, data impact, contracts, and NFRs.
* DoD is a binary checklist.
* Every task has ≥2 AC in `GIVEN/WHEN/THEN` format.
* Tasks have routing tags (`[backend]`, `[frontend]`).
* `depends_on` is declared.
* The epic is small enough for one agent team to complete and verify without cross-room ambiguity.
* QA can test the epic without inventing requirements.

### Epic Sizing Rule

If an epic cannot fit into one clear outcome, split it. The usual split order is:

1. Product journey slice.
2. System boundary.
3. Data ownership boundary.
4. Risk or rollout boundary.

Avoid epics named after activities such as "Build backend" or "Create UI." Prefer outcomes such as "Customer can approve a policy exception with an auditable decision trail."

---

## 09. Agentic Ops: Best Practices

Agents fail differently than humans. They hallucinate silently, get stuck in loops, or produce plausible-looking but wrong output.

### The Five Pillars of Agentic Ops

1. **Observable**: Every action is posted to ROOM.jsonl.
2. **Bounded**: Agents operate within scoped MCP servers.
3. **Recoverable**: All context files are append-only.
4. **Heartbeated**: Long-running agents post WORKING events every ~5 min.
5. **Escalating**: Max 3 BUG cycles. On cycle 4, post BLOCKED and escalate to Supervisor.

> **The File-First Rule:** Always write your file completely *before* posting the ROOM event. File first. Event second. Always.

---

## 10. Code Quality = Context Quality

Everything converges on a single, non-negotiable truth:
**The quality of the AI's code is entirely determined by the quality of the EPICs, Definitions of Done, and Acceptance Criteria.**

### The 2-22 Framework

* **Invest 2 hours:** Human writes precise EPIC, AC, DoD, CONTEXT.md, seeds the ROOM.
* **Unlock 22 hours:** Agents execute, loop, validate, and ship — autonomously, correctly.

Every technique in this playbook serves one purpose: **to make your context so precise that the agent cannot fail to understand what you want.** That is the craft of agentic engineering.
