"""Dashboard API routes for Agentic Memory.

Reads memory data from the centralized ~/.ostwin/memory/{plan_id}/
directory to serve graph snapshots, memory notes, and search results to the frontend.
"""

import os

from fastapi import APIRouter, HTTPException, Depends
from pathlib import Path
from typing import Annotated, Optional
import asyncio
import json
import re
import sys

from dashboard.api_utils import PLANS_DIR, GLOBAL_PLANS_DIR, find_plan_file
from dashboard.auth import get_current_user

MEMORY_BASE_DIR = Path(os.environ.get("OSTWIN_MEMORY_DIR", str(Path.home() / ".ostwin" / "memory")))

# Reuse the canonical note parser from the co-located agentic_memory package
# instead of duplicating the YAML/frontmatter logic. We import from `memory_note`
# (not `memory_system`) to avoid pulling in the heavy retriever stack
# (chromadb, nltk, litellm) at dashboard startup.

try:
    from dashboard.agentic_memory.memory_note import MemoryNote  # type: ignore
except ImportError:
    MemoryNote = None  # type: ignore

router = APIRouter(tags=["amem"])


def _resolve_memory_dir(plan_id: str) -> Optional[Path]:
    """Resolve the centralized memory directory for a plan.

    Resolution order:
    1. ~/.ostwin/memory/{plan_id}/          (Plan 009 format — no prefix)
    2. ~/.ostwin/memory/memory-{plan_id}/   (legacy format)
    3. Plan's working_dir/.memory/          (follows symlink)
    4. None
    """
    # Plan 009: direct plan_id directory
    direct = MEMORY_BASE_DIR / plan_id
    if direct.exists():
        return direct
    # Legacy: memory-{plan_id} prefix
    legacy = MEMORY_BASE_DIR / f"memory-{plan_id}"
    if legacy.exists():
        return legacy
    # Fallback: look up plan's working_dir and follow .memory symlink
    plan_meta = PLANS_DIR / f"{plan_id}.meta.json"
    if plan_meta.exists():
        try:
            meta = json.loads(plan_meta.read_text())
            wdir = meta.get("working_dir")
            if wdir:
                mem_path = Path(wdir) / ".memory"
                if mem_path.exists():
                    return mem_path.resolve()
        except Exception:
            pass
    return None


def _require_memory_dir(plan_id: str) -> Path:
    """Resolve memory dir or raise 404."""
    mem_dir = _resolve_memory_dir(plan_id)
    if mem_dir is None:
        raise HTTPException(status_code=404, detail=f"No memory found for plan {plan_id}")
    return mem_dir


def _parse_legacy_metadata(text: str) -> tuple[list[str], list[str], list[str]]:
    """Extract Tags/Keywords/Links from **bold-label**: lines in raw markdown."""
    tags: list[str] = []
    keywords: list[str] = []
    links: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        for label, target in [
            ("**Tags**:", tags),
            ("**Keywords**:", keywords),
            ("**Links**:", links),
        ]:
            if stripped.startswith(label):
                value = stripped[len(label) :].strip()
                items = [v.strip().lstrip("#") for v in value.split(",") if v.strip()]
                target.extend(items)
    return tags, keywords, links


def _stub_note_dict(
    md_file: Path,
    rel_path: str,
    rel_file: str,
    body: str,
    raw: str,
) -> dict:
    """Build a minimal note dict when frontmatter parsing is unavailable."""
    tags, keywords, links = _parse_legacy_metadata(raw)
    title = _resolve_title(None, body, md_file)
    return {
        "id": md_file.stem,
        "filename": md_file.name,
        "path": rel_path,
        "relativePath": rel_file,
        "title": title,
        "body": body,
        "content": raw,
        "excerpt": body[:280],
        "tags": tags,
        "keywords": keywords,
        "links": links,
        "context": None,
        "summary": None,
        "category": None,
        "timestamp": None,
        "last_accessed": None,
        "retrieval_count": 0,
    }


def _extract_excerpt(body: str) -> str:
    """Build a short excerpt from body text, skipping headings and code fences."""
    excerpt_lines: list[str] = []
    in_code = False
    for ln in body.split("\n"):
        stripped = ln.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not stripped or stripped.startswith("#"):
            continue
        excerpt_lines.append(stripped)
        if sum(len(s) for s in excerpt_lines) > 280:
            break
    return " ".join(excerpt_lines)[:280]


