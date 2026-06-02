#!/usr/bin/env python3
"""Global Memory MCP Server — provides cross-project memory access for the manager role.

This MCP server gives the manager agent read-only access to memories across ALL
plans and projects, enabling it to:
1. Learn from past decisions and patterns
2. Track cross-project knowledge
3. Understand historical context
4. Monitor plan progress through saved memories

Mounted at: /api/global-memory/mcp (remote MCP over HTTP)
Tools provided: global_memory_search, global_memory_tree, global_memory_stats,
                global_memory_list_plans, global_memory_grep

The manager can use this to answer questions like:
- "What did we learn about authentication patterns?"
- "What are the recurring issues across projects?"
- "What decisions were made about database design?"
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# sys.path setup for memory module
# ---------------------------------------------------------------------------
_MEMORY_PATH_CANDIDATES = [
    Path.home() / ".ostwin" / ".agents" / "memory",
    Path(__file__).resolve().parent.parent / "memory",
]
for _p in _MEMORY_PATH_CANDIDATES:
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# ---------------------------------------------------------------------------
# Global memory base directory
# ---------------------------------------------------------------------------
MEMORY_BASE_DIR: Path = Path(
    os.environ.get("OSTWIN_MEMORY_DIR", str(Path.home() / ".ostwin" / "memory"))
)

# ---------------------------------------------------------------------------
# Lazy imports to keep startup fast
# ---------------------------------------------------------------------------
AgenticMemorySystem = None
_memory_systems: dict[str, Any] = {}
_memory_lock = threading.Lock()


def _get_all_plan_dirs() -> list[Path]:
    """Return all plan directories under MEMORY_BASE_DIR.

    Convention: ~/.ostwin/memory/<plan_id>/
    Directories starting with underscore (e.g., _global, _default) are excluded.
    Legacy ``memory-<plan_id>`` directories are also discovered for migration.
    """
    if not MEMORY_BASE_DIR.is_dir():
        return []
    excluded = {"_global", "_default"}
    return [
        d
        for d in MEMORY_BASE_DIR.iterdir()
        if d.is_dir() and d.name not in excluded and not d.name.startswith(".")
    ]


def _dir_to_plan_id(dir_name: str) -> str:
    """Extract plan_id from a MEMORY_BASE_DIR subdirectory name.

    Convention: directory name IS the plan_id.
    Legacy ``memory-`` prefix is stripped for backward compat.
    """
    if dir_name == "_global":
        return "_global"
    if dir_name.startswith("memory-"):
        return dir_name[len("memory-") :]
    return dir_name


def _get_global_dir() -> Path:
    """Return the global memory directory."""
    return MEMORY_BASE_DIR / "_global"


def _plan_id_to_dir(plan_id: str) -> Path:
    """Resolve a plan_id to its MEMORY_BASE_DIR subdirectory.

    Convention: ~/.ostwin/memory/<plan_id>/
    Falls back to legacy ``memory-<plan_id>`` for backward compat.
    """
    # Current convention: bare plan_id
    current = MEMORY_BASE_DIR / plan_id
    if current.is_dir():
        return current
    # Legacy fallback: memory-<plan_id>
    legacy = MEMORY_BASE_DIR / f"memory-{plan_id}"
    if legacy.is_dir():
        return legacy
    # Return current convention path even if it doesn't exist yet
    return current


def _get_or_create_memory_system(persist_dir: Path) -> Any:
    """Get or create an AgenticMemorySystem for the given directory."""
    global AgenticMemorySystem

    persist_str = str(persist_dir)

    with _memory_lock:
        if persist_str in _memory_systems:
            return _memory_systems[persist_str]

        if AgenticMemorySystem is None:
            from dashboard.agentic_memory.memory_system import (
                AgenticMemorySystem as _AMS,
            )

            AgenticMemorySystem = _AMS

        from dashboard.agentic_memory.config import load_config

        cfg = load_config()

        system = AgenticMemorySystem(
            model_name=cfg.embedding.model,
            embedding_backend=cfg.embedding.backend,
            vector_backend=cfg.vector.backend,
            llm_backend=cfg.llm.backend,
            llm_model=cfg.llm.model,
            persist_dir=persist_str,
            context_aware_analysis=cfg.evolution.context_aware,
            context_aware_tree=cfg.evolution.context_aware_tree,
            max_links=cfg.evolution.max_links,
            similarity_weight=cfg.search.similarity_weight,
            decay_half_life_days=cfg.search.decay_half_life_days,
            conflict_resolution=cfg.sync.conflict_resolution,
        )
        _memory_systems[persist_str] = system
        return system


# ---------------------------------------------------------------------------
# FastMCP instance
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "ostwin-global-memory",
    instructions="""You have READ-ONLY access to the global memory system that spans ALL plans
