# Knowledge System User Guide

The Knowledge system is a semantic document storage and retrieval system built into ostwin. It provides REST and MCP APIs for ingesting documents, building knowledge graphs, and querying with natural language.

## Quick Start

### 1. Create a Namespace

A namespace is a self-contained knowledge base. Create one via REST API:

```bash
curl -X POST http://localhost:9000/api/knowledge/namespaces \
  -H "Authorization: Bearer $OSTWIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-docs", "description": "My documentation"}'
```

Or via MCP tool:
```python
# In an ostwin agent
knowledge_create_namespace(name="my-docs", description="My documentation")
```

### 2. Import Documents

Import a folder of documents:

```bash
curl -X POST http://localhost:9000/api/knowledge/namespaces/my-docs/import \
  -H "Authorization: Bearer $OSTWIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"folder_path": "/absolute/path/to/docs"}'
# Returns: {"job_id": "abc123", "namespace": "my-docs"}
```

Poll for job status:
```bash
curl http://localhost:9000/api/knowledge/namespaces/my-docs/jobs/abc123 \
  -H "Authorization: Bearer $OSTWIN_API_KEY"
```

### 3. Query the Knowledge Base

Three query modes are available:

**Raw mode** (vector search only):
```bash
curl -X POST http://localhost:9000/api/knowledge/namespaces/my-docs/query \
  -H "Authorization: Bearer $OSTWIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "how to install", "mode": "raw", "top_k": 10}'
```

**Graph mode** (vector + graph expansion):
```bash
curl -X POST http://localhost:9000/api/knowledge/namespaces/my-docs/query \
  -H "Authorization: Bearer $OSTWIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "authentication flow", "mode": "graph", "top_k": 10}'
```

**Summarized mode** (graph + LLM answer):
```bash
curl -X POST http://localhost:9000/api/knowledge/namespaces/my-docs/query \
  -H "Authorization: Bearer $OSTWIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "explain the architecture", "mode": "summarized", "top_k": 5}'
```

## REST API Reference

### Namespace Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/knowledge/namespaces` | List all namespaces |
| POST | `/api/knowledge/namespaces` | Create a namespace |
| GET | `/api/knowledge/namespaces/{name}` | Get namespace metadata |
| DELETE | `/api/knowledge/namespaces/{name}` | Delete a namespace |

### Import Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/knowledge/namespaces/{name}/import` | Import folder |
| GET | `/api/knowledge/namespaces/{name}/jobs` | List all jobs |
| GET | `/api/knowledge/namespaces/{name}/jobs/{job_id}` | Get job status |

### Query Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/knowledge/namespaces/{name}/query` | Query the namespace |
| GET | `/api/knowledge/namespaces/{name}/graph` | Get graph visualization data |



### Ontology Profile Endpoints

Ontology profiles define the dynamic concept types, relationship types, aliases, and validation rules used by a namespace knowledge graph. All endpoints use the same authentication and error response conventions as the other `/api/knowledge/namespaces/*` routes.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/knowledge/namespaces/{name}/ontology/profile` | Return the active profile, or default suggestion metadata for a legacy namespace with no saved profile |
| PUT | `/api/knowledge/namespaces/{name}/ontology/profile` | Validate and save a profile payload |
| POST | `/api/knowledge/namespaces/{name}/ontology/validate` | Validate a profile, node, edge, or pack manifest without saving |
| POST | `/api/knowledge/namespaces/{name}/ontology/reset-default` | Create or replace the active profile with deterministic default seed data |
| GET | `/api/knowledge/namespaces/{name}/ontology/summary` | Return concept, relation, alias, candidate, and validation issue counts |

Get the active profile or default suggestion:

```bash
curl http://localhost:9000/api/knowledge/namespaces/my-docs/ontology/profile \
  -H "Authorization: Bearer $OSTWIN_API_KEY"
# Legacy namespaces return: {"profile": null, "default_suggested": true, "default_profile": {...}}
```

Save a validated profile:

```bash
curl -X PUT http://localhost:9000/api/knowledge/namespaces/my-docs/ontology/profile \
  -H "Authorization: Bearer $OSTWIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"profile":{"profile_id":"enterprise_feature_map","namespace":"my-docs","version":"1.0.0","concept_types":{},"relationship_types":{},"layers":{},"abstraction_levels":{},"metadata_fields":{},"aliases":{},"validation_rules":[]}}'
