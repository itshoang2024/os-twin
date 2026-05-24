# Component Detail Plans

This document provides the detailed, per-component breakdown for each EPIC in PLAN.template.md.
Each component plan specifies: files to document/improve, data models, flows, and the specific
tasks a technical-writer agent should execute.

---

## Component 1: Engine Core (EPIC-001)

### Source Files

| Script | Location | Lines | Key Functions |
|--------|----------|-------|---------------|
| `Start-Plan.ps1` | `.agents/plan/` | ~925 | Plan parsing, room creation, DAG build, manager launch |
| `Invoke-Agent.ps1` | `.agents/roles/_base/` | ~400 | Universal runner, MCP config, skill copy, prompt build |
| `Build-SystemPrompt.ps1` | `.agents/roles/_base/` | ~300 | Identity + capabilities + quality gates + task context |
| `Resolve-Role.ps1` | `.agents/roles/_base/` | ~200 | 5-tier role discovery |
| `Resolve-RoleSkills.ps1` | `.agents/roles/_base/` | ~200 | 3-tier skill resolution |
| `Start-ManagerLoop.ps1` | `.agents/roles/manager/` | ~600 | Room polling, worker spawning, lifecycle enforcement |
| `Build-DependencyGraph.ps1` | `.agents/plan/` | ~345 | Kahn's algorithm, critical path, waves |
| `New-WarRoom.ps1` | `.agents/war-rooms/` | ~400 | Room directory creation, config generation |
| `Post-Message.ps1` | `.agents/channel/` | ~150 | JSONL message append |
| `Resolve-Pipeline.ps1` | `.agents/lifecycle/` | ~200 | Lifecycle state machine generation |

### Key Flows to Document

1. **Plan Execution Flow**: PLAN.md -> Start-Plan.ps1 -> parse epics -> New-WarRoom.ps1 -> Build-DependencyGraph.ps1 -> Start-ManagerLoop.ps1
2. **Agent Spawning Flow**: Manager detects ready room -> Invoke-Agent.ps1 -> Resolve-Role.ps1 -> Build-SystemPrompt.ps1 -> Resolve-RoleSkills.ps1 -> OpenCode CLI
3. **DAG Execution Flow**: Kahn's algorithm -> topological order -> waves -> parallel execution -> dependency gating
4. **Error Recovery Flow**: Room failure -> retry check -> increment retries -> re-spawn or fail-final

### Tasks

- TASK-001: Document Start-Plan.ps1 entry point and argument handling
- TASK-002: Document Invoke-Agent.ps1 universal runner with MCP config resolution
- TASK-003: Document Build-SystemPrompt.ps1 prompt composition chain
- TASK-004: Document manager loop lifecycle with state transitions
- TASK-005: Document DAG construction with Kahn's algorithm example
- TASK-006: Create engine-core.md with unified flow diagrams

---

## Component 2: War-Rooms (EPIC-002)

### Source Files

| File | Purpose |
|------|---------|
| `.agents/war-rooms/New-WarRoom.ps1` | Room creation |
| `.agents/war-rooms/Remove-WarRoom.ps1` | Teardown with archiving |
| `.agents/war-rooms/Get-WarRoomStatus.ps1` | CLI status dashboard |
| `.agents/war-rooms/config-schema.json` | JSON schema for room config |
| `.agents/war-rooms/Test-GoalCompletion.ps1` | DoD/AC verification |
| `.agents/channel/Post-Message.ps1` | JSONL channel append |
| `.agents/channel/Read-Messages.ps1` | Channel read/filter |
| `dashboard/tasks.py` | Background polling |
| `dashboard/routes/rooms.py` | REST API |

### Data Models to Document

1. **config.json schema**: room_id, task_ref, plan_id, assignment, goals (DoD, AC, quality_requirements), constraints, status, skill_refs
2. **channel.jsonl message format**: ts, from, to, type (task/done/review/pass/fail/fix/error/signoff), ref, body
3. **lifecycle.json state machine**: states, transitions, terminal states
4. **Room isolation guarantees**: message isolation, skill isolation, MCP isolation, process isolation, memory isolation

### Tasks

- TASK-001: Document all room files with their schemas
- TASK-002: Document channel message protocol with all message types
- TASK-003: Document multi-agent collaboration patterns (manager -> engineer -> QA flow)
- TASK-004: Document room creation and teardown flows
- TASK-005: Create war-rooms-architecture.md

---

## Component 3: Roles & Zero-Agent (EPIC-003)

### Source Files

