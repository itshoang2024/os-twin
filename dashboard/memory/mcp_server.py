"""MCP Server for Agentic Memory System.

Exposes the memory system as MCP tools for LLM agents.
Run with: python mcp_server.py
"""


# --- Self-healing interpreter check (must run BEFORE heavy imports) ---
# Various MCP launchers (deepagents, opencode, codex) invoke this script with
# whatever `python` resolves to in their own environment, which often lacks
# the heavy deps (`requests`, `litellm`, `chromadb`, `sentence-transformers`).
# If the current interpreter can't import a required dep, re-exec ourselves
# with the venv shipped next to this script.
def _ensure_correct_interpreter() -> None:
    import importlib.util
    import os as _os
    import sys as _sys

    # Honor an opt-out so users can debug interpreter resolution.
    if _os.getenv("MEMORY_NO_REEXEC", "").lower() in ("1", "true", "yes"):
        return

    # Pick a sentinel dep that the project needs but lightweight venvs lack.
    if importlib.util.find_spec("requests") is not None:
        return

    here = _os.path.dirname(_os.path.abspath(__file__))
    home = _os.path.expanduser("~")
    candidates = [
        # Installed venv (primary)
        _os.path.join(home, ".ostwin", ".venv", "bin", "python"),
        _os.path.join(home, ".ostwin", ".venv", "bin", "python3"),
        # Fallback: venv adjacent to script
        _os.path.join(here, ".venv", "bin", "python"),
        _os.path.join(here, ".venv", "bin", "python3"),
        _os.path.join(here, "venv", "bin", "python"),
    ]
    target = next((c for c in candidates if _os.path.isfile(c) and _os.access(c, _os.X_OK)), None)
    if target is None or _os.path.realpath(target) == _os.path.realpath(_sys.executable):
        # No alternative found, or we ARE the alternative — let the import
        # fail naturally with the standard ModuleNotFoundError downstream.
        return

    # Verify the candidate actually has `requests` before we re-exec, to
    # avoid an infinite loop if the alternate venv is also broken.
    import subprocess as _sp

    probe = _sp.run(
        [target, "-c", "import requests"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        return

    # Re-exec. We're early enough that no MCP traffic has been read yet, so
    # stdin/stdout/stderr are still attached to the parent and the re-exec
    # is transparent to the launcher.
    _sys.stderr.write(f"mcp_server: re-execing with {target} (current {_sys.executable} lacks 'requests')\n")
    _sys.stderr.flush()
    _os.execv(target, [target, _os.path.abspath(__file__), *_sys.argv[1:]])


# Only re-exec when running as a standalone stdio process.  When imported as
# a module (e.g. by the dashboard for HTTP transport), the host process
# already has the right interpreter and deps.
if __name__ == "__main__":
    _ensure_correct_interpreter()

import json
import logging
import os
import re
import subprocess
import threading
from typing import Any, Optional
from mcp.server.fastmcp import FastMCP

# Lazy import: AgenticMemorySystem loads heavy deps (embeddings, vector DB).
# Deferring to first tool call keeps MCP startup fast (<1s).
AgenticMemorySystem = None


# --- Configuration via environment variables ---
# Resolve project root for .memory storage.
# AGENT_OS_ROOT may be "." which is useless when CWD is /tmp/deepagents_server_xxx/.
# Fall back to AGENT_OS_PROJECT_DIR, or walk up from CWD to find a dir with .agents/.
def _find_project_root() -> str:
    """Find the actual project root directory.

    deepagents-cli runs MCP servers from /tmp/deepagents_server_xxx/ with
    AGENT_OS_ROOT="." — which is useless. We try multiple strategies to find
    the real project directory.
    """
    # 1. Explicit absolute AGENT_OS_ROOT
    root = os.getenv("AGENT_OS_ROOT", "")
    if root and os.path.isabs(root) and os.path.isdir(root):
        return root
    # 2. AGENT_OS_PROJECT_DIR (set by Invoke-Agent wrapper)
    proj = os.getenv("AGENT_OS_PROJECT_DIR", "")
    if proj and os.path.isabs(proj) and os.path.isdir(proj):
        return proj
    # 3. MEMORY_PERSIST_DIR if explicitly set and absolute
    mem = os.getenv("MEMORY_PERSIST_DIR", "")
    if mem and os.path.isabs(mem):
        return os.path.dirname(mem)
    # 4. Read parent process (deepagents) CWD — it's often the project dir
    try:
        ppid = os.getppid()
        parent_cwd = os.readlink(f"/proc/{ppid}/cwd")
        if os.path.isdir(os.path.join(parent_cwd, ".agents")):
            return parent_cwd
        # Walk up parent chain (deepagents -> langgraph -> wrapper -> shell)
        for _ in range(5):
            with open(f"/proc/{ppid}/stat") as _f:
                ppid_stat = _f.read()
            ppid = int(ppid_stat.split(")")[1].split()[1])  # 4th field = ppid
            if ppid <= 1:
                break
            parent_cwd = os.readlink(f"/proc/{ppid}/cwd")
            if os.path.isdir(os.path.join(parent_cwd, ".agents")):
                return parent_cwd
    except (OSError, ValueError, IndexError):
        pass
    # 5. Fall back to CWD
    return os.getcwd()


_project_root = _find_project_root()
_default_persist = os.path.realpath(os.path.join(_project_root, ".memory"))
PERSIST_DIR = os.getenv("MEMORY_PERSIST_DIR", _default_persist)
LOG_DIR = os.getenv("MEMORY_LOG_DIR", PERSIST_DIR)

# --- Logging setup ---
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "mcp_server.log")),
    ],
)
logger = logging.getLogger(__name__)


