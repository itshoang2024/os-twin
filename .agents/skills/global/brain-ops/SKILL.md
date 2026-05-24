---
name: brain-ops
description: The dual-layer context system for team operations. Defines how workers
  and evaluators read and write to Knowledge (source of truth) and
  Memory (working context). Read this before any start and complete any plan to ensure your work is aligned with the team's knowledge base.
---

# Brain Operations — The Dual-Layer Context System

The brain is two complementary layers — **Knowledge** and **Memory** — that
every agent reads from and writes to as part of normal work. Neither layer is
an archive; both are live, authoritative systems that shape every decision.

Both layers are accessed via MCP tools or the `npx mcporter call` CLI.

---

## The Two Layers

### Knowledge — The Source of Truth

Knowledge namespaces hold the **canonical, trusted documentation** the team
believes in. This is the project's institutional memory — the things that are
*true* regardless of which epic is running.

| What goes in Knowledge | Examples |
|------------------------|----------|
| Architecture decisions (ADRs) | "We use PostgreSQL with JSONB for product attributes" |
| API contracts and schemas | OpenAPI specs, protobuf definitions, DB schemas |
| Coding conventions | Error shapes, naming rules, folder structure |
| Onboarding guides | "How to set up local dev", "How auth works" |
| Domain glossary | Business terms, bounded context definitions |
| Reference documentation | Imported docs, specs, compliance requirements |
| Project configuration | Env var catalog, deployment topology, infra docs |

**Properties:**
- Persistent across epics — survives after the war-room closes
- High-trust — curated, reviewed, versioned
- Queryable via RAG — vector search, graph, or LLM-summarized
- Importable in bulk — entire folders of docs, PDFs, images
- Owned by anyone, curated by knowledge-curator

### Memory — The Working Context

Memory notes capture the **operational context** of how the team works across
epics. This is what agents leave behind so that the *next* agent in a
different war-room can pick up where they left off.

| What goes in Memory | Examples |
|---------------------|----------|
| Code written this epic | "Created `src/auth.py` — JWT validation with 24h expiry" |
| Interfaces exposed | "POST /api/v1/users — request/response shapes" |
| Decisions made during work | "Chose bcrypt over argon2 because..." |
| Gotchas discovered | "The CHECK constraint on `status` requires a migration" |
| QA findings and patterns | "Login endpoint missing rate limiting — recurring issue" |
| Cross-room coordination | "Room-003 schema depends on Room-001's User model" |
| User preferences | "User prefers bundled PRs for refactors" |

**Properties:**
- Scoped to the working session — accumulates across epics
- Medium-trust — auto-generated, auto-tagged, auto-linked
- Semantically searchable via vector embeddings
- Fast to write — no approval needed, background analysis (~10s)
- Every agent is both a reader and a writer

---

## Command Reference — Knowledge MCP

Server name: `knowledge`

All tools are invoked via MCP or CLI:
```bash
npx mcporter call knowledge.<tool_name> [args...]
```

### `knowledge_list_namespaces`

List all knowledge namespaces with their stats.

**Returns:** `{ namespaces: [{ name, created_at, updated_at, language, description, stats: { files_indexed, chunks, entities, relations, vectors }, imports }] }`

**Use when:** discovering what knowledge bases exist, before querying or importing.

```bash
# MCP
knowledge_list_namespaces()

# CLI
npx mcporter call knowledge.list_namespaces
```

### `knowledge_create_namespace`

Create a new knowledge namespace.

| Arg | Type | Required | Description |
|-----|------|----------|-------------|
| `name` | string | ✅ | Lowercase alphanumeric + dashes/underscores, 1–64 chars. Must start with letter or digit. |
| `language` | string | ❌ | Human language of content (default: `"English"`). Used by LLM during entity extraction. |
| `description` | string | ❌ | Free-form description for discoverability. |

**Returns:** NamespaceMeta dict, or `{ error, code }` on failure.