```

Validate without saving:

```bash
curl -X POST http://localhost:9000/api/knowledge/namespaces/my-docs/ontology/validate \
  -H "Authorization: Bearer $OSTWIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"subject":"edge","edge":{"relation_type":"requires","source_type":"feature","target_type":"service"}}'
# Returns: {"valid": true|false, "issues": [...]}
```

Reset to defaults and inspect summary:

```bash
curl -X POST http://localhost:9000/api/knowledge/namespaces/my-docs/ontology/reset-default \
  -H "Authorization: Bearer $OSTWIN_API_KEY"

curl http://localhost:9000/api/knowledge/namespaces/my-docs/ontology/summary \
  -H "Authorization: Bearer $OSTWIN_API_KEY"
# Returns counts for concept_type_count, relation_type_count, alias_count,
# candidate_count, validation_issue_count, and validation_issues.
```

### Backup & Restore

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/knowledge/namespaces/{name}/backup` | Create backup archive |
| POST | `/api/knowledge/namespaces/restore` | Restore from archive |

### Observability

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/knowledge/metrics` | Get metrics (JSON or Prometheus) |
| GET | `/api/knowledge/health` | Health check |

## MCP Tools

The Knowledge system exposes 7 MCP tools for agent use:

1. **knowledge_list_namespaces** — List all namespaces
2. **knowledge_create_namespace** — Create a new namespace
3. **knowledge_delete_namespace** — Delete a namespace
4. **knowledge_import_folder** — Import documents from a folder
5. **knowledge_get_import_status** — Poll import job status
6. **knowledge_query** — Query a namespace
7. **knowledge_get_graph** — Get graph data for visualization

### MCP Tool Examples

```python
# List namespaces
namespaces = knowledge_list_namespaces()
# Returns: {"namespaces": [{"name": "my-docs", ...}]}

# Create namespace
ns = knowledge_create_namespace(name="project-docs", description="Project documentation")

# Import folder (MUST be absolute path)
job = knowledge_import_folder(namespace="project-docs", folder_path="/home/user/docs")

# Poll job
status = knowledge_get_import_status(namespace="project-docs", job_id=job["job_id"])

# Query
result = knowledge_query(
    namespace="project-docs",
    query="how does authentication work",
    mode="graph",
    top_k=10
)

# Get graph
graph = knowledge_get_graph(namespace="project-docs", limit=200)
```

## Frontend Integration

The Knowledge system integrates with the ostwin dashboard frontend at `localhost:9000`. Navigate to a plan workspace and click the "Knowledge" tab to:

- View and manage namespaces
- Import documents from folders
- Query across namespaces
- Visualize the knowledge graph
- Configure retention policies

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OSTWIN_KNOWLEDGE_DIR` | Directory for knowledge storage | `~/.ostwin/knowledge/` |
| `ANTHROPIC_API_KEY` | API key for LLM-based entity extraction | Required for graph mode |
| `OSTWIN_KNOWLEDGE_METRICS_BACKEND` | Metrics backend (`memory` or `prometheus`) | `prometheus` |

## Supported File Types

The ingestion pipeline supports:
- **Markdown** (`.md`) — Parsed as structured documents
- **Plain text** (`.txt`) — Split into paragraphs
- **HTML** (`.html`) — Stripped to text
- **JSON** (`.json`) — Flattened to text

## Query Modes Explained

### Raw Mode
- Vector similarity search only
- Fast, no graph traversal, no LLM calls
- Returns matching chunks with similarity scores

### Graph Mode
- Vector search + graph expansion
- Uses PageRank to rank entities
- Returns chunks and related entities
- Requires `kuzu` graph database

### Summarized Mode
- Graph mode + LLM-generated answer
- Best for complex questions
- Returns chunks, entities, answer, and citations
- Requires `ANTHROPIC_API_KEY`

## Common Errors

| Error Code | Description | Solution |
|------------|-------------|----------|
| `INVALID_NAMESPACE_ID` | Namespace name doesn't match `[a-z0-9_-]+` | Use lowercase letters, numbers, hyphens, underscores |
| `NAMESPACE_NOT_FOUND` | Namespace doesn't exist | Create it first |
| `NAMESPACE_EXISTS` | Namespace already exists | Use a different name or delete first |
| `INVALID_FOLDER_PATH` | Folder path is relative or invalid | Use an absolute path |
| `FOLDER_NOT_FOUND` | Folder doesn't exist | Check the path |
| `NOT_A_DIRECTORY` | Path is a file, not a directory | Provide a directory path |
| `IMPORT_IN_PROGRESS` | Another import is already running | Wait for it to complete |

