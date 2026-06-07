# Agentic Memory MCP Server

A semantic knowledge base that lets war-room agents persist and retrieve knowledge as markdown notes with auto-linking, tagging, and vector search. This is **Pillar 5.5** — a separate system from the Layered Memory (shared ledger) documented in `memory.md`.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [System Components](#system-components)
3. [Data Flow](#data-flow)
4. [Note Storage Format](#note-storage-format)
5. [LLM Analysis Pipeline](#llm-analysis-pipeline)
6. [Memory Evolution (Auto-Linking)](#memory-evolution-auto-linking)
7. [Vector Retrieval System](#vector-retrieval-system)
8. [MCP Tools Exposed](#mcp-tools-exposed)
9. [Concurrency Handling](#concurrency-handling)
10. [Configuration](#configuration)
11. [Startup Optimizations](#startup-optimizations)
12. [Integration with ostwin](#integration-with-ostwin)
13. [CLI Usage](#cli-usage)
14. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
+-----------------------------------------------------------------------------------+
|                           Agentic Memory System                                   |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|  +-------------+     +------------------+     +------------------+               |
|  | MCP Server  |────>| AgenticMemory    |────>| Vector Retriever |               |
|  | (stdio/SSE) |     | System           |     | (zvec/chroma)    |               |
|  +-------------+     +------------------+     +------------------+               |
|         |                    |                         |                         |
|         |                    v                         v                         |
|         |           +------------------+     +------------------+               |
|         |           | LLMController    |     | Embedding Model  |               |
|         |           | (Gemini/OpenAI)  |     | (Gemini/SBERT)   |               |
|         |           +------------------+     +------------------+               |
|         |                    |                                                   |
|         v                    v                                                   |
|  +-------------+     +------------------+                                        |
|  | FastMCP     |     | MemoryNote       |                                        |
|  | Tools       |     | (.md on disk)    |                                        |
|  +-------------+     +------------------+                                        |
|                                                                                   |
+-----------------------------------------------------------------------------------+
                                    |
                                    v
                     +---------------------------+
                     | Filesystem (.memory/)      |
                     | ├── notes/                 |
                     | │   └── <path>/<name>.md   |
                     | ├── vectordb/              |
                     | └── mcp_server.log         |
                     +---------------------------+
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Synchronous saves** | In stdio mode, opencode kills the process after the MCP response. Background threads die before writing to disk. |
| **Lazy ML imports** | Heavy deps (torch, transformers, sentence-transformers, litellm) take 6+ seconds to import. Deferred to first use. |
| **Background init thread** | Server responds to `initialize`/`tools/list` instantly while heavy deps load in background. |
| **Zvec lock retry** | Multiple agents spawn concurrent MCP processes that all try to open the same vectordb. 30s retry handles lock contention. |
| **Context-aware analysis** | LLM sees similar existing notes + directory tree to keep naming/categorization consistent. |

---

## System Components

### File Locations

| Component | Path | Lines | Purpose |
|-----------|------|-------|---------|
| **MCP Server** | `.agents/memory/mcp_server.py` | 1217 | Entry point, FastMCP tools, transport (stdio/sse), background init |
| **Memory System** | `.agents/memory/agentic_memory/memory_system.py` | 1232 | Core logic: save, search, link, evolve |
| **Memory Note** | `.agents/memory/agentic_memory/memory_note.py` | 200 | Markdown serialization/deserialization |
| **Vector Retriever** | `.agents/memory/agentic_memory/retrievers.py` | 370 | Embedding storage + similarity search (zvec/chroma) |
| **LLM Controller** | `.agents/memory/agentic_memory/llm_controller.py` | 366 | Dispatches to Gemini/OpenAI/Ollama/etc. for analysis |
| **CLI** | `.agents/memory/memory-cli.py` | 118 | Standalone CLI for testing without MCP |

### Class Hierarchy

```
AgenticMemorySystem
├── MemoryNote (data model)
├── LLMController
│   ├── OpenAIController
│   ├── OllamaController
│   ├── SGLangController
│   ├── OpenRouterController
│   └── GeminiController (default)
└── Retriever
    ├── ChromaRetriever
    └── ZvecRetriever (default)
        └── GeminiEmbeddingFunction | SentenceTransformerEmbeddingFunction
```

---

## Data Flow

### `memory_save` Flow (most important)

```
Agent calls memory_save(content, name?, path?, tags?) via MCP (stdio)
  │
  ├─ 1. mcp_server.py:memory_save()
  │     - Pre-generate UUID for stable client handle
  │     - Log incoming request
  │
  ├─ 2. get_memory() — wait for background init (up to 60s)
  │     - If init failed, raise RuntimeError with full diagnostics
  │
  ├─ 3. AgenticMemorySystem.add_note(content, **kwargs)
  │     │
  │     ├─ a. Create MemoryNote(content, id=uuid, name?, path?, tags?)
  │     │
  │     ├─ b. _apply_llm_analysis(note)
  │     │     - analyze_content(note.content)
  │     │     - LLM generates: name, path, keywords, context, tags, summary
  │     │     - If context_aware=True: include top-5 similar notes + directory tree
  │     │
  │     ├─ c. Add to self.memories[id] before evolution
  │     │
  │     ├─ d. process_memory(note) — EVOLUTION
  │     │     - find_related_memories(note.content, k=5) — vector search
  │     │     - LLM decides: should_evolve? which actions?
  │     │     - Actions: "strengthen" (create links) | "update_neighbor"
  │     │     - add_link(note.id, suggested_connection_id)
  │     │     - Update neighbor tags/context
  │     │
  │     ├─ e. _save_note(note)
  │     │     - note.to_markdown() → write to .memory/notes/<path>/<name>.md
  │     │
  │     └─ f. retriever.add_document(content, metadata, id)
  │           - Build enhanced_document = summary || content + context + keywords + tags
  │           - Generate embedding via Gemini/SBERT
  │           - Insert into zvec collection with HNSW index
  │
  └─ 4. Return JSON: {"id": "<uuid>", "status": "saved"}
        - Note is now on disk and in vector index
```

### Critical: Synchronous Saves

**Location**: `mcp_server.py:620-656`

```python
# In stdio mode the server process exits as soon as the response is sent,
# so background threads get killed before they can finish. Run synchronously
# so the note is on disk before we return. This adds ~10s latency for the
# LLM analysis, but is the only way to guarantee persistence in stdio mode.
try:
    mem.add_note(content, **kwargs)
    note = mem.read(memory_id)
    ...
```

**Why not background threads?** In stdio mode:
1. opencode sends a tool call to stdin
2. MCP server processes it, writes response to stdout
3. opencode reads response, **immediately kills the process**
4. Any `threading.Thread(daemon=True)` dies before completing

**Earlier bug**: Daemon threads returned "queued" fast but never wrote to disk. Result: zero notes persisted.

---

## Note Storage Format

### On-Disk Location

```
<project>/.memory/
├── notes/                                    # Markdown files organized in tree
│   ├── architecture/
│   │   └── database/
│   │       └── postgresql/
│   │           └── postgres-jsonb-indexing.md
│   ├── devops/
│   │   ├── ci-cd/
│   │   │   └── github-actions-triggers.md
│   │   └── containerization/
│   │       └── docker/
│   │           └── docker-kernel-sharing-basics.md
│   └── ml/
│       └── deep-learning/
│           └── transformer-architecture-fundamentals.md
├── vectordb/                                 # zvec store files + lock
│   └── memories/
└── mcp_server.log                            # Server activity log
```

### Markdown Format

**Location**: `memory_note.py:129-154`

```markdown
---
id: "0c56a5d2-a737-45ec-92e2-ade0163b1d90"
name: "github actions triggers"
path: "devops/ci-cd"
keywords: ["github actions", "workflow triggers", "event-driven automation", "push", "pull request"]
links: ["6878f09f-e327-4c90-8c07-8c89a82237e3"]
retrieval_count: 0
timestamp: "202604042021"
last_accessed: "202604042021"
context: "Explaining the foundational event-driven architecture..."
evolution_history: []
category: "Uncategorized"
tags: ["github-actions", "ci-cd", "workflow-automation", "devops", "gitops"]
summary: "GitHub Actions workflows are triggered by events like push, pull_request, or schedule."
---

GitHub Actions workflows are triggered by events like push, pull_request, or schedule.
You can configure multiple triggers for a single workflow, and each trigger can have
additional configuration options like branches, paths, or types.
```

### Frontmatter Fields

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `id` | UUID | Auto-generated | Unique identifier for the note |
| `name` | string | LLM | 2-5 word descriptive name (e.g., "docker container basics") |
| `path` | string | LLM | Directory path for knowledge tree placement |
| `keywords` | string[] | LLM | Salient terms ordered by importance |
| `context` | string | LLM | One-sentence domain summary |
| `tags` | string[] | LLM | Broad categories for classification |
| `summary` | string? | LLM | 2-3 sentence summary (only if content > 250 words) |
| `links` | UUID[] | Evolution | Forward links to related notes |
| `backlinks` | UUID[] | Derived | **Never persisted** — derived from forward links on load |
| `timestamp` | string | Auto | Creation time in `YYYYMMDDHHMM` format |
| `last_accessed` | string | Auto | Last access time |
| `retrieval_count` | int | Auto | Number of times retrieved via search |
| `evolution_history` | any[] | Evolution | Record of how the memory has evolved |
| `category` | string | Auto | Classification category (default: "Uncategorized") |

### Filepath Generation

**Location**: `memory_note.py:111-127`

```python
@property
def filepath(self) -> str:
    name_slug = self.filename  # slugified name or id
    if self.path:
        segments = [self._slugify(s) for s in self.path.strip("/").split("/")]
        return os.path.join(*segments, f"{name_slug}.md")
    return f"{name_slug}.md"
```

**Example**: `name="GitHub Actions Triggers"` + `path="devops/ci-cd"` → `devops/ci-cd/github-actions-triggers.md`

---

## LLM Analysis Pipeline

### Content Analysis

**Location**: `memory_system.py:361-481`

When a note is saved, the LLM generates structured metadata:

```python
def analyze_content(self, content: str) -> Dict:
    prompt = f"""Generate a structured analysis of the following content by:
        1. Creating a short, descriptive name (2-5 words, lowercase)
        2. Creating a directory path that categorizes this content in a knowledge tree
        3. Identifying the most salient keywords (focus on nouns, verbs, key concepts)
        4. Extracting core themes and contextual elements
        5. Creating relevant categorical tags
        {summary_instruction}
        {context_section}

        Format the response as a JSON object:
        {{
            "name": "...",
            "path": "...",
            "keywords": [...],
            "context": "...",
            "tags": [...],
            "summary": "..."  // only if content > 250 words
        }}

        Content for analysis:
        {content}"""
    
    response = self.llm_controller.llm.get_completion(
        prompt,
        response_format={"type": "json_schema", "json_schema": {...}}
    )
    return json.loads(response)
```

### Context-Aware Analysis

**Location**: `memory_system.py:315-360`

When `MEMORY_CONTEXT_AWARE=true` (default), the LLM prompt includes:

1. **Top-5 similar existing notes** — names, paths, tags
2. **Directory tree** — either top-level paths or full tree (if `MEMORY_CONTEXT_AWARE_TREE=true`)
3. **Instruction**: "Reuse existing paths and tags when the content fits"

```python
def _get_existing_context(self, content: str, include_tree: bool = False) -> str:
    lines = []
    # Search for similar memories
    results = self.retriever.search(content, k=5)
    for doc_id in results["ids"][0]:
        mem = self.memories.get(doc_id)
        if mem:
            similar.append(f"{mem.name} (path: {mem.path})")
    
    # Include directory structure
    if include_tree:
        lines.append(f"Full memory tree:\n{self.tree()}")
    else:
        all_paths = sorted({m.path for m in self.memories.values() if m.path})
        lines.append(f"Existing directory tree: {', '.join(tree_paths)}")
    
    return "\n".join(lines)
```

This ensures consistent naming and categorization as the knowledge base grows.

### Summary Generation

**Location**: `memory_system.py:274-279`

When content exceeds 250 words, the LLM generates a 2-3 sentence summary:

- Used for embedding instead of full content (to stay within token limits)
- Stored in `summary` field of frontmatter
- `all-MiniLM-L6-v2` supports 256 tokens; Gemini embedding truncates to 512

### LLM Backend Selection

**Location**: `llm_controller.py:332-361`

`LLMController` dispatches to one of 5 backends:

| Backend | Controller | Model Example | API Key Env Var |
|---------|------------|---------------|-----------------|
| `gemini` | `GeminiController` | `gemini-3-flash-preview` | `GOOGLE_API_KEY` |
| `openai` | `OpenAIController` | `gpt-4o-mini` | `OPENAI_API_KEY` |
| `ollama` | `OllamaController` | `llama2` | (local) |
| `sglang` | `SGLangController` | `meta-llama/Llama-3.1-8B-Instruct` | (local server) |
| `openrouter` | `OpenRouterController` | `openai/gpt-4o-mini` | `OPENROUTER_API_KEY` |

All backends support `response_format` with JSON schema for structured output. On failure, they return an empty response matching the expected schema rather than crashing.

---

## Memory Evolution (Auto-Linking)

### Evolution Process

**Location**: `memory_system.py:1144-1176`

After LLM analysis, every new note goes through **evolution**:

```
process_memory(note)
  │
  ├─ 1. find_related_memories(note.content, k=5)
  │     - Vector search for 5 nearest neighbors
  │     - Returns: (formatted_text, [memory_ids])
  │
  ├─ 2. _get_evolution_decision(note, neighbors_text, memory_ids)
  │     - LLM prompt with evolution instructions
  │     - Returns structured JSON decision
  │
  └─ 3. If should_evolve: _apply_evolution_actions()
        - "strengthen": create links, update tags
        - "update_neighbor": update neighbor context/tags
```

### Evolution Prompt

**Location**: `memory_system.py:240-272`

```python
_evolution_system_prompt = """
    You are an AI memory evolution agent responsible for managing and evolving a knowledge base.
    Analyze the new memory note according to keywords and context, also with their several 
    nearest neighbors memory. Make decisions about its evolution.

    The new memory context:
    {context}
    content: {content}
    keywords: {keywords}

    The nearest neighbors memories (each line starts with memory_id):
    {nearest_neighbors_memories}

    Based on this information, determine:
    1. Should this memory be evolved? Consider its relationships with other memories.
    2. What specific actions should be taken (strengthen, update_neighbor)?
       2.1 If choose to strengthen the connection, which memory should it be connected to?
       2.2 If choose to update_neighbor, you can update the context and tags...
    
    Return your decision in JSON format:
    {{
        "should_evolve": True or False,
        "actions": ["strengthen", "update_neighbor"],
        "suggested_connections": ["memory_id_1", "memory_id_2"],
        "tags_to_update": ["tag_1", "tag_2"],
        "new_context_neighborhood": ["updated context 1", ...],
        "new_tags_neighborhood": [["tag_1", "tag_2"], ...],
    }}
"""
```

### Evolution Actions

**Location**: `memory_system.py:1194-1232`

#### `strengthen` — Create forward links

```python
def _apply_strengthen(self, note: MemoryNote, response_json: dict) -> None:
    connections = response_json["suggested_connections"]
    if self.max_links is not None:
        connections = connections[:self.max_links]  # Cap at MEMORY_MAX_LINKS
    for conn_id in connections:
        self.add_link(note.id, conn_id)
    note.tags = response_json["tags_to_update"]
```

#### `update_neighbor` — Update existing notes

```python
def _apply_update_neighbors(self, response_json: dict, memory_ids: List[str]) -> None:
    new_contexts = response_json["new_context_neighborhood"]
    new_tags = response_json["new_tags_neighborhood"]
    
    for i, memory_id in enumerate(memory_ids):
        neighbor = self.memories[memory_id]
        neighbor.tags = new_tags[i]
        neighbor.context = new_contexts[i]
        self._save_note(neighbor)  # Persist updated neighbor
```

### Link/Backlink System

**Location**: `memory_system.py:836-858`

```python
def add_link(self, from_id: str, to_id: str):
    """Create a forward link from one note to another. Backlink is auto-created."""
    from_note = self.memories[from_id]
    to_note = self.memories[to_id]
    
    if to_id not in from_note.links:
        from_note.links.append(to_id)
        self._save_note(from_note)  # Persist forward link
    
    if from_id not in to_note.backlinks:
        to_note.backlinks.append(from_id)  # Backlinks are NOT persisted
```

**Key insight**: Backlinks are **never persisted** to disk. They are always derived from forward links during `_rebuild_backlinks()` on load.

```python
def _rebuild_backlinks(self):
    """Derive all backlinks from forward links. Also prunes dead links."""
    # Clear all backlinks
    for note in self.memories.values():
        note.backlinks = []
    
    # Rebuild: if A.links contains B, then B.backlinks gets A
    for note in self.memories.values():
        for linked_id in note.links:
            if linked_id in self.memories:
                self.memories[linked_id].backlinks.append(note.id)
```

---

## Vector Retrieval System

### Two Backend Options

**Location**: `retrievers.py`

| Backend | Class | Use Case |
|---------|-------|----------|
| `zvec` | `ZvecRetriever` | **Default in production** — HNSW index, file-based persistence |
| `chroma` | `ChromaRetriever` | Alternative — ChromaDB's PersistentClient |

### ZvecRetriever (Default)

**Location**: `retrievers.py:203-370`

```python
class ZvecRetriever:
    def __init__(self, collection_name, model_name, persist_dir, embedding_backend):
        # Create embedding function
        self.embedding_function = _create_embedding_function(embedding_backend, model_name)
        
        # Determine embedding dimension
        test_embedding = self.embedding_function(["test"])
        self._dimension = len(test_embedding[0])
        
        # Open or create collection with HNSW index
        collection_path = os.path.join(persist_dir, collection_name)
        if os.path.exists(collection_path):
            self.collection = self._open_with_retry(_zvec, collection_path)
        else:
            self.collection = _zvec.create_and_open(
                path=collection_path,
                schema=_zvec.CollectionSchema(
                    name=collection_name,
                    fields=[_zvec.FieldSchema(name="metadata_json", data_type=STRING)],
                    vectors=[_zvec.VectorSchema(
                        name="embedding",
                        data_type=VECTOR_FP32,
                        dimension=self._dimension,
                        index_param=_zvec.HnswIndexParam(metric_type=COSINE)
                    )]
                )
            )
```

### Lock Retry (Critical for Concurrency)

**Location**: `retrievers.py:250-268`

```python
@staticmethod
def _open_with_retry(_zvec, collection_path: str):
    """Open a Zvec collection with retry on lock contention.
    
    Multiple MCP server processes may try to open the same collection
    simultaneously when several agents call memory_save concurrently.
    """
    last_err = None
    for _attempt in range(30):  # ~30s total wait
        try:
            return _zvec.open(path=collection_path)
        except RuntimeError as e:
            last_err = e
            if "lock" not in str(e).lower():
                raise  # Only retry on lock errors
            time.sleep(1.0)
    raise last_err
```

**Problem**: zvec uses a single-writer file lock on `.memory/vectordb/`. When multiple agents spawn concurrent MCP server processes, all but one would fail with `RuntimeError: Can't lock read-write collection`.

**Solution**: 30-second retry loop with 1s intervals. Only `RuntimeError` messages containing "lock" are retried.

### Enhanced Documents for Embedding

**Location**: `retrievers.py:55-71`

Before embedding, documents are enriched for better semantic search:

```python
def _build_enhanced_document(document: str, metadata: Dict) -> str:
    # Use summary if available (for long content)
    enhanced = summary if summary else document
    
    # Append metadata for richer embedding
    if context and context != "General":
        enhanced += f" context: {context}"
    if keywords:
        enhanced += f" keywords: {', '.join(keywords)}"
    if tags:
        enhanced += f" tags: {', '.join(tags)}"
    
    return enhanced
```

### Search Results Format

Both backends return results in ChromaDB-compatible format:

```python
{
    "ids": [["uuid1", "uuid2", "uuid3"]],  # Note: nested list
    "metadatas": [[{...}, {...}, {...}]],
    "distances": [[0.12, 0.34, 0.56]]  # Cosine similarity (lower = more similar)
}
```

---

## MCP Tools Exposed

**Location**: `mcp_server.py:552-1190`

### Tool Enablement System

Tools are controlled by `MEMORY_DISABLED_TOOLS` env var:

```python
DISABLED_TOOLS = {
    t.strip()
    for t in os.getenv(
        "MEMORY_DISABLED_TOOLS",
        "read_memory,update_memory,delete_memory,link_memories,unlink_memories,"
        "memory_stats,sync_from_disk,sync_to_disk,graph_snapshot"
    ).split(",")
    if t.strip()
}
```

### Default-Enabled Tools

| Tool | Location | Description |
|------|----------|-------------|
| `memory_save` | 552-656 | Save a new memory with full LLM analysis |
| `memory_search` | 659-695 | Semantic vector search |
| `memory_tree` | 866-877 | Directory tree visualization |
| `grep_memory` | 1062-1101 | Grep across note .md files |
| `find_memory` | 1151-1190 | Find notes by filename patterns |

### Default-Disabled Tools

| Tool | Location | Description |
|------|----------|-------------|
| `read_memory` | 698-733 | Read single note by ID |
| `update_memory` | 736-793 | Update existing note |
| `delete_memory` | 796-815 | Delete note + cleanup links |
| `link_memories` | 818-847 | Manual link creation |
| `unlink_memories` | 850-863 | Manual link removal |
| `memory_stats` | 880-903 | Statistics about the memory system |
| `sync_from_disk` | 906-930 | Reload from disk files |
| `sync_to_disk` | 933-951 | Write in-memory state to disk |
| `graph_snapshot` | 954-965 | Full graph data for UI visualization |

### `memory_save` Tool Details

```python
@optional_tool("memory_save")
def memory_save(
    content: str,
    name: Optional[str] = None,
    path: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> str:
    """Save a new memory note to the knowledge base.

    Write detailed, comprehensive memories — not just brief notes. Include context,
    reasoning, examples, trade-offs, and lessons learned. The more detail you provide,
    the more useful the memory will be when retrieved later.

    Good memories are 3-10 sentences and capture:
    - WHAT happened or was decided
    - WHY it matters or was chosen over alternatives
    - HOW it works in practice, with specific details
    - GOTCHAS or edge cases discovered

    Args:
        content: The memory content. Be detailed and thorough.
        name: Optional human-readable name (2-5 words). Auto-generated if not provided.
        path: Optional directory path (e.g. "backend/database"). Auto-generated if not provided.
        tags: Optional list of tags. Auto-generated if not provided.

    Returns:
        JSON with the saved memory's id and status.
    """
```

### `memory_search` Tool Details

```python
@optional_tool("memory_search")
def memory_search(query: str, k: int = 5) -> str:
    """Search the knowledge base using natural language.

    Returns the most semantically relevant memories for the query. Results include
    full content, metadata, and relationship information.

    Use specific, descriptive queries for best results:
    - Good: "PostgreSQL indexing strategies for JSON data"
    - Bad: "database"

    Args:
        query: Natural language search query. Be specific and descriptive.
        k: Maximum number of results to return (default: 5).

    Returns:
        JSON array of matching memories with content, tags, path, and links.
    """
```

### `grep_memory` Tool Details

```python
@optional_tool("grep_memory")
def grep_memory(pattern: str, flags: Optional[str] = None) -> str:
    """Search memory files using grep (full CLI grep).

    Examples:
        grep_memory("PostgreSQL")                    -- basic search
        grep_memory("oauth.*token", "-i")            -- case-insensitive regex
        grep_memory("TODO", "-l")                    -- list filenames only
        grep_memory("error", "-c")                   -- count matches per file
        grep_memory("docker|kubernetes", "-E")       -- extended regex (OR)

    Args:
        pattern: Search pattern (string or regex depending on flags).
        flags: Optional grep flags (-i, -n, -l, -c, -w, -v, -E, -P, -A N, -B N, -C N).

    Returns:
        Grep output with paths relative to notes directory.
    """
```

---

## Concurrency Handling

### Problem Statement

In ostwin's war-room orchestration:

1. Multiple agents (architect, engineer, qa, etc.) run in parallel
2. Each agent's opencode instance spawns a **separate MCP server process** via stdio
3. All processes try to access the same `.memory/vectordb/` directory
4. zvec uses a single-writer file lock

### Three Solutions

| Solution | Location | How |
|----------|----------|-----|
| **Zvec lock retry** | `retrievers.py:250-268` | 30-second retry loop when file lock is held |
| **Synchronous saves** | `mcp_server.py:620-656` | One note written per process at a time |
| **Background auto-sync** | `mcp_server.py:968-994` | Daemon thread syncs to disk every 60s (SSE mode) |

### Auto-Sync Background Thread

```python
def _auto_sync_loop(interval: int):
    """Background thread that periodically syncs memory to disk."""
    while True:
        _sync_stop_event.wait(interval)
        if _sync_stop_event.is_set():
            break
        if _memory is not None:
            result = _memory.sync_to_disk()
            logger.info("Auto-sync to disk: %s", result)

if AUTO_SYNC_ENABLED:  # Default: true
    _sync_thread = threading.Thread(
        target=_auto_sync_loop,
        args=(AUTO_SYNC_INTERVAL,),  # Default: 60 seconds
        daemon=True,
        name="memory-auto-sync",
    )
    _sync_thread.start()
```

---

## Configuration

### Environment Variables

**Location**: `mcp_server.py:215-236`

| Variable | Default | Purpose |
|----------|---------|---------|
| `MEMORY_PERSIST_DIR` | `<project>/.memory` | Where notes and vectordb live |
| `MEMORY_LOG_DIR` | Same as `PERSIST_DIR` | Where `mcp_server.log` goes |
| `MEMORY_LLM_BACKEND` | `gemini` | LLM for analysis (gemini/openai/ollama/sglang/openrouter) |
| `MEMORY_LLM_MODEL` | `gemini-3-flash-preview` | Specific LLM model |
| `MEMORY_EMBEDDING_MODEL` | `gemini-embedding-001` | Embedding model |
| `MEMORY_EMBEDDING_BACKEND` | `gemini` | Embedding provider (gemini/sentence-transformer) |
| `MEMORY_VECTOR_BACKEND` | `zvec` | Vector DB (zvec or chroma) |
| `MEMORY_CONTEXT_AWARE` | `true` | Pass existing notes to analysis LLM |
| `MEMORY_CONTEXT_AWARE_TREE` | `false` | Include full tree in analysis context |
| `MEMORY_MAX_LINKS` | `3` | Max links per evolution |
| `MEMORY_AUTO_SYNC` | `true` | Enable background sync-to-disk |
| `MEMORY_AUTO_SYNC_INTERVAL` | `60` | Sync interval in seconds |
| `MEMORY_DISABLED_TOOLS` | (see above) | Comma-separated tools to hide from MCP clients |
| `MEMORY_NO_REEXEC` | `false` | Opt out of interpreter self-healing |

### Project Root Resolution

**Location**: `mcp_server.py:86-123`

Tries (in order):

1. `AGENT_OS_ROOT` (if absolute)
2. `AGENT_OS_PROJECT_DIR` (set by Invoke-Agent wrapper)
3. `MEMORY_PERSIST_DIR` parent (if absolute)
4. Parent process CWD walk via `/proc/<ppid>/cwd` (up to 5 levels)
5. Current working directory

### MCP Config Flow

```
~/.ostwin/.agents/mcp/mcp-builtin.json (source template with {env:VAR})
  │
  └─ config_resolver.py resolves placeholders
       │
       └─ <project>/.opencode/opencode.json (what opencode reads at runtime)
```

**Source template** (`mcp-builtin.json:23-31`):

```json
"memory": {
    "type": "local",
    "command": ["python", "{env:AGENT_DIR}/.agents/memory/mcp_server.py"],
    "environment": {
        "AGENT_OS_ROOT": "{env:PROJECT_DIR}",
        "MEMORY_PERSIST_DIR": "./.memory",
        "GOOGLE_API_KEY": "{env:GOOGLE_API_KEY}"
    }
}
```

**Resolution** (`config_resolver.py`):

- `{env:AGENT_DIR}` → `~/.ostwin`
- `{env:PROJECT_DIR}` → absolute project path
- `./.memory` → `<project_dir>/.memory` (relative path resolution)
- `GOOGLE_API_KEY` → resolved from `.env` files or shell rc files
- `python` → absolute path of current Python interpreter

---

## Startup Optimizations

### Self-Healing Interpreter

**Location**: `mcp_server.py:14-66`

Various MCP launchers (opencode, deepagents, codex) invoke the script with whatever `python` resolves in their environment — which often lacks heavy deps (`requests`, `litellm`, `chromadb`, `sentence-transformers`).

```python
def _ensure_correct_interpreter() -> None:
    # Skip if opt-out set
    if os.getenv("MEMORY_NO_REEXEC", "").lower() in ("1", "true", "yes"):
        return
    
    # Check if current interpreter has 'requests'
    if importlib.util.find_spec("requests") is not None:
        return
    
    # Try to find venv python
    candidates = [
        os.path.join(here, ".venv", "bin", "python"),
        os.path.join(here, ".venv", "bin", "python3"),
    ]
    target = next((c for c in candidates if os.path.isfile(c)), None)
    
    # Verify candidate has 'requests' before re-exec
    probe = subprocess.run([target, "-c", "import requests"], capture_output=True)
    if probe.returncode != 0:
        return  # Let import fail naturally downstream
    
    # Re-exec transparently
    os.execv(target, [target, os.path.abspath(__file__), *sys.argv[1:]])
```

### Lazy ML Imports

**Location**: `memory_system.py:28-53`

Heavy deps take 6+ seconds to import:

```python
# Lazy imports for heavy ML libraries
SentenceTransformer = None
AutoModel = None
AutoTokenizer = None
word_tokenize = None
BM25Okapi = None
cosine_similarity = None
completion = None

def _ensure_ml_imports():
    """Import heavy ML libraries on first use."""
    global SentenceTransformer, AutoModel, AutoTokenizer, word_tokenize, BM25Okapi, cosine_similarity, completion
    if completion is not None:
        return  # already imported
    from sentence_transformers import SentenceTransformer as _ST
    from transformers import AutoModel as _AM, AutoTokenizer as _AT
    from nltk.tokenize import word_tokenize as _wt
    from rank_bm25 import BM25Okapi as _BM
    from sklearn.metrics.pairwise import cosine_similarity as _cs
    from litellm import completion as _comp
    SentenceTransformer = _ST
    # ... etc
```

**Impact**: Startup reduced from ~9s to <1s.

### Background Init Thread

**Location**: `mcp_server.py:274-319`

The memory system loads heavy deps in a background thread:

```python
_memory = None
_memory_init_error: Optional[Exception] = None
_memory_lock = threading.Lock()
_memory_ready = threading.Event()

def _init_memory():
    """Initialize the memory system (runs in background thread)."""
    global _memory, _memory_init_error, AgenticMemorySystem
    try:
        from dashboard.agentic_memory.memory_system import AgenticMemorySystem as _AMS
        AgenticMemorySystem = _AMS
        with _memory_lock:
            _memory = AgenticMemorySystem(
                model_name=EMBEDDING_MODEL,
                embedding_backend=EMBEDDING_BACKEND,
                vector_backend=VECTOR_BACKEND,
                llm_backend=LLM_BACKEND,
                llm_model=LLM_MODEL,
                persist_dir=PERSIST_DIR,
                context_aware_analysis=CONTEXT_AWARE,
                context_aware_tree=CONTEXT_AWARE_TREE,
                max_links=MAX_LINKS,
            )
    except Exception as exc:
        _memory_init_error = exc
    finally:
        _memory_ready.set()

# Start background initialization immediately
_init_thread = threading.Thread(target=_init_memory, daemon=True, name="memory-init")
_init_thread.start()
```

**Benefit**: Server responds to `initialize`/`tools/list` instantly while heavy deps load in background.

### Noise Suppression

**Location**: `mcp_server.py:147-214`

Two mechanisms silence junk from stdin (stray newlines, invalid JSON):

1. A `_DropStreamParseErrors` logging filter on MCP's lowlevel loggers
2. A monkey-patch of `mcp.server.lowlevel.Server._handle_message`

```python
class _DropStreamParseErrors(logging.Filter):
    _NOISE = (
        "Received exception from stream",
        "Invalid JSON",
        "Internal Server Error",
    )
    def filter(self, record: logging.LogRecord) -> bool:
        return not any(needle in record.getMessage() for needle in self._NOISE)

# Monkey-patch to suppress stream errors
def _patch_mcp_exception_silence() -> None:
    async def _handle_message_quiet(self, message, session, lifespan_context, raise_exceptions=False):
        # ... handles message without forwarding exceptions to client
    _lowlevel.Server._handle_message = _handle_message_quiet
```

---

## Integration with ostwin

### How ostwin Uses Memory

1. **Each war-room agent** (architect, engineer, qa) has access to the memory MCP tool
2. **Agents save decisions, context, learnings** as notes during execution
3. **Notes persist across sessions** in `<project>/.memory/`
4. **Agents can search** for relevant knowledge from previous sessions

### MCP Config in ostwin

**Location**: `~/.ostwin/.agents/mcp/mcp-builtin.json`

```json
{
  "mcp": {
    "memory": {
      "type": "local",
      "command": ["python", "{env:AGENT_DIR}/.agents/memory/mcp_server.py"],
      "environment": {
        "AGENT_OS_ROOT": "{env:PROJECT_DIR}",
        "MEMORY_PERSIST_DIR": "./.memory",
        "GOOGLE_API_KEY": "{env:GOOGLE_API_KEY}"
      }
    }
  }
}
```

### Relationship to Layered Memory

The **Layered Memory** (Pillar 5, `docs/memory.md`) is a **different system**:

| Aspect | Layered Memory | Agentic Memory (this doc) |
|--------|----------------|---------------------------|
| **Purpose** | Cross-room knowledge sharing | Long-term semantic knowledge base |
| **Storage** | `.agents/memory/ledger.jsonl` | `<project>/.memory/notes/*.md` |
| **Search** | BM25 + time decay | Vector similarity |
| **Links** | No | Auto-generated by LLM evolution |
| **Scope** | Plan-level | Project-level (persists across plans) |

Both systems coexist — Layered Memory for short-term cross-room coordination, Agentic Memory for long-term semantic memory.

---

## CLI Usage

### Standalone CLI

**Location**: `.agents/memory/memory-cli.py`

```bash
# Save a note
memory-cli.py save "PostgreSQL JSONB provides flexible semi-structured storage with GIN index support." \
    --name "postgres-jsonb-basics" \
    --path "backend/database" \
    --tags postgresql,database,jsonb

# Search
memory-cli.py search "JSON indexing strategies"

# Show tree
memory-cli.py tree

# Stats
memory-cli.py stats
```

### Testing MCP Server Directly

```bash
# Test memory_save via raw MCP JSON-RPC
echo -e '{
  "jsonrpc":"2.0",
  "id":1,
  "method":"initialize",
  "params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0.1"}}
}\n{
  "jsonrpc":"2.0",
  "method":"notifications/initialized"
}\n{
  "jsonrpc":"2.0",
  "id":2,
  "method":"tools/call",
  "params":{
    "name":"memory_save",
    "arguments":{"content":"test note with enough content to be meaningful for the LLM to analyze"}
  }
}' | \
  MEMORY_PERSIST_DIR=/tmp/test/.memory \
  GOOGLE_API_KEY=$(grep GOOGLE_API_KEY ~/.ostwin/.env | cut -d= -f2) \
  ~/.ostwin/.venv/bin/python ~/.ostwin/.agents/memory/mcp_server.py
```

---

## Troubleshooting

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `RuntimeError: Can't lock read-write collection` | Concurrent zvec writers | Already fixed with 30s retry. If persists, reduce concurrent agents. |
| `Memory queued for save` but no notes appear | Old version with daemon background thread | Already fixed — `memory_save` is synchronous now |
| `ModuleNotFoundError: No module named 'requests'` | Wrong Python interpreter | Self-healing should re-exec. If fails, set `MEMORY_NO_REEXEC=false` or check venv. |
| `GOOGLE_API_KEY not found` | Missing API key | Set in `~/.ostwin/.env` or shell rc file |
| `{env:VAR}` placeholder visible in compiled config | Var not in shell, .env, or rc files | Add to `~/.ostwin/.env` and re-run `ostwin init` |
| `memory_save` takes 10+ seconds | Normal — synchronous LLM analysis | Expected behavior in stdio mode |
| Notes in wrong directory | `WARROOMS_DIR` or `MEMORY_PERSIST_DIR` resolution | Check `_find_project_root()` fallback chain |

### Logs

```bash
# View server activity
cat <project>/.memory/mcp_server.log

# See what tools an opencode-launched agent called
grep "Calling tool\|⚙\|memory_save" ~/.ostwin/.agents/plans/*.log
```

### Debugging Tips

```bash
# Find where notes are stored
find ~/ostwin-workingdir ~/os-twin -name "*.md" -path "*/.memory/notes/*" 2>/dev/null

# Check vector DB lock status
ls -la <project>/.memory/vectordb/

# Test vector search directly
python -c "
from dashboard.agentic_memory.retrievers import ZvecRetriever
r = ZvecRetriever('memories', 'gemini-embedding-001', '<project>/.memory/vectordb', 'gemini')
print(r.search('test query', k=3))
"
```

---

## Key Source Files Summary

| File | Lines | Key Sections |
|------|-------|--------------|
| `mcp_server.py` | 1217 | Entry point, tools, background init, noise suppression |
| `memory_system.py` | 1232 | `AgenticMemorySystem`, evolution, search, sync |
| `memory_note.py` | 200 | `MemoryNote` model, markdown serialization |
| `retrievers.py` | 370 | `ZvecRetriever`, `ChromaRetriever`, lock retry |
| `llm_controller.py` | 366 | Backend dispatch, structured output |
| `memory-cli.py` | 118 | Standalone CLI |

---

## Summary

The Agentic Memory MCP Server provides:

1. **Semantic knowledge persistence** — Notes stored as markdown with auto-generated metadata
2. **LLM-powered analysis** — Automatic name, path, keywords, tags, summary generation
3. **Auto-linking** — Memory evolution creates relationships between related notes
4. **Vector search** — Similarity-based retrieval using embeddings
5. **Concurrency-safe** — Lock retry + synchronous saves handle parallel agents
6. **Fast startup** — Lazy imports + background init keep MCP responsive

The key insight is that **all persistence is synchronous** in stdio mode — there's no background queue. The ~10s latency for `memory_save` is the cost of guaranteeing data is on disk before the process is killed.