def _resolve_relative_paths(md_file: Path, notes_dir: Path) -> tuple[str, str]:
    """Compute relative path and relative file from a note's md_file."""
    try:
        rel_path = str(md_file.parent.relative_to(notes_dir))
        rel_file = str(md_file.relative_to(notes_dir))
    except ValueError:
        rel_path = md_file.parent.name
        rel_file = md_file.name
    return rel_path, rel_file


def _resolve_title(note_name: Optional[str], body: str, md_file: Path) -> str:
    """Derive a title from frontmatter name, first H1, or filename slug."""
    title = (note_name or "").strip()
    if not title:
        h1 = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        title = h1.group(1).strip() if h1 else md_file.stem.replace("-", " ").replace("_", " ").title()
    return title


def _note_to_dict(md_file: Path, notes_dir: Path) -> Optional[dict]:
    """Read a single markdown file and convert it to the dashboard's wire shape.

    Delegates frontmatter parsing to ``MemoryNote.from_markdown`` so we share
    one parser with the memory system. Falls back to a minimal stub if
    the import is unavailable (shouldn't happen at runtime, but defensive).
    """
    try:
        raw = md_file.read_text(encoding="utf-8")
    except OSError:
        return None

    rel_path, rel_file = _resolve_relative_paths(md_file, notes_dir)

    if MemoryNote is None:
        return _stub_note_dict(md_file, rel_path, rel_file, raw, raw)

    try:
        note = MemoryNote.from_markdown(raw)
    except ValueError:
        return _stub_note_dict(md_file, rel_path, rel_file, raw.strip(), raw)

    body = (note.content or "").strip()
    title = _resolve_title(note.name, body, md_file)
    category_val = note.category if note.category and note.category != "Uncategorized" else None

    return {
        "id": note.id,
        "filename": md_file.name,
        "path": rel_path,
        "relativePath": rel_file,
        "title": title,
        "body": body,
        "content": raw,
        "excerpt": _extract_excerpt(body),
        "tags": list(note.tags or []),
        "keywords": list(note.keywords or []),
        "links": list(note.links or []),
        "context": note.context if note.context and note.context != "General" else None,
        "summary": note.summary or None,
        "category": category_val,
        "timestamp": note.timestamp,
        "last_accessed": note.last_accessed,
        "retrieval_count": int(note.retrieval_count or 0),
    }


def _load_notes(notes_dir: Path) -> list:
    """Load all markdown notes from the notes directory.

    Each note's frontmatter is parsed by ``MemoryNote.from_markdown`` (the
    same code path the memory system uses to write the file), so the dashboard sees
    exactly the structured fields the MCP server intended.
    """
    if not notes_dir.exists():
        return []
    notes = []
    for md_file in sorted(notes_dir.rglob("*.md")):
        d = _note_to_dict(md_file, notes_dir)
        if d is not None:
            notes.append(d)
    return notes


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


def _build_graph(notes: list) -> dict:
    """Build a graph visualization from notes."""
    groups = {}
    nodes = []
    links = []
    note_ids = {n["id"] for n in notes}

    for note in notes:
        note_path = note.get("path") or "."
        path_parts = note_path.split("/") if note_path != "." else ["unfiled"]
        group_key = path_parts[0] if path_parts else "unfiled"

        if group_key not in groups:
            color = GRAPH_GROUP_COLORS[len(groups) % len(GRAPH_GROUP_COLORS)]
            groups[group_key] = {
                "id": group_key,
                "label": group_key.replace("-", " ").replace("_", " ").title(),
                "query": f'path:"{group_key}/"',
                "color": color,
                "pathPrefix": group_key,
                "description": f"Notes in {group_key}",
            }

        color = groups[group_key]["color"]
        connections = len(note.get("links", []))

        nodes.append(
            {
                "id": note["id"],
                "title": note["title"],
                "path": note["relativePath"],
                "pathLabel": note["path"],
                "excerpt": note["excerpt"],
                "body": note.get("body", ""),
                "content": note["content"],
                "summary": note.get("summary") or note["excerpt"][:150],
                "context": note.get("context"),
                "category": note.get("category"),
                "timestamp": note.get("timestamp"),
                "last_accessed": note.get("last_accessed"),
                "retrieval_count": note.get("retrieval_count", 0),
                "keywords": note["keywords"],
                "tags": note["tags"],
                "groupId": group_key,
                "color": color,
                "weight": 1.0 + min(2.0, connections * 0.3),
                "connections": connections,
            }
        )

        for link_id in note.get("links", []):
            if link_id in note_ids:
                links.append(
                    {
                        "source": note["id"],
                        "target": link_id,
                        "strength": 0.5,
                    }
                )

    return {
        "groups": list(groups.values()),
        "nodes": nodes,
        "links": links,
        "stats": {
            "total_memories": len(nodes),
            "total_links": len(links),
            "total_groups": len(groups),
        },
    }


