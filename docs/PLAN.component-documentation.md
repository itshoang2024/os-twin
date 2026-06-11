# Plan: Comprehensive Component Documentation & Architecture Refinement

> Created: 2026-05-08
> Status: draft
> Owner: technical-writer

## Config

working_dir: ./

## Goal

Produce a unified, high-quality documentation suite for every OSTwin subsystem — closing gaps between existing docs, incorporating runtime knowledge from `dashboard/knowledge/` and `.agents/memory/`, and improving system design through documentation-driven analysis.

## Architecture Synthesis

OSTwin is a filesystem-first, agent-orchestration platform built on five architectural pillars:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              OSTwin Platform                                    │
├───────────┬───────────┬───────────┬───────────┬───────────┬─────────────────────┤
│  Engine   │ Dashboard  │   Bot     │  Memory   │ Knowledge │  MCP / Skills /    │
│(.agents/) │(dashboard/)│ (bot/)    │ (2-tier)  │(knowledge/)│  Roles / Lifecycle │
│           │            │           │           │           │                     │
│ PS core   │ FastAPI+   │ TS multi- │ Ledger +  │ Namespace │  Per-room MCP      │
│ plan→DAG  │ Next.js FE │ platform  │ Agentic   │ Vector +  │  Zero-agent roles  │
│ manager   │ 15+ routes │ Discord/  │ Memory    │ Graph DB  │  SKILL.md packs    │
│ loop      │ DAG viz    │ Tele/Slk  │ MCP svcs  │ Ingestion │  Lifecycle FSM     │
└───────────┴───────────┴───────────┴───────────┴───────────┴─────────────────────┘
         │                │            │            │              │
         ▼                ▼            ▼            ▼              ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                  Filesystem as Coordination Primitive                            │