**Error codes:** `INVALID_NAMESPACE_ID`, `NAMESPACE_EXISTS`, `MAX_NAMESPACES_REACHED`, `INTERNAL_ERROR`

**Note:** NOT required before `knowledge_import_folder` — that auto-creates the namespace.

```bash
# MCP
knowledge_create_namespace("project_docs", "English", "Internal product handbook v3")

# CLI
npx mcporter call knowledge.create_namespace name:'project_docs' language:'English' description:'Internal product handbook v3'
```

### `knowledge_delete_namespace`

Delete a knowledge namespace and ALL its data permanently. **IRREVERSIBLE.**

| Arg | Type | Required | Description |
|-----|------|----------|-------------|
| `name` | string | ✅ | Namespace to delete. |
| `confirm` | boolean | ❌ | Must be `true` to proceed. Required by knowledge-curator to prevent accidental deletion. |

**Returns:** `{ deleted: true }` if removed, `{ deleted: false }` if it didn't exist (no error).

**Error codes:** `INTERNAL_ERROR` on unexpected failure.

**⚠️ DANGEROUS:** This is irreversible. Always confirm with the user before calling.

```bash
# MCP
knowledge_delete_namespace("temp_test_kb", true)

# CLI
npx mcporter call knowledge.delete_namespace name:'temp_test_kb' confirm:true
```

### `knowledge_import_folder`

Import all supported files from an absolute folder path into a namespace.

| Arg | Type | Required | Description |
|-----|------|----------|-------------|
| `namespace` | string | ✅ | Target namespace. Auto-created if it doesn't exist. |
| `folder_path` | string | ✅ | **ABSOLUTE** local filesystem path. Relative paths rejected. |
| `force` | boolean | ❌ | When `true`, re-process files whose content hash already exists. Default: skip indexed files. |

**Supported file types:** docx, pdf, xlsx, pptx, doc, ppt, xls, html, htm, txt, md, csv, json, xml, yaml, yml, rtf, png, jpg, jpeg, gif, bmp, tiff, webp

**Image OCR:** Requires `ANTHROPIC_API_KEY` in dashboard environment. Without it, images are skipped silently.

**Returns:** `{ job_id, status: "submitted", message }` — import runs in background.

**Error codes:** `INVALID_FOLDER_PATH`, `FOLDER_NOT_FOUND`, `NOT_A_DIRECTORY`, `INVALID_NAMESPACE_ID`, `IMPORT_IN_PROGRESS`, `INTERNAL_ERROR`

**After calling:** Poll `knowledge_get_import_status` with the returned `job_id`.

```bash
# MCP
knowledge_import_folder("project_docs", "/Users/me/projects/docs")
knowledge_import_folder("project_docs", "/Users/me/projects/docs", true)  # force re-import

# CLI
npx mcporter call knowledge.import_folder namespace:'project_docs' folder_path:'/Users/me/projects/docs'
npx mcporter call knowledge.import_folder namespace:'project_docs' folder_path:'/Users/me/projects/docs' force:true
```

### `knowledge_import_text`

Ingest plain text directly into a namespace — **synchronous**, no job polling needed. Ideal for notes, design decisions, meeting summaries, or any short-form text.

| Arg | Type | Required | Description |
|-----|------|----------|-------------|
| `namespace` | string | ✅ | Target namespace. Auto-created if it doesn't exist. |
| `text` | string | ✅ | Plain text to ingest (1–100,000 characters). |
| `source_label` | string | ❌ | Label identifying the text source (default: `"inline"`). Examples: `"meeting-notes"`, `"design-decision"`, `"auth-design"`. |

**Returns:** `{ namespace, chunks_added, entities_added, relations_added, elapsed_seconds }` on success, or `{ error, code }` on failure.

**Error codes:** `EMPTY_TEXT`, `TEXT_TOO_LONG`, `INVALID_NAMESPACE_ID`, `IMPORT_IN_PROGRESS`, `INTERNAL_ERROR`