@router.get("/api/amem/{plan_id}/graph", responses={404: {"description": "Not found"}})
async def get_memory_graph(plan_id: str, user: Annotated[dict, Depends(get_current_user)] = None):
    """Get the memory graph for a plan's project."""
    mem_dir = _require_memory_dir(plan_id)
    notes_dir = mem_dir / "notes"
    # File I/O + graph computation is CPU-bound — offload to thread pool
    notes = await asyncio.to_thread(_load_notes, notes_dir)
    return await asyncio.to_thread(_build_graph, notes)


def _render_graph_png(graph_data: dict) -> bytes:
    """Render graph data as a PNG image. Runs in a thread (CPU-bound)."""
    import io
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import networkx as nx
    from matplotlib.patches import Patch

    G = nx.Graph()
    node_colors = []
    node_sizes = []
    labels = {}

    for node in graph_data["nodes"]:
        G.add_node(node["id"])
        node_colors.append(node.get("color", "#8b5cf6"))
        node_sizes.append(300 + node.get("connections", 0) * 150)
        title = node.get("title", node["id"])
        labels[node["id"]] = title[:25] + "..." if len(title) > 28 else title

    for link in graph_data["links"]:
        if G.has_node(link["source"]) and G.has_node(link["target"]):
            G.add_edge(link["source"], link["target"])

    fig, ax = plt.subplots(1, 1, figsize=(12, 8), facecolor="#0f0f0f")
    ax.set_facecolor("#0f0f0f")

    if len(G.nodes) > 1 and len(G.edges) > 0:
        pos = nx.spring_layout(G, k=2.5, iterations=60, seed=42)
    else:
        pos = nx.spring_layout(G, k=3.0, seed=42)

    nx.draw_networkx_edges(G, pos, ax=ax, edge_color="#444444", width=1.5, alpha=0.6)
    nx.draw_networkx_nodes(
        G,
        pos,
        ax=ax,
        node_color=node_colors,
        node_size=node_sizes,
        edgecolors="#222222",
        linewidths=1.5,
        alpha=0.9,
    )
    nx.draw_networkx_labels(
        G,
        pos,
        labels=labels,
        ax=ax,
        font_size=8,
        font_color="white",
        font_weight="bold",
    )

    legend_handles = []
    for group in graph_data["groups"]:
        legend_handles.append(Patch(facecolor=group["color"], label=group["label"], alpha=0.9))
    if legend_handles:
        legend = ax.legend(
            handles=legend_handles,
            loc="upper left",
            fontsize=8,
            facecolor="#1a1a1a",
            edgecolor="#333333",
            labelcolor="white",
        )
        legend.get_frame().set_alpha(0.8)

    stats = graph_data["stats"]
    ax.set_title(
        f"Memory Graph \u2014 {stats['total_memories']} notes, {stats['total_links']} links",
        color="white",
        fontsize=14,
        fontweight="bold",
        pad=15,
    )
    ax.axis("off")
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="#0f0f0f")
    plt.close(fig)
    return buf.getvalue()


@router.get(
    "/api/amem/{plan_id}/graph-image",
    responses={404: {"description": "Not found"}},
)
async def get_memory_graph_image(plan_id: str, user: Annotated[dict, Depends(get_current_user)] = None):
    """Render the memory graph as a PNG image."""
    from fastapi.responses import StreamingResponse

    mem_dir = _require_memory_dir(plan_id)
    notes_dir = mem_dir / "notes"
    # File I/O + graph computation + matplotlib rendering are all CPU-heavy
    notes = await asyncio.to_thread(_load_notes, notes_dir)
    graph_data = await asyncio.to_thread(_build_graph, notes)

    if not graph_data["nodes"]:
        raise HTTPException(status_code=404, detail="No memories to graph")

    # CPU-bound matplotlib rendering — must run in executor
    loop = asyncio.get_event_loop()
    try:
        png_bytes = await loop.run_in_executor(None, _render_graph_png, graph_data)
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    return StreamingResponse(io.BytesIO(png_bytes), media_type="image/png")