| File | Purpose |
|------|---------|
| `.agents/roles/_base/Invoke-Agent.ps1` | Universal agent runner |
| `.agents/roles/_base/Resolve-Role.ps1` | 5-tier role discovery |
| `.agents/roles/_base/Build-SystemPrompt.ps1` | Prompt composition |
| `.agents/roles/_base/New-DynamicRole.ps1` | Runtime role creation |
| `.agents/roles/registry.json` | Master role catalog (~700 lines) |
| `dashboard/routes/roles.py` | REST API |
| `dashboard/models.py` | Pydantic Role model |

### Key Flows to Document

1. **Role Discovery**: 5-tier chain (Explicit path -> Registry lookup -> Project/contrib/core dirs -> Capability matching -> Ephemeral)
2. **Model Resolution**: 4-level priority (Plan-specific roles.json -> Global config -> Role's own role.json -> Default model)
3. **Dynamic Role Creation**: Manager invents role -> New-DynamicRole.ps1 -> role.json + ROLE.md generated -> added to room config

### Tasks

- TASK-001: Document role.json schema with all fields and examples
- TASK-002: Document ROLE.md format with frontmatter and best practices
- TASK-003: Document 5-tier discovery chain with resolution examples
- TASK-004: Document model resolution priority chain
- TASK-005: Catalog all 20+ roles with their skill_refs, capabilities, and models
- TASK-006: Create roles-and-zero-agent-architecture.md

---

## Component 4: Skills System (EPIC-004)

### Source Files

| File | Purpose |
|------|---------|
| `.agents/roles/_base/Resolve-RoleSkills.ps1` | 3-tier skill resolution |
| `.agents/roles/_base/Invoke-Agent.ps1` | Copies skills to room, sets AGENT_OS_SKILLS_DIR |
| `.agents/skills/` | Skill pack directory |
| `.agents/bin/skills/load.py` | Python skill loader |
| `.agents/bin/skills/commands.py` | Skill CLI commands |
| `dashboard/routes/skills.py` | REST API for CRUD, search, marketplace |

### Key Flows to Document

1. **Skill Resolution**: 3-tier (Registry lookup -> Local fallback -> Dashboard API) + platform/enabled gates
2. **Skill Injection**: Resolve -> Copy to room/skills/ -> Set AGENT_OS_SKILLS_DIR -> Agent discovers at runtime
3. **Skill Linking**: role.json skill_refs -> Merge with config.json -> Merge with plan roles.json (union, not replace)

### Tasks

- TASK-001: Document SKILL.md format with all frontmatter fields
- TASK-002: Document 3-tier resolution chain with platform/enabled gating
- TASK-003: Document skill-to-room injection flow end-to-end
- TASK-004: Document ClawHub marketplace API endpoints
- TASK-005: Create skills-architecture.md

---

## Component 5: MCP Isolation (EPIC-005)

### Source Files

| File | Purpose |
|------|---------|
| `.agents/roles/_base/Invoke-Agent.ps1` | MCP config resolution and no_mcp gating |
| `.agents/mcp/mcp-proxy.py` | Audit proxy with JSONL logging |
| `.agents/mcp/config_resolver.py` | 4-tier config resolution, vault secret expansion |
| `.agents/mcp/memory-server.py` | Memory MCP server |
| `.agents/mcp/channel-server.py` | Channel MCP server |
| `.agents/mcp/warroom-server.py` | War-room MCP server |
| `.agents/mcp/mcp-builtin.json` | Built-in server definitions |
| `.agents/mcp/mcp-config.json` | Production MCP config |
| `.agents/mcp/validate_mcp.py` | Config validation and normalization |
| `dashboard/routes/mcp.py` | REST API for MCP management |

### Key Flows to Document

1. **MCP Config Resolution**: 4-tier (Pre-compiled opencode.json -> Project-local mcp/config.json -> Engine-level -> User-level)
2. **Per-Room Config Generation**: Resolve config -> Expand placeholders -> Write opencode.json in room artifacts/ -> Set OPENCODE_CONFIG
3. **Vault Secret Resolution**: `${vault:server/key}` syntax -> ConfigResolver walks config -> Resolves secrets
4. **Audit Logging**: Every MCP tool call -> mcp-tools.jsonl with ts, server, tool, args, elapsed_ms, ok, result

### Tasks

- TASK-001: Document 4-tier config resolution chain
- TASK-002: Document vault-based secret resolution
- TASK-003: Document no_mcp flag and per-room config generation
- TASK-004: Catalog all built-in MCP servers with their tools
- TASK-005: Document audit logging format and usage
- TASK-006: Document future per-server allowlist design
- TASK-007: Create mcp-isolation-architecture.md (expand existing)

---

## Component 6: Memory System Unified (EPIC-006)

### Source Files

#### Layered Memory
| File | Purpose |
|------|---------|
| `.agents/mcp/memory-core.py` | Core logic: JSONL ledger, BM25, time-decay |
| `.agents/mcp/memory-server.py` | MCP server wrapping memory-core |
| `.agents/memory/ledger.jsonl` | The shared knowledge base |
| `.agents/memory/index.json` | Materialized index |
| `dashboard/routes/memory.py` | REST API |

#### Agentic Memory
| File | Purpose |
|------|---------|
| `.agents/memory/mcp_server.py` | MCP server (1217 lines) |
| `.agents/memory/agentic_memory/memory_system.py` | Core logic (1232 lines) |
| `.agents/memory/agentic_memory/memory_note.py` | Data model (200 lines) |
| `.agents/memory/agentic_memory/retrievers.py` | Vector retrieval (370 lines) |
| `.agents/memory/agentic_memory/llm_controller.py` | LLM backend adapters (366 lines) |

#### Bridge
| File | Purpose |
|------|---------|
| `dashboard/knowledge/bridge.py` | SQLite reverse index |

### Key Flows to Document

1. **Layered Memory Operations**: publish -> ledger.jsonl append -> index materialization; query -> filter by room/kind/tags; search -> BM25 + time-decay scoring
2. **Agentic Memory memory_save Flow**: content -> LLM analysis (name/path/keywords/tags) -> vector index -> evolution (auto-linking) -> markdown file
3. **Agentic Memory Auto-Sync**: Background thread -> sync_to_disk() every 60s -> merge_from_disk() -> write all memories
4. **Bridge Index Flow**: Knowledge chunk (namespace, file_hash, chunk_idx) -> SQLite lookup -> list of note_ids

### Architecture Comparison Table

| Aspect | Layered Memory | Agentic Memory | Knowledge Service |
|--------|----------------|----------------|-------------------|
| **Scope** | Plan-level (cross-room) | Project-level (persists across plans) | Namespace-level (per-corpus) |
| **Storage** | ledger.jsonl (JSONL) | .memory/notes/*.md (markdown) | ~/.ostwin/knowledge/{ns}/ (KuzuDB + Zvec) |
| **Search** | BM25 + time-decay | Vector similarity (cosine) | Vector + Graph + PageRank |
| **Links** | No | Auto-generated by LLM evolution | Entity-relation graph (KuzuDB) |
| **MCP Tools** | 3 (publish, query, search) | 14 (save, search, read, update, delete, link, etc.) | 8+ (namespace CRUD, import, query, stats) |
| **LLM Usage** | None | Content analysis + evolution | Entity extraction + summarization |
| **Concurrency** | fcntl file lock | Zvec lock retry + sync saves | Centralized cache + thread-safe locks |

### Tasks

- TASK-001: Document Layered Memory operations (publish, query, search)
- TASK-002: Document Agentic Memory memory_save flow end-to-end
- TASK-003: Document Agentic Memory evolution process (auto-linking)
- TASK-004: Document concurrency model for both systems
- TASK-005: Document Bridge index and enable it by default
- TASK-006: Create decision matrix: "which memory system when"
- TASK-007: Create unified-memory-architecture.md

---

## Component 7: Knowledge Service (EPIC-007)

### Source Files

| File | Lines | Purpose |
|------|-------|---------|
| `dashboard/knowledge/service.py` | 1058 | Top-level KnowledgeService facade |
| `dashboard/knowledge/namespace.py` | 557 | Namespace lifecycle (CRUD, retention) |
| `dashboard/knowledge/ingestion.py` | 946 | Folder -> graph + vectors pipeline |
| `dashboard/knowledge/query.py` | 650 | Per-namespace query engine (3 modes) |
| `dashboard/knowledge/mcp_server.py` | 532 | FastMCP server for external tools |
| `dashboard/knowledge/bridge.py` | 363 | Memory <-> Knowledge reverse index |
| `dashboard/knowledge/config.py` | 161 | Configuration constants and paths |
| `dashboard/knowledge/embeddings.py` | -- | KnowledgeEmbedder (shared) |
| `dashboard/knowledge/llm.py` | -- | KnowledgeLLM (shared) |
| `dashboard/knowledge/jobs.py` | -- | JobManager (background ingestion) |
| `dashboard/knowledge/audit.py` | -- | Import concurrency protection, quotas |
| `dashboard/knowledge/stats.py` | -- | Stats computer (disk, queries, ingests) |
| `dashboard/knowledge/metrics.py` | -- | Prometheus metrics registry |
| `dashboard/knowledge/vector_store.py` | -- | NamespaceVectorStore (Zvec wrapper) |
| `dashboard/knowledge/graph/` | -- | GraphRAG (KuzuDB, PageRank, extractors) |

### Key Flows to Document

1. **Namespace Lifecycle**: create -> import_folder -> query -> backup -> retention sweep -> delete
2. **Ingestion Pipeline**: folder walk -> MarkItDown parse -> chunk (1024 chars, 200 overlap) -> embed -> KuzuDB entity extraction -> Zvec vector insert
3. **Query Modes**: raw (vector only) -> graph (+ PageRank rerank) -> summarized (+ LLM aggregation)
4. **GraphRAG Architecture**: PropertyGraphIndex -> GraphRAGStore (KuzuDB) -> GraphRAGExtractor (entity/relation) -> GraphRAGQueryEngine (hit-aware PageRank)

### Tasks

- TASK-001: Document namespace lifecycle (CRUD, retention, backup/restore)
- TASK-002: Document ingestion pipeline with chunking and entity extraction
- TASK-003: Document query engine with mode comparison table
- TASK-004: Document GraphRAG architecture (KuzuDB + PageRank)
- TASK-005: Document MCP server tools
- TASK-006: Document metrics and monitoring
- TASK-007: Create knowledge-service-architecture.md

---

## Component 8: Dashboard Architecture (EPIC-008)

### Route Modules

| Module | Endpoints | Purpose |
|--------|-----------|---------|
| `plans.py` | ~2042 lines | Plan/epic CRUD, state changes, DAG, progress |
| `rooms.py` | -- | Room status, actions, messages |
| `skills.py` | -- | Skill CRUD, search, marketplace |
| `roles.py` | -- | Role CRUD, registry |
| `memory.py` | -- | Memory query/search/publish |
| `knowledge.py` | -- | Knowledge namespace CRUD, import, query |
| `mcp.py` | -- | MCP config management |
| `settings.py` | -- | MasterSettings management |
| `auth.py` | -- | API key auth |

### Tasks

- TASK-001: Catalog all route modules with endpoint summary
- TASK-002: Document SSE/WebSocket event system
- TASK-003: Document background task polling mechanism
- TASK-004: Document frontend architecture (React 19, Tailwind 4, zustand)
- TASK-005: Document dev mode vs build mode differences
- TASK-006: Create dashboard-architecture.md

---

## Component 9: Bot & Connectors (EPIC-009)

### Source Files

| File | Purpose |
|------|---------|
| `bot/src/connectors/base.ts` | Connector interface |
| `bot/src/connectors/registry.ts` | ConnectorRegistry singleton |
| `bot/src/connectors/discord.ts` | Discord implementation |
| `bot/src/connectors/telegram.ts` | Telegram implementation |
| `bot/src/connectors/slack.ts` | Slack implementation |
| `bot/src/commands.ts` | COMMAND_REGISTRY + routing |
| `bot/src/agent-bridge.ts` | Gemini AI Q&A |
| `bot/src/api.ts` | Dashboard REST client (46+ endpoints) |
| `bot/src/sessions.ts` | Per-user session state |
| `bot/src/notifications.ts` | WebSocket event router |

### Tasks

- TASK-001: Document Connector interface and ConnectorRegistry
- TASK-002: Document command routing flow (COMMAND_REGISTRY -> routeCommand -> BotResponse)
- TASK-003: Document platform differences (message limits, formatting, special handling)
- TASK-004: Document session management and notification routing
- TASK-005: Catalog all 30+ commands with arguments
- TASK-006: Create bot-architecture.md

---

## Component 10: Plan/Epic/DAG (EPIC-010)

### Source Files

| File | Lines | Purpose |
|------|-------|---------|
| `Start-Plan.ps1` | ~925 | Parse plan, create rooms, build DAG |
| `Build-DependencyGraph.ps1` | ~345 | Kahn's algorithm, critical path |
| `Build-PlanningDAG.ps1` | ~261 | AI-powered advisory DAG |
| `Expand-Plan.ps1` | ~475 | AI plan expansion |
| `Update-Progress.ps1` | ~126 | Scan rooms, write progress |
| `dashboard/routes/plans.py` | ~2042 | REST API |
| `dashboard/plan_agent.py` | ~572 | AI plan refinement |

### Tasks

- TASK-001: Document plan markdown format with all directives
- TASK-002: Document epic structure (DoD, AC, Tasks)
- TASK-003: Document DAG construction with Kahn's algorithm example
- TASK-004: Document two-stage DAG generation (advisory vs solid)
- TASK-005: Document dependency gating and wave execution
- TASK-006: Create plan-epic-dag-architecture.md

---

## Component 11: OpenCode Integration (EPIC-011)

### Source Files

| File | Purpose |
|------|---------|
| `.agents/mcp/config.json` | Source MCP config |
| `.agents/mcp/validate_mcp.py` | Config validation and normalization |
| `.agents/mcp/resolve_opencode.py` | Placeholder resolution |
| `.agents/mcp/mcp-extension.sh` | MCP extension manager |
| `.agents/install.sh` | Full install pipeline |
| `.agents/lifecycle/Resolve-Pipeline.ps1` | Position-based lifecycle generator |

### Tasks

- TASK-001: Document agent execution flow (role -> prompt -> MCP -> skills -> task)
- TASK-002: Document MCP config compilation pipeline
- TASK-003: Document role sync mechanism
- TASK-004: Document lifecycle pipeline generation
- TASK-005: Document verification checklist
- TASK-006: Create opencode-integration-architecture.md

---

## Component 12-16: Design Improvements (EPIC-012 through EPIC-016)

These are engineering-focused epics. Each requires:

1. **ADR (Architecture Decision Record)** documenting the current state, options considered, and decision
2. **Implementation plan** with phased rollout
3. **Migration guide** for existing deployments
4. **Testing strategy** for validation

### EPIC-012: Unified Memory Facade

**Design Approach**:
- Create `UnifiedMemoryClient` that wraps Layered Memory, Agentic Memory, and Knowledge Service
- Single `search(query, scope="all")` method that fans out to all systems
- Result merging with `source` field attribution
- Bidirectional bridge: extend bridge.py to also index memory notes into knowledge chunks

**Files to Create/Modify**:
- New: `.agents/memory/unified_client.py`
- Modify: `dashboard/knowledge/bridge.py` (add memory->knowledge direction)
- Modify: `.agents/mcp/memory-server.py` (add unified search tool)

### EPIC-013: Embedding Model Unification

**Design Approach**:
- ADR selecting one model (recommend gemini-embedding-001 for cost, or BAAI/bge-base-en-v1.5 for offline)
- Extend MasterSettings to also govern Agentic Memory embedding
- Migration tool: `knowledge-migrate-embeddings` CLI command that re-embeds a namespace

**Files to Create/Modify**:
- New: `dashboard/knowledge/migrate_embeddings.py`
- Modify: `.agents/memory/agentic_memory/retrievers.py` (respect MasterSettings)
- Modify: `dashboard/lib/settings.py` (add memory embedding settings)

### EPIC-014: Event-Driven Architecture

**Design Approach**:
- In-process event bus using Python's `asyncio.Event` / `blinker` library
- Filesystem watcher via `watchdog` for war-room status changes
- Event types: room_state_changed, message_posted, namespace_updated, job_completed
- Dashboard subscribes to events instead of polling

**Files to Create/Modify**:
- New: `.agents/events/bus.py` (event bus)
- New: `.agents/events/watcher.py` (filesystem watcher)
- Modify: `dashboard/tasks.py` (subscribe to events)
- Modify: `.agents/roles/manager/Start-ManagerLoop.ps1` (subscribe to events)

### EPIC-015: Token Budget Accounting

**Design Approach**:
- Token budget estimator in `Build-SystemPrompt.ps1` that calculates total tokens before launch
- Per-component breakdown: system prompt + MCP tools + skills + predecessor context + memory
- Warning at 80%, hard block at 95% of model context window
- Dashboard endpoint: `GET /api/plans/{plan_id}/rooms/{room_id}/token-budget`

**Files to Create/Modify**:
- Modify: `.agents/roles/_base/Build-SystemPrompt.ps1` (add token estimation)
- New: `dashboard/routes/token_budget.py` (budget API)
- Modify: `dashboard/fe/` (budget visualization in room detail)

### EPIC-016: Operations Runbook

**Files to Create**:
- `docs/runbooks/stuck-room-debugging.md`
- `docs/runbooks/mcp-server-recovery.md`
- `docs/runbooks/memory-maintenance.md`
- `docs/runbooks/knowledge-namespace-management.md`
- `docs/runbooks/health-checks.md`
- `docs/runbooks/incident-response.md`
