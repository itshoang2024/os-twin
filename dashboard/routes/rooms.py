from fastapi import APIRouter, HTTPException, Query, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import AsyncIterator
from datetime import datetime, timezone
import asyncio
import json
import shutil
from pathlib import Path

from dashboard.api_utils import (
    WARROOMS_DIR, PROJECT_ROOT, AGENTS_DIR, PLANS_DIR,
    read_room, read_channel, process_notification
)
import dashboard.global_state as global_state
from dashboard.auth import get_current_user

router = APIRouter(tags=["rooms"])

@router.get("/api/rooms")
async def list_rooms(user: dict = Depends(get_current_user)):
    """List all war-rooms with current status."""
    rooms = []
    if not WARROOMS_DIR.exists():
        return {"rooms": [], "summary": {}}

    for room_dir in sorted(WARROOMS_DIR.glob("room-*")):
        if room_dir.is_dir():
            rooms.append(read_room(room_dir))

    # Summary counts
    summary = {"total": len(rooms)}
    statuses = (
        "pending", "developing", "review", 
        "optimize", "done", "failed"
    )
    for status in statuses:
        s_key = status.replace("-", "_")
        summary[s_key] = sum(1 for r in rooms if r["status"] == status)
    summary["passed"] = summary.get("done", 0)
    summary["failed_final"] = summary.get("failed", 0)

    return {
        "rooms": rooms, 
        "summary": summary, 
        "debug": {
            "project_root": str(PROJECT_ROOT), 
            "agents_dir": str(AGENTS_DIR)
        }
    }

