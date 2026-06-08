import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from dashboard.api_utils import (
    PLANS_DIR,
    WARROOMS_DIR,
    canonical_room_status,
    resolve_runtime_plan_warrooms_dir,
)
from dashboard.auth import get_current_user

router = APIRouter(tags=["plan-logs"])

_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_TERMINAL_STATUSES = {"done", "failed"}
_IDLE_STATUSES = {"pending", "blocked", "unknown", "paused"}
_TERMINAL_OR_IDLE_STATUSES = _TERMINAL_STATUSES | _IDLE_STATUSES
_MAX_TAIL_BYTES = 512 * 1024
_MAX_INCREMENTAL_READ_BYTES = 256 * 1024


def _validate_identifier(value: str, field: str) -> str:
    if not value or not _SAFE_IDENTIFIER_RE.match(value):
        raise HTTPException(status_code=422, detail=f"Invalid {field}")
    return value


def _parse_room_filter(rooms: Optional[str]) -> Optional[set[str]]:
    if not rooms:
        return None
    selected = {part.strip() for part in rooms.split(",") if part.strip()}
    for room_id in selected:
        _validate_identifier(room_id, "room_id")
    return selected or None


def _utc_from_mtime(path: Path) -> Optional[str]:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return None


def _safe_read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return default


def _safe_read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _is_shared_warrooms_dir(warrooms_dir: Path) -> bool:
    try:
        return warrooms_dir.resolve() == WARROOMS_DIR.resolve()
    except OSError:
        return False


def _room_belongs_to_plan(room_dir: Path, plan_id: str, *, shared_warrooms: bool) -> bool:
    config = _safe_read_json(room_dir / "config.json")
    room_plan_id = config.get("plan_id")
    if room_plan_id:
        return room_plan_id == plan_id
    # Shared/global war-room directories can contain rooms from multiple plans;
    # require an explicit plan stamp there to avoid leaking another plan's logs.
    return not shared_warrooms


def _room_status(room_dir: Path, fallback: str = "unknown") -> str:
    raw_status = _safe_read_text(room_dir / "status", fallback) or fallback
    return canonical_room_status(raw_status)


def _room_task_ref(room_dir: Path, fallback: str = "?") -> str:
    task_ref = _safe_read_text(room_dir / "task-ref")
    if task_ref:
        return task_ref
    config = _safe_read_json(room_dir / "config.json")
    return str(config.get("task_ref") or fallback)


def _is_active_status(status: str) -> bool:
    return canonical_room_status(status) not in _TERMINAL_OR_IDLE_STATUSES


def _is_followable_log(status: str, path: Path) -> bool:
    """Return true when a log should be tailed by the default stream.

    Runtime progress can lag behind the process writing the per-room log.  In
    practice a room may still be marked ``pending`` while its
    ``{plan_id}.{room_id}.log`` file is actively appended by the runner.  The
    default SSE stream therefore follows all non-terminal rooms that have a log
    file, plus rooms explicitly marked active by lifecycle status.
    """
    normalized = canonical_room_status(status)
    return _is_active_status(normalized) or (path.exists() and normalized not in _TERMINAL_STATUSES)


def _log_path(plan_id: str, room_id: str) -> Path:
    # The path is constructed only from validated identifiers; no user-provided
    # slashes are accepted, so this cannot escape PLANS_DIR.
    return PLANS_DIR / f"{plan_id}.{room_id}.log"


def _source_public_payload(source: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in source.items() if k != "path"}


