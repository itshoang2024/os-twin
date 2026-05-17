"""Dashboard API routes for shared memory — thin wrapper around memory-core.py."""

from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional
import asyncio
import json
import os
import importlib.util

from dashboard.api_utils import AGENTS_DIR
from dashboard.auth import get_current_user

# Import memory-core.py (same source of truth as MCP server and CLI)
_core_path = os.path.join(str(AGENTS_DIR), "mcp", "memory-core.py")
if not os.path.exists(_core_path):
    # Fallback: look relative to this file
    _core_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        ".agents", "mcp", "memory-core.py",
    )
_spec = importlib.util.spec_from_file_location("memory_core", _core_path)
_core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_core)

router = APIRouter(tags=["memory"])


@router.get("/api/memory")
async def list_memories(
    kind: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """List all live memory entries (index view)."""
    result = json.loads(await asyncio.to_thread(_core.list_memories, kind=kind))
    return {"count": len(result), "entries": result}


@router.get("/api/memory/query/search")
async def search_memory(
    text: str = Query(..., description="Search query"),
    kind: Optional[str] = None,
    exclude_room: Optional[str] = None,
    max_results: int = Query(10, ge=1, le=50),
    user: dict = Depends(get_current_user),
):
    """Full-text search across shared memory (BM25 + time decay)."""
    result = json.loads(
        await asyncio.to_thread(
            _core.search, text=text, kind=kind, exclude_room=exclude_room, max_results=max_results
        )
    )
    return {"results": result}


@router.get("/api/memory/context/{room_id}")
async def get_room_context(
    room_id: str,
    keywords: Optional[str] = Query(None, description="Comma-separated keywords"),
    max_entries: int = Query(15, ge=1, le=50),
    user: dict = Depends(get_current_user),
):
    """Generate cross-room context for a war-room."""
    # Run the entire context computation in a thread to avoid blocking
    def _compute_context():
        brief_keywords = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else None
        entries_json = _core.query(exclude_room=room_id)
        entries = json.loads(entries_json)

        if brief_keywords:
            # Use get_context for keyword-filtered markdown, but return structured data
            bm25_results = _core._bm25_rank(" ".join(brief_keywords), entries)
            ref_ts = _core._newest_ts(entries)
            scored_raw = [(rel, _core._time_decay(e, ref_ts), e) for rel, e in bm25_results]
            scored = _core._compute_scores(scored_raw)
            entries = [e for _, e in scored[:max_entries]]
        else:
            entries = entries[-max_entries:]

        return entries

    entries = await asyncio.to_thread(_compute_context)
    return {
        "room_id": room_id,
        "context_entries": len(entries),
        "entries": entries,
    }


@router.get("/api/memory/{memory_id}")
async def get_memory(memory_id: str, user: dict = Depends(get_current_user)):
    """Get a single memory entry by ID (includes detail)."""
    def _find_entry():
        all_entries = json.loads(_core.query())
        for entry in all_entries:
            if entry["id"] == memory_id:
                return entry
        return None

    entry = await asyncio.to_thread(_find_entry)
    if entry is None:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return entry


@router.post("/api/memory")
async def publish_memory(
    body: dict,
    user: dict = Depends(get_current_user),
):
    """Publish a new memory entry from the dashboard."""
    kind = body.get("kind")
    if kind not in _core.VALID_KINDS:
        raise HTTPException(400, f"Invalid kind '{kind}'. Must be one of: {sorted(_core.VALID_KINDS)}")

    result = await asyncio.to_thread(
        _core.publish,
        kind=kind,
        summary=body.get("summary", ""),
        tags=body.get("tags", []),
        room_id=body.get("room_id", "dashboard"),
        author_role=body.get("author_role", "human"),
        ref=body.get("ref", ""),
        detail=body.get("detail"),
        supersedes=body.get("supersedes"),
    )

    if result.startswith("error:"):
        raise HTTPException(400, result)

    mem_id = result.replace("published:", "")
    return {"id": mem_id, "status": "published"}


@router.get("/api/memory/stats")
async def memory_stats(user: dict = Depends(get_current_user)):
    """Aggregate statistics about shared memory."""
    def _compute_stats():
        entries = json.loads(_core.query())
        by_kind: dict[str, int] = {}
        by_room: dict[str, int] = {}
        for e in entries:
            k = e.get("kind", "unknown")
            r = e.get("room_id", "unknown")
            by_kind[k] = by_kind.get(k, 0) + 1
            by_room[r] = by_room.get(r, 0) + 1
        return {
            "total": len(entries),
            "by_kind": by_kind,
            "by_room": by_room,
        }

    return await asyncio.to_thread(_compute_stats)
