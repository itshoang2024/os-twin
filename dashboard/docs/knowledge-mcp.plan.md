# Plan: Knowledge MCP — Graph-RAG over Imported Folders, Exposed via REST + MCP

> Created: 2026-04-19
> Status: draft
> Project: /Users/paulaan/PycharmProjects/agent-os/dashboard
> Author: opencode/architect (refactor authority granted)

## Config

working_dir: /Users/paulaan/PycharmProjects/agent-os/dashboard

---

## Goal

Stand up a **knowledge management service** inside the dashboard that:

1. **Imports** an arbitrary folder of documents (md, pdf, docx, xlsx, html, txt, …) into a **named namespace** as a **graph + vector** index, given an absolute folder path.
2. **Queries** that namespace for retrieval-augmented answers, supporting both raw chunk retrieval and multi-step graph-aware planning.
3. **Exposes** all operations through (a) a versioned REST API (`/api/knowledge/...`) for the dashboard frontend, and (b) a streamable-HTTP MCP endpoint (`/mcp`) so external agents (opencode, claude-desktop, custom clients) can call it as tools.

The current `dashboard/knowledge/` package is a broken extract from another project — every file imports from `app.core.graph.*`, `app.env`, `app.core.llm.dspy`, etc., none of which exist here. **Refactor authority has been explicitly granted** to restructure the entire package; this plan treats it as a green-field rewrite that *re-uses the algorithmic ideas* (Kuzu graph, ChromaDB vectors, MarkItDown parsing, multi-step query planning, PageRank-weighted retrieval) but discards the dead code and the `app.*` namespace.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  External MCP clients (opencode, claude-desktop, custom)        │
│  HTTP clients (dashboard frontend)                              │
└─────────────────┬───────────────────────────┬───────────────────┘
                  │                           │
                  │ streamable-HTTP           │ JSON / REST
                  ▼                           ▼
   ┌──────────────────────────┐  ┌──────────────────────────────┐
   │  /mcp  (FastMCP server)  │  │  /api/knowledge/*  (FastAPI) │
   │  • knowledge_import      │  │  • POST /namespaces/{ns}     │
   │  • knowledge_query       │  │  • POST /import              │
   │  • knowledge_list        │  │  • GET  /import/{job_id}     │
   │  • knowledge_get_graph   │  │  • POST /query               │
   │  • knowledge_delete      │  │  • GET  /graph               │
   └─────────────┬────────────┘  │  • DELETE /namespaces/{ns}   │
                 │               └────────────┬─────────────────┘
                 └───────────────┬────────────┘
                                 ▼
              ┌───────────────────────────────────────┐
              │  KnowledgeService (sync façade)       │
              │  • import_folder(ns, path) → job_id   │
              │  • get_job(job_id)                    │
              │  • query(ns, q, mode, top_k)          │
              │  • list_namespaces(), delete_ns(ns)   │
              │  • get_graph(ns)                      │
              └───────────────┬───────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   ┌─────────┐          ┌──────────┐          ┌──────────┐
   │ Ingest  │          │ Storage  │          │ Retrieval│
   │ Pipeline│          │  Layer   │          │  Engine  │
   └────┬────┘          └────┬─────┘          └────┬─────┘
        │                    │                     │
        ▼                    ▼                     ▼
   • MarkItDown            • KuzuDB (graph.db)   • Vector search (Chroma)
   • Chunker               • ChromaDB (chroma/)  • Graph expand (Kuzu)
   • Anthropic extractor   • manifest.json       • PageRank rerank
   • sentence-transformers • per-namespace dir   • Anthropic aggregator
                                                   (mode=summarized)

  Filesystem:
  ~/.ostwin/knowledge/
  └── {namespace}/
      ├── graph.db                  ← Kuzu single-file DB
      ├── vectors/                  ← zvec collection directory (was chroma/)
      ├── manifest.json             ← imports, files, jobs, stats
      └── jobs/                     ← job logs (one .jsonl per job)
```

### Architecture Decision Records (ADRs)

These resolve the open questions surfaced during exploration. Engineer MUST follow these unless an ADR is explicitly revised in a follow-up PR:

| # | Decision | Rationale | Implication |
|---|---|---|---|
| ADR-01 | Storage at `~/.ostwin/knowledge/{namespace}/` | Global, cross-plan reuse. Knowledge isn't owned by a single plan. | New env var `OSTWIN_KNOWLEDGE_DIR` overrides default. |
| ADR-02 | LLM = **Direct Anthropic SDK** | Avoid DSPy/litellm complexity; project already favors Claude. | New env var `ANTHROPIC_API_KEY` required. Fallback: graceful degradation when key missing → embedding-only mode (no graph extraction, but vector search still works). |
| ADR-03 | Embeddings = **sentence-transformers** with `BAAI/bge-small-en-v1.5` (384-dim) | No new heavy deps; offline-capable; matches existing zvec stack. | Configurable via `OSTWIN_KNOWLEDGE_EMBED_MODEL`. Kuzu `EMBEDDING_DIMENSION` = 384. |
| ADR-04 | Vector store = **zvec** (persistent local) — *revised 2026-04-19, originally ChromaDB* | chromadb in this env has a fragile dep on `opentelemetry` that breaks reliably; zvec is already in `requirements.txt`, used by `.agents/memory/agentic_memory/retrievers.py`, supports HNSW vector index + filterable string fields, and has fewer transitive deps. | Removes `chromadb` from requirements. zvec already pinned at `>=0.2.0`. Storage path becomes `~/.ostwin/knowledge/{namespace}/vectors/`. |
| ADR-05 | Graph store = **KuzuDB** (single .db file per namespace) | Existing knowledge code uses it; supports vector indexes natively; embedded (no server). | Adds `kuzu` to requirements. |
| ADR-06 | Document parsing = **MarkItDown** | Universal coverage (Office, HTML, PDF, etc.); MIT-licensed. | Adds `markitdown` to requirements. |
| ADR-07 | MCP transport = **Streamable-HTTP** mounted at `/mcp` | Modern MCP spec; opencode-compatible. | Use FastMCP from `mcp[cli]`. |
| ADR-08 | Background jobs = **In-process executor + manifest persistence** | No Redis/Celery dependency. Single dashboard process. | Limit: jobs lost on restart unless completed. Acceptable for MVP. |
| ADR-09 | **Drop** `mem0/`, `parsers/{docx,sheet,raw}.py`, `significance_analyzer.py` from the refactor | Dead code, unused, or replaceable by simpler logic for MVP. | Deletion happens in EPIC-001. |
| ADR-10 | **Drop** Vietnamese-locked prompts → parameterize language | Current prompts hardcoded for Vietnamese audit reports. | Default `language="English"`; namespace can declare its language. |
| ADR-11 | **Drop** DSPy → write thin Anthropic wrapper | Removes a large transitive-dep tree. | New module `dashboard/knowledge/llm.py` (~150 LOC). |
| ADR-12 | Namespace ID format = `^[a-z0-9][a-z0-9_-]{0,63}$` | Filesystem-safe, URL-safe, Kuzu-table-safe. | Validation enforced at API layer; rejected with 400. |
| ADR-14 | Image parsing via **MarkItDown's LLM-vision** path (added 2026-04-19) | MarkItDown 0.1.4 supports `MarkItDown(llm_client=anthropic_client, llm_model=...)` to OCR/describe images. Uses the configured Anthropic key. Free fallback (tesseract) deferred. | When `ANTHROPIC_API_KEY` unset, image files are walked but produce empty markdown — chunk count 0, logged as warning. `IMAGE_EXTENSIONS` now included in folder walk. |
| ADR-15 | **Knowledge runtime settings stored in `MasterSettings.knowledge` namespace** (added 2026-04-19) | Reuses existing `/api/settings` machinery (vault, broadcaster, persistence). Consistent with `runtime`, `memory`, `providers` namespaces. Settings override env-var defaults at `KnowledgeService` construction time. | New `KnowledgeSettings` Pydantic model: `llm_model: str`, `embedding_model: str`, `embedding_dimension: int` (read-only/derived from embedder). Surfaces at `GET/PUT /api/settings/knowledge`. |
| ADR-16 | **EPIC-005 partial scope shipped with EPIC-006** (added 2026-04-19) | User asked to skip ahead to MCP. We ship: (a) the `/api/settings/knowledge` endpoint (needed by the FE settings panel), (b) the FastMCP server with all 7 tools (the user-facing surface). The remaining 7 REST endpoints (CRUD on namespaces + import/jobs/query/graph) are deferred to a follow-up EPIC because MCP tools cover the same surface. | EPIC-005 marked PARTIAL; remaining endpoints become EPIC-005b (follow-up). EPIC-007 hardening updated to test what shipped only. |
| ADR-17 | **`SUPPORTED_DOCUMENT_EXTENSIONS` extended to include `IMAGE_EXTENSIONS`** (added 2026-04-19) | Single source-of-truth for "what gets walked"; ADR-14 already gates LLM-vision parsing per-file. | `dashboard/knowledge/config.py` updated; `Ingestor._walk_folder` filter unchanged in code (still uses `SUPPORTED_DOCUMENT_EXTENSIONS`) but the set now includes images. |

---

## Available Roles

- **@engineer** — Owns implementation. Writes production code, unit tests, integration tests. Must produce a "done report" after each EPIC summarizing what was built, what was deleted, what changed, and the manifest of files touched. Responsible for fixing QA failures.
- **@qa** — Owns verification. Independently runs the engineer's tests, performs additional black-box and integration checks, validates the API surface against this plan, measures performance, and produces a structured QA report (see "QA Report Template" below). Has authority to fail an EPIC.
- **@architect (reviewer — me)** — Reviews QA reports + engineer artifacts after every EPIC. Has authority to override QA verdicts (in either direction). Provides structured feedback when items must be fixed. Cannot write code.

---

## EPIC Lifecycle (Closed Loop)

Every EPIC uses this lifecycle:

```text
pending → @engineer → @qa → @architect ─┬─► passed → signoff → next EPIC
                ▲                       │
                └────── @engineer ◄─────┘ (on fail/changes-requested → fixing)
                                             │
                                             └─ max 3 fix cycles, then escalate to user
```

## Task Ownership Convention

Starting with EPIC-004, every task in an EPIC is tagged with its owner so there's never ambiguity about who does what:

- **`TASK-E-NNN`** — owned by **@engineer**. Implementation, including writing the engineer's own test suite as part of implementation.
- **`TASK-Q-NNN`** — owned by **@qa**. Independent verification, additional black-box probes, performance measurement, defect hunting. QA may add new test files in `dashboard/tests/` to verify a claim, but never modifies engineer's production code.
- **`CARRY-NNN`** — explicit carry-forward from a prior EPIC's review. Tagged `*(@engineer)*` or `*(@qa)*` to indicate ownership. Must be addressed FIRST in the receiving EPIC, before new work begins.

Each EPIC has:
- `### @engineer tasks (implementation)` — list of `TASK-E-NNN`
- `### @qa tasks (verification)` — list of `TASK-Q-NNN`
- `### Definition of Done (joint)` — both roles' deliverables must be satisfied
- `### Acceptance criteria` — each criterion annotated `*(verifier: @qa TASK-Q-NNN)*` so QA knows which probe validates which criterion
- `### QA Gate` — mandatory checks @qa must perform beyond their TASK-Q-NNN list

EPICs 001–003 (already complete at time of plan revision) use the older "single Tasks list" format; they're grandfathered.

**Transition rules:**

- `pending → @engineer` — manager spawns engineer with the EPIC brief and ADR list.
- `@engineer → @qa` — engineer posts a "done report" (template below). QA pulls fresh, reads report + diff, runs the verification checklist, posts a "QA report" (template below).
- `@qa → @architect` — automatic. Architect reads QA report + cross-checks against plan ADRs and acceptance criteria. Posts verdict: `passed`, `changes-requested`, or `escalate`.
- `@architect → @engineer (on changes-requested)` — architect's verdict includes a numbered list of specific fixes. Engineer addresses each one and re-submits to @qa.
- `@architect → user (on escalate)` — only after 3 fix cycles, or on architectural divergence (e.g., engineer wants to revise an ADR).

---

## Done Report Template (engineer → qa)

```markdown
## DONE: EPIC-NNN — <title>

### What I built
- bullet list of new modules / classes / endpoints

### What I deleted / refactored
- bullet list of files removed and reasons
- bullet list of refactored files and what changed

### Files touched
| Path | Action | Lines added | Lines removed |
| ... | new/modified/deleted | N | N |

### How to verify
```bash
# commands QA can run to see the work
pytest dashboard/tests/test_knowledge_<area>.py -v
python -c "from dashboard.knowledge import KnowledgeService; ..."
```

### Acceptance criteria self-check
- [x] criterion 1 — verified by `test_xxx.py::test_yyy`
- [x] criterion 2 — verified by `test_xxx.py::test_zzz`

### Open issues / known limits
- bullet list of things deferred to a later EPIC, with justification

### ADR compliance
- ADR-01: <how complied>
- ADR-XX: <how complied>
```

## QA Report Template (qa → architect)

```markdown
## QA REPORT: EPIC-NNN — <title>

### Verdict: PASS | FAIL | CHANGES-REQUESTED

### Test execution summary
| Suite | Pass | Fail | Skip | Coverage % |
| ... | N | N | N | NN.N |

### Acceptance criteria check
| # | Criterion | Status | Evidence |
| 1 | <criterion> | ✅ / ❌ | test_xxx.py::test_yyy / log line / curl output |

### ADR compliance check
| ADR | Status | Notes |
| ADR-01 | ✅ | confirmed via test_storage_path |
| ADR-02 | ⚠️ | no fallback path tested when ANTHROPIC_API_KEY unset |

### Black-box checks performed
- bullet list of additional tests QA ran beyond engineer's suite

### Performance measurements (if applicable)
| Operation | Sample | Latency p50 | p95 | Memory peak |
| import 100-doc folder | 100 files / 5 MB | ... | ... | ... |
| query (mode=raw) | top_k=10 | ... | ... | ... |
| query (mode=summarized) | top_k=10 | ... | ... | ... |

### Defects found
1. [SEVERITY] description — repro steps — file:line
2. ...

### Recommendation
- bullet list of suggested fixes / improvements
```

## Architect Review Template (architect → engineer | user)

```markdown
## REVIEW: EPIC-NNN — <title>

### Verdict: PASSED | CHANGES-REQUESTED | ESCALATED

### Cross-checks performed
- [ ] All ADRs honored
- [ ] No scope creep beyond EPIC's DoD
- [ ] Acceptance criteria objectively met (not gamed)
- [ ] Test coverage adequate for the EPIC's risk surface
- [ ] Public API surface matches plan
- [ ] No regressions in unrelated dashboard routes

### Specific items requiring fix (if any)
1. <file:line> — <what's wrong> — <expected fix>
2. ...

### Blockers for next EPIC
- list of things that must land before EPIC-(N+1) starts
```

---

## Cross-Cutting Concerns (apply to every EPIC)

| Concern | Standard |
|---|---|
| **Auth** | All `/api/knowledge/*` routes use `Depends(get_current_user)` (matches existing pattern in `routes/amem.py`). MCP endpoint uses MCP's own auth (or `Authorization: Bearer ${OSTWIN_API_KEY}` per ADR-13). |
| **Logging** | `logger = logging.getLogger(__name__)` — never `print`. INFO for state changes, DEBUG for chatter, ERROR for failures with stack trace. |
| **Path safety** | Reject any namespace not matching `^[a-z0-9][a-z0-9_-]{0,63}$`. Reject any folder path that doesn't exist or isn't readable. NEVER traverse outside the supplied folder during import. |
| **Error responses** | HTTPException with `detail` field. 400 for bad input, 404 for missing namespace, 409 for namespace exists, 422 for missing required field, 500 for internal. Include `error_code` for machine parsing. |
| **Config via env** | `OSTWIN_KNOWLEDGE_DIR`, `ANTHROPIC_API_KEY`, `OSTWIN_KNOWLEDGE_EMBED_MODEL`, `OSTWIN_KNOWLEDGE_LLM_MODEL`. Loaded from `~/.ostwin/.env` by existing `api.py` bootstrap. |
| **Lazy imports** | Heavy deps (`kuzu`, `chromadb`, `markitdown`, `sentence_transformers`) imported lazily inside functions, NOT at module top — matches dashboard's <2s boot-time target. |
| **Async vs sync** | Route handlers `async def`. KnowledgeService methods sync (called via `asyncio.to_thread()` from routes). Background jobs run on a `ThreadPoolExecutor`. |

ADR-13 added: MCP endpoint authenticates with `Authorization: Bearer ${OSTWIN_API_KEY}` (re-uses existing dashboard key). Anonymous access allowed only when `OSTWIN_DEV_MODE=1`.

---

## EPIC-001 — Refactor Knowledge Package (de-app-ify, strip dead code)

Roles: @engineer, @qa, @architect

Objective: Make `dashboard/knowledge/` a self-contained, importable Python package with zero `app.*` references and zero dead code. After this EPIC, `from dashboard.knowledge import KnowledgeService` must succeed in a fresh venv with the new requirements.

Lifecycle:
```text
pending → @engineer → @qa → @architect ─┬─► passed → EPIC-002
                ▲                       │
                └────── @engineer ◄─────┘ (on fail → fixing)
```

### Tasks
- [ ] TASK-001 — **Delete** dead code: `knowledge/graph/mem0/`, `knowledge/graph/parsers/{docx,sheet,raw}.py`, `knowledge/graph/core/significance_analyzer.py`, `knowledge/processing/document_router.py` (all ADR-09).
- [ ] TASK-002 — **Rename imports** throughout the package: `app.core.graph.*` → `dashboard.knowledge.*` (relative or absolute, engineer's choice but consistent).
- [ ] TASK-003 — **Replace** `from app._logging import ...` → standard `logging.getLogger(__name__)` everywhere.
- [ ] TASK-004 — **Create** `dashboard/knowledge/config.py` exposing the env-var-backed constants previously in `app.env`: `KNOWLEDGE_DIR`, `EMBEDDING_DIMENSION` (default 384), `EMBEDDING_MODEL` (default `BAAI/bge-small-en-v1.5`), `LLM_MODEL` (default `claude-sonnet-4-5-20251022`), `PAGERANK_SCORE_THRESHOLD` (default 0.001), `KUZU_MIGRATE` (default True). Resolves `KUZU_DATABASE_PATH` and `CHROMA_PERSIST_DIRECTORY` from `KNOWLEDGE_DIR/{namespace}/`.
- [ ] TASK-005 — **Create** `dashboard/knowledge/llm.py` — thin Anthropic wrapper exposing: `extract_entities(text, language) -> list[dict]`, `plan_query(query, knowledge_summary, max_steps) -> list[step_dict]`, `aggregate_answers(community_summaries, query) -> str`. Internally uses `anthropic.Anthropic(api_key=...)`. Graceful no-op when `ANTHROPIC_API_KEY` unset (returns `[]` for extract; returns single-step plan for plan_query; returns concatenation for aggregate).
- [ ] TASK-006 — **Create** `dashboard/knowledge/embeddings.py` — sentence-transformers wrapper exposing: `embed(texts: list[str]) -> list[list[float]]`, `embed_one(text: str) -> list[float]`, `dimension() -> int`. Lazy-loads model on first use; module instance cached.
- [ ] TASK-007 — **Replace** `from app.core.llm.dspy import DspyModel` everywhere → `from dashboard.knowledge.llm import KnowledgeLLM`. Adapt callsites to the new API surface.
- [ ] TASK-008 — **Replace** `get_default_embedding_model(...)` calls in `kuzudb.py`, `graph_rag_extractor.py`, `track_vector_retriever.py` → `KnowledgeEmbedder().embed(...)`.
- [ ] TASK-009 — **Stub or replace** all remaining missing imports: `app.core.database.local_database.local_db` (drop), `app.core.caching.cache_manager.cache_result` (replace with `functools.lru_cache` or remove), `app.core.extraction.file_extraction.FileExtraction` (replace with direct `markitdown.MarkItDown` calls), `app.services.setting.SettingService` (drop — pull settings from `config.py`), `app.middlewares.folder.FolderMiddleware` (drop — namespace info passed through), `app.i18n.translator` (replace with `language` parameter), `app.utils.file_helper.FileHelper` (replace with `pathlib`/`json`), `app.utils.constant.IMAGE_EXTENSIONS` and `SUPPORTED_DOCUMENT_EXTENSIONS` (move to `config.py`), `app.utils.coro.run_async_in_thread` (replace with `asyncio.run` in a thread or drop).
- [ ] TASK-010 — **Update** `dashboard/knowledge/__init__.py` to export the public surface that EPIC-002+ will use: `KnowledgeService` (placeholder class for now — implemented in EPIC-002), `KnowledgeLLM`, `KnowledgeEmbedder`, plus existing `KuzuLabelledPropertyGraph`, `RAGStorage`, `GraphRAGExtractor`, `GraphRAGQueryEngine`. NOT exported: anything in `mem0/`, the deleted parsers, `significance_analyzer`.
- [ ] TASK-011 — **Update** `dashboard/requirements.txt` to add: `kuzu>=0.6,<1.0`, `chromadb>=0.5,<1.0`, `markitdown>=0.0.1`, `anthropic>=0.40`, `networkx>=3.0`, `pyyaml`, `tenacity`. (sentence-transformers, fastapi, etc. already present.)
- [ ] TASK-012 — Write a **smoke test** at `dashboard/tests/test_knowledge_smoke.py` that simply imports the package and verifies symbols are importable. NO functional tests yet — just clean imports.
- [ ] TASK-013 — Delete or rename pycache and `.DS_Store` files in `knowledge/`.

### Definition of Done
- [ ] `python -c "from dashboard.knowledge import KnowledgeService, KnowledgeLLM, KnowledgeEmbedder, KuzuLabelledPropertyGraph, RAGStorage, GraphRAGExtractor, GraphRAGQueryEngine"` succeeds with no errors.
- [ ] `pytest dashboard/tests/test_knowledge_smoke.py -v` passes (≥5 tests checking importability).
- [ ] `grep -r "from app\." dashboard/knowledge/` returns **zero** matches.
- [ ] `grep -r "import app\." dashboard/knowledge/` returns **zero** matches.
- [ ] `dashboard/knowledge/mem0/`, `dashboard/knowledge/processing/`, `dashboard/knowledge/graph/parsers/{docx,sheet,raw}.py`, `dashboard/knowledge/graph/core/significance_analyzer.py` no longer exist.
- [ ] `dashboard/knowledge/config.py`, `dashboard/knowledge/llm.py`, `dashboard/knowledge/embeddings.py` exist with the documented APIs.
- [ ] `dashboard/requirements.txt` updated and `pip install -r dashboard/requirements.txt` succeeds in a fresh venv.

### Acceptance criteria
- [ ] No file in `dashboard/knowledge/` references `app.*`.
- [ ] No `import dspy` anywhere in the codebase (except possibly transitively, but our code doesn't call DSPy).
- [ ] `dashboard/knowledge/__init__.py` exports the documented public symbols and only those.
- [ ] Smoke test imports complete in <3 seconds (measured) — confirms lazy-loading is in place.
- [ ] All deleted modules verified gone via `git status`.
- [ ] Engineer's done report enumerates every file deleted with a one-line justification each.

### QA Gate (architect-mandated checks beyond engineer's tests)
1. Run `pytest dashboard/tests/ -k "not knowledge" --no-header -q` — confirm **zero** regressions in unrelated dashboard tests.
2. `python -X importtime -c "import dashboard.knowledge" 2>&1 | tail -20` — confirm none of `kuzu`, `chromadb`, `sentence_transformers`, `markitdown`, `anthropic` are imported at module load.
3. Run `pip-compile` or `pip install --dry-run -r dashboard/requirements.txt` to confirm dependency resolution.
4. Confirm the `KnowledgeService` placeholder raises `NotImplementedError` when constructed (so EPIC-002 has something to fill in, not silent broken behavior).

depends_on: []

---

## EPIC-002 — Storage Layer & Namespace Lifecycle

Roles: @engineer, @qa, @architect

Objective: Build the per-namespace storage layout (Kuzu file + Chroma dir + manifest) and the `NamespaceManager` that creates / lists / deletes namespaces atomically.

Lifecycle:
```text
pending → @engineer → @qa → @architect ─┬─► passed → EPIC-003
                ▲                       │
                └────── @engineer ◄─────┘ (on fail → fixing)
```

### Tasks
- [ ] TASK-001 — Create `dashboard/knowledge/namespace.py` with `NamespaceManager` class. Methods: `create(namespace, language="English", description=None) -> NamespaceMeta`, `get(namespace) -> NamespaceMeta | None`, `list() -> list[NamespaceMeta]`, `delete(namespace) -> bool`, `validate_id(namespace) -> bool` (regex check), `path_for(namespace) -> Path`.
- [ ] TASK-002 — Define `NamespaceMeta` Pydantic model: `name: str`, `created_at: datetime`, `updated_at: datetime`, `language: str`, `description: str | None`, `stats: dict (files_indexed, entities, relations, vectors)`, `imports: list[ImportRecord]`.
- [ ] TASK-003 — Define `manifest.json` schema (NamespaceMeta serialized). Add `_schema_version: int = 1` field for future migrations.
- [ ] TASK-004 — Implement atomic write: `manifest.json.tmp` → `os.rename` → `manifest.json` so crashes don't corrupt.
- [ ] TASK-005 — Implement `delete()` that removes the entire `~/.ostwin/knowledge/{namespace}/` tree and tears down any cached Kuzu connection (use `KuzuLabelledPropertyGraph.close_all_connections()`).
- [ ] TASK-006 — Wire `KuzuLabelledPropertyGraph.database_path` to `KNOWLEDGE_DIR/{namespace}/graph.db` (note: kuzudb.py currently treats the path as a directory and appends `{index}.db` — refactor so that one namespace = one file at the EXACT path).
- [ ] TASK-007 — Wire `init_vector_store(...)` (in `storage.py`) to use `KNOWLEDGE_DIR/{namespace}/chroma/` as `persist_directory`.
- [ ] TASK-008 — Implement `KnowledgeService` (replace EPIC-001 placeholder). Constructor: `KnowledgeService(namespace_manager: NamespaceManager | None = None)`. Methods stubbed for now: `import_folder(...)` and `query(...)` raise `NotImplementedError("EPIC-003"/"EPIC-004")`; the rest are wired to `NamespaceManager`.
- [ ] TASK-009 — Write tests at `dashboard/tests/test_knowledge_namespace.py` covering: create-success, create-duplicate-409, create-invalid-name-400, list, get-missing, delete-success, delete-missing, delete-cleans-disk, manifest-roundtrip, atomic-write-survives-crash (use `monkeypatch` to inject a failing `os.rename`).

### Definition of Done
- [ ] `NamespaceManager` and `KnowledgeService` exist with documented API.
- [ ] `manifest.json` schema documented in a docstring with example.
- [ ] All tests pass; coverage of `namespace.py` ≥ 90%.
- [ ] `dashboard/tests/test_knowledge_smoke.py` extended to cover `KnowledgeService` instantiation.
- [ ] On `delete()`, no Kuzu file handles remain open (verified by re-creating a namespace with the same name immediately after).

### Acceptance criteria
- [ ] `NamespaceManager().create("test-ns")` produces `~/.ostwin/knowledge/test-ns/{graph.db,chroma/,manifest.json,jobs/}` (jobs/ may be lazily created in EPIC-003).
- [ ] `NamespaceManager().create("Bad Name!")` raises `ValueError` (caught by API layer → 400).
- [ ] `NamespaceManager().delete("test-ns")` returns True and the directory is gone.
- [ ] Manifest survives a process restart (load round-trip).
- [ ] Two different namespaces are fully isolated — entities in `ns_a` not retrievable from `ns_b`.

### QA Gate
1. Run `python -c "from dashboard.knowledge.namespace import NamespaceManager; nm = NamespaceManager(); nm.create('qa-test'); print(nm.list()); nm.delete('qa-test')"` and confirm filesystem state matches expectation at each step.
2. Verify `OSTWIN_KNOWLEDGE_DIR=/tmp/qa-knowledge python -m pytest dashboard/tests/test_knowledge_namespace.py -v` works (env override honored).
3. Verify `pagerank_score_threshold` and other config defaults documented.
4. Concurrent-create race: spawn 5 threads each calling `create("same")` — only one succeeds, rest get 409-equivalent.

depends_on: [EPIC-001]

---

## EPIC-003 — Ingestion Pipeline (folder → graph + vectors)

Roles: @engineer, @qa, @architect

Objective: Implement `KnowledgeService.import_folder(namespace, folder_path)` end-to-end. Walk the folder, parse each supported file with MarkItDown, chunk the markdown, extract entities+relations via Anthropic, embed chunks + entities, and write everything into the namespace's Kuzu + Chroma stores. Track progress via a job system.

Lifecycle:
```text
pending → @engineer → @qa → @architect ─┬─► passed → EPIC-004
                ▲                       │
                └────── @engineer ◄─────┘ (on fail → fixing)
```

### Tasks
- [ ] TASK-001 — Create `dashboard/knowledge/ingestion.py` with `Ingestor` class: `ingest(namespace, folder_path, options) -> Generator[ProgressEvent]`. Yields events as files are processed.
- [ ] TASK-002 — Implement `_walk_folder(folder_path, options) -> list[FileEntry]`. Filters by extension (use `SUPPORTED_DOCUMENT_EXTENSIONS` from config). Skips hidden files, files >50 MB by default (configurable). Returns absolute paths.
- [ ] TASK-003 — Implement `_parse_file(path) -> list[Document]` using MarkItDown. Falls back to plain-text read for unsupported types. Chunk with target chunk size 1024 chars, 200 overlap (configurable). Each Document carries metadata: `file_path`, `filename`, `mime_type`, `chunk_index`, `total_chunks`, `file_size`, `mtime`.
- [ ] TASK-004 — Implement `_extract_entities(doc) -> tuple[list[entity_dict], list[relation_dict]]` using `KnowledgeLLM.extract_entities`. Adapt prompts in `knowledge/graph/prompt.py` — keep the JSON-output format but parameterize language. When no API key, returns `([], [])`.
- [ ] TASK-005 — Implement `_embed_and_store(doc, entities, relations, namespace)` — embed chunk text + entity descriptions in batch, write nodes + edges to Kuzu, write chunk vectors to Chroma. Use `KuzuLabelledPropertyGraph.add_nodes` (batch) and Chroma `add` (batch).
- [ ] TASK-006 — Create `dashboard/knowledge/jobs.py` with `JobManager`: `submit(fn, *args, **kwargs) -> job_id`, `get(job_id) -> JobStatus`, `list_for_namespace(namespace) -> list[JobStatus]`, `cancel(job_id) -> bool`. Backed by `concurrent.futures.ThreadPoolExecutor(max_workers=2)` and a thread-safe in-memory dict. Status persisted to `{namespace}/jobs/{job_id}.jsonl` (append-only event log).
- [ ] TASK-007 — Wire `KnowledgeService.import_folder(namespace, folder_path, options=None) -> str` to call `JobManager.submit(Ingestor().ingest, namespace, folder_path, options)`. Returns job_id immediately.
- [ ] TASK-008 — Add `KnowledgeService.get_job(job_id) -> JobStatus` and `KnowledgeService.list_jobs(namespace)`.
- [ ] TASK-009 — On job completion, append `ImportRecord` (folder_path, file_count, started_at, finished_at, status, errors) to namespace manifest.
- [ ] TASK-010 — Idempotency: each file's content gets a content-hash; re-importing the same file skips it unless `--force`. Hash stored in chunk metadata.
- [ ] TASK-011 — Error handling: per-file errors are logged + accumulated in job status; one bad file does NOT fail the whole import.
- [ ] TASK-012 — Tests at `dashboard/tests/test_knowledge_ingestion.py`:
  - Walk folder with mixed extensions; verify expected files picked up.
  - Walk folder with hidden files / >50MB / unsupported; verify exclusions.
  - Parse a sample md / txt / json file; verify chunking produces ≥1 Document.
  - With `ANTHROPIC_API_KEY` UNSET: import folder; verify chunks indexed in Chroma but no entities in Kuzu (graceful degradation).
  - With Anthropic mocked (returning fixed entities): import folder; verify Kuzu contains expected entities + relations.
  - Job lifecycle: submit → poll status → completion; status transitions through `pending → running → completed`.
  - Idempotency: import same folder twice; second import skips files (verified by chunk count not doubling).
  - Error injection: corrupt file in folder; verify it's logged but other files complete.
- [ ] TASK-013 — Sample test fixtures: create `dashboard/tests/fixtures/knowledge_sample/` with 5–10 small docs (md, txt, html, json — committed to repo, no binary).

### Definition of Done
- [ ] Importing the fixture folder produces a populated namespace (≥10 chunks in Chroma, ≥1 entity in Kuzu when Anthropic available).
- [ ] All ingestion tests pass; coverage of `ingestion.py` and `jobs.py` ≥ 80%.
- [ ] Job status survives multiple status polls (no race conditions).
- [ ] `import_folder` returns within 100ms (work happens in background).
- [ ] Re-importing same folder is a no-op (verified).
- [ ] Manifest reflects every import event.

### Acceptance criteria
- [ ] `KnowledgeService.import_folder("test-ns", "/abs/path/to/fixture/folder")` returns a job_id string.
- [ ] `KnowledgeService.get_job(job_id).status` transitions `pending → running → completed`.
- [ ] On completion, `KnowledgeService.list_namespaces()[0].stats.files_indexed >= 5`.
- [ ] Importing a non-existent folder raises `FileNotFoundError` (translated to 400 at API layer in EPIC-005).
- [ ] Importing into a non-existent namespace creates it on the fly (or returns 404 — engineer chooses; documents the choice).
- [ ] Per-file errors recorded in `JobStatus.errors[]` not raised.
- [ ] No file >50 MB ever attempted (configurable cap).

### QA Gate
1. Import a real folder of mixed-format documents (QA picks 30+ files from somewhere on their machine, e.g., `~/Documents/some-project`). Confirm completion within reasonable time (target: <2 min for 100 small files with no LLM, <10 min with Anthropic).
2. Verify graceful degradation: unset `ANTHROPIC_API_KEY`, run an import, confirm vector search still works (entities just absent).
3. Cancel an in-flight job — verify partial state doesn't corrupt namespace.
4. Run two concurrent imports into different namespaces — confirm no cross-contamination, no Kuzu lock conflicts.
5. Memory measurement: import 500 small docs, confirm peak RSS < 2 GB.
6. Verify rentrancy: kill the dashboard mid-import; on restart, the manifest reflects the last completed file but the running job is marked `interrupted`.

depends_on: [EPIC-002]

---

## EPIC-004 — Query Engine (retrieval, graph expansion, optional LLM aggregation)

Roles: @engineer, @qa, @architect

Objective: Implement `KnowledgeService.query(namespace, query, mode, top_k, threshold)` returning ranked, cited results. Three modes: `raw` (vector hits only), `graph` (vector + graph neighbours, ranked by PageRank), `summarized` (LLM-aggregated answer with citations). Also fix EPIC-003 carry-forward (ZVEC-LIVE-1) by centralizing the per-namespace store cache in `KnowledgeService`.

Lifecycle:
```text
pending → @engineer → @qa → @architect ─┬─► passed → EPIC-005
                ▲                       │
                └────── @engineer ◄─────┘ (on changes-requested → fixing)
```

### EPIC-003 carry-forward (must be first work in this EPIC)

The architect's EPIC-003 review surfaced **ZVEC-LIVE-1**: opening a fresh `NamespaceVectorStore` to the same path while another instance is alive in the same process fails. This blocks the query engine if not addressed before TASK-E-001.

- [ ] **CARRY-001** *(@engineer)* — Centralize the vector-store cache in `KnowledgeService`. Add `_vector_stores: dict[str, NamespaceVectorStore]`, `_kuzu_graphs: dict[str, KuzuLabelledPropertyGraph]`, and `_query_engines: dict[str, KnowledgeQueryEngine]` instance dicts protected by `self._cache_lock = threading.RLock()`. Add `get_vector_store(ns)` and `get_kuzu_graph(ns)` getters. Both `Ingestor` and the query path MUST go through these getters.
- [ ] **CARRY-002** *(@engineer)* — Tighten `NamespaceVectorStore._open_or_create`: use `path.exists() and any(path.iterdir())` to decide between "open existing" vs "create fresh". On open-failure of an existing collection, re-raise instead of falling through to `create_and_open` (which would silently mask the real error).
- [ ] **CARRY-003** *(@engineer)* — Add `NamespaceVectorStore.close()` and call it from a new `KnowledgeService.shutdown()` method. Also evict from `_vector_stores`/`_kuzu_graphs`/`_query_engines` in `delete_namespace(ns)` BEFORE removing the directory.
- [ ] **CARRY-004** *(@engineer)* — Update `Ingestor.__init__` to accept `vector_store_factory` and `kuzu_factory` callables. `KnowledgeService` injects `self.get_vector_store` and `self.get_kuzu_graph` so the Ingestor reuses the central cache.
- [ ] **CARRY-005** *(@qa)* — Verify CARRY-001..004 with an explicit probe: ingest into namespace `X`, then immediately call `service.query("X", ...)` from a different thread. No `path validate failed`, no deadlock, no data corruption.

### @engineer tasks (implementation)

- [ ] **TASK-E-001** — Create `dashboard/knowledge/query.py` with the `KnowledgeQueryEngine` class. Constructor takes pre-built `vector_store`, `kuzu_graph`, `embedder`, `llm` (no DB construction inside the engine — the cache supplies these).
- [ ] **TASK-E-002** — Define Pydantic models in `dashboard/knowledge/query.py`: `QueryResult` (`query, mode, namespace, chunks: list[ChunkHit], entities: list[EntityHit], answer: str | None, citations: list[Citation], latency_ms: int, warnings: list[str]`); `ChunkHit` (`text, score, file_path, filename, chunk_index, total_chunks, file_hash, mime_type, category_id`); `EntityHit` (`id, name, label, score, description, category_id`); `Citation` (`file, page: int | None, chunk_index, snippet_id`).
- [ ] **TASK-E-003** — Implement `mode="raw"`: embed query → `NamespaceVectorStore.search(q_embed, top_k, category_id)` → filter by `threshold` → return as `ChunkHit[]` + `Citation[]`. No graph touched. No LLM touched.
- [ ] **TASK-E-004** — Implement `mode="graph"`: do `mode="raw"` first, THEN call `KuzuLabelledPropertyGraph.get_all_nodes(label_type="entity", category_id=category)` + `pagerank(personalize_dict)` to add `entities: list[EntityHit]`. When Kuzu has no entities (e.g., LLM was unavailable during ingest), return chunks-only and append `"no_graph_data"` to `warnings`.
- [ ] **TASK-E-005** — Implement `mode="summarized"`: do `mode="graph"` first, THEN call `KnowledgeLLM.aggregate_answers(community_summaries=[h.text for h in hits], query)` to produce `answer`. When `KnowledgeLLM.is_available()` is False: append `"llm_unavailable"` to `warnings`, leave `answer=None`, still return chunks+entities. NO crash on missing API key.
- [ ] **TASK-E-006** — Refactor (or delete + re-derive) `dashboard/knowledge/graph/core/graph_rag_query_engine.py` to be no-op or deleted. The new `KnowledgeQueryEngine` is the canonical entry point — the legacy file's complex multi-step planner can be deferred to a future EPIC if real-world quality demands it.
- [ ] **TASK-E-007** — Wire `KnowledgeService.query(...)` and `KnowledgeService.get_graph(...)`: replace the EPIC-003 `NotImplementedError` placeholders. Cache `KnowledgeQueryEngine` per namespace via `_get_query_engine(ns)`. Validate `mode in ("raw", "graph", "summarized")` (else `ValueError`). Validate namespace exists (else `NamespaceNotFoundError`).
- [ ] **TASK-E-008** — Implement `KnowledgeQueryEngine.get_graph(limit=200) -> dict`. Returns `{"nodes": [...], "edges": [...], "stats": {"node_count": N, "edge_count": M}}`. Filter edges to only those whose endpoints are in the returned node set. Cap at `limit` nodes.
- [ ] **TASK-E-009** — Update `dashboard/knowledge/__init__.py` to export `KnowledgeQueryEngine`, `QueryResult`, `ChunkHit`, `EntityHit`, `Citation`. Add to `__all__`.
- [ ] **TASK-E-010** — Write engineer's test suite at `dashboard/tests/test_knowledge_query.py` covering ALL acceptance criteria with test fixtures. Use `TestClass` grouping (`TestRawMode`, `TestGraphMode`, `TestSummarizedMode`, `TestErrorPaths`, `TestGetGraph`, `TestCacheBehaviour`, `TestServiceShutdown`). Aim for ~25 tests; coverage of `query.py` ≥ 80%. Tests use real `KnowledgeEmbedder` (cached after first download) + `KnowledgeLLM(api_key=None)` for graceful-degradation paths and `monkeypatch` for LLM-available paths.
- [ ] **TASK-E-011** — Engineer benchmark: include a `tests/bench_knowledge_query.py` (not a pytest test — a script) that runs 100 queries and records p50/p95/max for each mode. Output as a markdown table in the done report.
- [ ] **TASK-E-012** — Write done report at `dashboard/docs/done-reports/EPIC-004-engineer.md` per the template, including the CARRY-001..004 verification, the benchmark table, and a confirmation that `python -X importtime -c "from dashboard.knowledge.query import KnowledgeQueryEngine"` does NOT load `kuzu`/`zvec`/`sentence_transformers`/`anthropic`.

### @qa tasks (verification)

- [ ] **TASK-Q-001** — Re-verify every engineer DoD bullet by re-running the listed commands from a fresh shell. Record any deviation between engineer-claimed output and your-observed output.
- [ ] **TASK-Q-002** — Acceptance-criteria check (table format, one row per criterion, with evidence): `mode=raw top_k=5` returns ≤5 hits; `mode=graph` returns ≥1 entity when Kuzu populated; `mode=summarized` returns non-empty answer with Anthropic; citations point at real files; `latency_ms` populated on every result.
- [ ] **TASK-Q-003** — Independent retrieval-quality probe: hand-build a namespace with 3 docs of known content, query for facts unique to each, verify the right doc ranks #1. Document any obvious-wrong-answer case as a defect.
- [ ] **TASK-Q-004** — Determinism probe: run the same query 5× in `mode=raw`. Assert `chunks` are identical across runs (vector search is deterministic).
- [ ] **TASK-Q-005** — Read-during-write probe: spawn a long ingestion in one thread, fire 10 queries from another thread. No crash, no `path validate failed`, no Kuzu lock errors. (Closes ZVEC-LIVE-1 carry-forward.)
- [ ] **TASK-Q-006** — Empty-result probe: query an empty namespace → returns empty `chunks`/`entities`, status valid, no exception.
- [ ] **TASK-Q-007** — `get_graph(limit=200)` cap probe: pre-populate >200 entities (mocked LLM with many returns), call `get_graph(limit=200)`, assert `len(result["nodes"]) <= 200`.
- [ ] **TASK-Q-008** — Cache-eviction probe: ingest into ns `X`, query, then `delete_namespace("X")`, then `create_namespace("X")`, then query again — must return empty (not stale). This catches cache-eviction bugs.
- [ ] **TASK-Q-009** — Concurrent-query probe: 10 simultaneous `query()` calls via `ThreadPoolExecutor`, all complete, no deadlock, results structurally valid. Measure wall time.
- [ ] **TASK-Q-010** — Performance budget check: `mode=raw` p95 < 500ms on a 50-chunk namespace. Run engineer's benchmark independently. If engineer's benchmark shows ≥500ms, mark CHANGES-REQUESTED.
- [ ] **TASK-Q-011** — Lazy-import audit: `python -X importtime -c "from dashboard.knowledge.query import KnowledgeQueryEngine"` MUST NOT contain ` zvec$`, ` kuzu$`, ` sentence_transformers$`, ` anthropic$`. Same check for `from dashboard.knowledge import KnowledgeService`.
- [ ] **TASK-Q-012** — Regression sweep: `pytest dashboard/tests/ -k "not knowledge"` MUST show 568 passed. Any drop = hard fail.
- [ ] **TASK-Q-013** — All previous-EPIC test suites still green: `pytest dashboard/tests/test_knowledge_smoke.py tests/test_knowledge_namespace.py tests/test_knowledge_ingestion.py -q` — same pass count as end of EPIC-003.
- [ ] **TASK-Q-014** — `KnowledgeService.shutdown()` releases handles probe: instantiate service, ingest, query, shutdown, then assert `service._vector_stores == {}` and `service._kuzu_graphs == {}` and re-instantiation works without "path is existed" errors.
- [ ] **TASK-Q-015** — `mode="summarized"` with `monkeypatch` of `KnowledgeLLM.is_available → True` and `aggregate_answers → "fixed string"` returns the fixed string in `answer`. Without the patch, returns `answer=None` and `warnings` includes `"llm_unavailable"`.
- [ ] **TASK-Q-016** — Write QA report at `dashboard/docs/qa-reports/EPIC-004-qa.md` per the template, with verdict PASS/FAIL/CHANGES-REQUESTED, defect counts by severity, and a recommendation to architect.

### Definition of Done (joint — both roles must satisfy)

- [ ] All three query modes implemented (TASK-E-003..005).
- [ ] `get_graph()` returns valid graph data (TASK-E-008).
- [ ] All query tests pass; coverage of `query.py` ≥ 80%.
- [ ] Concurrent queries against same namespace don't deadlock (TASK-Q-009).
- [ ] CARRY-001..004 fully addressed; ZVEC-LIVE-1 cannot be reproduced (TASK-Q-005, TASK-Q-014).
- [ ] No regressions: 568 baseline preserved (TASK-Q-012).

### Acceptance criteria (joint — both roles validate)

- [ ] `query("ns", "test", mode="raw", top_k=5)` returns ≤5 chunks with scores ≥ threshold. *(verifier: @qa TASK-Q-002)*
- [ ] `query("ns", "test", mode="graph")` returns chunks + at least one entity for a populated namespace (with mocked LLM during ingest). *(verifier: @qa TASK-Q-002)*
- [ ] `query("ns", "test", mode="summarized")` returns a non-empty `answer` when Anthropic is available. *(verifier: @qa TASK-Q-015)*
- [ ] Citations in `summarized` mode reference real file paths from the imported docs. *(verifier: @qa TASK-Q-002)*
- [ ] All queries record `latency_ms` in the result. *(verifier: @qa TASK-Q-002)*
- [ ] Engineer's done report includes a benchmark table showing p50/p95 latency per mode (TASK-E-011).
- [ ] No silent regressions in earlier EPICs (TASK-Q-013).

### QA Gate (additional black-box probes for @qa)

These are MANDATORY beyond TASK-Q-001..015 and must be in the QA report:

1. **Manual quality probe** — query a hand-built 3-doc namespace; the most-relevant doc must rank #1 for queries about its unique content.
2. **Determinism** — `mode=raw` produces identical chunks across 5 runs.
3. **Read-during-write** — query during concurrent ingest; no crash.
4. **No-match query** — empty result, not exception.
5. **`get_graph` limit honored**.

depends_on: [EPIC-003]

---

## EPIC-005 — REST API (`/api/knowledge/*`)

Roles: @engineer, @qa, @architect

Objective: Expose the full `KnowledgeService` surface as a versioned REST API following the dashboard's existing patterns (`routes/amem.py`, `routes/files.py`). All routes auth-protected.

Lifecycle:
```text
pending → @engineer → @qa → @architect ─┬─► passed → EPIC-006
                ▲                       │
                └────── @engineer ◄─────┘ (on fail → fixing)
```

### @engineer tasks (implementation)

- [ ] **TASK-E-001** — Create `dashboard/routes/knowledge.py` with `router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])`. Module-level `_get_service()` lazy-instantiates a singleton `KnowledgeService` so route registration stays cheap.
- [ ] **TASK-E-002** — Implement the 9 endpoints (all `async def`, all `Depends(get_current_user)`):
  - `GET /namespaces` → `list[NamespaceMeta]`
  - `POST /namespaces` body `{name, language?, description?}` → `NamespaceMeta` (status 201)
  - `GET /namespaces/{namespace}` → `NamespaceMeta`
  - `DELETE /namespaces/{namespace}` → `{deleted: bool}`
  - `POST /namespaces/{namespace}/import` body `{folder_path: str, options?: {chunk_size?, force?, max_file_size_mb?, extract_entities?}}` → `{job_id: str}`
  - `GET /namespaces/{namespace}/jobs` → `list[JobStatus]`
  - `GET /namespaces/{namespace}/jobs/{job_id}` → `JobStatus`
  - `POST /namespaces/{namespace}/query` body `{query: str, mode?: "raw"|"graph"|"summarized", top_k?, threshold?, category?}` → `QueryResult`
  - `GET /namespaces/{namespace}/graph?limit=200` → `GraphData`
- [ ] **TASK-E-003** — Define request/response Pydantic models in `dashboard/routes/knowledge_models.py` (separate file). All response models reuse the EPIC-002/003/004 types (`NamespaceMeta`, `JobStatus`, `QueryResult`) directly — no duplicate definitions.
- [ ] **TASK-E-004** — Implement error mapping in route handlers (use a small `_map_error(exc) -> HTTPException` helper):
  - `InvalidNamespaceIdError` → 400 with `error_code: "INVALID_NAMESPACE_ID"`
  - `ValueError` (other) → 400 with `error_code: "BAD_REQUEST"`
  - `NamespaceNotFoundError` → 404 with `error_code: "NAMESPACE_NOT_FOUND"`
  - `NamespaceExistsError` → 409 with `error_code: "NAMESPACE_EXISTS"`
  - `FileNotFoundError` (folder) → 400 with `error_code: "FOLDER_NOT_FOUND"`
  - `NotADirectoryError` → 400 with `error_code: "NOT_A_DIRECTORY"`
  - Internal exceptions → 500 with `error_code: "INTERNAL_ERROR"` and a logged stack trace.
- [ ] **TASK-E-005** — Register router in `dashboard/api.py`: add `knowledge` to the import tuple at line ~57 and `app.include_router(knowledge.router)` after `amem.router` at line ~158.
- [ ] **TASK-E-006** — Async wrapping: route handlers wrap sync `KnowledgeService` calls with `await asyncio.to_thread(service.method, ...)`. EXCEPT: `import_folder` is fast (returns job_id within 100ms) — call it synchronously to keep the response simple.
- [ ] **TASK-E-007** — Path-safety validation in `import_folder` route: verify `folder_path` is absolute (`Path(p).is_absolute()`), exists, is a directory, and is not under `/etc`, `/sys`, `/proc`, or other system paths. Reject with 400 + `error_code: "INVALID_FOLDER_PATH"` otherwise.
- [ ] **TASK-E-008** — OpenAPI documentation: each endpoint has a docstring + `responses={...}` with documented status codes, request/response examples in the schema.
- [ ] **TASK-E-009** — Engineer's test suite at `dashboard/tests/test_knowledge_api.py`. Use `TestClient(app)` pattern from `test_amem_api.py`. Test classes: `TestNamespacesAPI`, `TestImportAPI`, `TestJobsAPI`, `TestQueryAPI`, `TestGraphAPI`, `TestErrorMapping`, `TestAuth`. Cover all happy paths, 4xx errors per `error_code`, auth-required negative tests, response-shape assertions. ~30 tests; coverage of `routes/knowledge.py` ≥ 90%.
- [ ] **TASK-E-010** — Done report at `dashboard/docs/done-reports/EPIC-005-engineer.md` per template, including a curl walkthrough sample and the OpenAPI snippet.

### @qa tasks (verification)

- [ ] **TASK-Q-001** — Re-run engineer's test suite from a fresh shell. Record any deviation.
- [ ] **TASK-Q-002** — End-to-end curl walkthrough: `create namespace → import folder → poll job → query → get_graph → delete namespace`. Document exact commands in QA report. Each step must succeed and produce a valid response shape.
- [ ] **TASK-Q-003** — Auth-bypass sweep: for every endpoint, send a request WITHOUT any auth header. Every response must be 401 (not 200, not 500). Document which endpoints accidentally allow anonymous access (these are CRITICAL defects).
- [ ] **TASK-Q-004** — Path-injection sweep: try `namespace=../etc`, `namespace=foo/../bar`, `folder_path=../../etc`, `folder_path=/etc/shadow`, `folder_path=` (empty), `folder_path=relative/path`. All must be rejected with 400 + appropriate `error_code`.
- [ ] **TASK-Q-005** — Concurrent-query load: 50 simultaneous `POST /namespaces/{ns}/query` via `ThreadPoolExecutor` or `ab`. Zero 5xx. Document p50/p95/p99 latency.
- [ ] **TASK-Q-006** — OpenAPI validation: fetch `/openapi.json` and validate with `swagger-cli validate` (or `python -c "import json; json.load(open('/tmp/openapi.json'))"` and structural checks). Confirm all 9 endpoints have request/response schemas, all `responses` map to declared status codes.
- [ ] **TASK-Q-007** — Idempotent-import API behaviour: call `POST .../import` twice with the same folder; verify second call returns a new `job_id` but the job result reports `files_skipped == files_total` (matches EPIC-003 idempotency).
- [ ] **TASK-Q-008** — Job-poll lifecycle: `GET .../jobs/{job_id}` returns valid status through `pending → running → completed`. Verify state transitions without skipping or stuck in pending.
- [ ] **TASK-Q-009** — Error-code parity check: every `HTTPException` raised in `routes/knowledge.py` includes `error_code` in detail. Grep for `HTTPException(` in the file; for each, check `error_code` is in the args.
- [ ] **TASK-Q-010** — Lazy-import audit: `python -X importtime -c "from dashboard.routes import knowledge"` MUST NOT load `kuzu`/`zvec`/`sentence_transformers`/`anthropic`. (KnowledgeService should be lazy-instantiated.)
- [ ] **TASK-Q-011** — Regression sweep: `pytest dashboard/tests/ -k "not knowledge"` 568 passed.
- [ ] **TASK-Q-012** — Previous-EPIC suites still green: smoke + namespace + ingestion + query.
- [ ] **TASK-Q-013** — Dashboard boot still <2s for cold start with the new router registered.
- [ ] **TASK-Q-014** — QA report at `dashboard/docs/qa-reports/EPIC-005-qa.md` per template.

### Definition of Done (joint)

- [ ] All 9 endpoints implemented (TASK-E-002).
- [ ] Test coverage of `routes/knowledge.py` ≥ 90%.
- [ ] Auth enforced on all endpoints — verified by negative tests (TASK-Q-003).
- [ ] No regressions (TASK-Q-011, TASK-Q-012).
- [ ] OpenAPI spec at `/docs` includes the new routes with all models (TASK-Q-006).

### Acceptance criteria

- [ ] `curl -X POST -H "X-API-Key: $KEY" -d '{"name":"docs"}' http://localhost:9000/api/knowledge/namespaces` returns 201 with `NamespaceMeta` JSON. *(verifier: @qa TASK-Q-002)*
- [ ] `curl -X POST -H "X-API-Key: $KEY" -d '{"folder_path":"/tmp/test"}' .../namespaces/docs/import` returns 200 with `{"job_id":"..."}`. *(verifier: @qa TASK-Q-002)*
- [ ] `curl -H "X-API-Key: $KEY" .../namespaces/docs/jobs/<job_id>` polls correctly through `pending`/`running`/`completed`. *(verifier: @qa TASK-Q-008)*
- [ ] `curl -X POST -H "X-API-Key: $KEY" -d '{"query":"foo"}' .../namespaces/docs/query` returns valid `QueryResult`. *(verifier: @qa TASK-Q-002)*
- [ ] Bad namespace name returns 400 with `error_code: "INVALID_NAMESPACE_ID"`. *(verifier: @qa TASK-Q-004, TASK-Q-009)*
- [ ] No-such-namespace returns 404 with `error_code: "NAMESPACE_NOT_FOUND"`. *(verifier: @qa TASK-Q-004, TASK-Q-009)*
- [ ] No auth header → 401 on every endpoint. *(verifier: @qa TASK-Q-003)*

### QA Gate (mandatory beyond TASK-Q-001..013)

1. **End-to-end curl walkthrough** documented (TASK-Q-002).
2. **50-concurrent-query load** with no 5xx (TASK-Q-005).
3. **Auth-bypass sweep** all-401 (TASK-Q-003).
4. **Path-injection sweep** all-400 (TASK-Q-004).
5. **OpenAPI lint** clean (TASK-Q-006).

depends_on: [EPIC-004]

---

## EPIC-006 — MCP Endpoint (`/mcp` streamable-HTTP)

Roles: @engineer, @qa, @architect

Objective: Expose the same KnowledgeService operations as MCP tools at `/mcp` using FastMCP (streamable-HTTP transport from `mcp[cli]`). External MCP clients (opencode, claude-desktop, custom) can connect, list tools, and call them.

Lifecycle:
```text
pending → @engineer → @qa → @architect ─┬─► passed → EPIC-007
                ▲                       │
                └────── @engineer ◄─────┘ (on fail → fixing)
```

### Carry-forward from earlier EPICs (must be first work in this EPIC, per ADR-14/15/16/17)

- [ ] **CARRY-001** *(@engineer)* — **Image support in ingestion (ADR-14, ADR-17)**. Update `dashboard/knowledge/config.py` so `SUPPORTED_DOCUMENT_EXTENSIONS` is computed as the union of the existing document set + `IMAGE_EXTENSIONS` (`.png .jpg .jpeg .gif .bmp .tiff .webp`). Update `dashboard/knowledge/graph/parsers/markitdown_reader.py`'s `_get_markitdown()` to construct `MarkItDown(llm_client=anthropic_client, llm_model=cfg.LLM_MODEL)` when an Anthropic key is available. When unavailable, instantiate with no LLM client and accept that images yield empty markdown (logged once per file via `logger.warning`).
- [ ] **CARRY-002** *(@engineer)* — **Knowledge settings backend (ADR-15)**. Add `KnowledgeSettings` Pydantic model to `dashboard/models.py` (or `dashboard/lib/settings/models.py`, wherever `MasterSettings` lives) with fields `llm_model: str`, `embedding_model: str`, `embedding_dimension: int = 384` (read-only). Add `knowledge: KnowledgeSettings` field to `MasterSettings`. Add `GET /api/settings/knowledge` and `PUT /api/settings/knowledge` to `dashboard/routes/settings.py` mirroring the existing `runtime`/`memory` patterns (broadcasts `settings_updated` event). On PUT, validate `llm_model` is in the configured-models registry; validate `embedding_model` is a known sentence-transformers model id (or a free-form string with warning).
- [ ] **CARRY-003** *(@engineer)* — **`KnowledgeService` reads from settings** (ADR-15). On construction, read `MasterSettings.knowledge.llm_model` and `embedding_model` (via `get_settings_resolver()`) — fall back to env-var defaults from `config.py` only when no settings persisted. Pass these into `KnowledgeLLM(model=...)` and `KnowledgeEmbedder(model_name=...)`. Document the precedence: `MasterSettings.knowledge` > env var > hardcoded default.
- [ ] **CARRY-004** *(@qa)* — Verify CARRY-001..003 with explicit probes: (a) ingest a folder containing 1 PNG + 1 PDF + 1 DOCX with Anthropic key set — image gets non-empty chunks; (b) without Anthropic key — image walked but skipped, no crash; (c) `PUT /api/settings/knowledge` with `{"llm_model": "claude-haiku-4-5"}` then `GET` returns the new value; (d) instantiating a new `KnowledgeService` after the PUT picks up the new model.

### @engineer tasks — MCP server (implementation)

- [ ] **TASK-E-001** — Create `dashboard/knowledge/mcp_server.py` defining a `FastMCP` instance (`from mcp.server.fastmcp import FastMCP; mcp = FastMCP("ostwin-knowledge")`) with the following 7 tools (one Python function per tool, decorated with `@mcp.tool()`):
  - `knowledge_list_namespaces() -> list[dict]`
  - `knowledge_create_namespace(name: str, language: str = "English", description: str = "") -> dict`
  - `knowledge_delete_namespace(name: str) -> dict`
  - `knowledge_import_folder(namespace: str, folder_path: str, force: bool = False) -> dict` — `folder_path` MUST be an absolute path; returns `{job_id, status, message}`
  - `knowledge_get_import_status(namespace: str, job_id: str) -> dict`
  - `knowledge_query(namespace: str, query: str, mode: str = "raw", top_k: int = 10) -> dict`
  - `knowledge_get_graph(namespace: str, limit: int = 100) -> dict`
- [ ] **TASK-E-002** — Tool docstrings (each becomes the MCP description seen by the calling LLM): be explicit about arguments, return shape, when to use each tool, and when NOT to use it. For `knowledge_import_folder`: explicitly state "supports docx, pdf, xlsx, pptx, html, txt, md, csv, json, png, jpg (image OCR via Anthropic vision)". Include 1-line examples in the docstring.
- [ ] **TASK-E-003** — Each tool returns a JSON-serializable dict — never raises. Catch exceptions in the tool body and return `{"error": str(e), "code": "ERROR_CODE"}`. Tools wrap a singleton `KnowledgeService` (lazy-instantiated on first tool call so the import is cheap).
- [ ] **TASK-E-004** — Mount the MCP ASGI app on the dashboard at `/mcp` in `dashboard/api.py`: `app.mount("/mcp", mcp.streamable_http_app())` — verify exact API for `mcp[cli] >= 1.1.3` and pin the version in `requirements.txt`.
- [ ] **TASK-E-005** — Auth: if `OSTWIN_DEV_MODE=1`, allow anonymous local development access. Otherwise require `OSTWIN_API_KEY` to be configured and require `Authorization: Bearer <key>` on the MCP HTTP handshake. If no key is configured outside dev mode, fail closed with `503` / `MCP_AUTH_NOT_CONFIGURED` rather than allowing anonymous access. Use FastMCP's auth hook OR wrap the mounted app with middleware.
- [ ] **TASK-E-006** — Generate `dashboard/docs/knowledge-mcp-opencode.md` with a copy-pasteable `opencode.json` snippet that registers `http://localhost:9000/mcp` as an MCP server. Include both the streamable-HTTP transport block and the auth-header configuration.
- [ ] **TASK-E-007** — Dev-mode startup banner: when `OSTWIN_DEV_MODE=1`, log the MCP endpoint URL on dashboard startup so users see `MCP server live at http://localhost:9000/mcp` in the console.
- [ ] **TASK-E-008** — Engineer's integration test at `dashboard/tests/test_knowledge_mcp.py`. Spin up the FastAPI app via `TestClient(app)` OR a real uvicorn on a random port; connect a `mcp.ClientSession` using `streamable_http_client`; call `list_tools()` (verify 7 tools); then walk the lifecycle: `knowledge_create_namespace → knowledge_import_folder (with abs path) → knowledge_get_import_status (poll) → knowledge_query → knowledge_delete_namespace`. Assert structured responses for each. ~10 tests; coverage of `mcp_server.py` ≥ 80%.
- [ ] **TASK-E-009** — Done report at `dashboard/docs/done-reports/EPIC-006-engineer.md`, including a verbatim opencode config snippet, the exact mcp[cli] version pinned, evidence that the abs-path import works for an image fixture, and a transcript of either `opencode mcp list` OR an MCP CLI client (`mcp` command from the `mcp[cli]` package) showing the server recognized.

### @qa tasks (verification)

- [ ] **TASK-Q-001** — Re-run engineer's integration test from a fresh shell.
- [ ] **TASK-Q-002** — Real-MCP-client probe: write your own short script (in QA scratch dir, NOT committed to the repo) using `mcp.client.streamable_http.streamablehttp_client(url)` to connect to `http://localhost:9000/mcp`, list tools, call each one. Independent of engineer's tests.
- [ ] **TASK-Q-003** — Walk every tool's error path: bad namespace name (`"Bad!"`), non-existent namespace (`"never-created"`), non-existent job (`"fake-uuid"`), missing folder (`"/tmp/does-not-exist"`). Each must return a JSON `{"error": ..., "code": ...}` — NEVER an HTTP 5xx or raw exception traceback.
- [ ] **TASK-Q-004** — Coexistence check: `curl http://localhost:9000/api/knowledge/namespaces` AND `curl http://localhost:9000/mcp/...` both work in the same dashboard process. No route conflicts. Both visible in `/openapi.json` (REST routes; MCP is its own protocol layer).
- [ ] **TASK-Q-005** — Boot-time check: dashboard cold-starts in < 5 seconds with `mcp_server.py` added (lazy-import discipline preserved). Measure with `time python -c "from dashboard import api"`.
- [ ] **TASK-Q-006** — Auth probe: with `OSTWIN_API_KEY=test`, `OSTWIN_DEV_MODE=0`, attempt MCP handshake without Authorization header → must be rejected (401 or whatever the MCP transport's equivalent is). Then with `Authorization: Bearer test` → succeeds. Then with `OSTWIN_DEV_MODE=1` and no header → allowed.
- [ ] **TASK-Q-007** — Lazy-import audit: `python -X importtime -c "from dashboard.knowledge.mcp_server import mcp"` MUST NOT load `kuzu`/`zvec`/`sentence_transformers`/`anthropic` at import time. (Tools should defer KnowledgeService construction to first invocation.)
- [ ] **TASK-Q-008** — Real opencode validation: take the engineer's config snippet from `knowledge-mcp-opencode.md`, paste it into a test `opencode.json`, run `opencode mcp list` (or equivalent), confirm the dashboard server is listed and tools are discoverable. If you cannot install opencode locally, document this and use the `mcp` Python client as a substitute (and flag for follow-up).
- [ ] **TASK-Q-009** — `mode=summarized` graceful degradation through the MCP layer: with `ANTHROPIC_API_KEY` unset, call `knowledge_query(mode="summarized")` via MCP — response includes a `warnings` array containing `"llm_unavailable"`, `answer` is null, `chunks` populated. NO exception.
- [ ] **TASK-Q-010** — Regression sweep: 568 baseline preserved.
- [ ] **TASK-Q-011** — Previous-EPIC suites still green.
- [ ] **TASK-Q-012** — QA report at `dashboard/docs/qa-reports/EPIC-006-qa.md`.

### Definition of Done (joint)

- [ ] FastMCP server runs at `/mcp` and serves streamable-HTTP (TASK-E-004).
- [ ] All 7 tools listable via `mcp.ClientSession.list_tools()` (TASK-Q-002).
- [ ] Integration test runs the full lifecycle (TASK-E-008).
- [ ] Auth enforced when `OSTWIN_API_KEY` set + not in dev mode (TASK-Q-006).
- [ ] opencode config snippet documented + validated (TASK-E-006, TASK-Q-008).
- [ ] No regressions (TASK-Q-010).

### Acceptance criteria

- [ ] An MCP client connecting to `http://localhost:9000/mcp` with the right auth can:
  1. List tools (sees 7 named tools) *(verifier: @qa TASK-Q-002)*
  2. Create a namespace *(verifier: @qa TASK-Q-002)*
  3. Import a folder *(verifier: @qa TASK-Q-002)*
  4. Poll the job until completion *(verifier: @qa TASK-Q-002)*
  5. Query the namespace *(verifier: @qa TASK-Q-002)*
  6. Get the graph *(verifier: @qa TASK-Q-002)*
  7. Delete the namespace *(verifier: @qa TASK-Q-002)*
- [ ] Each tool's response is a JSON object (not a raw exception). *(verifier: @qa TASK-Q-003)*
- [ ] When `ANTHROPIC_API_KEY` is unset, `knowledge_query(mode="summarized")` returns a result with `warnings` field but no crash. *(verifier: @qa TASK-Q-009)*
- [ ] opencode config snippet validated by `opencode mcp list` against a local opencode + dashboard. *(verifier: @qa TASK-Q-008)*

### QA Gate (mandatory beyond TASK-Q-001..011)

1. Walk the tool surface with a real MCP client (TASK-Q-002).
2. Test every tool's error path (TASK-Q-003).
3. Confirm `/api/*` + `/mcp/*` coexist (TASK-Q-004).
4. Boot time < 5 s (TASK-Q-005).
5. opencode `mcp list` recognizes the server (TASK-Q-008).

depends_on: [EPIC-005]

---

## EPIC-007 — End-to-End Tests, Documentation, Hardening

Roles: @engineer, @qa, @architect

Objective: A real-world E2E test, comprehensive documentation, performance benchmarks, and a final hardening pass.

Lifecycle:
```text
pending → @engineer → @qa → @architect ─┬─► passed → SIGNOFF
                ▲                       │
                └────── @engineer ◄─────┘ (on fail → fixing)
```

### Carry-forward from earlier EPICs (must address in this EPIC)

- [ ] **CARRY-001** *(@engineer)* — Concurrent auto-create race in `KnowledgeService.import_folder` (QA-noted in EPIC-003 v2 Minor 1): wrap auto-create in a try/except for `NamespaceExistsError` (treat as success).
- [ ] **CARRY-002** *(@engineer)* — Vietnamese strings in `dashboard/knowledge/graph/prompt.py` (still inert from EPIC-001 ADR-10 partial): delete the file or strip the strings if `extract_KP_*_fn` helpers in `graph/utils/rag.py` are confirmed unused.
- [ ] **CARRY-003** *(@qa)* — After CARRY-001..002, verify with grep that no Vietnamese diacritics remain in active code, and run the concurrent auto-create probe to confirm the race is fixed.

### @engineer tasks (implementation)

- [ ] **TASK-E-001** — End-to-end REST test at `dashboard/tests/test_knowledge_e2e.py`: full flow `create namespace → import folder → poll job → query (all 3 modes) → get_graph → re-query (cache hit) → delete namespace`. Use `TestClient(app)`. Assert end-state is clean (`~/.ostwin/knowledge/test-e2e-ns` does not exist).
- [ ] **TASK-E-002** — End-to-end MCP test at `dashboard/tests/test_knowledge_mcp_e2e.py`: same flow as TASK-E-001 but via the MCP client. Verify all tool calls succeed and produce structured responses.
- [ ] **TASK-E-003** — Performance benchmark script `dashboard/scripts/bench_knowledge.py` (NOT a pytest test — a standalone CLI). Measures: ingestion throughput (docs/sec, MB/sec), query latency per mode per top_k, peak RSS memory. Outputs a markdown table to stdout AND writes `dashboard/docs/knowledge-mcp-bench-results.md`.
- [ ] **TASK-E-004** — Documentation suite:
  - `dashboard/docs/knowledge-mcp.md` — user-facing guide (what is it, REST API examples, MCP connection, env vars, common errors)
  - `dashboard/docs/knowledge-mcp-opencode.md` — finalize from EPIC-006 draft
  - `dashboard/docs/knowledge-mcp-architecture.md` — contributor guide (module layout, data flow, ADRs, extension points, schema diagrams)
  - `dashboard/knowledge/README.md` — new file, module overview
  - Add a "Knowledge MCP" section to root `CLAUDE.md` linking to the above
- [ ] **TASK-E-005** — Hardening: rate limiting on `import_folder` (1 in-flight per namespace; concurrent calls → 409 `error_code: "IMPORT_IN_PROGRESS"`). Implement as a `set[str]` of in-flight namespaces guarded by `KnowledgeService._cache_lock`.
- [ ] **TASK-E-006** — Hardening: `max_namespaces` env var (`OSTWIN_KNOWLEDGE_MAX_NAMESPACES`, default 100). Creating the (max+1)th returns 429 `error_code: "MAX_NAMESPACES_REACHED"`.
- [ ] **TASK-E-007** — Hardening: 60s timeout on LLM calls in `KnowledgeLLM` (env override `OSTWIN_KNOWLEDGE_LLM_TIMEOUT`). Use `anthropic.Anthropic(timeout=60)` or wrap calls.
- [ ] **TASK-E-008** — Hardening: circuit breaker on Anthropic — after 5 consecutive `AnthropicError` failures within 5 min, switch `is_available()` → False for 5 min (cool-down), then retry. State on `KnowledgeLLM` instance, thread-safe.
- [ ] **TASK-E-009** — Structured logging: every API call AND every MCP tool call emits a single log line at INFO level with `namespace`, `operation`, `latency_ms`, `result_status` (e.g. `"GET /api/knowledge/namespaces ok ns=- op=list latency_ms=12 result=ok"`). Use a small `_log_call(...)` helper.
- [ ] **TASK-E-010** — (Optional, stretch) Frontend tab `dashboard/fe/src/components/plan/KnowledgeTab.tsx` showing namespace list, import button, query box, graph viz (small SVG with d3-force-style layout). If pursued: separate done sub-report; otherwise document as deferred to a follow-up plan.
- [ ] **TASK-E-011** — Done report at `dashboard/docs/done-reports/EPIC-007-engineer.md`. Include the benchmark output table, links to all docs, and confirmation each hardening item is implemented + tested.

### @qa tasks (verification)

- [ ] **TASK-Q-001** — Run engineer's E2E REST test from a fresh `~/.ostwin/knowledge/` directory.
- [ ] **TASK-Q-002** — Run engineer's E2E MCP test from a fresh state.
- [ ] **TASK-Q-003** — Fresh-install simulation: `rm -rf ~/.ostwin/knowledge/` then run TASK-E-001 + TASK-E-002 again. Both pass.
- [ ] **TASK-Q-004** — Long-running soak test: import the EPIC-003 fixture folder, then run 1000 mixed-mode queries via API, monitor RSS memory across the run. Document peak memory and any drift. Acceptance: peak < 2 GB; growth < 100 MB across 1000 queries.
- [ ] **TASK-Q-005** — Documentation correctness probe: follow `dashboard/docs/knowledge-mcp.md` user guide step-by-step from a clean state. Every documented command must work as written. Document deviations.
- [ ] **TASK-Q-006** — Run engineer's benchmark script independently. Sanity-check the numbers (no funny rounding, no obviously-wrong measurements). Confirm: ingestion ≥ 5 docs/sec; `mode=raw` p95 < 500ms.
- [ ] **TASK-Q-007** — Hardening test: `import_folder` while another import for the same namespace is in-flight → 409. Test programmatically: spawn two simultaneous import calls, second returns 409.
- [ ] **TASK-Q-008** — Hardening test: create 100 namespaces; the 101st returns 429.
- [ ] **TASK-Q-009** — Hardening test: mock `KnowledgeLLM.aggregate_answers` to sleep 70s; verify it aborts at 60s with a logged timeout warning.
- [ ] **TASK-Q-010** — Hardening test: mock Anthropic to raise `AnthropicError` 5 times; verify `KnowledgeLLM.is_available()` returns False for the next call; verify it returns True again after 5+ minutes (use `monkeypatch.setattr` on the timer).
- [ ] **TASK-Q-011** — Structured-logging probe: tail `~/.ostwin/dashboard/debug.log` while running TASK-E-001's E2E flow; verify every API/MCP call has the documented log line shape with `namespace=`, `operation=`, `latency_ms=`, `result_status=`.
- [ ] **TASK-Q-012** — Final regression sweep: full `pytest dashboard/tests/` — every test in the suite passes (no `-k` filter). Coverage report ≥ 80% overall for `dashboard/knowledge/`.
- [ ] **TASK-Q-013** — Lazy-import audit one final time on the new modules.
- [ ] **TASK-Q-014** — QA report at `dashboard/docs/qa-reports/EPIC-007-qa.md`. Include benchmark data, soak-test memory graph (if possible), and a sign-off section ready for architect.

### Definition of Done (joint)

- [ ] Both E2E tests pass against a fresh install (TASK-Q-003).
- [ ] Benchmark script runnable; results documented (TASK-E-003, TASK-Q-006).
- [ ] All 5 documentation files exist and are correct (TASK-E-004, TASK-Q-005).
- [ ] Rate limiting + max namespaces + LLM timeout + circuit breaker + structured logging implemented & tested (TASK-E-005..009, TASK-Q-007..011).
- [ ] CARRY-001..002 addressed (concurrent auto-create + Vietnamese strings).
- [ ] Full dashboard test suite green (TASK-Q-012).
- [ ] Test coverage of `dashboard/knowledge/` ≥ 80% overall.
- [ ] (Optional) Frontend tab demoed by engineer (separate sign-off if pursued).

### Acceptance criteria

- [ ] E2E REST test runs in < 2 minutes (excluding model download cold-start). *(verifier: @qa TASK-Q-001)*
- [ ] Benchmarks document: ingestion ≥ 5 docs/sec on small corpus (CPU embedding); `mode=raw` p95 < 500ms. *(verifier: @qa TASK-Q-006)*
- [ ] Importing into a namespace currently being imported returns 409 with `error_code: "IMPORT_IN_PROGRESS"`. *(verifier: @qa TASK-Q-007)*
- [ ] Creating the 101st namespace (default cap) returns 429 with `error_code: "MAX_NAMESPACES_REACHED"`. *(verifier: @qa TASK-Q-008)*
- [ ] LLM call exceeding 60 s aborts cleanly and is logged. *(verifier: @qa TASK-Q-009)*
- [ ] After 5 consecutive Anthropic failures, subsequent calls skipped (circuit open) for 5 min. *(verifier: @qa TASK-Q-010)*
- [ ] Documentation reviewed by architect for accuracy + completeness.

### QA Gate (mandatory beyond TASK-Q-001..013)

1. **Fresh-install simulation** (TASK-Q-003).
2. **Long-running soak: 200-doc + 1000 queries, no memory leak** (TASK-Q-004).
3. **Doc-correctness walk-through** (TASK-Q-005).
4. **Benchmarks reasonable** (TASK-Q-006).
5. **Structured-log shape correct** (TASK-Q-011).

depends_on: [EPIC-006]

---

## EPIC-008 — Frontend Settings Panel for Knowledge

Roles: @engineer, @qa, @architect

Objective: Add a "Knowledge" tab to the existing dashboard settings page (`dashboard/fe/src/app/settings/page.tsx`) that lets the user configure the LLM model + embedding model used by the knowledge service. Backed by `GET/PUT /api/settings/knowledge` (built in EPIC-006 CARRY-002).

Lifecycle:
```text
pending → @engineer → @qa → @architect ─┬─► passed → SIGNOFF
                ▲                       │
                └────── @engineer ◄─────┘ (on changes-requested → fixing)
```

### @engineer tasks (frontend implementation)

- [ ] **TASK-E-001** — Add `'knowledge'` to the `SettingsNamespace` union in `dashboard/fe/src/types/settings.ts` (or wherever the namespace type is defined). Add a `KnowledgeSettings` interface mirroring the backend Pydantic model: `{ llm_model: string; embedding_model: string; embedding_dimension: number }`.
- [ ] **TASK-E-002** — Add a "Knowledge" entry to the `SettingsSidebar` (`dashboard/fe/src/components/settings/SettingsSidebar.tsx`). Use Material Symbols icon `school` or `library_books`. Position after `memory`.
- [ ] **TASK-E-003** — Create `dashboard/fe/src/components/settings/KnowledgePanel.tsx`:
  - Props: `{ knowledge: KnowledgeSettings; onUpdate: (value: Partial<KnowledgeSettings>) => void; allModels: ModelInfo[] }` (pull `allModels` from the existing `useConfiguredModels` hook).
  - Two model-picker dropdowns: one for `llm_model` (filtered to chat-capable models), one for `embedding_model` (free-form text + suggestions of common sentence-transformers ids: `BAAI/bge-small-en-v1.5`, `BAAI/bge-base-en-v1.5`, `sentence-transformers/all-MiniLM-L6-v2`, `intfloat/e5-small-v2`).
  - A read-only "Embedding dimension" line showing the value.
  - Standard settings-page styling (use existing `--color-*` CSS variables; match `RuntimePanel` and `MemoryPanel`).
  - Save-on-change with optimistic UI update + toast on failure.
- [ ] **TASK-E-004** — Wire the new namespace in `dashboard/fe/src/app/settings/page.tsx`'s `renderActivePanel()` switch:
  ```tsx
  case 'knowledge':
    return (
      <KnowledgePanel
        knowledge={settings.knowledge || { llm_model: '', embedding_model: '', embedding_dimension: 384 }}
        onUpdate={(value) => updateNamespace('knowledge', { ...settings.knowledge, ...value })}
        allModels={allModels}
      />
    );
  ```
- [ ] **TASK-E-005** — Update the `useSettings` hook (`dashboard/fe/src/hooks/use-settings.ts`) — should already handle namespaces generically via `updateNamespace(name, value)`. If hardcoded for known namespaces only, extend it to accept `'knowledge'`.
- [ ] **TASK-E-006** — Frontend tests at `dashboard/fe/src/__tests__/KnowledgePanel.test.tsx` (Jest + React Testing Library — match the existing pattern). Cover: renders with no settings (uses defaults); model dropdowns populate; selecting a value calls `onUpdate`; embedding-model accepts free text. ~5 tests.
- [ ] **TASK-E-007** — Done report at `dashboard/docs/done-reports/EPIC-008-engineer.md`. Include a screenshot of the new panel (rendered via `npm run dev`) AND an example of changing a model from the UI.

### @qa tasks (verification)

- [ ] **TASK-Q-001** — Build the frontend: `cd dashboard/fe && npm run build` — must succeed with no TypeScript errors.
- [ ] **TASK-Q-002** — Run frontend tests: `npm test -- KnowledgePanel` — all pass.
- [ ] **TASK-Q-003** — Manual flow: start dashboard (`python dashboard/api.py`), open `http://localhost:3366/settings`, click the new "Knowledge" tab in the sidebar. Verify both dropdowns render, current values match `GET /api/settings/knowledge`, changing a value persists (verify via curl GET after change).
- [ ] **TASK-Q-004** — Round-trip: change `llm_model` in the UI; verify `KnowledgeService` instantiated AFTER the change uses the new model (instantiate via Python REPL, check `service._llm.model`).
- [ ] **TASK-Q-005** — Settings-broadcaster: open the dashboard in two browser tabs; change a setting in tab A; verify tab B reflects the change live (the existing `settings_updated` WebSocket event should propagate it).
- [ ] **TASK-Q-006** — No regressions in other settings tabs (`providers`, `runtime`, `memory`).
- [ ] **TASK-Q-007** — QA report at `dashboard/docs/qa-reports/EPIC-008-qa.md`.

### Definition of Done (joint)

- [ ] `KnowledgePanel` component renders cleanly in the existing settings page (TASK-E-003).
- [ ] Sidebar shows the new entry between `memory` and bottom (TASK-E-002).
- [ ] Settings change persists via `PUT /api/settings/knowledge` (TASK-Q-003).
- [ ] `KnowledgeService` reads the persisted settings (TASK-Q-004 + EPIC-006 CARRY-003).
- [ ] Frontend build passes; no TS errors (TASK-Q-001).
- [ ] Frontend tests pass (TASK-Q-002).
- [ ] Existing settings tabs not regressed (TASK-Q-006).

### Acceptance criteria

- [ ] User can navigate to `/settings`, click "Knowledge", change LLM model, save, and the next ingestion uses the new model. *(verifier: @qa TASK-Q-003 + TASK-Q-004)*
- [ ] Embedding model field accepts free text (so users can paste arbitrary HF model ids). *(verifier: @qa TASK-Q-002)*
- [ ] No console errors on the page. *(verifier: @qa TASK-Q-003)*

depends_on: [EPIC-006]

---

## Out of Scope (explicit non-goals)

The following are deliberately **NOT** part of this plan. Engineer must NOT silently scope-creep into these:

| Item | Why deferred | Future plan |
|---|---|---|
| Frontend Knowledge tab UI | Frontend work is its own concern; backend must work first. | Optional in EPIC-007; otherwise follow-up plan. |
| Multi-tenant user namespaces | Dashboard is single-tenant per `OSTWIN_API_KEY`. Adding per-user scoping is an auth-system change. | Future plan, after auth refactor. |
| Distributed background jobs (Redis/Celery) | In-process executor sufficient for single-node dashboard. | When we hit >10 concurrent imports. |
| Incremental re-indexing on file change | Idempotency skips identical files; full re-index sufficient for v1. | Future enhancement after watchdog integration. |
| OCR for image PDFs | MarkItDown handles text PDFs; OCR adds tesseract dep. | Optional follow-up. |
| Cross-namespace federated query | Each namespace is isolated by design. | Future feature once we have user demand. |
| Memory short-term graph (mem0) | Different problem (per-conversation vs per-corpus). The existing `.agents/memory/` system solves it for war-rooms. | Stays separate; not merged into knowledge. |
| Migration from old `app.core.graph` data files | No existing data to migrate (the package was never wired in). | N/A. |

---

## Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-1 | KuzuDB single-process limitation causes lock contention with concurrent ingest+query | Med | High | EPIC-002: each namespace = its own .db file (process-wide cache by path, similar to `.agents/memory/`). EPIC-004 QA gate explicitly tests concurrent read+write. |
| R-2 | sentence-transformers model download blocks first request | High | Med | Pre-warm on dashboard startup if `OSTWIN_KNOWLEDGE_PREWARM=1`. Document the cold-start cost. |
| R-3 | Anthropic API rate limits or outages stall ingestion | Med | High | EPIC-007 circuit breaker + graceful degradation. Per-call timeout. |
| R-4 | MarkItDown choking on unusual file formats | Med | Low | Per-file error isolation in ingestion (EPIC-003 TASK-011). Fallback to plain-text read. |
| R-5 | zvec schema evolution requires collection recreation | Low | Med | zvec collections are namespace-scoped — recreate is cheap. Document the schema in `knowledge-mcp-architecture.md`. (Originally about chromadb; revised after ADR-04 swap.) |
| R-6 | Disk space exhaustion from large namespaces | Med | Med | Per-namespace size accounting in manifest; warn when > 1 GB. EPIC-007 max namespaces cap. |
| R-7 | MCP transport bugs in `mcp[cli]` | Low | Med | Pin mcp[cli] version. Engineer logs the working version in done report. Have SSE fallback documented if HTTP path doesn't work. |
| R-8 | Refactor breaks unrelated dashboard tests | Med | High | EPIC-001 QA gate explicitly runs `pytest -k "not knowledge"`. Architect re-runs at every EPIC. |
| R-9 | Embedding-model dim mismatch (changing model after ingest) | Low | High | `manifest.json` records the embedding model and dim used. Refuse to query if active model dim ≠ recorded. EPIC-002 enforces. |
| R-10 | Engineer over-engineers and slips schedule | Med | Med | Explicit "Out of Scope" section above. Per-EPIC architect review catches scope creep early. |

---

## Reviewer Feedback Loop — How I (architect) will use this plan

For each EPIC, my (architect) review will:

1. **Read** the engineer's done report.
2. **Read** the QA report.
3. **Run** every command in the QA "How to verify" section myself.
4. **Run** the QA gate's specific extra checks.
5. **Diff** the engineer's changes against the EPIC's task list to detect:
   - Tasks completed but not listed (scope creep, may be okay)
   - Tasks listed but not completed (must justify or fix)
   - Tasks completed differently than spec (ADR violation? must justify)
6. **Verdict**:
   - **PASSED** — proceed to next EPIC.
   - **CHANGES-REQUESTED** — issue numbered list of fixes; engineer addresses, re-submits to QA, then back to me.
   - **ESCALATED** — to user, when (a) ADR needs revision, (b) >3 fix cycles, or (c) ambiguity in plan needs user judgement.

I will be **strict but non-punitive**. Defects are surfaced as plain technical statements, not blame. Engineer is expected to push back if my feedback is wrong — I will revise the plan when justified.

---

## Final notes for the Engineer

- **Don't refactor outside `dashboard/knowledge/` and `dashboard/routes/knowledge.py` unless the task explicitly calls for it** (api.py registration is the one exception).
- **If you discover an ADR is wrong, stop and propose a revision** — don't silently deviate.
- **Preserve the algorithmic ideas** in the existing `knowledge/graph/core/` files (KuzuDB schema, GraphRAGExtractor flow, multi-step planning). They're the value here. The wrapper code (`app.*` shims) is what we're throwing away.
- **Lazy-load heavy deps**. The dashboard's <2s boot time is a hard requirement.
- **Test as you go**. Do not write all the code first and then write all the tests. Each EPIC's tests should land in the same commit as its code.
- **Over-document the MCP tool docstrings**. Those go to LLMs; ambiguity = wrong tool calls.
