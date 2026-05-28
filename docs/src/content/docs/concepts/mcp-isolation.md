---
title: "Pillar 3: MCP Isolation"
description: "Selective MCP server attachment eliminates thousands of wasted tokens per agent session."
sidebar:
  order: 3
  icon: rocket
---

OSTwin's third pillar solves a critical cost and performance problem: **not every agent needs every tool**. MCP (Model Context Protocol) servers expose tool definitions that consume prompt tokens whether or not the agent uses them. MCP Isolation ensures each agent only sees the tools it actually needs.

## The Token Cost Problem

A typical MCP server exposes 5-15 tool definitions. Each tool definition consumes 200-800 tokens in the system prompt. When an agent connects to multiple MCP servers:

- **3 MCP servers** with 10 tools each = ~8,000-12,000 tokens wasted
- **Per-session cost**: $0.02-0.05 in prompt tokens alone
- **Per-plan cost** (30 epics, 4 roles each): $2.40-6.00 in pure overhead

For a QA agent that only reads code and posts verdicts, connecting Unity MCP servers is pure waste. For an architect writing ADRs, filesystem tools are enough.

:::caution[Hidden Cost Multiplier]
Token waste compounds across every message in a conversation. A 20-turn agent session with 10K tokens of unnecessary tool definitions wastes **200K tokens** -- equivalent to reading a 500-page book of irrelevant content.
:::

## The no_mcp Flag

The simplest isolation mechanism is a binary flag in `role.json`:

```json
{
  "name": "architect",
  "no_mcp": true
}
```

When `no_mcp` is `true`, the agent launches with **zero MCP servers**. It can still read files, write code, and use bash -- but through the LLM client's built-in tools, not MCP.

### Resolution Chain

The `no_mcp` flag is resolved through three levels:

1. **Room config** (`config.json`) -- highest priority, per-room override
2. **Role config** (`role.json`) -- role-level default
3. **System default** -- `false` (MCP enabled)

## MCP Config Format

OSTwin uses an OpenCode-compatible MCP configuration format. Each server entry declares a `type` (`local` or `remote`), along with the command or URL needed to start it:

```json
{
  "mcp": {
    "channel": {
      "type": "local",
      "command": [
        "{env:OSTWIN_PYTHON}",
        "{env:AGENT_DIR}/mcp/channel-server.py"
      ],
      "environment": {
        "AGENT_OS_ROOT": "."
      }
    },
    "memory": {
      "type": "remote",
      "url": "http://localhost:3366/api/memory-pool/mcp",
      "headers": {
        "Authorization": "Bearer {env:OSTWIN_API_KEY}"
      }
    }
  }
}
```

### Local vs Remote

| Type | Launch | Best For |
|------|--------|----------|
| `local` | Spawns a subprocess (stdio transport) | Python scripts, npx packages, CLI tools |
| `remote` | Connects to an HTTP endpoint (SSE transport) | Dashboard APIs, hosted services, shared daemons |

### Variable Interpolation

Config values support environment variable expansion:

| Syntax | Resolves To |
|--------|-------------|
| `{env:OSTWIN_PYTHON}` | Path to the project's Python interpreter |
| `{env:AGENT_DIR}` | Path to the `.agents/` directory |
| `{env:PATH}` | System PATH (needed by npx-based servers) |
| `{env:OSTWIN_API_KEY}` | Dashboard API key for authenticated endpoints |

## Built-in MCP Servers

OSTwin ships with six MCP servers. They are defined in `.agents/mcp/mcp-builtin.json` and automatically available to every agent session (unless `no_mcp` is set).

### Local Servers (Subprocess)

| Server | Script | Key Tools |
|--------|--------|-----------|
| **channel** | `.agents/mcp/channel-server.py` | `post_message`, `read_messages`, `get_latest` |
| **warroom** | `.agents/mcp/warroom-server.py` | `update_status`, `report_progress`, `list_artifacts` |
| **chrome-devtools** | `.agents/mcp/obscura-browser-server.py` | Chrome DevTools automation via CDP-compatible endpoint |
| **playwright** | `npx @playwright/mcp@latest` | Browser automation and testing |

Local servers are launched as subprocesses by the agent runner. Each gets its own process, ensuring isolation -- a crash in one server does not affect others.

### Remote Servers (HTTP)