def _build_log_sources(
    plan_id: str,
    *,
    active_only: bool = False,
    room_filter: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    _validate_identifier(plan_id, "plan_id")
    warrooms_dir = resolve_runtime_plan_warrooms_dir(plan_id)
    has_warrooms = bool(warrooms_dir and warrooms_dir.exists())
    shared_warrooms = _is_shared_warrooms_dir(warrooms_dir) if has_warrooms and warrooms_dir else False
    rooms_by_id: dict[str, dict[str, Any]] = {}
    excluded_room_ids: set[str] = set()

    if has_warrooms and warrooms_dir:
        progress = _safe_read_json(warrooms_dir / "progress.json")
        progress_rooms = progress.get("rooms")
        if isinstance(progress_rooms, list):
            for entry in progress_rooms:
                if not isinstance(entry, dict):
                    continue
                room_id = str(entry.get("room_id") or "").strip()
                if not room_id or not _SAFE_IDENTIFIER_RE.match(room_id):
                    continue
                room_dir = warrooms_dir / room_id
                if not room_dir.exists() or not _room_belongs_to_plan(room_dir, plan_id, shared_warrooms=shared_warrooms):
                    excluded_room_ids.add(room_id)
                    continue
                rooms_by_id[room_id] = {
                    "room_id": room_id,
                    "epic_ref": str(entry.get("task_ref") or _room_task_ref(room_dir)),
                    "status": canonical_room_status(str(entry.get("status") or _room_status(room_dir))),
                }

        # Merge in live room state from disk so newly-created rooms are discoverable
        # even before progress.json is regenerated.
        for room_dir in sorted(warrooms_dir.glob("room-*")):
            if not room_dir.is_dir():
                continue
            room_id = room_dir.name
            if not _SAFE_IDENTIFIER_RE.match(room_id):
                continue
            if not _room_belongs_to_plan(room_dir, plan_id, shared_warrooms=shared_warrooms):
                excluded_room_ids.add(room_id)
                continue
            rooms_by_id[room_id] = {
                "room_id": room_id,
                "epic_ref": _room_task_ref(room_dir, rooms_by_id.get(room_id, {}).get("epic_ref", "?")),
                "status": _room_status(room_dir, rooms_by_id.get(room_id, {}).get("status", "unknown")),
            }

    # The canonical stream source is now ~/.ostwin/.agents/plans/{plan_id}.{room_id}.log.
    # Discovering log files directly makes ``tail -f`` behavior work even when
    # progress.json/status files are stale or a room has not been projected yet.
    for log_file in sorted(PLANS_DIR.glob(f"{plan_id}.room-*.log")):
        prefix = f"{plan_id}."
        suffix = ".log"
        room_id = log_file.name[len(prefix):-len(suffix)]
        if not room_id or not _SAFE_IDENTIFIER_RE.match(room_id):
            continue
        if room_id in excluded_room_ids:
            continue
        if room_filter and room_id not in room_filter:
            continue
        rooms_by_id.setdefault(room_id, {
            "room_id": room_id,
            "epic_ref": room_id,
            "status": "unknown",
            "log_only": True,
        })

    sources: list[dict[str, Any]] = []
    for room_id, entry in sorted(rooms_by_id.items()):
        if room_filter and room_id not in room_filter:
            continue
        status = canonical_room_status(entry.get("status"))
        path = _log_path(plan_id, room_id)
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        active = _is_active_status(status)
        followable = _is_followable_log(status, path)
        # A room filter means the caller asked for the exact tail target (for
        # example room-001); do not hide it because lifecycle state is stale.
        if active_only and not room_filter and not followable:
            continue
        sources.append({
            "plan_id": plan_id,
            "room_id": room_id,
            "epic_ref": entry.get("epic_ref") or "?",
            "status": status,
            "active": active,
            "followable": followable,
            "exists": exists,
            "size": size,
            "updated_at": _utc_from_mtime(path) if exists else None,
            "path": path,
        })
    return sources


def _tail_lines(path: Path, tail_lines: int, *, strip_ansi: bool) -> list[str]:
    if tail_lines <= 0 or not path.exists():
        return []
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - _MAX_TAIL_BYTES))
            text = handle.read(_MAX_TAIL_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()[-tail_lines:]
    if strip_ansi:
        lines = [_ANSI_RE.sub("", line) for line in lines]
    return lines


def _sse(event: str, data: dict[str, Any], *, event_id: Optional[str] = None) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    chunks: list[str] = []
    if event_id:
        chunks.append(f"id: {event_id}")
    chunks.append(f"event: {event}")
    chunks.append(f"data: {payload}")
    return "\n".join(chunks) + "\n\n"


@router.get("/api/plans/{plan_id}/logs")
async def list_plan_logs(
    plan_id: str,
    active_only: bool = Query(False),
    rooms: Optional[str] = Query(None, description="Comma-separated room IDs to include"),
    user: dict = Depends(get_current_user),
):
    """Return discoverable per-EPIC log files for a plan."""
    room_filter = _parse_room_filter(rooms)
    sources = _build_log_sources(plan_id, active_only=active_only, room_filter=room_filter)
    return {
        "plan_id": plan_id,
        "logs_dir": str(PLANS_DIR),
        "rooms": [_source_public_payload(source) for source in sources],
        "count": len(sources),
    }


@router.get("/api/plans/{plan_id}/logs/stream")
async def stream_plan_logs(
    request: Request,
    plan_id: str,
    active_only: bool = Query(True),
    rooms: Optional[str] = Query(None, description="Comma-separated room IDs to include"),
    tail_lines: int = Query(200, ge=0, le=1000),
    poll_ms: int = Query(750, ge=100, le=5000),
    strip_ansi: bool = Query(True),
    once: bool = Query(False, description="Emit initial state and close; useful for tests/debugging"),
    user: dict = Depends(get_current_user),
):
    """Stream current plan EPIC logs as a single multiplexed SSE feed."""
    room_filter = _parse_room_filter(rooms)
    poll_seconds = poll_ms / 1000

    async def event_generator():
        sources = _build_log_sources(plan_id, active_only=active_only, room_filter=room_filter)
        states: dict[str, dict[str, Any]] = {}
        yield _sse("init", {
            "plan_id": plan_id,
            "active_only": active_only,
            "rooms": [_source_public_payload(source) for source in sources],
        })

        for source in sources:
            room_id = source["room_id"]
            states[room_id] = {"offset": source["size"], "partial": "", "status": source["status"]}
            if source["exists"]:
                for idx, line in enumerate(_tail_lines(source["path"], tail_lines, strip_ansi=strip_ansi)):
                    yield _sse(
                        "line",
                        {
                            "plan_id": plan_id,
                            "room_id": room_id,
                            "epic_ref": source["epic_ref"],
                            "status": source["status"],
                            "text": line,
                            "offset": source["size"],
                            "initial": True,
                        },
                        event_id=f"{room_id}:tail:{idx}",
                    )

        if once:
            yield _sse("done", {"plan_id": plan_id})
            return

        heartbeat_deadline = asyncio.get_running_loop().time() + 15
        while True:
            if await request.is_disconnected():
                break

            sources = _build_log_sources(plan_id, active_only=active_only, room_filter=room_filter)
            current_rooms = {source["room_id"] for source in sources}

            for source in sources:
                room_id = source["room_id"]
                state = states.setdefault(room_id, {"offset": 0, "partial": "", "status": source["status"]})

                if state.get("status") != source["status"]:
                    state["status"] = source["status"]
                    yield _sse("room_status", {
                        "plan_id": plan_id,
                        "room_id": room_id,
                        "epic_ref": source["epic_ref"],
                        "status": source["status"],
                        "active": source["active"],
                    })

                path: Path = source["path"]
                if not path.exists():
                    continue

                try:
                    size = path.stat().st_size
                except OSError:
                    continue

                if size < state["offset"]:
                    state["offset"] = 0
                    state["partial"] = ""
                    yield _sse("rotate", {
                        "plan_id": plan_id,
                        "room_id": room_id,
                        "epic_ref": source["epic_ref"],
                        "size": size,
                    })

                if size <= state["offset"]:
                    continue

                try:
                    with path.open("rb") as handle:
                        handle.seek(state["offset"])
                        chunk = handle.read(_MAX_INCREMENTAL_READ_BYTES)
                        state["offset"] = handle.tell()
                except OSError:
                    continue

                if not chunk:
                    continue

                text = chunk.decode("utf-8", errors="replace")
                if strip_ansi:
                    text = _ANSI_RE.sub("", text)
                text = state.get("partial", "") + text
                if text.endswith(("\n", "\r")):
                    lines = text.splitlines()
                    state["partial"] = ""
                else:
                    lines = text.splitlines()
                    state["partial"] = lines.pop() if lines else text

                for line in lines:
                    yield _sse(
                        "line",
                        {
                            "plan_id": plan_id,
                            "room_id": room_id,
                            "epic_ref": source["epic_ref"],
                            "status": source["status"],
                            "text": line,
                            "offset": state["offset"],
                            "initial": False,
                        },
                        event_id=f"{room_id}:{state['offset']}",
                    )

            for room_id in list(states.keys()):
                if room_id not in current_rooms and active_only:
                    states.pop(room_id, None)

            now = asyncio.get_running_loop().time()
            if now >= heartbeat_deadline:
                yield _sse("heartbeat", {"plan_id": plan_id, "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
                heartbeat_deadline = now + 15

            await asyncio.sleep(poll_seconds)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
