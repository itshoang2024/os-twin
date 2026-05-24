---
name: global-context
description: Query global memory and knowledge across ALL plans and projects. Use when you need historical context, cross-project learnings, or to understand patterns from past work.
tags: [manager, global, memory, knowledge, context, cross-project]
---

# Global Context

## Overview

The manager has access to **global memory** and **global knowledge** MCPs that provide
read-only access to information across ALL plans and projects in the Ostwin system.

## When to Use

Use these tools when you need to:

1. **Find historical decisions** — "What did we decide about authentication?"
2. **Learn from past issues** — "What problems did we encounter with database migrations?"
3. **Track patterns across projects** — "What testing strategies work best?"
4. **Discover relevant knowledge** — "What documentation exists about our API?"
5. **Understand cross-project dependencies** — "Which projects use PostgreSQL?"

## Available Tools

### Global Memory Tools

| Tool | Description |
|------|-------------|
| `global_memory_search` | Search memories across ALL plans |
| `global_memory_tree` | Show directory tree of all memories |
| `global_memory_stats` | Get statistics across all namespaces |
| `global_memory_list_plans` | List all plans with memory data |
| `global_memory_grep` | Grep across all memory files |
| `global_memory_read` | Read a specific memory by ID |

### Knowledge Tools

| Tool | Description |
|------|-------------|
| `knowledge_query` | Query a specific knowledge namespace |
| `knowledge_list_namespaces` | List all knowledge namespaces and their statistics |

## Usage Patterns

### Pattern 1: Understanding Historical Context

Before starting a new epic, query for relevant past decisions:

```
global_memory_search("authentication decisions", k=10)
knowledge_query("project-docs", "authentication flow", mode="summarized")
```

### Pattern 2: Learning from Past Issues

When triage reveals a recurring problem:

```
global_memory_search("database migration issues")
global_memory_grep("migration.*failed", "-i")
```

### Pattern 3: Cross-Project Pattern Discovery

To understand common approaches:

```
global_memory_search("testing strategy")
global_memory_stats()  # See which projects have similar memories
```

### Pattern 4: Finding Relevant Documentation

When you need reference materials:

```
knowledge_list_namespaces()  # Find available namespaces
knowledge_query("project-docs", "rate limiting implementation", mode="summarized")
```

## Important Notes

1. **Read-Only Access** — These tools cannot modify memories or knowledge. Use
   project-specific memory tools for saving new information.

2. **Cross-Plan Context** — Results include `plan_id` to identify which project
   the memory/knowledge belongs to.

3. **Performance** — Searching across all namespaces may take longer than
   project-specific queries. Use `plans` or `namespaces` parameters to scope
   searches when possible.

4. **Freshness** — Memory systems sync every 60 seconds. Very recent memories
   may not appear immediately in global queries.

## Example Workflow

When starting a new epic:

1. **Discover context:**
   ```
   global_memory_list_plans()  # What projects exist?
   knowledge_list_namespaces()  # What knowledge bases exist?
   ```

2. **Find relevant patterns:**
   ```
   global_memory_search("[feature keyword]", k=5)
   ```

3. **Query detailed knowledge:**
   ```
   knowledge_query("project-docs", "[feature keyword]", mode="summarized", top_k=10)
   ```

4. **Apply learnings to current work:**
   - Use discovered patterns in your planning
   - Reference past decisions in brief.md
   - Avoid repeating past mistakes