**When to use instead of `knowledge_import_folder`:**
- Promoting a single memory finding to Knowledge (no file needed)
- Ingesting meeting notes, design rationale, or ADRs written inline
- Quick one-off knowledge additions during a session

```bash
# MCP
knowledge_import_text("project_docs", "The authentication system uses JWT tokens with 24-hour expiry...", source_label="auth-design")

# CLI
npx mcporter call knowledge.import_text \
  namespace:'project_docs' \
  text:'The authentication system uses JWT tokens with 24-hour expiry and refresh token rotation. Access tokens are validated via middleware on every request.' \
  source_label:'auth-design'
```

### `knowledge_get_import_status`

Poll the status of a background import job.

| Arg | Type | Required | Description |
|-----|------|----------|-------------|
| `namespace` | string | ✅ | Namespace where import was started (informational). |
| `job_id` | string | ✅ | Job ID returned by `knowledge_import_folder`. |

**Returns:** `{ state, progress_current, progress_total, message, errors, result }`

**Job states:** `pending → running → completed | failed | interrupted | cancelled`

**Error codes:** `JOB_NOT_FOUND` if the job_id is unknown.

**Polling strategy:**
- Small imports (<50 files): poll every 5–10 seconds
- Large imports (>100 files): poll every 30 seconds
- Stop when state is `completed`, `failed`, or `cancelled`

```bash
# MCP
knowledge_get_import_status("project_docs", "abc-123-uuid")

# CLI
npx mcporter call knowledge.get_import_status namespace:'project_docs' job_id:'abc-123-uuid'
```

### `knowledge_query`

Query a knowledge namespace using natural language.

| Arg | Type | Required | Description |
|-----|------|----------|-------------|
| `namespace` | string | ✅ | Target namespace to search. |
| `query` | string | ✅ | Natural-language question or search phrase. |
| `mode` | string | ❌ | `"raw"` (vector only, fast), `"graph"` (vector + graph, PageRank), `"summarized"` (graph + LLM answer with citations, slowest). |
| `top_k` | number | ❌ | Max chunk hits to return (default: 10). |

**Returns:** `{ chunks, entities, answer?, citations?, latency_ms, warnings }`

**Mode selection guide:**
- `"raw"` — fast lookup, just need relevant snippets
- `"graph"` — need entity relationships and context
- `"summarized"` — need a synthesized answer with citations (requires LLM API key)

**Fallback:** If no LLM key configured and `mode="summarized"`, returns `warnings: ["llm_unavailable"]` and `answer: null` but still returns chunks.

**Error codes:** `NAMESPACE_NOT_FOUND`, `BAD_REQUEST`

```bash
# MCP
knowledge_query("project_docs", "How does auth work?", "summarized", 5)

# CLI
npx mcporter call knowledge.query namespace:'project_docs' query:'How does auth work?' mode:'summarized' top_k:5
```

### `knowledge_find_notes_by_knowledge_link`

Find memory notes that link to a specific knowledge chunk. Part of the Memory ↔ Knowledge Bridge.

| Arg | Type | Required | Description |
|-----|------|----------|-------------|
| `namespace` | string | ✅ | Knowledge namespace to search. |
| `file_hash` | string | ✅ | SHA256 hash of the source file. |
| `chunk_idx` | number | ❌ | Specific chunk index. If omitted, matches any chunk in the file. |

**Returns:** `{ note_ids: [...], count: N }`

**Error codes:** `BRIDGE_DISABLED`, `INTERNAL_ERROR`

```bash
# MCP — specific chunk
knowledge_find_notes_by_knowledge_link("docs", "abc123def456", 0)

# MCP — any chunk in file
knowledge_find_notes_by_knowledge_link("docs", "abc123def456")

# CLI
npx mcporter call knowledge.find_notes_by_knowledge_link namespace:'docs' file_hash:'abc123def456' chunk_idx:0
```

---

## Command Reference — Memory MCP