@router.get("/api/amem/{plan_id}/tree", responses={404: {"description": "Not found"}})
async def get_memory_tree(plan_id: str, user: Annotated[dict, Depends(get_current_user)] = None) -> dict:
    """Get a tree-like directory structure of all memory notes."""
    mem_dir = _require_memory_dir(plan_id)
    notes_dir = mem_dir / "notes"
    notes = await asyncio.to_thread(_load_notes, notes_dir)

    if not notes:
        return {"tree": "(empty)", "total": 0}

    # Build nested dict from note paths
    root: dict = {}
    for note in sorted(notes, key=lambda n: n.get("relativePath", "")):
        rel = note.get("relativePath", note.get("path", "unfiled"))
        parts = [p for p in rel.replace("\\", "/").split("/") if p]
        node = root
        for part in parts:
            node = node.setdefault(part, {})

    # Render as tree string
    def _render(node: dict, prefix: str = "") -> list[str]:
        lines = []
        items = list(node.items())
        for i, (name, children) in enumerate(items):
            last = i == len(items) - 1
            connector = "\u2514\u2500\u2500 " if last else "\u251c\u2500\u2500 "
            lines.append(f"{prefix}{connector}{name}")
            if children:
                ext = "    " if last else "\u2502   "
                lines.extend(_render(children, prefix + ext))
        return lines

    tree_str = "\n".join(_render(root))
    return {"tree": tree_str, "total": len(notes)}


@router.get("/api/amem/{plan_id}/notes", responses={404: {"description": "Not found"}})
async def list_memory_notes(plan_id: str, user: Annotated[dict, Depends(get_current_user)] = None) -> list:
    """List all memory notes for a plan's project."""
    mem_dir = _require_memory_dir(plan_id)
    notes_dir = mem_dir / "notes"
    notes = await asyncio.to_thread(_load_notes, notes_dir)
    for n in notes:
        n.pop("content", None)
    return notes


@router.get("/api/amem/{plan_id}/notes/{note_id}", responses={404: {"description": "Not found"}})
async def get_memory_note(plan_id: str, note_id: str, user: Annotated[dict, Depends(get_current_user)] = None) -> dict:
    """Get a single memory note by ID."""
    mem_dir = _require_memory_dir(plan_id)
    notes_dir = mem_dir / "notes"
    notes = await asyncio.to_thread(_load_notes, notes_dir)
    for note in notes:
        if note["id"] == note_id:
            return note
    raise HTTPException(status_code=404, detail=f"Note {note_id} not found")


@router.get("/api/amem/{plan_id}/stats", responses={404: {"description": "Not found"}})
async def get_memory_stats(plan_id: str, user: Annotated[dict, Depends(get_current_user)] = None) -> dict:
    """Get memory statistics for a plan's project."""
    mem_dir = _require_memory_dir(plan_id)
    notes_dir = mem_dir / "notes"
    notes = await asyncio.to_thread(_load_notes, notes_dir)

    tags = set()
    keywords = set()
    paths = set()
    for n in notes:
        tags.update(n.get("tags", []))
        keywords.update(n.get("keywords", []))
        paths.add(n.get("path", ""))

    return {
        "total_notes": len(notes),
        "total_tags": len(tags),
        "total_keywords": len(keywords),
        "total_paths": len(paths),
        "memory_dir": str(mem_dir),
        "tags": sorted(tags),
        "paths": sorted(paths),
    }


# ── Lifecycle Management (Plan 010) ──────────────────────────────────────────

import os
import shutil
import tarfile
import io
import time
from datetime import datetime
from fastapi.responses import StreamingResponse


MEMORY_BASE_DIR = Path(os.environ.get("OSTWIN_MEMORY_DIR", str(Path.home() / ".ostwin" / "memory")))


@router.get("/api/amem/namespaces")
async def list_namespaces(user: Annotated[dict, Depends(get_current_user)]):
    """List all memory namespaces with stats."""
    # Heavy file system scanning — offload to thread pool
    def _scan_namespaces():
        if not MEMORY_BASE_DIR.exists():
            return []

        namespaces = []
        for entry in sorted(MEMORY_BASE_DIR.iterdir()):
            if not entry.is_dir():
                continue
            # Skip archived namespaces in listing (they have .archive- in name)
            if ".archive-" in entry.name:
                continue

            plan_id = entry.name
            notes_dir = entry / "notes"
            notes_count = len(list(notes_dir.rglob("*.md"))) if notes_dir.exists() else 0

            # Disk usage
            disk_bytes = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())

            # Plan title from registry
            title = plan_id
            meta_file = PLANS_DIR / f"{plan_id}.meta.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text())
                    title = meta.get("title", plan_id)
                except Exception:
                    pass
            if plan_id == "_global":
                title = "(Global)"

            # Archived versions count
            archived = len(
                [d for d in MEMORY_BASE_DIR.iterdir() if d.is_dir() and d.name.startswith(f"{plan_id}.archive-")]
            )

            # Timestamps
            created_at = None
            last_modified = None
            if notes_dir.exists():
                md_files = list(notes_dir.rglob("*.md"))
                if md_files:
                    times = [f.stat().st_mtime for f in md_files]
                    created_at = datetime.fromtimestamp(min(times)).isoformat()
                    last_modified = datetime.fromtimestamp(max(times)).isoformat()

            namespaces.append(
                {
                    "plan_id": plan_id,
                    "title": title,
                    "notes_count": notes_count,
                    "disk_bytes": disk_bytes,
                    "created_at": created_at,
                    "last_modified": last_modified,
                    "archived_versions": archived,
                }
            )

        return namespaces

    return await asyncio.to_thread(_scan_namespaces)


