"""Dashboard orchestration event tailing and projection helpers.

The dashboard treats ``events.jsonl`` as the orchestration source of truth.
This module tails complete JSONL rows, maintains in-process cursor state, updates
dashboard read-model projections, and hands a normalized event envelope to bot
consumers without changing the legacy frontend messages during migration.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from dashboard.api_utils import PLANS_DIR, WARROOMS_DIR, read_room, process_notification, canonical_room_status

logger = logging.getLogger(__name__)


REQUIRED_EVENT_FIELDS = ("v", "event_id", "event_type", "ts", "plan_id", "run_id")

PLAN_STATUS_BY_EVENT = {
    "plan.run.started": "running",
    "plan.run.failed": "failed",
    "plan.run.completed": "completed",
}

ROOM_STATUS_BY_EVENT = {
    "room.status.changed": None,  # status comes from payload/status field
    "epic.passed": "done",
    "epic.retrying": "optimize",
    "epic.failed": "failed",
}

LEGACY_EVENT_BY_ORCHESTRATION_EVENT = {
    "room.created": "room_created",
    "room.status.changed": "room_updated",
    "epic.passed": "room_updated",
    "epic.failed": "room_updated",
    "plan.run.completed": "plans_updated",
    "plan.run.failed": "plans_updated",
}


class OrchestrationEventBuffer:
    """Bounded in-memory event buffer for live WebSocket ingestion."""

    def __init__(self, maxlen: int = 500):
        self.events: deque[dict[str, Any]] = deque(maxlen=max(1, maxlen))
        self.event_ids: set[str] = set()

    def append_if_new(self, event: dict[str, Any]) -> bool:
        event_id = str(event.get("event_id") or "")
        if not event_id:
            return False
        if event_id in self.event_ids:
            return False
        if len(self.events) == self.events.maxlen and self.events:
            evicted = self.events[0]
            evicted_id = evicted.get("event_id")
            if evicted_id:
                self.event_ids.discard(str(evicted_id))
        self.events.append(event)
        self.event_ids.add(event_id)
        return True

    def has_seen(self, event_id: str) -> bool:
        return event_id in self.event_ids

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self.events)


EVENT_BUFFER_SIZE = int(os.environ.get("OSTWIN_ORCHESTRATION_EVENT_BUFFER_SIZE", "500"))
event_buffer = OrchestrationEventBuffer(EVENT_BUFFER_SIZE)


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload", {})
    return payload if isinstance(payload, dict) else {}


def _event_log_context(event: dict[str, Any]) -> tuple[Any, Any, Any, Any, Any, Any]:
    payload = _event_payload(event)
    return (
        event.get("event_type"),
        event.get("event_id"),
        event.get("plan_id"),
        event.get("run_id"),
        event.get("room_id") or payload.get("room_id"),
        event.get("epic_ref") or payload.get("epic_ref"),
    )


@dataclass
class EventCursor:
    """Byte cursor for one event log path."""

    events_path: str
    byte_offset: int = 0
    last_event_id: str | None = None
    last_mtime: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "events_path": self.events_path,
            "byte_offset": self.byte_offset,
            "last_event_id": self.last_event_id,
            "last_mtime": self.last_mtime,
        }


def validate_orchestration_event(event: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate the normalized orchestration event row fields."""

    for field in REQUIRED_EVENT_FIELDS:
        if not event.get(field):
            return False, f"missing required field {field!r}"
    if not isinstance(event.get("payload", {}), dict):
        return False, "payload must be an object when present"
    return True, None