│  .war-rooms/room-*/  │  .agents/memory/  │  .memory/  │  ~/.ostwin/            │
│  config.json         │  ledger.jsonl     │  notes/    │  mcp/config.json       │
│  channel.jsonl       │  index.json       │  vectordb/ │  plans/*.md            │
│  status              │                   │            │  channels.json         │
│  lifecycle.json      │                   │            │                        │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Dual Memory Architecture (Key Finding)

OSTwin operates **two independent memory systems** that serve different scopes:

| Aspect | Layered Memory (Pillar 5) | Agentic Memory (Pillar 5.5) | Knowledge Service |
|--------|--------------------------|----------------------------|-------------------|
| **Purpose** | Cross-room coordination | Long-term semantic notes | Document-based RAG |
| **Storage** | `.agents/memory/ledger.jsonl` | `<project>/.memory/notes/*.md` | `~/.ostwin/knowledge/<ns>/` |
| **Search** | BM25 + time decay | Vector similarity (zvec) | Vector + Graph (KuzuDB) |
| **Links** | None | Auto-evolution links | Knowledge→Memory bridge |
| **Scope** | Plan-level (session) | Project-level (persistent) | Namespace-level |
| **LLM** | None | Gemini/OpenAI analysis | Gemini/OpenAI extraction |
| **Graph** | None | None | KuzuDB entity-relation |
| **MCP** | `memory-server.py` | `mcp_server.py` | `dashboard/knowledge/mcp_server.py` |
| **Bridge** | — | ← `bridge.py` reverse index → | — |

**Gap**: These three systems have no unified query interface. The `bridge.py` module exists but is disabled by default (`OSTWIN_KNOWLEDGE_MEMORY_BRIDGE=0`).

---

## Epics

### EPIC-001 — Unified Architecture Reference

Roles: technical-writer
Objective: Rewrite `architecture-overview.md` as the canonical system reference, incorporating all subsystems

#### Definition of Done
- [ ] Architecture overview covers all 6 subsystems (Engine, Dashboard, Bot, Memory, Knowledge, MCP/Skills/Roles)
- [ ] Includes the dual-memory architecture diagram
- [ ] Cross-references every other component doc
- [ ] Documents the filesystem coordination layer with all 12 file types
- [ ] Includes concurrency model with actual limits (50 rooms, 5s poll, 30s zvec lock retry)
- [ ] Source locations table is complete and verified

#### Acceptance Criteria
- [ ] A new developer can read this single doc and understand the full system topology
- [ ] Every doc in `docs/` links back to this overview
- [ ] No orphaned subsystems — everything connects

#### Design Improvements Identified

1. **Missing: Knowledge Service** — The architecture overview doesn't mention `dashboard/knowledge/` at all. This is a full subsystem with namespace management, ingestion, vector+graph query, backup/restore, and retention sweeping. Must be added.

2. **Missing: Dual Memory** — The overview lists `.agents/memory/ledger.jsonl` but doesn't explain that Agentic Memory (`.memory/`) is a separate system with its own MCP server, vector DB, and evolution pipeline.

3. **Missing: Bridge Index** — `dashboard/knowledge/bridge.py` provides a SQLite-backed reverse index between knowledge chunks and memory notes. This is infrastructure that should be documented.

4. **Improvement: Concurrency diagram** — The current doc says "up to 50 war-rooms" but doesn't show the full concurrency model including: MCP server processes (one per agent), zvec lock contention, dashboard background polling, retention sweeper thread, and auto-sync timer.

depends_on: []

---

### EPIC-002 — Memory Systems Deep Dive

Roles: technical-writer
Objective: Merge `memory.md` and `agentic-memory.md` into a coherent dual-memory reference with a bridging section

#### Definition of Done
- [ ] Single doc covers both Layered Memory and Agentic Memory with clear scope boundaries
- [ ] Documents the Knowledge Service as the third memory-like system
- [ ] Includes `bridge.py` architecture and its enablement
- [ ] Data flow diagrams for all three systems
- [ ] Conflict resolution strategies documented (content_hash, last_modified, LLM merge)
- [ ] Concurrency model fully explained (zvec locks, auto-sync, short-lived handles)

#### Acceptance Criteria
- [ ] No ambiguity about which "memory" a developer is working with
- [ ] Token budget impact is quantified for each system
- [ ] Operational runbook included: "how to debug a memory inconsistency"

#### Design Improvements Identified

1. **Unify MCP tool naming** — Layered Memory exposes `publish`/`query`/`search` via `memory-server.py`. Agentic Memory exposes `memory_save`/`memory_search` via `mcp_server.py`. An agent calling `memory_search` hits Agentic Memory; calling `query` hits Layered Memory. This naming collision is confusing. Recommend: rename Layered Memory tools to `ledger_publish`/`ledger_query`/`ledger_search`.

2. **Bridge index should be enabled by default** — Currently `OSTWIN_KNOWLEDGE_MEMORY_BRIDGE=0`. The bridge is the only way to trace "which knowledge backs this memory note?" Disabling it means the two systems are siloed. Recommend: enable by default, add to architecture overview.

3. **Missing: Memory lifecycle** — What happens to Layered Memory entries when a plan completes? What happens to Agentic Memory notes when a project is archived? No TTL or cleanup is documented. The Knowledge Service has `RetentionSweeper` but the memory systems don't.

4. **Missing: Memory migration** — When `MEMORY_EMBEDDING_MODEL` changes, all vectors in `.memory/vectordb/` become stale. The Agentic Memory handles this via `content_hash` consistency checks, but there's no documented procedure for "I changed my embedding model, how do I rebuild?"

5. **Missing: Memory quotas** — Layered Memory has bounds (4KB summary, 16KB detail, 20 results). Agentic Memory has no documented limits. A runaway agent could fill `.memory/notes/` with thousands of notes.

depends_on: ["EPIC-001"]

---

### EPIC-003 — Knowledge Service Architecture

Roles: technical-writer
Objective: Create a new `docs/knowledge-service.md` documenting the full Knowledge subsystem

#### Definition of Done
- [ ] Documents namespace lifecycle (create, import, query, backup, restore, delete)
- [ ] Explains the three query modes (raw, graph, summarized) with latency expectations
- [ ] Documents GraphRAG pipeline (llama-index PropertyGraphIndex → KuzuDB → zvec)
- [ ] Covers ingestion pipeline: chunking → embedding → entity extraction → upsert
- [ ] Documents the centralized handle cache (ZVEC-LIVE-1 fix)
- [ ] Explains concurrent import protection, namespace quotas, audit logging
- [ ] Includes environment variables and configuration reference
- [ ] Documents the bridge to Agentic Memory

#### Acceptance Criteria
- [ ] A dashboard developer can set up a new knowledge namespace from this doc alone
- [ ] Query mode selection guidance (when to use raw vs graph vs summarized)
- [ ] Troubleshooting section for common errors (dimension mismatch, lock contention)

#### Design Improvements Identified

1. **Missing: REST API reference** — The Knowledge Service is exposed via `dashboard/routes/knowledge.py` but has no API documentation. Each endpoint should be documented with request/response schemas.

2. **Missing: Metrics/observability** — EPIC-005 added Prometheus metrics (`namespaces_total`, `vector_count_per_namespace`, etc.) but these aren't documented. Developers don't know what to monitor.

3. **Improvement: Query mode defaults** — The `mode` parameter defaults to `"raw"` but most users would benefit from `"graph"`. Document the trade-offs and recommend `graph` as the default for interactive use.

4. **Missing: Namespace templates** — There's no concept of "namespace templates" (e.g., a pre-configured namespace with specific extraction rules for code repos vs design docs vs meeting notes). This would be a useful extension point.

5. **Missing: Ingestion progress tracking** — `JobManager` provides job status but there's no documented way to track ingestion progress in the frontend.

depends_on: ["EPIC-001"]

---

### EPIC-004 — MCP Isolation & Configuration Reference

Roles: technical-writer
Objective: Expand `mcp-isolation.md` into a complete MCP system reference

#### Definition of Done
- [ ] Documents the full 4-tier config resolution chain with examples
- [ ] Covers vault-based secret resolution with actual vault backends
- [ ] Documents `validate_mcp.py` normalization pipeline
- [ ] Explains the tools-deny + agent-grants security model
- [ ] Documents per-room `opencode.json` generation flow
- [ ] Includes the future per-server allowlist architecture
- [ ] Troubleshooting section with common misconfigurations

#### Acceptance Criteria
- [ ] A developer can add a new MCP server by following this doc
- [ ] All config priority tiers are demonstrated with concrete examples
- [ ] Security model (deny-by-default, grant-by-role) is clearly explained

#### Design Improvements Identified

1. **Missing: MCP health monitoring** — There's no documented way to check if an MCP server is healthy. The audit log (`mcp-tools.jsonl`) records calls but there's no dashboard view of MCP server status.

2. **Missing: MCP server lifecycle** — What happens when an MCP server crashes mid-task? Is there automatic restart? The `mcp-proxy.py` wraps calls but doesn't document recovery behavior.

3. **Improvement: Allowlist implementation** — The doc mentions `mcp_allowed_servers` as a future direction but the infrastructure is "already in place." The technical-writer should document what exactly is in place and what's needed to complete it.

4. **Missing: MCP versioning** — When `mcp-builtin.json` is updated (e.g., a new server is added), how do existing rooms get the update? Rooms have their own `opencode.json` — is it regenerated?

5. **Missing: MCP cost attribution** — The audit log tracks tool calls but there's no documented way to aggregate "how much did EPIC-001 spend on GitHub API calls?"

depends_on: ["EPIC-001"]

---

### EPIC-005 — Skills & Roles System Reference

Roles: technical-writer
Objective: Merge `skills.md` and `roles-and-zero-agent.md` into a unified "Extensibility" reference

#### Definition of Done
- [ ] Single doc covers both Skills and Roles as two sides of the same extensibility model
- [ ] Documents the full 5-tier role discovery chain
- [ ] Documents the 3-tier skill resolution chain
- [ ] Includes the skill marketplace (ClawHub) architecture
- [ ] Documents dynamic role creation (`New-DynamicRole.ps1`)
- [ ] Includes the quality_gates system and how it integrates with lifecycle
- [ ] Model resolution priority fully documented

#### Acceptance Criteria
- [ ] A user can add a new role by following this doc (zero code)
- [ ] A user can add a new skill by following this doc
- [ ] The relationship between roles, skills, and quality gates is clear

#### Design Improvements Identified

1. **Missing: Skill versioning protocol** — Skills support `.versions/v{version}.md` snapshots but there's no documented versioning workflow (when to bump, how to deprecate, how to migrate).

2. **Missing: Skill testing** — There's no documented way to test a skill in isolation before assigning it to a role. A skill test harness would improve iteration speed.

3. **Missing: Role composition** — Can a role inherit from another role? The `role.json` format doesn't have a `extends` field. This would enable role variants (e.g., `qa-strict extends qa`).

4. **Improvement: Skill dependency graph** — Skills can reference other skills (e.g., `implement-epic` needs `create-lifecycle`), but there's no dependency tracking. Circular skill dependencies would fail silently.

5. **Missing: Role capability matching** — Tier 3 of role discovery uses "capability-based matching" but the matching algorithm isn't documented. How does "highest capability overlap" work exactly?

depends_on: ["EPIC-001"]

---

### EPIC-006 — Lifecycle & State Machine Reference

Roles: technical-writer
Objective: Expand `lifecycle.md` into a complete state machine reference with all transitions, guards, and side effects

#### Definition of Done
- [ ] Documents every state with entry/exit conditions and side effects
- [ ] Includes the full transition table with trigger, guard, and action columns
- [ ] Documents `Resolve-Pipeline.ps1` position-based role assignment
- [ ] Covers retry logic, timeout enforcement, and crash recovery
- [ ] Documents `Start-Plan.ps1 -Resume` recovery behavior
- [ ] Includes audit trail format and query API
- [ ] Documents the `manager-triage` decision tree (fix/redesign/reject)

#### Acceptance Criteria
- [ ] A developer can implement a new lifecycle state by following this doc
- [ ] All terminal states and their entry conditions are documented
- [ ] The difference between `engineering` and `developing` states is explained

#### Design Improvements Identified

1. **Missing: State-specific context injection** — When transitioning from `developing` to `review`, what context does the QA agent receive? The doc doesn't specify what's in the system prompt at each state.

2. **Missing: Lifecycle customization guide** — `ConvertFrom-AsciiLifecycle.ps1` supports inline lifecycle definitions but there's no documented syntax reference or examples.

3. **Improvement: Timeout enforcement** — The doc says "40 minutes for complex epics" but the default is 900 seconds (15 minutes). This discrepancy needs resolution.

4. **Missing: Concurrent state transitions** — What happens if the manager loop and the dashboard API both try to change a room's status simultaneously? Is there locking?

5. **Missing: Failed-state analytics** — When a room reaches `failed-final`, what data is available for post-mortem? The audit log exists but there's no structured failure report.

depends_on: ["EPIC-001"]

---

### EPIC-007 — Plans, Epics & DAG Reference

Roles: technical-writer
Objective: Expand `plan-epic-dag.md` with complete plan lifecycle and DAG generation details

#### Definition of Done
- [ ] Documents the full plan lifecycle (draft → refined → launched → completed)
- [ ] Explains the two-stage DAG generation (advisory vs solid)
- [ ] Documents `Expand-Plan.ps1` AI refinement process
- [ ] Covers per-plan files (roles.json, meta.json, refined.md)
- [ ] Includes the PLAN-REVIEW root node behavior
- [ ] Documents wave computation and critical path algorithm
- [ ] Includes the complete epic directive reference

#### Acceptance Criteria
- [ ] A user can write a plan.md from scratch by following this doc
- [ ] The dependency gating algorithm is fully explained
- [ ] Advisory vs solid DAG merge rules are clear

#### Design Improvements Identified

1. **Missing: Plan schema validation** — There's no documented schema for plan.md. A linter would catch malformed plans before execution.

2. **Missing: Plan branching** — Can you have two plans running simultaneously against the same working_dir? The DAG is per-plan but war-rooms are in a shared `.war-rooms/` directory. Room ID collisions?

3. **Missing: Plan rollback** — When a plan fails, what's the rollback strategy? The doc doesn't address what happens to code changes made by failed epics.

4. **Improvement: DAG visualization** — The dashboard has DAG visualization but the doc doesn't explain how waves map to parallel execution or how to read the critical path.

5. **Missing: Plan expansion prompt** — `Expand-Plan.ps1` uses AI to enrich plans but the expansion logic isn't documented. What does "enriches DoD, AC, deps" mean exactly?

depends_on: ["EPIC-001"]

---

### EPIC-008 — Dashboard Architecture & API Reference

Roles: technical-writer
Objective: Create a new `docs/dashboard-architecture.md` documenting the full dashboard subsystem

#### Definition of Done
- [ ] Documents FastAPI backend architecture (15+ route modules)
- [ ] Documents Next.js 16 frontend architecture (React 19, Tailwind 4, zustand)
- [ ] Covers build mode vs dev mode with exact commands
- [ ] Documents the background task polling (1s interval, SSE events)
- [ ] Includes the plan agent (AI refinement) architecture
- [ ] Documents all REST API endpoint groups
- [ ] Covers authentication (API key, local key mode)
- [ ] Includes the `--project-dir` path resolution behavior

#### Acceptance Criteria
- [ ] A frontend developer can set up the dev environment from this doc
- [ ] All 15+ route modules are listed with their endpoints
- [ ] The difference between build mode and dev mode is clearly explained

#### Design Improvements Identified

1. **Missing: API schema documentation** — No OpenAPI/Swagger docs are generated or linked. The FastAPI app likely has auto-generated docs but this isn't mentioned.

2. **Missing: Dashboard state management** — The frontend uses zustand stores but there's no documentation of the store architecture (what stores exist, how they interact).

3. **Missing: WebSocket event protocol** — SSE events are mentioned but the event types and payloads aren't documented.

4. **Improvement: Dev mode stability** — The developer-context.md lists several dev mode issues (missing routes, CORS, path handling). These should be tracked as known issues with workarounds.

5. **Missing: Dashboard configuration** — How is the dashboard configured? Port, API key, project dir, etc. The `api.py` CLI args aren't documented.

depends_on: ["EPIC-001"]

---

### EPIC-009 — Bot & Connector Architecture Reference

Roles: technical-writer
Objective: Expand `connectors.md` into a complete bot system reference

#### Definition of Done
- [ ] Documents the full plugin-driven connector architecture
- [ ] Covers all three platforms (Telegram, Discord, Slack) with setup guides
- [ ] Documents the agent-bridge (Gemini AI Q&A) architecture
- [ ] Covers session management and stateful editing
- [ ] Documents the notification routing system
- [ ] Includes the complete command reference with examples
- [ ] Covers asset staging and file handling per platform

#### Acceptance Criteria
- [ ] A user can set up a new platform connector by following this doc
- [ ] All 30+ commands are documented with arguments and examples
- [ ] The session lifecycle is fully explained

#### Design Improvements Identified

1. **Missing: Error handling** — What happens when the dashboard API is unreachable? The bot should have graceful degradation behavior.

2. **Missing: Rate limiting** — Platform APIs have rate limits. The doc doesn't discuss how the bot handles them.

3. **Missing: Multi-user support** — The `authorized_users` list is mentioned but multi-user session isolation isn't documented.

4. **Improvement: Voice channel** — Discord voice support (join/leave/transcribe) is mentioned but undocumented.

5. **Missing: Bot deployment** — No documentation on deploying the bot as a service (systemd, Docker, PM2).

depends_on: ["EPIC-001"]

---

### EPIC-010 — OpenCode Integration & Runtime Reference

Roles: technical-writer
Objective: Expand `opencode-integration.md` into a complete runtime integration guide

#### Definition of Done
- [ ] Documents the three runtime modes (dev, run.sh, installed)
- [ ] Covers the full `ostwin install` pipeline
- [ ] Documents role sync mechanism
- [ ] Covers MCP config compilation (normalize → validate → build tools → merge)
- [ ] Includes verification checklist with actual commands
- [ ] Documents the `run-at-dev-mode.md` information in a structured format
- [ ] Covers path resolution for all three modes

#### Acceptance Criteria
- [ ] A new developer can install and verify OSTwin from this doc
- [ ] All three runtime modes are documented with exact file write locations
- [ ] The install pipeline is fully explained step by step

#### Design Improvements Identified

1. **Missing: Uninstall procedure** — There's no documented way to cleanly uninstall OSTwin. What files exist in `~/.ostwin/`, `~/.config/opencode/`, etc.?

2. **Missing: Version upgrade** — When upgrading OSTwin, what needs to be re-compiled? MCP configs? Role syncs? Skill caches?

3. **Improvement: Path resolution diagram** — `run-at-dev-mode.md` has the information but it's in a tabular format that's hard to follow. A visual diagram would help.

4. **Missing: Environment variable reference** — Many env vars are scattered across docs. A consolidated reference is needed.

5. **Missing: Debug mode** — How to run OSTwin with verbose logging? What log files exist and where?

depends_on: ["EPIC-001", "EPIC-004"]

---

### EPIC-011 — System-Wide Cross-Cutting Concerns

Roles: technical-writer
Objective: Create a new `docs/cross-cutting-concerns.md` documenting concerns that span all subsystems

#### Definition of Done
- [ ] Documents the filesystem coordination primitive in detail
- [ ] Covers all environment variables in a single reference table
- [ ] Documents all `.env` file locations and loading priority
- [ ] Covers logging architecture (ostwin.log, ostwin.jsonl, mcp_server.log)
- [ ] Documents security model (API keys, vault, deny-by-default)
- [ ] Covers error taxonomy and escalation patterns
- [ ] Includes the "how to debug a stuck room" playbook

#### Acceptance Criteria
- [ ] Every environment variable used anywhere in the system is listed
- [ ] The filesystem coordination model is fully explained with locking semantics
- [ ] Security model is documented end-to-end

depends_on: ["EPIC-001", "EPIC-002", "EPIC-003", "EPIC-004"]

---

## Design Improvement Summary

### Critical (P0) — Architecture Gaps

| ID | Component | Issue | Impact |
|----|-----------|-------|--------|
| D-001 | Architecture Overview | Knowledge Service not documented | Developers unaware of RAG capabilities |
| D-002 | Memory | Dual-memory systems poorly delineated | Agents use wrong memory for wrong task |
| D-003 | Dashboard | No API documentation | Frontend integration by trial-and-error |
| D-004 | Runtime | Three runtime modes poorly documented | New developers can't set up environment |

### High (P1) — Design Gaps

| ID | Component | Issue | Impact |
|----|-----------|-------|--------|
| D-005 | Memory | Bridge index disabled by default | Knowledge↔Memory systems siloed |
| D-006 | MCP | Per-server allowlists not implemented | All-or-nothing MCP access |
| D-007 | Skills | No dependency tracking | Circular skill dependencies |
| D-008 | Lifecycle | Timeout value mismatch (15min vs 40min) | Confusing configuration |
| D-009 | Plans | No plan schema validation | Malformed plans fail at runtime |

### Medium (P2) — Quality Improvements

| ID | Component | Issue | Impact |
|----|-----------|-------|--------|
| D-010 | Memory | MCP tool naming collision | Agent confusion between ledger and agentic tools |
| D-011 | Knowledge | No namespace templates | Manual setup for every new namespace |
| D-012 | Roles | No role inheritance | Duplication for role variants |
| D-013 | Dashboard | No dev mode stability docs | Wasted debugging time |
| D-014 | Bot | No deployment guide | Manual deployment each time |
| D-015 | Runtime | No env var consolidated reference | Scattered configuration |

## Execution Plan

### Phase 1: Foundation (EPIC-001)
The architecture overview is the hub — all other docs reference it. Must be done first.

### Phase 2: Core Subsystems (EPIC-002 through EPIC-006)
Memory, Knowledge, MCP, Skills/Roles, and Lifecycle docs can be written in parallel by different technical-writer delegates.

### Phase 3: Application Layer (EPIC-007 through EPIC-009)
Plans/DAG, Dashboard, and Bot docs depend on understanding the core subsystems.

### Phase 4: Integration & Cross-Cutting (EPIC-010, EPIC-011)
Runtime integration and cross-cutting concerns synthesize everything.

### Delegation Model

Each EPIC is assigned to a technical-writer delegate with:
1. This PLAN as the master reference
2. The specific EPIC brief (Definition of Done + Acceptance Criteria + Design Improvements)
3. Access to the existing doc as a starting point
4. Access to the source code for verification

### Review Process

Each completed doc is reviewed against:
1. Its Acceptance Criteria
2. Cross-references to other docs (no broken links)
3. Design improvement coverage (are D-001 through D-015 addressed?)
4. Code verification (do the file paths and line references still match?)