Server name: `memory`

All tools are invoked via MCP or CLI:
```bash
npx mcporter call memory.<tool_name> [args...]
```

### `memory_save`

Save a new memory note. Write detailed, comprehensive memories — **not one-liners**.

| Arg | Type | Required | Description |
|-----|------|----------|-------------|
| `content` | string | ✅ | The memory content. 3–10 sentences minimum. Include WHAT, WHY, HOW, and GOTCHAS. |
| `name` | string | ❌ | Human-readable name (2–5 words). Auto-generated if omitted. |
| `path` | string | ❌ | Directory path (e.g. `"backend/database"`, `"qa/reviews"`). Auto-generated if omitted. |
| `tags` | list | ❌ | List of tags. Auto-generated if omitted. |

**Auto-processing (background, ~10s):**
- Generates name and path if not provided
- Extracts keywords and tags for semantic search
- Finds and links related existing memories
- Creates a summary for long content (>150 words)

**Returns:** `{ id, status: "accepted" }` — note appears in `memory_search` / `memory_tree` once background analysis completes.

**Good vs Bad memories:**
```bash
# GOOD — detailed, with context, reasoning, gotchas
npx mcporter call memory.save \
  content:'PostgreSQL JSONB stores semi-structured data with full GIN indexing. We chose it over MongoDB because our data has relational aspects (user->orders->items) but product attributes vary per category. The GIN index on product.attributes reduced catalog search from 800ms to 12ms. Key gotcha: JSONB equality checks are exact-match, so normalize data before insertion.' \
  name:'PostgreSQL JSONB decision' \
  path:'architecture/database' \
  tags:'database,postgresql,jsonb,architecture'

# BAD — one-liner, no context
npx mcporter call memory.save content:'Use PostgreSQL JSONB for products.'
```

### `memory_search`

Semantic search across all memories. Returns the most relevant memories ranked by vector similarity.

| Arg | Type | Required | Description |
|-----|------|----------|-------------|
| `query` | string | ✅ | Natural language query. Be specific and descriptive. |
| `k` | number | ❌ | Max results to return (default: 5). |

**Returns:** JSON array of matching memories with `content`, `tags`, `path`, `links`, `backlinks`.

```bash
# MCP
memory_search("PostgreSQL indexing strategies for JSON data")
memory_search("authentication flow and JWT token handling", 10)

# CLI
npx mcporter call memory.search query:'PostgreSQL indexing strategies for JSON data'
npx mcporter call memory.search query:'auth flow JWT' k:10
```

### `memory_tree`

Show the full directory tree of all memories. Useful for understanding organization before saving.

**Returns:** Tree-formatted string of the memory directory structure.

```bash
# MCP
memory_tree()

# CLI
npx mcporter call memory.tree
```

### `grep_memory`

Full-text grep across all memory markdown files. Supports regex and standard grep flags.

| Arg | Type | Required | Description |
|-----|------|----------|-------------|
| `pattern` | string | ✅ | Search pattern (string or regex). |
| `flags` | string | ❌ | Grep flags: `-i`, `-n`, `-l`, `-c`, `-w`, `-v`, `-E`, `-P`, `-A N`, `-B N`, `-C N` |

**Returns:** Grep output with paths relative to notes directory.

```bash
# MCP
grep_memory("PostgreSQL")                    # basic search
grep_memory("oauth.*token", "-i")            # case-insensitive regex
grep_memory("TODO", "-l")                    # filenames only
grep_memory("error", "-c")                   # count matches per file
grep_memory("BEGIN", "-A 3")                 # 3 lines after match
grep_memory("docker|kubernetes", "-E")       # extended regex OR

# CLI
npx mcporter call memory.grep pattern:'PostgreSQL'
npx mcporter call memory.grep pattern:'oauth.*token' flags:'-i'
npx mcporter call memory.grep pattern:'TODO' flags:'-l'
```

### `find_memory`

Search memory files by name, path, size, or modification time. Runs `find` on the notes directory.