def _coerce_warrooms_path(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.name != ".war-rooms":
        path = path / ".war-rooms"
    return path


def discover_event_logs(plans_dir: Path = PLANS_DIR, warrooms_dir: Path = WARROOMS_DIR) -> list[Path]:
    """Discover active orchestration event logs from global and plan metadata."""

    warroom_dirs: set[Path] = set()
    if warrooms_dir.exists():
        warroom_dirs.add(warrooms_dir)

    if plans_dir.exists():
        for meta_file in plans_dir.glob("*.meta.json"):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            for key in ("warrooms_dir", "working_dir"):
                path = _coerce_warrooms_path(meta.get(key))
                if path and path.exists():
                    warroom_dirs.add(path)

    return sorted((d / "events.jsonl") for d in warroom_dirs if (d / "events.jsonl").exists())


def _find_plan_meta_file(plan_id: str, plans_dir: Path) -> Path | None:
    direct = plans_dir / f"{plan_id}.meta.json"
    if direct.exists():
        return direct
    for meta_file in plans_dir.glob("*.meta.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if meta.get("plan_id") == plan_id:
            return meta_file
    return None


def _write_plan_status(plan_id: str, status: str, plans_dir: Path) -> None:
    meta_file = _find_plan_meta_file(plan_id, plans_dir)
    if not meta_file:
        return
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        meta = {"plan_id": plan_id}
    meta["status"] = status
    meta_file.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _find_room_dir(event: dict[str, Any], events_path: Path, warrooms_dir: Path) -> Path | None:
    room_id = event.get("room_id") or event.get("payload", {}).get("room_id")
    if not room_id:
        return None
    candidates = [events_path.parent / room_id, warrooms_dir / room_id]
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _events_path_for_live_event(event: dict[str, Any], warrooms_dir: Path) -> Path:
    payload = _event_payload(event)
    raw_path = event.get("events_path") or payload.get("events_path")
    if raw_path:
        return Path(str(raw_path))
    raw_warrooms = payload.get("warrooms_dir")
    if raw_warrooms:
        return Path(str(raw_warrooms)) / "events.jsonl"
    return warrooms_dir / "events.jsonl"


def _project_room_status(event: dict[str, Any], events_path: Path, warrooms_dir: Path) -> Path | None:
    event_type = event.get("event_type")
    if event_type not in ROOM_STATUS_BY_EVENT and event_type != "room.created":
        return None

    room_dir = _find_room_dir(event, events_path, warrooms_dir)
    if not room_dir:
        return None

    status = event.get("status") or event.get("payload", {}).get("status") or ROOM_STATUS_BY_EVENT.get(event_type)
    if status:
        (room_dir / "status").write_text(canonical_room_status(str(status)), encoding="utf-8")
    return room_dir


def apply_projection(
    event: dict[str, Any],
    *,
    events_path: Path,
    plans_dir: Path = PLANS_DIR,
    warrooms_dir: Path = WARROOMS_DIR,
    store: Any = None,
) -> dict[str, Any]:
    """Update dashboard read models for plan and room status events."""

    event_type = event.get("event_type")
    plan_id = event.get("plan_id") or event.get("payload", {}).get("plan_id")
    room_dir = _project_room_status(event, events_path, warrooms_dir)

    if plan_id and event_type in PLAN_STATUS_BY_EVENT:
        _write_plan_status(plan_id, PLAN_STATUS_BY_EVENT[event_type], plans_dir)

    if store:
        room_id = event.get("room_id") or event.get("payload", {}).get("room_id")
        epic_ref = event.get("epic_ref") or event.get("payload", {}).get("epic_ref")
        room_status = canonical_room_status(event.get("status") or event.get("payload", {}).get("status") or ROOM_STATUS_BY_EVENT.get(event_type))
        try:
            if room_dir:
                store.upsert_room_metadata(room_dir.name, read_room(room_dir))
            if plan_id and epic_ref and room_status and hasattr(store, "update_epic_status"):
                store.update_epic_status(plan_id, epic_ref, room_status)
        except Exception:  # noqa: BLE001 - projection must not kill tailing loop
            logger.warning("Failed to update zvec projection for event %s", event.get("event_id"), exc_info=True)

    return {"room_dir": str(room_dir) if room_dir else None, "plan_id": plan_id}


def legacy_message_for_event(
    event: dict[str, Any], events_path: Path, warrooms_dir: Path = WARROOMS_DIR
) -> tuple[str, dict[str, Any]] | None:
    """Build legacy frontend compatibility messages for event-derived state."""

    event_type = event.get("event_type")
    legacy_type = LEGACY_EVENT_BY_ORCHESTRATION_EVENT.get(event_type)
    if not legacy_type:
        return None
    if legacy_type == "plans_updated":
        return legacy_type, {"plan_id": event.get("plan_id"), "orchestration_event": event}

    room_dir = _find_room_dir(event, events_path, warrooms_dir)
    room_id = event.get("room_id") or event.get("payload", {}).get("room_id")
    if room_dir:
        room = read_room(room_dir)
    else:
        room = {
            "room_id": room_id,
            "plan_id": event.get("plan_id"),
            "task_ref": event.get("epic_ref") or event.get("payload", {}).get("epic_ref"),
            "status": canonical_room_status(event.get("status") or event.get("payload", {}).get("status") or ROOM_STATUS_BY_EVENT.get(event_type) or "unknown"),
        }
    if event.get("plan_id") and not room.get("plan_id"):
        room["plan_id"] = event.get("plan_id")
    return legacy_type, {"room": room, "orchestration_event": event}


class EventTailer:
    """Heartbeat task that tails orchestration event logs with cursor semantics."""

    def __init__(
        self,
        broadcaster: Any,
        *,
        plans_dir: Path = PLANS_DIR,
        warrooms_dir: Path = WARROOMS_DIR,
        interval: float = 1.0,
        store_getter: Callable[[], Any] | None = None,
        notification_processor: Callable[[str, dict[str, Any]], Awaitable[None]] = process_notification,
    ):
        self.broadcaster = broadcaster
        self.plans_dir = plans_dir
        self.warrooms_dir = warrooms_dir
        self.interval = interval
        self.store_getter = store_getter or (lambda: None)
        self.notification_processor = notification_processor
        self.cursors: dict[str, EventCursor] = {}
        self.seen_event_ids: set[str] = set()

    def discover_logs(self) -> list[Path]:
        return discover_event_logs(self.plans_dir, self.warrooms_dir)

    async def run(self) -> None:
        while True:
            try:
                await self.heartbeat()
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("EventTailer heartbeat failed", exc_info=True)
                await asyncio.sleep(max(self.interval, 1.0))

    async def heartbeat(self) -> None:
        for events_path in self.discover_logs():
            await self.tail_file(events_path)

    async def tail_file(self, events_path: Path) -> None:
        resolved = str(events_path.resolve())
        cursor = self.cursors.setdefault(resolved, EventCursor(events_path=resolved))
        stat = events_path.stat()
        if stat.st_size < cursor.byte_offset:
            logger.warning("Event log %s shrank or rotated; resetting cursor to 0", events_path)
            cursor.byte_offset = 0
            cursor.last_mtime = stat.st_mtime

        with events_path.open("rb") as fp:
            fp.seek(cursor.byte_offset)
            chunk = fp.read()

        if not chunk:
            cursor.last_mtime = stat.st_mtime
            return

        base_offset = cursor.byte_offset
        complete_chunk = chunk
        if not chunk.endswith(b"\n"):
            last_newline = chunk.rfind(b"\n")
            if last_newline == -1:
                cursor.last_mtime = stat.st_mtime
                return
            complete_chunk = chunk[: last_newline + 1]

        offset = base_offset
        for raw_line in complete_chunk.splitlines(keepends=True):
            line_start = offset
            offset += len(raw_line)
            text = raw_line.decode("utf-8", errors="replace").strip()
            if not text:
                cursor.byte_offset = offset
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed orchestration event in %s at byte %s", events_path, line_start)
                cursor.byte_offset = offset
                continue
            if not isinstance(event, dict):
                logger.warning("Skipping non-object orchestration event in %s at byte %s", events_path, line_start)
                cursor.byte_offset = offset
                continue
            valid, reason = validate_orchestration_event(event)
            if not valid:
                logger.warning("Skipping invalid orchestration event in %s at byte %s: %s", events_path, line_start, reason)
                cursor.byte_offset = offset
                continue

            event_id = str(event["event_id"])
            if event_id in self.seen_event_ids or event_buffer.has_seen(event_id):
                logger.debug(
                    "Skipping duplicate tailed orchestration event event_type=%s event_id=%s plan_id=%s",
                    event.get("event_type"),
                    event_id,
                    event.get("plan_id"),
                )
                cursor.byte_offset = offset
                cursor.last_event_id = event_id
                continue

            await self._project_and_broadcast(event, events_path)
            self.seen_event_ids.add(event_id)
            cursor.byte_offset = offset
            cursor.last_event_id = event_id

        cursor.last_mtime = events_path.stat().st_mtime

    async def _project_and_broadcast(self, event: dict[str, Any], events_path: Path) -> None:
        logger.info(
            "Broadcasting tailed orchestration event event_type=%s event_id=%s plan_id=%s run_id=%s room_id=%s epic_ref=%s",
            *_event_log_context(event),
        )
        apply_projection(
            event,
            events_path=events_path,
            plans_dir=self.plans_dir,
            warrooms_dir=self.warrooms_dir,
            store=self.store_getter(),
        )
        await self.broadcaster.broadcast_orchestration_event(event)
        await self.notification_processor("orchestration.event", {"type": "orchestration.event", "data": event})

        legacy = legacy_message_for_event(event, events_path, self.warrooms_dir)
        if legacy:
            legacy_type, legacy_data = legacy
            await self.broadcaster.broadcast(legacy_type, legacy_data)


async def ingest_live_orchestration_event(
    event: dict[str, Any],
    broadcaster: Any,
    *,
    plans_dir: Path = PLANS_DIR,
    warrooms_dir: Path = WARROOMS_DIR,
    store: Any = None,
    notification_processor: Callable[[str, dict[str, Any]], Awaitable[None]] = process_notification,
) -> dict[str, Any]:
    """Process an orchestration event delivered directly over WebSocket."""

    valid, reason = validate_orchestration_event(event)
    if not valid:
        logger.warning("Rejected live orchestration event: %s event=%s", reason, event)
        return {"accepted": False, "duplicate": False, "reason": reason}

    event_id = str(event["event_id"])
    if not event_buffer.append_if_new(event):
        logger.info("Rejected duplicate live orchestration event event_id=%s event_type=%s plan_id=%s", event_id, event.get("event_type"), event.get("plan_id"))
        return {"accepted": False, "duplicate": True, "event_id": event_id}

    logger.info(
        "Broadcasting live orchestration event event_type=%s event_id=%s plan_id=%s run_id=%s room_id=%s epic_ref=%s",
        *_event_log_context(event),
    )
    events_path = _events_path_for_live_event(event, warrooms_dir)
    apply_projection(
        event,
        events_path=events_path,
        plans_dir=plans_dir,
        warrooms_dir=warrooms_dir,
        store=store,
    )
    await broadcaster.broadcast_orchestration_event(event)
    await notification_processor("orchestration.event", {"type": "orchestration.event", "data": event})

    legacy = legacy_message_for_event(event, events_path, warrooms_dir)
    if legacy:
        legacy_type, legacy_data = legacy
        await broadcaster.broadcast(legacy_type, legacy_data)

    return {"accepted": True, "duplicate": False, "event_id": event_id}