and projects in the Ostwin system. Use this to:

1. Search for patterns and learnings across all projects
2. Find historical decisions and their rationale
3. Track recurring issues and their resolutions
4. Understand cross-project dependencies and relationships

This is a READ-ONLY view — you cannot modify memories through this interface.
To save new memories, use the project-specific memory tools instead.

Query examples:
- "What authentication patterns have we used?"
- "What database decisions were made across projects?"
- "What are common gotchas we've documented?"
- "What testing strategies work best?"
""",
)


@mcp.tool()
def global_memory_search(
    query: str, k: int = 10, plans: Optional[list[str]] = None
) -> str:
    """Search memories across ALL plans/projects.

    This searches the global memory pool and all plan-specific memories,
    returning the most relevant results aggregated from all namespaces.

    Args:
        query: Natural language search query. Be specific for best results.
        k: Maximum results per namespace (default 10).
        plans: Optional list of specific plan IDs to search. If None, searches all.

    Returns:
        JSON array of matching memories with plan_id, content, tags, and metadata.
    """
    logger.info("global_memory_search: query=%r k=%d plans=%s", query, k, plans)

    all_results = []

    # Determine which directories to search
    if plans:
        dirs_to_search = [_plan_id_to_dir(p) for p in plans]
        dirs_to_search = [d for d in dirs_to_search if d.is_dir()]
    else:
        dirs_to_search = _get_all_plan_dirs()

    # Always include global
    global_dir = _get_global_dir()
    if global_dir.is_dir() and global_dir not in dirs_to_search:
        dirs_to_search.insert(0, global_dir)

    for plan_dir in dirs_to_search:
        try:
            system = _get_or_create_memory_system(plan_dir)
            results = system.search(query, k=k)

            plan_id = _dir_to_plan_id(plan_dir.name)
            for r in results:
                note = system.read(r["id"])
                all_results.append(
                    {
                        "plan_id": plan_id,
                        "id": r["id"],
                        "name": note.name if note else None,
                        "path": note.path if note else None,
                        "content": r["content"],
                        "tags": r.get("tags", []),
                        "keywords": r.get("keywords", []),
                        "links": note.links if note else [],
                    }
                )
        except Exception as e:
            logger.warning("Failed to search %s: %s", plan_dir, e)

    # Sort by relevance (could implement cross-namespace ranking here)
    # For now, just return up to k*len(dirs) results
    return json.dumps(all_results[: k * len(dirs_to_search)], ensure_ascii=False)


@mcp.tool()
def global_memory_tree() -> str:
    """Show the directory tree of ALL memories across all plans.

    Returns a hierarchical view of how memories are organized across
    all plan namespaces, useful for understanding the overall knowledge
    structure.

    Returns:
        Tree-formatted string of all memory directories.
    """
    lines = [f"Global Memory Root: {MEMORY_BASE_DIR}"]

    all_dirs = [_get_global_dir()] + _get_all_plan_dirs()

    for plan_dir in sorted(all_dirs, key=lambda d: d.name):
        if not plan_dir.is_dir():
            continue
        plan_id = _dir_to_plan_id(plan_dir.name)
        lines.append(f"\n[{plan_id}]")

        try:
            system = _get_or_create_memory_system(plan_dir)
            tree = system.tree()
            # Indent the tree
            for line in tree.split("\n")[:50]:  # Limit output
                lines.append(f"  {line}")
        except Exception as e:
            lines.append(f"  Error: {e}")

    return "\n".join(lines)


@mcp.tool()
def global_memory_stats() -> str:
    """Get statistics about all memory namespaces.

    Returns counts of memories, links, and paths for each plan namespace.

    Returns:
        JSON with per-namespace and aggregate statistics.
    """
    stats = {
        "memory_base_dir": str(MEMORY_BASE_DIR),
        "namespaces": [],
        "aggregate": {
            "total_memories": 0,
            "total_links": 0,
            "namespace_count": 0,
        },
    }

    all_dirs = [_get_global_dir()] + _get_all_plan_dirs()

    for plan_dir in all_dirs:
        if not plan_dir.is_dir():
            continue

        plan_id = _dir_to_plan_id(plan_dir.name)

        try:
            system = _get_or_create_memory_system(plan_dir)
            total = len(system.memories)
            links = sum(len(m.links) for m in system.memories.values())
            paths = sorted({m.path for m in system.memories.values() if m.path})

            stats["namespaces"].append(
                {
                    "plan_id": plan_id,
                    "total_memories": total,
                    "total_links": links,
                    "unique_paths": len(paths),
                }
            )
            stats["aggregate"]["total_memories"] += total
            stats["aggregate"]["total_links"] += links
            stats["aggregate"]["namespace_count"] += 1
        except Exception as e:
            stats["namespaces"].append(
                {
                    "plan_id": plan_id,
                    "error": str(e),
                }
            )

    return json.dumps(stats, ensure_ascii=False)


@mcp.tool()
def global_memory_list_plans() -> str:
    """List all plan namespaces with memory data.

    Returns the plan IDs and their memory counts, useful for discovering
    what projects have stored memories.

    Returns:
        JSON array of {plan_id, memory_count, last_modified}.
    """
    plans = []

    all_dirs = [_get_global_dir()] + _get_all_plan_dirs()

    for plan_dir in sorted(all_dirs, key=lambda d: d.name):
        if not plan_dir.is_dir():
            continue

        plan_id = _dir_to_plan_id(plan_dir.name)

        try:
            system = _get_or_create_memory_system(plan_dir)
            # Get last modified from notes directory
            notes_dir = plan_dir / "notes"
            last_mod = 0
            if notes_dir.is_dir():
                for f in notes_dir.rglob("*.md"):
                    last_mod = max(last_mod, f.stat().st_mtime)

            plans.append(
                {
                    "plan_id": plan_id,
                    "memory_count": len(system.memories),
                    "last_modified": last_mod,
                }
            )
        except Exception as e:
            plans.append(
                {
                    "plan_id": plan_id,
                    "error": str(e),
                }
            )

    return json.dumps(plans, ensure_ascii=False)


@mcp.tool()
def global_memory_grep(pattern: str, flags: Optional[str] = None) -> str:
    """Search memory files across ALL plans using grep.

    Runs grep on all markdown files in all memory namespaces.

    Args:
        pattern: Search pattern (string or regex depending on flags).
        flags: Optional grep flags (-i, -n, -l, -c, etc.).

    Returns:
        Grep output with plan_id prefixes.
    """
    results = []

    all_dirs = [_get_global_dir()] + _get_all_plan_dirs()

    for plan_dir in all_dirs:
        if not plan_dir.is_dir():
            continue

        plan_id = _dir_to_plan_id(plan_dir.name)
        notes_dir = plan_dir / "notes"

        if not notes_dir.is_dir():
            continue

        cmd = ["grep", "-r", "--include=*.md"]
        if flags:
            cmd.extend(flags.split())
        cmd.extend(["-e", pattern, "--", str(notes_dir)])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.stdout:
                for line in result.stdout.strip().split("\n")[
                    :20
                ]:  # Limit per namespace
                    # Replace full path with plan_id
                    line = line.replace(str(notes_dir) + "/", f"[{plan_id}]/")
                    results.append(line)
        except subprocess.TimeoutExpired:
            results.append(f"[{plan_id}] ERROR: grep timed out")
        except FileNotFoundError:
            results.append(f"[{plan_id}] ERROR: grep not found")

    if not results:
        return "No matches found across all namespaces."

    return "\n".join(results[:100])  # Limit total output


@mcp.tool()
def global_memory_read(memory_id: str, plan_id: Optional[str] = None) -> str:
    """Read a specific memory note by ID.

    If plan_id is provided, searches only that namespace.
    Otherwise, searches all namespaces for the memory.

    Args:
        memory_id: The UUID of the memory to read.
        plan_id: Optional plan namespace to search in.

    Returns:
        JSON with full memory content and metadata.
    """
    dirs_to_search = []

    if plan_id:
        if plan_id == "_global":
            dirs_to_search = [_get_global_dir()]
        else:
            dirs_to_search = [_plan_id_to_dir(plan_id)]
    else:
        dirs_to_search = [_get_global_dir()] + _get_all_plan_dirs()

    for plan_dir in dirs_to_search:
        if not plan_dir.is_dir():
            continue

        try:
            system = _get_or_create_memory_system(plan_dir)
            note = system.read(memory_id)

            if note:
                found_plan_id = _dir_to_plan_id(plan_dir.name)
                return json.dumps(
                    {
                        "plan_id": found_plan_id,
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
                        "retrieval_count": note.retrieval_count,
                    },
                    ensure_ascii=False,
                )
        except Exception as e:
            logger.debug("Failed to read from %s: %s", plan_dir, e)

    return json.dumps({"error": f"Memory {memory_id} not found in any namespace"})


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse"],
        help="MCP transport: stdio (default) or sse",
    )
    parser.add_argument("--port", type=int, default=6470)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.transport == "sse":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
