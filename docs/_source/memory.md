# Pillar 5: Layered Memory and Context Scaling

## Core Concept

OSTwin implements memory as three distinct layers, each with different scope,
lifetime, and size bounds. This prevents context flooding while enabling
cross-room knowledge sharing.

## The Three Memory Layers

```
+--------------------------------------------------+
|  Layer 3: Shared Ledger (cross-room)              |
|  .agents/memory/ledger.jsonl                      |
|  Scope: global | Lifetime: plan | Bounded: yes    |
+--------------------------------------------------+
         |  publish / query / search
+--------------------------------------------------+
|  Layer 2: Code Artifacts (per-room)               |
|  room-*/brief.md, TASKS.md, artifacts/, contexts/ |
|  Scope: room | Lifetime: room | Bounded: by room  |
+--------------------------------------------------+
         |  read / write
+--------------------------------------------------+
|  Layer 1: Conversation (per-room)                 |
|  room-*/channel.jsonl                             |
|  Scope: room | Lifetime: room | Bounded: by room  |
+--------------------------------------------------+
```

### Layer 1: Conversation Memory

Each room's `channel.jsonl` is the conversation history between roles within
that room. Fully isolated -- no cross-contamination between rooms.

```json
{"ts": "...", "from": "manager", "to": "engineer", "type": "task", "body": "..."}
{"ts": "...", "from": "engineer", "to": "qa", "type": "done", "body": "..."}
```

### Layer 2: Code Artifacts

Each room maintains its working context:
- `brief.md` -- the task description
- `TASKS.md` -- work breakdown with checkboxes
- `config.json` -- the goal contract (DoD, AC)
- `artifacts/` -- room artifacts such as wrappers, reports, generated files
- `contexts/` -- per-role context snapshots

These persist for the room's lifetime and are scoped entirely to that room.

### Layer 3: Shared Memory Ledger

The cross-room knowledge base stored in `.agents/memory/ledger.jsonl`. This is
how rooms share knowledge without breaking isolation.

**Format**: Append-only JSONL with file locking (`fcntl.LOCK_EX`)

**Index**: Materialized at `.agents/memory/index.json` for fast lookups

**Entry structure**:
```json
{
  "id": "mem_abc123",
  "kind": "decision",
  "summary": "Use JWT for auth, not sessions",
  "detail": "After analyzing the requirements...",
  "room_id": "room-001",
  "author_role": "architect",
  "tags": ["auth", "jwt"],
  "created_at": "2026-04-01T10:00:00Z"
}
```

**Entry kinds**: `artifact`, `decision`, `interface`, `convention`, `warning`, `code`

## Memory Isolation via Filtering

The key insight: rooms access the shared ledger through **filtered views**.

When a room queries the ledger, it uses `exclude_room=room_id` to get
context from *other* rooms only. This prevents a room from re-reading its own
entries as external context.

```python
# In memory-core.py
def get_context(room_id):
    # Returns entries from ALL OTHER rooms, not this one
    return query(exclude_room=room_id)
```

This means:
- Room-001 sees knowledge published by Room-002, Room-003, etc.
- Room-001 does NOT see its own published entries as "external" context
- Each room has a unique view of the shared knowledge base

## Relevance Scoring: BM25 + Time Decay

Search results are ranked using a combined score:

```
score = 0.7 * normalized_BM25 + 0.3 * exponential_decay
```

Time decay uses per-kind half-lives:
| Kind | Half-life |
|------|-----------|
| `code` | 2 hours |
| `convention` | 24 hours |
| `decision` | 12 hours |
| `interface` | 6 hours |
| `artifact` | 4 hours |
| `warning` | 8 hours |

Recent entries are prioritized, but conventions decay slowly (they remain
relevant longer than code snippets).

## Memory Bounds

Every layer has hard limits to prevent context bloat:

| Bound | Limit | Enforced in |
|-------|-------|-------------|
| Memory entry summary | 4 KB max | `memory-server.py` |
| Memory entry detail | 16 KB max | `memory-server.py` |
| Memory search results | 20 entries max | `memory-server.py` |
| Predecessor outputs | 10 KB per upstream room | `Start-Engineer.ps1` |
| System prompt | 100 KB default (warning) | `Build-SystemPrompt.ps1` |
| MCP tool call results | 4 KB in audit log | `mcp-proxy.py` |

These bounds are not arbitrary -- they are calibrated to keep agent context
within LLM context window limits while preserving the most relevant information.

## Predecessor Context

When an epic starts, it receives context from its upstream dependencies in
the DAG. The engineer's launcher (`Start-Engineer.ps1`) reads outputs from
predecessor rooms, truncated to 10 KB per upstream room, and includes them
in the agent's initial prompt.

This is how knowledge flows through the DAG: EPIC-001's decisions become
EPIC-002's input context, without the two rooms sharing memory directly.

## Memory Operations

The shared memory supports three primary operations:

| Operation | Description |
|-----------|-------------|
| **publish** | Add an entry to the ledger with room_id and author_role provenance |
| **query** | Retrieve entries filtered by room_id, kind, tags, or exclude_room |
| **search** | Full-text BM25 search with time-decay relevance scoring |

These are exposed via:
- MCP server: `memory-server.py` (for agents)
- CLI: `memory-cli.py` (for debugging)
- REST API: `dashboard/routes/memory.py` (for the dashboard)

## Soft Delete

Entries support soft-delete semantics: they are marked as deleted but remain
in the ledger for audit purposes. The index excludes soft-deleted entries
from queries and searches.

## Key Source Files

| File | Purpose |
|------|---------|
| `.agents/mcp/memory-core.py` | Core logic: JSONL ledger, BM25, time-decay scoring |
| `.agents/mcp/memory-server.py` | MCP server wrapping memory-core |
| `.agents/mcp/memory-cli.py` | CLI for memory operations |
| `.agents/memory/ledger.jsonl` | The shared knowledge base (append-only) |
| `.agents/memory/index.json` | Materialized index for fast lookups |
| `dashboard/routes/memory.py` | REST API for memory query/search/publish |
| `.agents/roles/_base/Build-SystemPrompt.ps1` | Injects predecessor context |
