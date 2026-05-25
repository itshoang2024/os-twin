# Connecting opencode to the Ostwin Knowledge MCP server

The dashboard exposes a streamable-HTTP MCP server at **`/api/knowledge/mcp/`**
(note the trailing slash) that provides 7 tools for graph-RAG knowledge
management. opencode (and any other MCP-compatible client) can connect
and call them as native tools.

> **Note:** The endpoint moved from `/mcp/` → `/api/knowledge/mcp/` so the
> bare `/mcp` path can be used by the dashboard frontend (the MCP server
> registry UI). Update any old client configs to the new URL.

## 1) Configuration

Add this block to `~/.config/opencode/opencode.json` (or to your project's
`.opencode/opencode.json`):

```json
{
  "mcp": {
    "ostwin-knowledge": {
      "type": "remote",
      "url": "http://localhost:3366/api/knowledge/mcp/",
      "headers": {
        "Authorization": "Bearer ${env:OSTWIN_API_KEY}"
      }
    }
  }
}
```

> The trailing slash is required — `http://localhost:3366/api/knowledge/mcp`
> (no slash) returns a 404 because the FastAPI mount point is
> `/api/knowledge/mcp/...`.

Then in your shell:

```bash
export OSTWIN_API_KEY="your-key-from-~/.ostwin/.env"
opencode mcp list   # should list ostwin-knowledge with 7 tools
```

If the dashboard is in **dev mode** (`OSTWIN_DEV_MODE=1`) OR if
`OSTWIN_API_KEY` is unset on the dashboard side, the `Authorization`
header is not enforced — you can omit the `headers` block entirely.

## 2) Available tools

| Tool | Purpose |
|------|---------|
| `knowledge_list_namespaces` | List every namespace + its stats |
| `knowledge_create_namespace` | Create a new namespace (also auto-created on import) |
| `knowledge_delete_namespace` | Permanently delete a namespace and its data |
| `knowledge_import_folder` | Background-import an absolute folder path into a namespace |
| `knowledge_get_import_status` | Poll a job by `job_id` to track ingestion progress |
| `knowledge_query` | Query a namespace (`raw` / `graph` / `summarized` modes) |
| `knowledge_get_graph` | Get the entity-relation graph for visualisation |

Every tool returns a JSON object. On failure the response is
`{"error": "<message>", "code": "<ERROR_CODE>"}` — never an exception or
HTTP 5xx. Codes you may see:

| Code | When |
|------|------|
| `INVALID_NAMESPACE_ID` | Namespace name doesn't match `^[a-z0-9][a-z0-9_-]{0,63}$` |
| `NAMESPACE_EXISTS` | Trying to create a namespace that already exists |
| `NAMESPACE_NOT_FOUND` | Querying / get_graph against an unknown namespace |
| `INVALID_FOLDER_PATH` | `folder_path` is relative |
| `FOLDER_NOT_FOUND` | `folder_path` doesn't exist on disk |
| `NOT_A_DIRECTORY` | `folder_path` exists but is a file |
| `JOB_NOT_FOUND` | `job_id` doesn't match any submitted job |
| `BAD_REQUEST` | Invalid `mode` for `knowledge_query` (must be `raw`/`graph`/`summarized`) |
| `INTERNAL_ERROR` | Anything else — check dashboard logs |

## 3) Usage notes

- **Image files** (PNG / JPG / GIF / BMP / TIFF / WEBP) are walked as
  part of `knowledge_import_folder` but require `ANTHROPIC_API_KEY` in
  the dashboard environment for vision-based OCR. Without the key,
  images are skipped silently (one warning per file in the dashboard log).
- **Imports are background jobs** — `knowledge_import_folder` returns a
  `job_id` immediately; poll `knowledge_get_import_status` until
  `state` is `completed` (or `failed` / `cancelled` / `interrupted`).
- **`knowledge_query` mode `summarized`** requires `ANTHROPIC_API_KEY`.
  Without it the response includes `warnings: ["llm_unavailable"]` and
  `answer: null` — chunks are still returned, no exception is raised.
- **`folder_path` MUST be absolute**. Relative paths are rejected with
  code `INVALID_FOLDER_PATH`.

## 4) Verifying the connection