# Suppress noisy "Received exception from stream" errors that FastMCP would
# otherwise forward to the client as notifications/message events. These are
# triggered by junk on stdin (e.g. stray newlines when stdio is attached to a
# TTY) and have no useful signal — they just spam the terminal/client.
class _DropStreamParseErrors(logging.Filter):
    _NOISE = (
        "Received exception from stream",
        "Invalid JSON",
        "Internal Server Error",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(needle in msg for needle in self._NOISE)


_noise_filter = _DropStreamParseErrors()
for _name in ("mcp.server.lowlevel.server", "mcp.server.exception_handler"):
    logging.getLogger(_name).addFilter(_noise_filter)


# Monkey-patch the lowlevel server's _handle_message so stream-level exceptions
# (e.g. JSON parse errors from junk on stdin) are logged locally instead of
# forwarded to the client as "Internal Server Error" notifications. Upstream
# unconditionally calls session.send_log_message for any Exception on the read
# stream — see mcp/server/lowlevel/server.py:707. That's the spam source.
def _patch_mcp_exception_silence() -> None:
    try:
        import warnings as _warnings
        from mcp.server.lowlevel import server as _lowlevel
        from mcp.shared.session import RequestResponder as _RR
        from mcp import types as _mcp_types

        async def _handle_message_quiet(
            self,
            message,
            session,
            lifespan_context,
            raise_exceptions: bool = False,
        ):
            with _warnings.catch_warnings(record=True) as w:
                if isinstance(message, _RR) and isinstance(getattr(message, "request", None), _mcp_types.ClientRequest):
                    req = message.request.root
                    with message:
                        await self._handle_request(message, req, session, lifespan_context, raise_exceptions)
                elif isinstance(message, _mcp_types.ClientNotification):
                    await self._handle_notification(message.root)
                elif isinstance(message, Exception):
                    logger.debug("Suppressed stream exception: %r", message)
                    if raise_exceptions:
                        raise message

                for warning in w:
                    logger.info("Warning: %s: %s", warning.category.__name__, warning.message)

        _lowlevel.Server._handle_message = _handle_message_quiet
        logger.info("Patched mcp.server.lowlevel.Server._handle_message to silence stream errors")
    except Exception:
        logger.exception("Failed to patch mcp lowlevel server; stream errors may still spam client")


_patch_mcp_exception_silence()
# --- Configuration ---
# Defaults come from config.default.json, overridden by ~/.ostwin/.agents/config.json,
# then MEMORY_* env vars.  Config is re-read on every get_memory() call so the MCP
# server always reflects the latest dashboard settings.
from dashboard.agentic_memory.config import load_config as _load_config

_cfg = _load_config()

# Module-level snapshots used for startup logging and tool registration.
# These are NOT used by _init_memory — it reads fresh config each time.
LLM_BACKEND = _cfg.llm.backend
LLM_MODEL = _cfg.llm.model
EMBEDDING_MODEL = _cfg.embedding.model
EMBEDDING_BACKEND = _cfg.embedding.backend
VECTOR_BACKEND = _cfg.vector.backend
CONTEXT_AWARE = _cfg.evolution.context_aware
CONTEXT_AWARE_TREE = _cfg.evolution.context_aware_tree
MAX_LINKS = _cfg.evolution.max_links
AUTO_SYNC_ENABLED = _cfg.sync.auto_sync
AUTO_SYNC_INTERVAL = _cfg.sync.auto_sync_interval
CONFLICT_RESOLUTION = _cfg.sync.conflict_resolution
SIMILARITY_WEIGHT = _cfg.search.similarity_weight
DECAY_HALF_LIFE = _cfg.search.decay_half_life_days
DISABLED_TOOLS = set(_cfg.disabled_tools)


def tool_enabled(name: str) -> bool:
    """Check if a tool is enabled (not in the disabled list)."""
    return name not in DISABLED_TOOLS


def optional_tool(name: str):
    """Register an MCP tool only if it's not in DISABLED_TOOLS."""
    if tool_enabled(name):
        # structured_output=False avoids outputSchema which some clients don't support
        return mcp.tool(structured_output=False)

    # Return a no-op decorator that keeps the function but doesn't register it
    def noop(func):
        return func

    return noop


import sys as _sys

logger.info("=" * 60)
logger.info("MCP Server starting up (lazy init)")
logger.info("python=%s (%s)", _sys.executable, _sys.version.split()[0])
logger.info("script=%s  cwd=%s", os.path.abspath(__file__), os.getcwd())
logger.info(
    "persist_dir=%s  llm=%s/%s  embedding=%s/%s  vector=%s",
    PERSIST_DIR,
    LLM_BACKEND,
    LLM_MODEL,
    EMBEDDING_BACKEND,
    EMBEDDING_MODEL,
    VECTOR_BACKEND,
)
logger.info("auto_sync=%s  interval=%ds", AUTO_SYNC_ENABLED, AUTO_SYNC_INTERVAL)
logger.info(
    "search: similarity_weight=%.2f  decay_half_life=%.1f days",
    SIMILARITY_WEIGHT,
    DECAY_HALF_LIFE,
)

# --- Background-initialized memory system ---
# The memory system loads heavy deps (embeddings, vector DB) which takes ~9s.
# We start loading in a background thread immediately so it's ready by the time
# the first tool call arrives. The MCP server responds to initialize/tools/list
# instantly while the background load completes.
_memory = None
_memory_init_error: Optional[Exception] = None
_memory_lock = threading.Lock()
_memory_ready = threading.Event()
# Track the config fingerprint used to init the current _memory instance so
# get_memory() can detect when the dashboard settings changed.
_memory_config_fingerprint: Optional[str] = None


def _config_fingerprint(cfg) -> str:
    """Return a hashable string summarising the config keys that affect the
    memory system instance (backends, models, vector store, etc.)."""
    return (
        f"{cfg.llm.backend}|{cfg.llm.model}|"
        f"{cfg.embedding.backend}|{cfg.embedding.model}|"
        f"{cfg.vector.backend}|"
        f"{cfg.evolution.context_aware}|{cfg.evolution.context_aware_tree}|"
        f"{cfg.evolution.max_links}|"
        f"{cfg.search.similarity_weight}|{cfg.search.decay_half_life_days}|"
        f"{cfg.sync.conflict_resolution}"
    )


def _init_memory(cfg=None):
    """Initialize the memory system (runs in background thread).

    If *cfg* is None, a fresh config is loaded from all layers
    (defaults → dashboard → env vars).
    """
    global _memory, _memory_init_error, _memory_config_fingerprint, AgenticMemorySystem
    try:
        if cfg is None:
            cfg = _load_config()

        logger.info("Background: importing agentic_memory...")
        from dashboard.agentic_memory.memory_system import AgenticMemorySystem as _AMS

        AgenticMemorySystem = _AMS
        logger.info(
            "Background: initializing memory system (llm=%s/%s  embedding=%s/%s  vector=%s)...",
            cfg.llm.backend,
            cfg.llm.model,
            cfg.embedding.backend,
            cfg.embedding.model,
            cfg.vector.backend,
        )
        with _memory_lock:
            # LLM calls go through MemoryLLM → BaseLLMWrapper — auto-resolves
            # model/provider from MasterSettings. No explicit llm_backend/llm_model
            # params needed here.
            _memory = AgenticMemorySystem(
                model_name=cfg.embedding.model,
                embedding_backend=cfg.embedding.backend,
                vector_backend=cfg.vector.backend,
                persist_dir=PERSIST_DIR,
                context_aware_analysis=cfg.evolution.context_aware,
                context_aware_tree=cfg.evolution.context_aware_tree,
                max_links=cfg.evolution.max_links,
                similarity_weight=cfg.search.similarity_weight,
                decay_half_life_days=cfg.search.decay_half_life_days,
                conflict_resolution=cfg.sync.conflict_resolution,
            )
            _memory_config_fingerprint = _config_fingerprint(cfg)
        logger.info(
            "Background: memory system ready (%d memories loaded)",
            len(_memory.memories),
        )

        # Import docs if .memory/docs/ exists
        docs_dir = os.path.join(PERSIST_DIR, "docs")
        if os.path.isdir(docs_dir):
            logger.info("Background: docs/ folder detected, importing...")
            import_result = _memory.import_docs(docs_dir)
            logger.info("Background: import_docs result: %s", import_result)

    except Exception as exc:
        _memory_init_error = exc
        logger.exception("Background: failed to initialize memory system")
    finally:
        _memory_ready.set()


# Start background initialization immediately
_init_thread = threading.Thread(target=_init_memory, daemon=True, name="memory-init")
_init_thread.start()


def get_memory():
    """Get the memory system, waiting for background init if needed.

    When the dashboard saves memory/knowledge settings it writes a sentinel
    file (``~/.ostwin/.agents/.memory_config_dirty``).  This function checks
    for that flag on every call (cheap ``os.path.exists``) and only reloads
    + reinitialises when the flag is present.

    Raises a RuntimeError that includes the original initialization exception
    (and python interpreter path) so MCP clients see actionable diagnostics
    instead of a generic failure.
    """
    global _memory, _memory_init_error, _memory_config_fingerprint

    if _memory is None:
        logger.info("Waiting for memory system initialization...")
        _memory_ready.wait(timeout=60)
        if _memory is None:
            err = _memory_init_error
            if err is not None:
                raise RuntimeError(
                    f"Memory system failed to initialize: "
                    f"{type(err).__name__}: {err}. "
                    f"python={_sys.executable} script={os.path.abspath(__file__)}. "
                    f"See {os.path.join(LOG_DIR, 'mcp_server.log')} for the full traceback."
                ) from err
            raise RuntimeError(
                "Memory system failed to initialize within 60s "
                f"(python={_sys.executable}). See {os.path.join(LOG_DIR, 'mcp_server.log')}."
            )

    # --- Hot-reload: check for dashboard config-dirty flag ---
    _dirty_flag = os.path.join(os.path.expanduser("~"), ".ostwin", ".agents", ".memory_config_dirty")
    if os.path.exists(_dirty_flag):
        try:
            os.remove(_dirty_flag)
            logger.info("Config-dirty flag detected, reloading config...")
            fresh_cfg = _load_config()
            fresh_fp = _config_fingerprint(fresh_cfg)
            if fresh_fp != _memory_config_fingerprint:
                logger.info(
                    "Config change detected (old=%s new=%s), reinitializing memory system...",
                    _memory_config_fingerprint,
                    fresh_fp,
                )
                _memory_ready.clear()
                _memory = None
                _memory_init_error = None
                _init_memory(cfg=fresh_cfg)
            else:
                logger.info("Config-dirty flag was set but config unchanged — skipping reinit")
        except Exception:
            logger.exception("Failed to reload config from dirty flag — using existing memory system")

    return _memory


GRAPH_GROUP_COLORS = [
    "#8b5cf6",
    "#facc15",
    "#2563eb",
    "#d4d4d8",
    "#16a34a",
    "#ff5d5d",
    "#14b8a6",
    "#f97316",
]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", value.lower().strip())
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug.strip("-") or "unfiled"


def _note_title(note) -> str:
    if note.name:
        return note.name
    return note.filename.replace("-", " ")


def _note_excerpt(note, max_length: int = 220) -> str:
    source = (note.summary or note.content or "").strip().replace("\n", " ")
    source = re.sub(r"\s+", " ", source)
    if len(source) <= max_length:
        return source
    return source[: max_length - 1].rstrip() + "…"


def _note_group_key(note) -> str:
    if note.path:
        return note.path.split("/")[0]
    if note.tags:
        return note.tags[0].lstrip("#")
    return "unfiled"


def _group_query(note, group_key: str) -> str:
    if note.path:
        return f'path:"{group_key}/"'
    if note.tags:
        return f"tag:{note.tags[0]}"
    return 'path:"unfiled/"'


def _collect_groups(notes) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Assign each note to a group, returning group order and metadata."""
    group_order: list[str] = []
    group_meta: dict[str, dict[str, Any]] = {}

    for note in notes:
        raw_group_key = _note_group_key(note)
        group_id = _slugify(raw_group_key)
        if group_id not in group_meta:
            color = GRAPH_GROUP_COLORS[len(group_meta) % len(GRAPH_GROUP_COLORS)]
            label = raw_group_key.replace("-", " ").replace("_", " ").title()
            group_meta[group_id] = {
                "id": group_id,
                "label": label,
                "query": _group_query(note, raw_group_key),
                "color": color,
                "pathPrefix": raw_group_key,
                "tag": note.tags[0] if note.tags else f"#{group_id}",
                "description": f"Notes grouped under {label.lower()}",
                "_count": 0,
            }
            group_order.append(group_id)
        group_meta[group_id]["_count"] += 1

    return group_order, group_meta


def _collect_links(notes) -> tuple[list[dict[str, Any]], int]:
    """Build deduplicated link list and count total forward links."""
    links: list[dict[str, Any]] = []
    link_pairs: set[tuple[str, str]] = set()
    total_forward_links = 0
    mem = get_memory()
    memories = mem.memories

    for note in notes:
        for target_id in note.links:
            if target_id not in memories:
                continue
            total_forward_links += 1
            pair = (note.id, target_id)
            if pair in link_pairs:
                continue
            link_pairs.add(pair)
            target = memories[target_id]
            overlap = len(set(note.tags) & set(target.tags))
            strength = 0.38 + min(0.5, overlap * 0.08 + len(target.backlinks) * 0.02)
            links.append(
                {
                    "source": note.id,
                    "target": target_id,
                    "strength": round(strength, 2),
                }
            )
    return links, total_forward_links


def _collect_nodes(notes, group_meta) -> list[dict[str, Any]]:
    """Build node list with group colors and weights.

    Content and summary are excluded to reduce memory allocation (F14).
    Clients that need full content should call read_memory() per-node.
    """
    nodes: list[dict[str, Any]] = []
    for note in notes:
        group_id = _slugify(_note_group_key(note))
        color = group_meta[group_id]["color"]
        connections = len(set(note.links + note.backlinks))
        weight = round(1.0 + min(2.4, connections * 0.25 + note.retrieval_count * 0.03), 2)
        nodes.append(
            {
                "id": note.id,
                "title": _note_title(note),
                "path": note.filepath,
                "pathLabel": note.path,
                "excerpt": _note_excerpt(note),
                "keywords": note.keywords,
                "tags": note.tags,
                "groupId": group_id,
                "color": color,
                "weight": weight,
                "connections": connections,
                "timestamp": note.timestamp,
                "retrievalCount": note.retrieval_count,
            }
        )
    return nodes


def _build_graph_snapshot() -> dict[str, Any]:
    notes = sorted(
        get_memory().memories.values(),
        key=lambda note: ((note.path or ""), _note_title(note), note.id),
    )

    if not notes:
        return {
            "groups": [],
            "nodes": [],
            "links": [],
            "stats": {
                "total_memories": 0,
                "total_links": 0,
                "persist_dir": PERSIST_DIR,
                "transport": "stdio",
            },
        }

    group_order, group_meta = _collect_groups(notes)
    links, total_forward_links = _collect_links(notes)
    nodes = _collect_nodes(notes, group_meta)

    groups = []
    for gid in group_order:
        group = dict(group_meta[gid])
        group["description"] = f"{group['_count']} notes in {group['label'].lower()}"
        del group["_count"]
        groups.append(group)

    return {
        "groups": groups,
        "nodes": nodes,
        "links": links,
        "stats": {
            "total_memories": len(nodes),
            "total_links": total_forward_links,
            "persist_dir": PERSIST_DIR,
            "transport": "stdio",
        },
    }


# --- MCP Server ---
mcp = FastMCP(
    "Agentic Memory",
    instructions="""You have access to a persistent memory system that stores knowledge as
interconnected notes organized in a directory tree. Use it to remember important information,
decisions, context, and learnings across conversations.

IMPORTANT GUIDELINES FOR WRITING MEMORIES:
- Write DETAILED, RICH memories. Don't just save a one-liner — include context, reasoning,
  examples, and nuance. A good memory is 3-10 sentences that capture the full picture.
- Think of each memory as a knowledge article that your future self will read. Include
  the WHY, not just the WHAT.
- Good memory: "PostgreSQL's JSONB type stores semi-structured data with full indexing
  support via GIN indexes. We chose it over MongoDB because our data has relational
  aspects (user->orders->items) but product attributes vary per category. The GIN index
  on product.attributes reduced our catalog search from 800ms to 12ms. Key gotcha:
  JSONB equality checks are exact-match, so normalize data before insertion."
- Bad memory: "Use PostgreSQL JSONB for product data."

The system automatically generates keywords, tags, directory paths, and links between
related memories. You can search by natural language — the richer your memories, the
better search results you'll get.""",
)


