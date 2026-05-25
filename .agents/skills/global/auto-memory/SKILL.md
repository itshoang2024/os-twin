---
name: auto-memory
description: Use this skill to save, search, and manage persistent memories via the Agentic Memory MCP server -- a semantic knowledge base with auto-linking, tagging, and vector search.
---

# auto-memory

## Overview

Auto-memory is a **persistent, semantic knowledge base** exposed as an MCP server over stdio. It stores knowledge as interconnected markdown notes with auto-generated tags, keywords, directory paths, and links between related memories. The system uses vector embeddings for semantic search.

The MCP server name is `memory`. Tools are prefixed accordingly (e.g. `memory.memory_save`, `memory.memory_search`).

## Available MCP Tools

### `memory_save` -- Store a new memory

Write detailed, rich memories (3-10 sentences). Include context, reasoning, examples, trade-offs, and gotchas. The system auto-generates name, path, keywords, tags, summary, and links if not provided.

```
memory_save(
  content: str,          # REQUIRED -- the memory content. Be thorough.
  name: str | None,      # Optional 2-5 word name. Auto-generated if omitted.
  path: str | None,      # Optional directory path (e.g. "backend/database"). Auto-generated.
  tags: list[str] | None # Optional tags. Auto-generated.
)
```

**Good memory:**
```
memory_save(
  content="PostgreSQL's JSONB type stores semi-structured data with full indexing
  support via GIN indexes. We chose it over MongoDB because our data has relational
  aspects (user->orders->items) but product attributes vary per category. The GIN index
  on product.attributes reduced our catalog search from 800ms to 12ms. Key gotcha:
  JSONB equality checks are exact-match, so normalize data before insertion.",
  path="backend/database"
)
```

**Bad memory:**
```
memory_save(content="Use PostgreSQL JSONB for product data.")
```

### `memory_search` -- Semantic search across all memories

Returns the most relevant memories ranked by vector similarity. Use specific, descriptive queries.

```
memory_search(
  query: str,   # Natural language query. Be specific.
  k: int = 5    # Max results to return.
)
```

**Examples:**
```
memory_search(query="PostgreSQL indexing strategies for JSON data")
memory_search(query="authentication flow and JWT token handling", k=10)
```

Results include: id, name, path, content, tags, keywords, links, backlinks.

### `memory_tree` -- Show directory structure

Returns a tree visualization of how memories are organized. Useful for understanding the knowledge structure before saving new memories.

```
memory_tree()
```

### `grep_memory` -- Full-text grep across memory files

Runs grep on all markdown files in the notes directory. Supports regex and standard grep flags.

```
grep_memory(
  pattern: str,          # Search pattern (string or regex)
  flags: str | None      # Optional grep flags: -i, -l, -c, -E, -A N, -B N, etc.
)
```

**Examples:**
```
grep_memory("PostgreSQL")                    # basic search
grep_memory("oauth.*token", "-i")            # case-insensitive regex
grep_memory("TODO", "-l")                    # filenames only
grep_memory("docker|kubernetes", "-E")       # extended regex OR
```

### `find_memory` -- Search by file/directory names

Runs find on the notes directory. Supports standard find arguments.

```
find_memory(
  args: str | None       # Optional find arguments
)
```

**Examples:**
```
find_memory()                                # list all files
find_memory("-name '*database*'")            # match filename pattern
find_memory("-path '*/backend/*'")           # files under backend/
find_memory("-mmin -60")                     # modified in last 60 minutes
```

## Disabled-by-Default Tools

These tools exist but are disabled by default via `MEMORY_DISABLED_TOOLS` env var. They can be enabled if needed:

- `read_memory(memory_id)` -- Read a specific memory by UUID
- `update_memory(memory_id, content?, name?, path?, tags?)` -- Update an existing memory
- `delete_memory(memory_id)` -- Delete a memory and clean up links
- `link_memories(from_id, to_id)` -- Manually link two memories
- `unlink_memories(from_id, to_id)` -- Remove a link
- `memory_stats()` -- System statistics
- `sync_from_disk()` / `sync_to_disk()` -- Manual disk sync
- `graph_snapshot()` -- Full graph data for UI visualization