| Arg | Type | Required | Description |
|-----|------|----------|-------------|
| `args` | string | ❌ | Find arguments: `-name`, `-type`, `-size`, `-mtime`, `-mmin`, `-maxdepth`, `-empty`, `-path`, `-iname` |

**Returns:** Find output with paths relative to notes directory.

```bash
# MCP
find_memory()                                # list all files
find_memory("-name '*.md'")                  # find by name
find_memory("-name '*database*'")            # match pattern
find_memory("-path '*/backend/*'")           # files under path
find_memory("-mmin -60")                     # modified last 60 min
find_memory("-maxdepth 2 -type d")           # directories, 2 levels

# CLI
npx mcporter call memory.find
npx mcporter call memory.find args:"-name '*database*'"
npx mcporter call memory.find args:"-mmin -60"
```

### `find_notes_by_knowledge_link` (Memory side)

Reverse lookup: find memory notes that cite a specific knowledge chunk.

| Arg | Type | Required | Description |
|-----|------|----------|-------------|
| `namespace` | string | ✅ | Knowledge namespace (e.g. `"docs"`, `"api"`). |
| `file_hash` | string | ✅ | SHA256 hash of the source file (truncated). |
| `chunk_idx` | number | ❌ | Chunk index. If omitted, matches any chunk in the file. |

**Returns:** JSON array of matching note IDs. Empty array if no matches.

```bash
# CLI
npx mcporter call knowledge.find_notes_by_knowledge_link namespace:'docs' file_hash:'abc123def456'
```

---

## The Read/Write Contract

### Who Reads What, When

```
┌─────────────────────────────────────────────────────────────────┐
│                        BEFORE STARTING WORK                     │
│                                                                 │
│  1. memory_search("terms from your brief")     ← Memory first  │
│  2. memory_tree()                              ← See structure  │
│  3. knowledge_query(ns, "how does X work?")    ← Knowledge next │
│                                                                 │
│  Memory tells you what OTHER ROOMS have built.                  │
│  Knowledge tells you what the PROJECT believes.                 │
└─────────────────────────────────────────────────────────────────┘
```

Every role — worker or evaluator — MUST do this lookup before starting.
Memory gives you the latest working context. Knowledge gives you the
ground truth. Together they prevent duplication, contradiction, and drift.

### Who Writes What, When

#### Workers (Engineers, Architects, Database Architects, etc.)

Workers **MUST** write to Memory after every deliverable:

| Trigger | Write To | What |
|---------|----------|------|
| Created/modified a file | Memory | Full content of key code (models, APIs, configs) |
| Made an architectural decision | Memory | Decision + rationale + trade-offs |
| Discovered a gotcha | Memory | The gotcha with reproduction steps |
| Completed an epic/task | Memory | Summary of all files, interfaces, decisions |
| Produced a reusable artifact | Knowledge | Import the artifact folder into a namespace |
| Made a decision worth canonizing | Knowledge | `knowledge_import_text()` with the decision + rationale |

```bash
# After creating a model (Memory — working context)
npx mcporter call memory.save \
  content:'Created src/models/user.py — User model with fields: id (UUID), email (str, unique), hashed_password (str), created_at (datetime). Uses SQLAlchemy declarative base. Relationship: User has_many Orders. Validation: email format checked at API layer, not DB layer.' \
  name:'User model — src/models/user.py' \
  path:'code/models' \
  tags:'models,user,sqlalchemy'

# After producing project docs (Knowledge — source of truth)
npx mcporter call knowledge.import_folder \
  namespace:'project-api-docs' \
  folder_path:'/Users/me/projects/generated-docs'
```

#### Evaluators (QA, Auditors, Reviewers)

Evaluators **MUST** write to Memory after every review:

| Trigger | Write To | What |
|---------|----------|------|
| Found a recurring issue | Memory | The pattern + affected areas |
| Verified a quality standard | Memory | What was checked, what passed |
| Discovered a cross-room dependency | Memory | Which rooms are coupled and how |
| Escalated a design issue | Memory | The architectural concern + context |
| Completed a review cycle | Memory | Summary of findings, verdict, open risks |

```bash
# After a QA review (Memory — working context)
npx mcporter call memory.save \
  content:'Reviewed EPIC-003 auth module. PASSED with notes: 1. JWT expiry correctly set to 24h with refresh rotation. 2. Rate limiting on /login confirmed at 5 req/min via middleware. 3. MINOR: Error messages on 401 leak whether email exists — suggest generic invalid credentials. 4. Cross-room note: Room-005 (payments) needs the User model from this room.' \
  name:'QA verdict — EPIC-003 auth' \
  path:'qa/reviews' \
  tags:'qa,auth,epic-003,passed'

# After discovering a recurring pattern across epics
npx mcporter call memory.save \
  content:'Recurring issue across EPIC-001, EPIC-003, EPIC-005: engineers not adding rate limiting to new endpoints. The middleware exists (src/middleware/rate_limit.py) but is opt-in per route. Recommend making it opt-OUT in architecture docs. Filed as convention gap.' \
  name:'Pattern — missing rate limiting' \
  path:'qa/patterns' \
  tags:'qa,rate-limiting,convention-gap,recurring,promote-to-knowledge'
```

#### Evaluators Promoting to Knowledge

Evaluators can **promote** findings to Knowledge when a pattern becomes a
team-wide convention or when documentation needs updating:

```bash
# For a single finding — use knowledge_import_text (synchronous, no files needed)
npx mcporter call knowledge.import_text \
  namespace:'coding-conventions' \
  text:'Rate limiting is mandatory on all public endpoints. The middleware (src/middleware/rate_limit.py) must be applied opt-out, not opt-in. Default: 5 req/min for auth endpoints, 100 req/min for general API. This was decided after recurring gaps in EPIC-001, EPIC-003, and EPIC-005.' \
  source_label:'convention-rate-limiting'

# For bulk docs — use knowledge_import_folder (async, for folders of files)
npx mcporter call knowledge.import_folder \
  namespace:'coding-conventions' \
  folder_path:'/path/to/updated/conventions'
```

**When to use which:**
- `knowledge_import_text` — promoting a single decision, convention, or finding (most common promotion path)
- `knowledge_import_folder` — importing generated docs, spec folders, or bulk artifacts

This is the **Memory → Knowledge promotion** path: operational findings
crystallize into trusted documentation over time.

---

## The Lookup Protocol — 5 Steps

Before ANY work begins, every agent runs this sequence:

### Step 1: Memory Search (What have other rooms done?)

```bash
npx mcporter call memory.search query:'schema API auth conventions'
```

Reveals: existing code, interfaces, decisions, and gotchas from parallel or prior work.

### Step 2: Memory Tree (What's the structure?)

```bash
npx mcporter call memory.tree
```

Shows how memories are organized — helps you place new memories correctly and spot what areas have been worked on.

### Step 3: Knowledge Query (What does the project believe?)

```bash
npx mcporter call knowledge.query \
  namespace:'project-docs' \
  query:'How does authentication work?' \
  mode:'summarized'
```

Returns: canonical docs, architecture decisions, API specs — the ground truth that your implementation must align with.

### Step 4: Reconcile