@router.post("/api/rooms/reset")
async def reset_rooms(user: dict = Depends(get_current_user)):
    """Wipe all war-room data to start fresh."""
    if not WARROOMS_DIR.exists():
        return {"status": "ok", "message": "No war-rooms to clean."}
    try:
        shutil.rmtree(WARROOMS_DIR)
        WARROOMS_DIR.mkdir()
        return {"status": "ok", "message": "All war-rooms cleaned."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset war-rooms: {e}")

@router.get("/api/rooms/{room_id}/channel")
async def get_channel(
    room_id: str,
    from_role: str | None = Query(None, alias="from"),
    to_role: str | None = Query(None, alias="to"),
    msg_type: str | None = Query(None, alias="type"),
    ref: str | None = Query(None),
    q: str | None = Query(None),
    limit: int | None = Query(None),
    user: dict = Depends(get_current_user)
):
    """Get messages for a specific war-room with filtering support."""
    room_dir = WARROOMS_DIR / room_id
    if not room_dir.exists():
        # Search plan-specific war-room directories
        plans_dir = PLANS_DIR
        if plans_dir.exists():
            for meta_file in plans_dir.glob("*.meta.json"):
                try:
                    meta = json.loads(meta_file.read_text())
                    wd = meta.get("working_dir")
                    if wd:
                        candidate = Path(wd) / ".war-rooms" / room_id
                        if candidate.exists():
                            room_dir = candidate
                            break
                except (ValueError, KeyError):
                    pass
    if not room_dir.exists():
        raise HTTPException(status_code=404, detail=f"Room {room_id} not found")
        
    messages = read_channel(
        room_dir,
        from_role=from_role,
        to_role=to_role,
        msg_type=msg_type,
        ref=ref,
        query=q,
        limit=limit
    )
    return {"messages": messages}

@router.get("/api/rooms/{room_id}/analyze")
async def analyze_messages(
    room_id: str,
    from_role: str | None = Query(None, alias="from"),
    to_role: str | None = Query(None, alias="to"),
    msg_type: str | None = Query(None, alias="type"),
    ref: str | None = Query(None),
    q: str | None = Query(None),
    user: dict = Depends(get_current_user)
):
    """Analyze messages for a specific war-room (summaries, stats, etc.)."""
    room_dir = WARROOMS_DIR / room_id
    if not room_dir.exists():
        raise HTTPException(status_code=404, detail=f"Room {room_id} not found")
        
    messages = read_channel(
        room_dir,
        from_role=from_role,
        to_role=to_role,
        msg_type=msg_type,
        ref=ref,
        query=q
    )

    if not messages:
        return {"summary": "No messages found for analysis.", "stats": {}}

    # Simple stats
    stats = {
        "count": len(messages),
        "types": {},
        "roles": {},
        "refs": {}
    }

    for msg in messages:
        msg_type_val = msg.get("type", "unknown")
        stats["types"][msg_type_val] = stats["types"].get(msg_type_val, 0) + 1

        role_val = msg.get("from", "unknown")
        stats["roles"][role_val] = stats["roles"].get(role_val, 0) + 1

        ref_val = msg.get("ref", "none")
        stats["refs"][ref_val] = stats["refs"].get(ref_val, 0) + 1

    # Heuristic summary
    done_iter = (m for m in reversed(messages) if m.get("type") == "done")
    latest_done = next(done_iter, None)

    fail_iter = (m for m in reversed(messages) if m.get("type") == "fail")
    latest_fail = next(fail_iter, None)

    summary_text = f"Analyzed {len(messages)} messages."
    if latest_done:
        body_snippet = latest_done.get('body', '')[:100]
        summary_text += f" Latest progress: {body_snippet}..."
    if latest_fail:
        body_snippet = latest_fail.get('body', '')[:100]
        summary_text += f" Latest issue: {body_snippet}..."

    return {
        "summary": summary_text,
        "stats": stats,
        "latest_milestones": {
            "done": latest_done,
            "fail": latest_fail
        }
    }

@router.get("/api/events")
async def sse_events():
    """Server-Sent Events stream."""
    async def event_generator() -> AsyncIterator[str]:
        queue = await global_state.broadcaster.subscribe_sse()
        try:
            while True:
                event = await queue.get()
                yield event
        except asyncio.CancelledError:
            pass
        finally:
            global_state.broadcaster.unsubscribe_sse(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

@router.get("/api/search")
async def search_messages(
    q: str = Query(..., min_length=1),
    room_id: str | None = Query(None),
    type: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """Semantic vector search across all indexed messages."""
    store = global_state.store
    if not store:
        raise HTTPException(status_code=503, detail="Vector search not available")
    results = store.search(q, room_id=room_id, msg_type=type, limit=limit)
    return {"results": results, "count": len(results)}

@router.get("/api/rooms/{room_id}/context")
async def search_room_context(
    room_id: str,
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
):
    """Semantic search scoped to a single room."""
    store = global_state.store
    if not store:
        raise HTTPException(status_code=503, detail="Vector search not available")
    results = store.search(q, room_id=room_id, limit=limit)
    return {"results": results, "count": len(results)}

@router.get("/api/rooms/{room_id}/state")
async def get_room_state(room_id: str):
    """Get room metadata."""
    room_dir = WARROOMS_DIR / room_id
    if not room_dir.exists():
        raise HTTPException(status_code=404, detail=f"Room {room_id} not found")
    
    data = read_room(room_dir, include_metadata=True)
    
    store = global_state.store
    if store:
        meta = store.get_room_metadata(room_id)
        if meta:
            data.update(meta)
            
    return data


@router.post("/api/rooms/{room_id}/action")
async def room_action(room_id: str, background_tasks: BackgroundTasks, action: str = Query(...)):
    """Perform an action on a room (stop, pause, resume)."""
    room_dir = WARROOMS_DIR / room_id
    if not room_dir.exists():
        raise HTTPException(status_code=404, detail=f"Room {room_id} not found")

    status_file = room_dir / "status"
    if action == "stop":
        status_file.write_text("failed")
    elif action == "pause":
        status_file.write_text("paused")
    elif action == "resume" or action == "start":
        status_file.write_text("pending")
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    data = {"room_id": room_id, "action": action}
    background_tasks.add_task(process_notification, "room_action", data)
    return {"status": "ok", "action": action, "room_id": room_id}


@router.post("/api/rooms/{room_id}/advance")
async def advance_room_state(
    room_id: str,
    request: dict,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user)
):
    """Advance the room to the next lifecycle state."""
    room_dir = WARROOMS_DIR / room_id
    if not room_dir.exists():
        raise HTTPException(status_code=404, detail=f"Room {room_id} not found")

    target_state = request.get("target_state")
    if not target_state:
        raise HTTPException(status_code=400, detail="target_state is required")

    # Update status file
    status_file = room_dir / "status"
    status_file.write_text(target_state)

    # Update state_changed_at
    sca_file = room_dir / "state_changed_at"
    sca_file.write_text(datetime.now(timezone.utc).isoformat())

    # Post a message to the channel about the state change
    channel_file = room_dir / "channel.jsonl"
    event_msg = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "from": "system",
        "to": "all",
        "type": "state_changed",
        "ref": target_state,
        "body": f"Lifecycle state advanced to: {target_state}"
    }
    with open(channel_file, "a") as f:
        f.write(json.dumps(event_msg) + "\n")

    # Broadcast update via notification channel
    data = {
        "room_id": room_id,
        "new_state": target_state,
        "event": "state_changed",
        "message": event_msg
    }
    background_tasks.add_task(process_notification, "state_changed", data)

    return {"status": "ok", "new_state": target_state}