## What to Save (and How)

### Architectural decisions -- Include the WHY

```
memory_save(
  content="Chose JWT stateless auth over server sessions because multiple services
  need to verify auth independently. Token stored in localStorage on frontend.
  24h expiry with refresh token rotation. Secret via JWT_SECRET env var.
  Libraries: python-jose (backend), jsonwebtoken (frontend).
  Trade-off: can't revoke individual tokens -- added a deny-list in Redis for emergency revocation.",
  path="architecture/auth",
  tags=["auth", "jwt", "architecture"]
)
```

### Code patterns and conventions

```
memory_save(
  content="All API errors return a standard shape: {detail: string, code: string, errors?: [{field, message}]}.
  HTTP codes: 400=validation, 401=missing auth, 403=forbidden, 404=not found, 409=conflict.
  The frontend error interceptor in src/lib/api.ts relies on this shape -- changing it breaks toast notifications.
  FastAPI exception handlers are registered in src/main.py via @app.exception_handler.",
  path="conventions/api",
  tags=["api", "errors", "convention"]
)
```

### Warnings and gotchas

```
memory_save(
  content="The cats.status column has a PostgreSQL CHECK constraint: CHECK (status IN ('available','reserved','sold')).
  Adding new statuses requires an Alembic migration. Without it, INSERT/UPDATE fails with
  psycopg2.errors.CheckViolation. Migration command: alembic revision --autogenerate -m 'add status'
  then alembic upgrade head. This has bitten two PRs already.",
  path="backend/database",
  tags=["database", "migration", "gotcha"]
)
```

### User preferences and workflow

```
memory_save(
  content="User prefers bundled PRs over many small ones for refactors. Confirmed when
  I chose a single PR for the auth middleware rewrite and they said 'yeah the single bundled PR
  was the right call here'. For feature work they prefer smaller PRs but for sweeping
  refactors, one PR with a clear description is preferred.",
  path="workflow/preferences"
)
```

## When to Search

- **At the start of a new task** -- search for relevant context before coding
- **Before making architectural decisions** -- check if a decision was already made
- **When you encounter unfamiliar code** -- search for explanations or gotchas
- **When the user references something from a past conversation**

## How to Save Memories (via shell)

Use the `shell` tool to call the memory CLI. This is the PRIMARY way to save memories.

```bash
# Save a memory
MEMORY_PERSIST_DIR="${AGENT_OS_ROOT:-.}/.memory" \
  python3 ~/.ostwin/.agents/memory/memory-cli.py save "Your detailed memory content here" \
  --name "Short name" --path "category/subcategory" --tags "tag1,tag2"

# Search memories
MEMORY_PERSIST_DIR="${AGENT_OS_ROOT:-.}/.memory" \
  python3 ~/.ostwin/.agents/memory/memory-cli.py search "your query" --k 5

# Show memory tree
MEMORY_PERSIST_DIR="${AGENT_OS_ROOT:-.}/.memory" \
  python3 ~/.ostwin/.agents/memory/memory-cli.py tree
```

**MANDATORY**: After completing any deliverable (schema, API contract, architecture decision), you MUST call the save command above via the `shell` tool. Do NOT skip saving to memory.

## Rules

1. **Write DETAILED memories** -- 3-10 sentences minimum. Include context, reasoning, and gotchas. One-liners are nearly useless when retrieved later.
2. **Search before saving** -- avoid duplicates. Update existing memories via `update_memory` (if enabled) rather than creating redundant entries.
3. **Use `memory_tree` to understand organization** before choosing a path for new memories.
4. **Be specific in search queries** -- "PostgreSQL JSONB indexing" beats "database".
5. **Include the WHY** -- decisions without reasoning lose value over time.
6. **Auto-sync is on by default** -- memories are written to disk every 60s. No manual sync needed under normal use.
7. **If MCP fails, use shell fallback** -- never skip memory just because the MCP tool errored.