## Backup & Restore

### Creating a Backup

```bash
curl -X POST http://localhost:9000/api/knowledge/namespaces/my-docs/backup \
  -H "Authorization: Bearer $OSTWIN_API_KEY"
# Returns: {"archive_path": "/path/to/my-docs.tar.zst", "size_bytes": 12345}
```

### Restoring from Backup

```bash
curl -X POST http://localhost:9000/api/knowledge/namespaces/restore \
  -H "Authorization: Bearer $OSTWIN_API_KEY" \
  -F "archive=@my-docs.tar.zst" \
  -F "overwrite=true"
```

## Retention Policies

Set automatic cleanup policies:

```bash
curl -X PUT http://localhost:9000/api/knowledge/namespaces/my-docs/retention \
  -H "Authorization: Bearer $OSTWIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"policy": "ttl_days", "ttl_days": 30, "auto_delete_when_empty": true}'
```

Policies:
- `manual` — No automatic cleanup (default)
- `ttl_days` — Delete imports older than `ttl_days`

## Further Reading

- [Architecture Guide](./knowledge-architecture.md) — Internal design and extension points
- [MCP Integration](./knowledge-mcp-opencode.md) — Using with opencode agents
- [Curator Guide](./knowledge-curator-guide.md) — Using the knowledge-curator agent role


## Ontology Operations Release References

EPIC-010 adds a dedicated operations guide, frontend extension guide, deterministic lifecycle fixture, and performance baseline for long-term ontology maintenance:

- `docs/knowledge-ontology-operations.md` — backend operations, profile schema, relation taxonomy, pack authoring, candidate review, and QA checklist.
- `docs/knowledge-frontend-ontology-extension.md` — frontend hooks, Enterprise Map extension points, and profile-driven UI rules.
- `docs/knowledge-ontology-performance-baseline.md` — baseline targets for profile load, validation, candidate listing, explorer seed, and Enterprise Map render.
- `scripts/bench_ontology_operations.py` — deterministic benchmark command for release gates.

### Domain pack and candidate endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/knowledge/ontology/packs` | List built-in domain packs such as Financial Services |
| GET | `/api/knowledge/namespaces/{name}/ontology/packs` | List installed pack state for a namespace |
| POST | `/api/knowledge/namespaces/{name}/ontology/packs/validate` | Preview pack compatibility and conflicts |
| POST | `/api/knowledge/namespaces/{name}/ontology/packs/install` | Install or upgrade a domain pack |
| POST | `/api/knowledge/namespaces/{name}/ontology/packs/uninstall` | Disable a domain pack and remove safe pack-owned additions |
| GET | `/api/knowledge/namespaces/{name}/ontology/candidates` | List ontology review candidates |
| POST | `/api/knowledge/namespaces/{name}/ontology/candidates/{id}/approve` | Promote a candidate to canonical profile definition |
| POST | `/api/knowledge/namespaces/{name}/ontology/candidates/{id}/map` | Map a candidate to an existing canonical ID |
| POST | `/api/knowledge/namespaces/{name}/ontology/candidates/{id}/reject` | Reject and suppress a candidate for the same source |
| POST | `/api/knowledge/namespaces/{name}/ontology/candidates/bulk` | Bulk candidate review update |

### Nexus explorer endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/knowledge/namespaces/{name}/explorer/summary` | Lightweight topology counts |
| GET | `/api/knowledge/namespaces/{name}/explorer/seed` | Profile-aware initial graph seed |
| POST | `/api/knowledge/namespaces/{name}/explorer/expand` | Expand from selected node IDs |
| POST | `/api/knowledge/namespaces/{name}/explorer/search` | Search graph nodes and context |
| GET | `/api/knowledge/namespaces/{name}/explorer/path` | Shortest path between two nodes |
| GET | `/api/knowledge/namespaces/{name}/explorer/nodes/{node_id}` | Detail drawer payload |
| GET | `/api/knowledge/namespaces/{name}/explorer/communities` | Community assignments |