After configuring `opencode.json`, run:

```bash
opencode mcp list
# expected output: ostwin-knowledge   7 tools   http://localhost:3366/api/knowledge/mcp/
```

Or hand-poke the endpoint to confirm it's reachable:

```bash
# Real MCP handshake — should return HTTP 200 with a JSON-RPC result body.
curl -i -X POST http://localhost:3366/api/knowledge/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"0.1"}}}'
```

## 5) Example: end-to-end import + query (via opencode)

Once registered, opencode (or any MCP client) can chain calls like:

```text
1. knowledge_create_namespace(name="my_docs", language="English")
2. knowledge_import_folder(namespace="my_docs", folder_path="/Users/me/docs")
3. knowledge_get_import_status(namespace="my_docs", job_id="<uuid>")  # poll
4. knowledge_query(namespace="my_docs", query="how do I deploy?", mode="summarized")
```

The `summarized` answer comes back with citations pointing to the
original files, so the LLM client can present a sourced response.

## 6) Authentication

### Dev Mode (No Auth)

When `OSTWIN_DEV_MODE=1` is set in the dashboard environment, the MCP endpoint accepts unauthenticated connections. This is useful for:
- Local development
- Testing in CI
- Quick prototyping

### Production Mode (Bearer Auth)

In production, set `OSTWIN_API_KEY` in `~/.ostwin/.env`:

```bash
# In ~/.ostwin/.env
OSTWIN_API_KEY=your-secure-api-key-here
```

Then configure opencode with the key:

```json
{
  "mcp": {
    "ostwin-knowledge": {
      "type": "remote",
      "url": "http://localhost:3366/api/knowledge/mcp/",
      "headers": {
        "Authorization": "Bearer ${env:OSTWIN_API_KEY}"
      }
    }
  }
}
```

### Security Notes

- **Never commit API keys** to source control
- Use environment variable substitution (`${env:VAR}`) in opencode.json
- Rotate keys periodically
- For multi-tenant setups, consider per-namespace access controls

## 7) Memory ↔ Knowledge Bridge

The Knowledge system integrates with the Memory (A-mem-sys) MCP server via a bridge that allows:

### Knowledge Links in Memory Notes

Memory notes can reference Knowledge entities using `knowledge://` URIs:

```
knowledge://namespace-name/file-hash#chunk-index
```

### Bridge MCP Tool

The `knowledge_find_notes_by_knowledge_link` tool searches memory notes that reference specific knowledge entities:

```python
# Find memory notes linked to a knowledge chunk
result = knowledge_find_notes_by_knowledge_link(
    namespace="my-docs",
    file_hash="abc123",
    chunk_idx=0
)
# Returns: {"note_ids": ["uuid1", "uuid2"], "count": 2}
```

### Configuring the Bridge

The bridge is enabled by default when both Knowledge and Memory MCP servers are configured. No additional configuration needed.

## 8) Troubleshooting

### Connection Refused

```
Error: Failed to connect to MCP server
```

**Solution**: Ensure the dashboard is running on the expected port (default 9000, or 3366 for the standalone MCP endpoint).

### 401 Unauthorized

```
{"error": "Missing API key", "code": "AUTH_REQUIRED"}
```

**Solution**: Either set `OSTWIN_DEV_MODE=1` for dev, or provide a valid `OSTWIN_API_KEY` in the Authorization header.

### Tools Not Appearing

```
opencode mcp list
# Shows 0 tools
```

**Solution**: 
1. Verify the MCP mount is correctly configured in `dashboard/api.py`
2. Check dashboard logs for startup errors
3. Ensure `OSTWIN_API_KEY` matches between client and server

### Import Timeout

Imports for large folders may take minutes. Check job status:

```python
status = knowledge_get_import_status(namespace="x", job_id="y")
print(f"State: {status['state']}")
print(f"Progress: {status['progress_current']}/{status['progress_total']}")
print(f"Errors: {status['errors']}")
```

## 9) Further Reading

- [Knowledge User Guide](./knowledge.md) — Full REST API reference
- [Architecture Guide](./knowledge-architecture.md) — Internal design
- [Curator Guide](./knowledge-curator-guide.md) — Agent role documentation