@router.delete("/api/amem/{plan_id}")
async def clear_namespace(
    plan_id: str,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Clear all notes for a plan namespace."""
    ns_dir = MEMORY_BASE_DIR / plan_id
    if not ns_dir.exists():
        raise HTTPException(status_code=404, detail=f"Namespace '{plan_id}' not found")

    notes_dir = ns_dir / "notes"
    vectordb_dir = ns_dir / "vectordb"
    count = len(list(notes_dir.rglob("*.md"))) if notes_dir.exists() else 0

    # Kill the pool slot if active (forces sync + cleanup)
    try:
        from dashboard.routes.memory_mcp import get_pool

        pool = get_pool()
        pool.kill_slot(str(ns_dir))
    except Exception:
        pass

    # Clear contents but keep the directory
    if notes_dir.exists():
        shutil.rmtree(notes_dir)
        notes_dir.mkdir()
    if vectordb_dir.exists():
        shutil.rmtree(vectordb_dir)

    return {"plan_id": plan_id, "cleared": count, "action": "cleared"}


@router.delete("/api/amem/{plan_id}/notes/{note_id}")
async def delete_note(
    plan_id: str,
    note_id: str,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Delete a single note by ID."""
    mem_dir = _resolve_memory_dir(plan_id)
    notes_dir = mem_dir / "notes"

    # Find the note file by ID in frontmatter
    for md_file in notes_dir.rglob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8")
            if MemoryNote:
                note = MemoryNote.from_markdown(text)
                if note and note.id == note_id:
                    md_file.unlink()
                    # Clean up empty parent dirs
                    parent = md_file.parent
                    while parent != notes_dir:
                        if not any(parent.iterdir()):
                            parent.rmdir()
                            parent = parent.parent
                        else:
                            break
                    return {"plan_id": plan_id, "note_id": note_id, "action": "deleted"}
            elif f'id: "{note_id}"' in text or f"id: '{note_id}'" in text:
                md_file.unlink()
                return {"plan_id": plan_id, "note_id": note_id, "action": "deleted"}
        except Exception:
            continue

    raise HTTPException(status_code=404, detail=f"Note '{note_id}' not found")


@router.post("/api/amem/{plan_id}/archive")
async def archive_namespace(
    plan_id: str,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Archive a namespace: rename to <plan_id>.archive-<date>, create fresh empty one."""
    ns_dir = MEMORY_BASE_DIR / plan_id
    if not ns_dir.exists():
        raise HTTPException(status_code=404, detail=f"Namespace '{plan_id}' not found")

    notes_dir = ns_dir / "notes"
    count = len(list(notes_dir.rglob("*.md"))) if notes_dir.exists() else 0

    # Kill pool slot first
    try:
        from dashboard.routes.memory_mcp import get_pool

        pool = get_pool()
        pool.kill_slot(str(ns_dir))
    except Exception:
        pass

    # Rename to archive
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_name = f"{plan_id}.archive-{timestamp}"
    archive_dir = MEMORY_BASE_DIR / archive_name
    ns_dir.rename(archive_dir)

    # Create fresh empty namespace
    ns_dir.mkdir(parents=True)
    (ns_dir / "notes").mkdir()

    return {
        "plan_id": plan_id,
        "archived_to": archive_name,
        "notes_archived": count,
        "action": "archived",
    }


@router.get("/api/amem/{plan_id}/export")
async def export_namespace(
    plan_id: str,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Export a namespace as a .tar.gz download."""
    ns_dir = MEMORY_BASE_DIR / plan_id
    if not ns_dir.exists():
        # Try via plan working_dir symlink
        try:
            ns_dir = _resolve_memory_dir(plan_id)
        except HTTPException:
            raise HTTPException(status_code=404, detail=f"Namespace '{plan_id}' not found")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(str(ns_dir), arcname=plan_id)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="memory-{plan_id}.tar.gz"'},
    )