Compare memory (what's been built) with knowledge (what should be built).
Flag any contradictions:

- Memory says "using bcrypt" but Knowledge says "use argon2" → raise in channel
- Memory says "no rate limiting middleware" but Knowledge has it documented → check actual code

### Step 5: Proceed with Full Context

Now you have both layers loaded. Your work should:
- **Align** with Knowledge (source of truth)
- **Extend** Memory (working context for other rooms)
- **Flag** contradictions between the two

---

## Knowledge vs Memory Decision Tree

```
Is this information...
│
├── True regardless of which epic is running?
│   ├── YES → Knowledge (source of truth)
│   │         Examples: API spec, coding standard, architecture decision
│   └── NO ──┐
│             │
├── Specific to work done in an epic/task?
│   ├── YES → Memory (working context)
│   │         Examples: "I created this file", "I chose this approach"
│   └── NO ──┐
│             │
├── A pattern discovered across multiple epics?
│   ├── YES → Memory NOW, promote to Knowledge LATER
│   │         Examples: recurring bugs, convention gaps
│   └── NO ──┐
│             │
└── User's direct statement or preference?
    └── YES → Memory with [Source: User, date] attribution
              Examples: "User prefers bundled PRs"
```

---

## The Memory → Knowledge Promotion Cycle

Over time, operational memory crystallizes into trusted knowledge:

```
Epic 1: Engineer saves "using PostgreSQL JSONB for products"     → Memory
Epic 2: Another engineer searches, finds it, follows it          → Memory read
Epic 3: QA notices it's become a de-facto standard              → Memory note
Sprint review: Team agrees to make it official                  → Knowledge import
```

**Who promotes?**
- **Knowledge Curator** runs periodic curation sessions
- **Architect** promotes ADRs after review
- **Manager** can request promotion during retrospectives
- **Any role** can flag a memory as "promote-worthy" via tags: `["promote-to-knowledge"]`

**How to promote:**
- **Inline promotion** (most common): `knowledge_import_text(namespace, text, source_label)` — synchronous, no files needed
- **Bulk promotion**: `knowledge_import_folder(namespace, folder_path)` — for folders of documents

---

## Role-Specific Obligations

### Workers (Engineers, Architects, etc.)

| Phase | Memory Action | Knowledge Action |
|-------|--------------|------------------|
| Before work | `memory_search()` + `memory_tree()` | `knowledge_query(ns, question)` |
| During work | — | — |
| After each file | `memory_save(content=full_code)` | — |
| After each decision | `memory_save(content=decision+why)` | — |
| After epic done | Summary `memory_save()` | `knowledge_import_folder()` if docs produced, or `knowledge_import_text()` for decisions |

### Evaluators (QA, Auditors, etc.)

| Phase | Memory Action | Knowledge Action |
|-------|--------------|------------------|
| Before review | `memory_search()` for engineer's work | `knowledge_query(ns, question)` for standards |
| During review | — | — |
| After verdict | `memory_save(content=findings)` | — |
| After pattern found | `memory_save(tags=["promote-to-knowledge"])` | — |
| After convention gap | `memory_save(content=gap_description)` | Flag for Knowledge Curator |

### Manager

| Phase | Memory Action | Knowledge Action |
|-------|--------------|------------------|
| Before assignment | `memory_search()` for dependencies | `knowledge_query()` for project context |
| After triage | `memory_save(content=triage_decision)` | — |
| After release | `memory_save(content=release_summary)` | `knowledge_import_folder()` for release docs |

---

## Anti-Patterns

- **Starting work without searching Memory** — you will duplicate or contradict
- **Starting work without querying Knowledge** — you will drift from the source of truth
- **Writing one-liners to Memory** — 3–10 sentences minimum, include WHY
- **Skipping Memory writes as an evaluator** — your findings are invisible to future rooms
- **Putting ephemeral work into Knowledge** — Knowledge is for canonical truth, not WIP
- **Putting canonical truth only in Memory** — it will get buried; promote to Knowledge
- **Announcing "I'm saving to memory"** — just do it silently as part of your workflow
- **Waiting until the end to save** — save after each deliverable, not in a batch

## Verification

When auditing brain-ops compliance:
1. Every worker's `done` message is preceded by `memory_save()` calls
2. Every evaluator's verdict is followed by a `memory_save()` call
3. Every agent's first action includes `memory_search()` + `knowledge_query()`
4. No agent answers questions that Knowledge could answer without checking first
5. Memories tagged `promote-to-knowledge` are reviewed in curation sessions