@optional_tool("save_memory")
def save_memory(
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

    The system will automatically:
    - Generate a name and directory path if not provided
    - Extract keywords and tags for semantic search
    - Find and link related existing memories
    - Create a summary for long content (>150 words)

    LLM analysis runs in a background thread (~10s) so this tool returns
    immediately with a stable UUID. The note appears in `search_memory` /
    `memory_tree` once analysis completes.

    Args:
        content: The memory content. Be detailed and thorough — include context,
            reasoning, specific examples, and lessons learned. Aim for 3-10 sentences
            minimum. Raw facts without context are far less useful when retrieved later.
        name: Optional human-readable name (2-5 words). Auto-generated if not provided.
        path: Optional directory path (e.g. "backend/database", "devops/ci-cd").
            Auto-generated if not provided.
        tags: Optional list of tags. Auto-generated if not provided.

    Returns:
        JSON with the saved memory's id and accepted status. Background analysis
        fills in keywords/tags/links/summary asynchronously.
    """
    import uuid as _uuid

    kwargs = {}
    if name:
        kwargs["name"] = name
    if path:
        kwargs["path"] = path
    if tags:
        kwargs["tags"] = tags

    # Pre-generate the ID so the client gets a stable handle immediately,
    # before the slow LLM analysis runs in the background.
    memory_id = str(_uuid.uuid4())
    kwargs["id"] = memory_id

    logger.info(
        "save_memory: id=%s name=%s path=%s tags=%s content_len=%d",
        memory_id,
        name,
        path,
        tags,
        len(content),
    )

    # Resolve the memory system synchronously so we can fail fast with a
    # useful error if init is broken (rather than swallowing it in a thread).
    mem = get_memory()

    # In stdio mode the server process exits as soon as the response is sent,
    # so background threads get killed before they can finish. Run synchronously
    # so the note is on disk before we return. This adds ~10s latency for the
    # LLM analysis, but is the only way to guarantee persistence in stdio mode.
    try:
        mem.add_note(content, **kwargs)
        note = mem.read(memory_id)
        if note is not None:
            logger.info(
                "save_memory: completed id=%s name=%s path=%s",
                note.id,
                note.name,
                note.path,
            )
        else:
            logger.warning("save_memory: note %s not found after add_note", memory_id)
    except Exception:
        logger.exception("save_memory: failed for id=%s", memory_id)
        return json.dumps(
            {
                "id": memory_id,
                "status": "error",
                "message": "Failed to save memory. See server log for details.",
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "id": memory_id,
            "status": "saved",
            "message": "Memory saved to disk with full LLM analysis.",
        },
        ensure_ascii=False,
    )


@optional_tool("search_memory")
def search_memory(query: str, k: int = 5) -> str:
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
    logger.info("search_memory: query=%r k=%d", query, k)
    mem = get_memory()
    results = mem.search(query, k=k)
    logger.info("search_memory: returned %d results", len(results))
    output = []
    for r in results:
        note = mem.read(r["id"])
        entry = {
            "id": r["id"],
            "name": note.name if note else None,
            "path": note.path if note else None,
            "content": r["content"],
            "tags": r.get("tags", []),
            "keywords": r.get("keywords", []),
            "links": note.links if note else [],
            "backlinks": note.backlinks if note else [],
        }
        output.append(entry)

    return json.dumps(output, ensure_ascii=False)


@optional_tool("read_memory")
def read_memory(memory_id: str) -> str:
    """Read a specific memory note by its ID.

    Returns the full content and all metadata for a single memory.

    Args:
        memory_id: The UUID of the memory to read.

    Returns:
        JSON with full memory content and metadata, or error if not found.
    """
    logger.info("read_memory: id=%s", memory_id)
    note = get_memory().read(memory_id)
    if not note:
        logger.warning("read_memory: not found id=%s", memory_id)
        return json.dumps({"error": f"Memory {memory_id} not found"})

    logger.info("read_memory: found name=%s", note.name)
    return json.dumps(
        {
            "id": note.id,
            "name": note.name,
            "path": note.path,
            "content": note.content,
            "summary": note.summary,
            "keywords": note.keywords,
            "tags": note.tags,
            "links": note.links,
            "backlinks": note.backlinks,
            "timestamp": note.timestamp,
            "last_accessed": note.last_accessed,
            "retrieval_count": note.retrieval_count,
        },
        ensure_ascii=False,
    )


@optional_tool("update_memory")
def update_memory(
    memory_id: str,
    content: Optional[str] = None,
    name: Optional[str] = None,
    path: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> str:
    """Update an existing memory note.

    When content changes, all metadata (name, path, keywords, tags, summary)
    is automatically re-generated. The old file is cleaned up if the path changes.

    Use this to enrich existing memories with new information, corrections,
    or additional context discovered later.

    Args:
        memory_id: The UUID of the memory to update.
        content: New content (triggers full re-analysis if changed).
        name: New name override.
        path: New path override.
        tags: New tags override.

    Returns:
        JSON with updated memory metadata, or error if not found.
    """
    kwargs = {}
    if content is not None:
        kwargs["content"] = content
    if name is not None:
        kwargs["name"] = name
    if path is not None:
        kwargs["path"] = path
    if tags is not None:
        kwargs["tags"] = tags

    if not kwargs:
        return json.dumps({"error": "No fields to update"})

    logger.info("update_memory: id=%s fields=%s", memory_id, list(kwargs.keys()))
    success = get_memory().update(memory_id, **kwargs)
    if not success:
        logger.warning("update_memory: not found id=%s", memory_id)
        return json.dumps({"error": f"Memory {memory_id} not found"})

    note = get_memory().read(memory_id)
    logger.info("update_memory: updated id=%s name=%s", note.id, note.name)
    return json.dumps(
        {
            "id": note.id,
            "name": note.name,
            "path": note.path,
            "filepath": note.filepath,
            "tags": note.tags,
            "has_summary": note.summary is not None,
        },
        ensure_ascii=False,
    )


@optional_tool("delete_memory")
def delete_memory(memory_id: str) -> str:
    """Delete a memory note and clean up all its links.

    This removes the memory from the knowledge base, deletes its markdown file,
    and cleans up all forward links and backlinks in related memories.

    Args:
        memory_id: The UUID of the memory to delete.

    Returns:
        JSON confirmation or error.
    """
    logger.info("delete_memory: id=%s", memory_id)
    success = get_memory().delete(memory_id)
    if not success:
        logger.warning("delete_memory: not found id=%s", memory_id)
        return json.dumps({"error": f"Memory {memory_id} not found"})
    logger.info("delete_memory: deleted id=%s", memory_id)
    return json.dumps({"deleted": memory_id})


@optional_tool("link_memories")
def link_memories(from_id: str, to_id: str) -> str:
    """Create a directional link between two memories.

    Links represent active, intentional connections. Backlinks are auto-maintained.
    Use this when you discover a relationship between two memories that the
    automatic evolution didn't catch.

    Args:
        from_id: Source memory ID (the one that "points to" the other).
        to_id: Target memory ID (the one being "pointed at").

    Returns:
        JSON confirmation with updated link info.
    """
    logger.info("link_memories: %s -> %s", from_id, to_id)
    get_memory().add_link(from_id, to_id)
    from_note = get_memory().read(from_id)
    to_note = get_memory().read(to_id)
    if not from_note or not to_note:
        return json.dumps({"error": "One or both memories not found"})

    return json.dumps(
        {
            "linked": f"{from_note.name} -> {to_note.name}",
            "from_links": from_note.links,
            "to_backlinks": to_note.backlinks,
        },
        ensure_ascii=False,
    )


@optional_tool("unlink_memories")
def unlink_memories(from_id: str, to_id: str) -> str:
    """Remove a link between two memories. Backlink is auto-removed.

    Args:
        from_id: Source memory ID.
        to_id: Target memory ID.

    Returns:
        JSON confirmation.
    """
    logger.info("unlink_memories: %s -> %s", from_id, to_id)
    get_memory().remove_link(from_id, to_id)
    return json.dumps({"unlinked": f"{from_id} -> {to_id}"})


@optional_tool("memory_tree")
def memory_tree() -> str:
    """Show the full directory tree of all memories.

    Returns a tree-like visualization of how memories are organized,
    similar to the `tree` command. Useful for understanding the knowledge
    structure and finding where to place new memories.

    Returns:
        Tree-formatted string of the memory directory structure.
    """
    return get_memory().tree()


@optional_tool("memory_stats")
def memory_stats() -> str:
    """Get statistics about the memory system.

    Returns:
        JSON with total count, directory paths, and link statistics.
    """
    mem = get_memory()
    total = len(mem.memories)
    paths = sorted({m.path for m in mem.memories.values() if m.path})
    total_links = sum(len(m.links) for m in mem.memories.values())
    total_backlinks = sum(len(m.backlinks) for m in mem.memories.values())

    return json.dumps(
        {
            "total_memories": total,
            "unique_paths": len(paths),
            "paths": paths,
            "total_links": total_links,
            "total_backlinks": total_backlinks,
            "persist_dir": PERSIST_DIR,
        },
        ensure_ascii=False,
    )


@optional_tool("sync_from_disk")
def sync_from_disk() -> str:
    """Sync: reload memories from disk files into the running system.

    Reads all markdown files from the persistent directory and updates the
    in-memory state and vector index to match what's on disk.

    Use this when:
    - You manually added/edited/deleted .md files in the notes folder
    - Another process modified the memory files
    - You suspect the in-memory state is stale

    Caveats:
    - Disk wins: if a file was edited, the disk version overwrites memory.
    - Notes deleted from disk are removed from memory.
    - New .md files on disk are added to memory.
    - Vector index is fully rebuilt (may take a moment for large databases).

    Returns:
        JSON with counts of added, updated, and removed notes.
    """
    logger.info("sync_from_disk: starting")
    result = get_memory().sync_from_disk()
    logger.info("sync_from_disk: %s", result)
    return json.dumps(result, ensure_ascii=False)


@optional_tool("sync_to_disk")
def sync_to_disk() -> str:
    """Sync: write current in-memory state to disk files.

    Saves all memories as markdown files and removes any orphan files
    on disk that don't correspond to a memory in the running system.

    Use this when:
    - You want to ensure disk matches the current state exactly
    - You suspect some file writes may have failed
    - You want to clean up stale files after bulk operations

    Returns:
        JSON with counts of written files and orphans removed.
    """
    logger.info("sync_to_disk: starting")
    result = get_memory().sync_to_disk()
    logger.info("sync_to_disk: %s", result)
    return json.dumps(result, ensure_ascii=False)


@optional_tool("graph_snapshot")
def graph_snapshot() -> str:
    """Return graph-ready memory data for UI clients.

    This is intended for visual frontends that need the whole vault graph:
    groups, nodes, links, and basic note metadata. It avoids forcing the UI
    to call `read_memory` repeatedly just to render the graph.

    Returns:
        JSON with groups, nodes, links, and graph stats.
    """
    return json.dumps(_build_graph_snapshot(), ensure_ascii=False)


def _auto_sync_loop(interval: int):
    """Background thread that periodically syncs memory to disk."""
    while True:
        _sync_stop_event.wait(interval)
        if _sync_stop_event.is_set():
            break
        # Only sync if memory system has been initialized
        if _memory is not None:
            try:
                result = _memory.sync_to_disk()
                logger.info("Auto-sync to disk: %s", result)
            except Exception:
                logger.exception("Auto-sync to disk failed")


_sync_stop_event = threading.Event()
_sync_thread: threading.Thread | None = None

if AUTO_SYNC_ENABLED:
    _sync_thread = threading.Thread(
        target=_auto_sync_loop,
        args=(AUTO_SYNC_INTERVAL,),
        daemon=True,
        name="memory-auto-sync",
    )
    _sync_thread.start()
    logger.info("Auto-sync enabled: every %ds", AUTO_SYNC_INTERVAL)


def _get_notes_dir() -> str:
    notes_dir = os.path.join(os.path.abspath(PERSIST_DIR), "notes")
    os.makedirs(notes_dir, exist_ok=True)
    return notes_dir


_SAFE_GREP_FLAGS = frozenset(
    {
        "-i",
        "-n",
        "-l",
        "-c",
        "-w",
        "-v",
        "-E",
        "-P",
        "-F",
        "-o",
        "-h",
        "-H",
        "-m",
        "-q",
        "-s",
        "-x",
        "-z",
    }
)
_SAFE_GREP_PREFIXED = frozenset({"-A", "-B", "-C", "-m"})


def _sanitize_grep_flags(flags: str) -> tuple:
    """Validate and sanitize grep flags. Returns (sanitized_list, error_msg)."""
    parsed = flags.split()
    sanitized: list = []
    i = 0
    while i < len(parsed):
        f = parsed[i]
        if f.startswith("--include") or f.startswith("--exclude") or f in {"-r", "-R", "--recursive"}:
            return (
                [],
                f"Error: flag '{f}' is not allowed — file scope is fixed to .md files in the notes directory.",
            )
        if f in _SAFE_GREP_FLAGS:
            sanitized.append(f)
        elif f in _SAFE_GREP_PREFIXED:
            sanitized.append(f)
            if i + 1 < len(parsed):
                i += 1
                sanitized.append(parsed[i])
        elif f.startswith("-") and len(f) > 1 and all(f"-{ch}" in _SAFE_GREP_FLAGS for ch in f[1:]):
            sanitized.append(f)
        elif f.startswith("-"):
            return [], f"Error: unsupported grep flag '{f}'."
        i += 1
    return sanitized, ""


@optional_tool("grep_memory")
def grep_memory(pattern: str, flags: Optional[str] = None) -> str:
    """Search memory files using grep (full CLI grep).

    Runs grep on all markdown files in the memory notes directory.

    Examples:
        grep_memory("PostgreSQL")                    -- basic search
        grep_memory("oauth.*token", "-i")            -- case-insensitive regex
        grep_memory("TODO", "-l")                    -- list filenames only
        grep_memory("error", "-c")                   -- count matches per file
        grep_memory("BEGIN", "-A 3")                 -- show 3 lines after match
        grep_memory("docker|kubernetes", "-E")       -- extended regex (OR)

    Args:
        pattern: Search pattern (string or regex depending on flags).
        flags: Optional grep flags as a single string (-i, -n, -l, -c, -w, -v, -E, -P, -A N, -B N, -C N).

    Returns:
        Grep output with paths relative to notes directory.
    """
    notes_dir = _get_notes_dir()
    cmd = ["grep", "-r", "--include=*.md"]
    if flags:
        sanitized, err = _sanitize_grep_flags(flags)
        if err:
            return err
        cmd.extend(sanitized)
    cmd.extend(["-e", pattern, "--", notes_dir])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if not result.stdout and result.returncode == 1:
            return "No matches found."
        if result.returncode > 1:
            return f"Error: {result.stderr.strip()}"
        return result.stdout.replace(notes_dir + "/", "")
    except subprocess.TimeoutExpired:
        return "Error: grep timed out after 30 seconds."
    except FileNotFoundError:
        return "Error: grep command not found on this system."


_SAFE_FIND_FLAGS = frozenset(
    {
        "-name",
        "-iname",
        "-type",
        "-size",
        "-mtime",
        "-mmin",
        "-maxdepth",
        "-mindepth",
        "-empty",
        "-path",
        "-ipath",
        "-newer",
        "-not",
        "!",
        "-a",
        "-o",
        "(",
        ")",
    }
)
_DANGEROUS_FIND_PREFIXES = ("-exec", "-delete", "-ok", "-fls", "-fprint", "-fprintf")


def _validate_find_args(args: str) -> tuple:
    """Validate find arguments. Returns (parsed_tokens, error_msg)."""
    import shlex

    parsed = shlex.split(args)
    for token in parsed:
        if token.startswith("/") or token.startswith("~"):
            return (
                [],
                "Error: absolute paths are not allowed — search is restricted to the notes directory.",
            )
        if any(token.startswith(dp) for dp in _DANGEROUS_FIND_PREFIXES):
            return [], f"Error: '{token}' is not allowed for security reasons."
        if token.startswith("-") and token not in _SAFE_FIND_FLAGS:
            if not any(token.startswith(sf) for sf in _SAFE_FIND_FLAGS):
                return (
                    [],
                    f"Error: unsupported find flag '{token}'. Allowed: {', '.join(sorted(_SAFE_FIND_FLAGS))}",
                )
    return parsed, ""


@optional_tool("find_memory")
def find_memory(args: Optional[str] = None) -> str:
    """Search memory files using find (full CLI find).

    Runs find on the memory notes directory.

    Examples:
        find_memory()                                -- list all files
        find_memory("-name '*.md'")                  -- find by name pattern
        find_memory("-type d")                       -- list directories only
        find_memory("-name '*database*'")            -- find files matching pattern
        find_memory("-size +1k")                     -- files larger than 1KB
        find_memory("-mmin -60")                     -- modified in last 60 minutes
        find_memory("-maxdepth 2 -type d")           -- directories, max 2 levels deep
        find_memory("-path '*/database/*'")          -- files under database/ path

    Args:
        args: Optional find arguments as a single string (-name, -type, -size, -mtime, -mmin, -maxdepth, -empty, -path, -iname).

    Returns:
        Find output with paths relative to notes directory.
    """
    notes_dir = _get_notes_dir()
    cmd = ["find", notes_dir]
    if args:
        parsed, err = _validate_find_args(args)
        if err:
            return err
        cmd.extend(parsed)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0 and result.stderr:
            return f"Error: {result.stderr.strip()}"
        if not result.stdout.strip():
            return "No results found."
        return result.stdout.replace(notes_dir + "/", "").replace(notes_dir, ".")
    except subprocess.TimeoutExpired:
        return "Error: find timed out after 30 seconds."
    except FileNotFoundError:
        return "Error: find command not found on this system."


@optional_tool("find_notes_by_knowledge_link")
def find_notes_by_knowledge_link(
    namespace: str,
    file_hash: str,
    chunk_idx: Optional[int] = None,
) -> str:
    """Find memory notes that link to a specific knowledge chunk.

    This is the reverse lookup for knowledge:// links. Given a namespace,
    file_hash, and optionally a chunk index, returns all memory notes
    that cite that knowledge chunk.

    Args:
        namespace: The knowledge namespace (e.g., "docs", "api")
        file_hash: SHA256 hash of the source file (truncated)
        chunk_idx: Optional chunk index. If None, matches any chunk in the file.

    Returns:
        JSON array of matching note IDs. Empty array if no matches.
    """
    logger.info(
        "find_notes_by_knowledge_link: ns=%s hash=%s idx=%s",
        namespace,
        file_hash,
        chunk_idx,
    )

    mem = get_memory()
    matching_ids = []

    # Build the link prefix to search for
    if chunk_idx is not None:
        target_prefix = f"knowledge://{namespace}/{file_hash}#{chunk_idx}"
    else:
        target_prefix = f"knowledge://{namespace}/{file_hash}#"

    for note_id, note in mem.memories.items():
        if not note.links:
            continue
        for link in note.links:
            if not link.startswith("knowledge://"):
                continue
            if chunk_idx is not None:
                # Exact match
                if link == target_prefix:
                    matching_ids.append(note_id)
                    break
            else:
                # Prefix match (any chunk in this file)
                if link.startswith(target_prefix):
                    matching_ids.append(note_id)
                    break

    logger.info(
        "find_notes_by_knowledge_link: found %d notes",
        len(matching_ids),
    )

    return json.dumps(matching_ids, ensure_ascii=False)


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse"],
        help="MCP transport: stdio (default) or sse (persistent HTTP daemon)",
    )
    parser.add_argument("--port", type=int, default=6463, help="Port for SSE transport (default: 6463)")
    parser.add_argument("--host", default="127.0.0.1", help="Host for SSE transport")
    args = parser.parse_args()

    if args.transport == "sse":
        logger.info("Starting SSE transport on %s:%d", args.host, args.port)
        # Reconfigure the FastMCP instance with the desired host/port
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