| Server | Endpoint | Key Tools |
|--------|----------|-----------|
| **memory** | `http://localhost:3366/api/memory-pool/mcp` | `publish`, `query`, `search`, `get_context` |
| **knowledge** | `http://localhost:3366/api/knowledge/mcp/` | `list_namespaces`, `query`, `search_all`, `get_stats`, `find_relevant` |

Remote servers connect to the dashboard API via SSE transport. They require an `Authorization` header with the `OSTWIN_API_KEY`. This design means the memory and knowledge servers share the dashboard's Python process rather than spawning their own, reducing resource usage while maintaining full tool availability.

### Server Selection by Role

Not every role needs every server. The typical assignment is:

| Role | channel | warroom | memory | knowledge | chrome-devtools | playwright |
|------|---------|---------|--------|-----------|-----------------|------------|
| engineer | yes | yes | yes | -- | -- | -- |
| qa | yes | yes | yes | -- | -- | -- |
| architect | -- | -- | yes | yes | -- | -- |
| manager | yes | yes | yes | yes | -- | -- |

Roles with `no_mcp: true` (like the architect in lightweight mode) get zero MCP servers. Roles that need browser automation get `chrome-devtools` or `playwright` injected via `mcp_refs` in their `role.json`.

## Vault-Based Secrets

MCP configs support secret references using the `{vault:path}` syntax:

```
{vault:server/key}     → resolves from .agents/vault.json
{vault:openai/api_key} → resolves the OpenAI key
```

:::note[Security]
The vault file (`.agents/vault.json`) is gitignored by default. Secrets never appear in MCP configs committed to version control. The resolution happens at agent invocation time inside `.agents/roles/_base/Invoke-Agent.ps1`.
:::

## Audit Logging

Every MCP tool call is logged to `mcp-tools.jsonl` in the war-room directory:

```jsonl
{"ts":"2025-01-15T10:30:00Z","server":"memory","tool":"publish","duration_ms":45,"status":"ok"}
{"ts":"2025-01-15T10:30:02Z","server":"memory","tool":"query","duration_ms":120,"status":"ok"}
{"ts":"2025-01-15T10:30:05Z","server":"warroom","tool":"post_message","duration_ms":30,"status":"error","error":"channel locked"}
```

This audit trail enables:

- **Cost attribution** per server and per tool
- **Performance profiling** to identify slow MCP servers
- **Error tracking** for reliability monitoring
- **Compliance auditing** for regulated environments

## Token Budget Impact

The savings from MCP Isolation are substantial at scale:

| Scenario | Without Isolation | With Isolation | Savings |
|----------|-------------------|----------------|---------|
| QA agent (reads only) | 12K tool tokens | 0 tokens | 12K/session |
| Architect (no tools) | 12K tool tokens | 0 tokens | 12K/session |
| Engineer (memory + warroom) | 12K tool tokens | 4K tokens | 8K/session |
| **10 epics, 4 roles each** | **480K tokens** | **120K-240K tokens** | **240K-360K saved** |

:::tip[Cost at Scale]
For a 30-epic plan with 4 roles per epic, MCP Isolation saves approximately **$3-8 in prompt token costs**. More importantly, it reduces latency -- smaller prompts mean faster first-token times.
:::

## Future Direction: Per-Server Allowlists

The current isolation model is binary (all servers or none, per config). A planned enhancement introduces **per-server tool allowlists**:

```json
{
  "mcp": {
    "memory": {
      "type": "remote",
      "url": "http://localhost:3366/api/memory-pool/mcp",
      "allow_tools": ["query", "search"],
      "deny_tools": ["publish"]
    }
  }
}
```

This will allow a QA agent to read from the memory ledger without being able to write to it, further tightening the principle of least privilege.

## Key Source Files

| File | Purpose |
|------|---------|
| `.agents/mcp/mcp-builtin.json` | Built-in MCP server definitions |
| `.agents/mcp/config_resolver.py` | 4-tier MCP config merge |
| `.agents/mcp/channel-server.py` | Channel messaging server |
| `.agents/mcp/warroom-server.py` | War-room coordination server |
| `.agents/mcp/global-knowledge-server.py` | Knowledge namespace server |
| `.agents/memory/mcp_server.py` | Memory pool MCP server |
| `.agents/roles/_base/Invoke-Agent.ps1` | no_mcp flag handling |
| `.agents/vault.json` | Secret storage (gitignored) |
