import json

import pytest

from dashboard.orchestration_events import EventTailer, discover_event_logs, ingest_live_orchestration_event


def _event(event_id: str, event_type: str = "epic.failed", **overrides):
    base = {
        "v": 1,
        "event_id": event_id,
        "event_type": event_type,
        "ts": "2026-06-06T00:00:00Z",
        "plan_id": "plan-1",
        "run_id": "run-1",
        "room_id": "room-001",
        "epic_ref": "EPIC-001",
        "severity": "error",
        "summary": "EPIC-001 failed after QA timeout.",
        "payload": {},
    }
    base.update(overrides)
    return base


class DummyBroadcaster:
    def __init__(self):
        self.normalized = []
        self.legacy = []

    async def broadcast_orchestration_event(self, event):
        self.normalized.append({"type": "orchestration.event", "data": event})

    async def broadcast(self, event_type, data):
        self.legacy.append((event_type, data))


class DummyStore:
    def __init__(self):
        self.rooms = []
        self.epics = []

    def upsert_room_metadata(self, room_id, room):
        self.rooms.append((room_id, room))

    def update_epic_status(self, plan_id, epic_ref, status):
        self.epics.append((plan_id, epic_ref, status))


async def noop_notification(*_args, **_kwargs):
    return None


@pytest.fixture
def warroom_tree(tmp_path):
    plans = tmp_path / ".agents" / "plans"
    plans.mkdir(parents=True)
    warrooms = tmp_path / ".war-rooms"
    warrooms.mkdir()
    room = warrooms / "room-001"
    room.mkdir()
    (room / "status").write_text("developing")
    (room / "task-ref").write_text("EPIC-001")
    (room / "config.json").write_text(json.dumps({"plan_id": "plan-1"}))
    (room / "channel.jsonl").write_text("")
    (plans / "plan-1.meta.json").write_text(json.dumps({"plan_id": "plan-1", "warrooms_dir": str(warrooms), "status": "running"}))
    return plans, warrooms, warrooms / "events.jsonl", room


@pytest.mark.asyncio
async def test_tailer_broadcasts_normalized_envelope_and_legacy_projection(warroom_tree):
    plans, warrooms, events_file, room = warroom_tree
    events_file.write_text(json.dumps(_event("evt-1")) + "\n")
    broadcaster = DummyBroadcaster()
    notifications = []

    async def collect_notification(event_type, data):
        notifications.append((event_type, data))

    tailer = EventTailer(
        broadcaster,
        plans_dir=plans,
        warrooms_dir=warrooms,
        notification_processor=collect_notification,
    )

    await tailer.heartbeat()

    assert broadcaster.normalized == [{"type": "orchestration.event", "data": _event("evt-1")}]
    assert broadcaster.legacy[0][0] == "room_updated"
    assert (room / "status").read_text() == "failed"
    assert notifications == [("orchestration.event", {"type": "orchestration.event", "data": _event("evt-1")})]
    cursor = tailer.cursors[str(events_file.resolve())]
    assert cursor.byte_offset == events_file.stat().st_size
    assert cursor.last_event_id == "evt-1"
    assert cursor.last_mtime > 0


@pytest.mark.asyncio
async def test_tailer_skips_duplicate_event_ids_in_same_process(warroom_tree):
    plans, warrooms, events_file, _room = warroom_tree
    events_file.write_text(json.dumps(_event("evt-dup")) + "\n" + json.dumps(_event("evt-dup", summary="duplicate")) + "\n")
    broadcaster = DummyBroadcaster()
    tailer = EventTailer(broadcaster, plans_dir=plans, warrooms_dir=warrooms, notification_processor=noop_notification)

    await tailer.heartbeat()
    await tailer.heartbeat()

    assert len(broadcaster.normalized) == 1
    assert tailer.cursors[str(events_file.resolve())].byte_offset == events_file.stat().st_size


@pytest.mark.asyncio
async def test_tailer_handles_malformed_and_partial_rows(warroom_tree):
    plans, warrooms, events_file, _room = warroom_tree
    complete_event = json.dumps(_event("evt-good", event_type="plan.run.completed"))
    partial_event = json.dumps(_event("evt-partial", event_type="plan.run.failed"))
    events_file.write_text("not-json\n" + complete_event + "\n" + partial_event)
    broadcaster = DummyBroadcaster()
    tailer = EventTailer(broadcaster, plans_dir=plans, warrooms_dir=warrooms, notification_processor=noop_notification)

    await tailer.heartbeat()

    assert [msg["data"]["event_id"] for msg in broadcaster.normalized] == ["evt-good"]
    assert tailer.cursors[str(events_file.resolve())].byte_offset == len(("not-json\n" + complete_event + "\n").encode())

    with events_file.open("a", encoding="utf-8") as fp:
        fp.write("\n")
    await tailer.heartbeat()
    assert [msg["data"]["event_id"] for msg in broadcaster.normalized] == ["evt-good", "evt-partial"]


@pytest.mark.asyncio
async def test_tailer_resets_safely_when_event_log_is_truncated(warroom_tree):
    plans, warrooms, events_file, _room = warroom_tree
    events_file.write_text(json.dumps(_event("evt-1")) + "\n")
    broadcaster = DummyBroadcaster()
    tailer = EventTailer(broadcaster, plans_dir=plans, warrooms_dir=warrooms, notification_processor=noop_notification)
    await tailer.heartbeat()

    events_file.write_text(json.dumps(_event("evt-2", event_type="plan.run.failed")) + "\n")
    tailer.cursors[str(events_file.resolve())].byte_offset = 10_000
    await tailer.heartbeat()

    assert [msg["data"]["event_id"] for msg in broadcaster.normalized] == ["evt-1", "evt-2"]


def test_discover_event_logs_uses_plan_metadata_and_global_dir(warroom_tree):
    plans, warrooms, events_file, _room = warroom_tree
    events_file.write_text("")

    assert discover_event_logs(plans, warrooms) == [events_file]


@pytest.mark.asyncio
async def test_tailer_skips_invalid_envelopes_missing_run_id(warroom_tree):
    plans, warrooms, events_file, _room = warroom_tree
    invalid = _event("evt-no-run")
    invalid.pop("run_id")
    events_file.write_text(json.dumps(invalid) + "\n" + json.dumps(_event("evt-valid")) + "\n")
    broadcaster = DummyBroadcaster()
    tailer = EventTailer(broadcaster, plans_dir=plans, warrooms_dir=warrooms, notification_processor=noop_notification)

    await tailer.heartbeat()

    assert [msg["data"]["event_id"] for msg in broadcaster.normalized] == ["evt-valid"]


@pytest.mark.asyncio
async def test_tailer_updates_store_projection_for_epic_failed(warroom_tree):
    plans, warrooms, events_file, _room = warroom_tree
    events_file.write_text(json.dumps(_event("evt-store")) + "\n")
    broadcaster = DummyBroadcaster()
    store = DummyStore()
    tailer = EventTailer(
        broadcaster,
        plans_dir=plans,
        warrooms_dir=warrooms,
        store_getter=lambda: store,
        notification_processor=noop_notification,
    )

    await tailer.heartbeat()

    assert store.rooms and store.rooms[0][0] == "room-001"
    assert store.epics == [("plan-1", "EPIC-001", "failed")]


@pytest.mark.asyncio
async def test_tailer_projects_plan_failure_status_from_events_jsonl(warroom_tree):
    plans, warrooms, events_file, _room = warroom_tree
    events_file.write_text(json.dumps(_event("evt-plan-fail", "plan.run.failed", room_id=None, epic_ref=None)) + "\n")
    broadcaster = DummyBroadcaster()
    tailer = EventTailer(broadcaster, plans_dir=plans, warrooms_dir=warrooms, notification_processor=noop_notification)

    await tailer.heartbeat()

    meta = json.loads((plans / "plan-1.meta.json").read_text())
    assert meta["status"] == "failed"
    assert broadcaster.normalized[0]["data"]["run_id"] == "run-1"


@pytest.mark.asyncio
async def test_live_ingest_broadcasts_once_and_tailer_skips_duplicate(warroom_tree):
    plans, warrooms, events_file, _room = warroom_tree
    event = _event("evt-live-ingest")
    events_file.write_text(json.dumps(event) + "\n")
    broadcaster = DummyBroadcaster()

    result = await ingest_live_orchestration_event(
        event,
        broadcaster,
        plans_dir=plans,
        warrooms_dir=warrooms,
        notification_processor=noop_notification,
    )
    tailer = EventTailer(broadcaster, plans_dir=plans, warrooms_dir=warrooms, notification_processor=noop_notification)
    await tailer.heartbeat()

    assert result["accepted"] is True
    assert [msg["data"]["event_id"] for msg in broadcaster.normalized] == ["evt-live-ingest"]


@pytest.mark.asyncio
async def test_live_ingest_rejects_duplicate_event_id(warroom_tree):
    plans, warrooms, _events_file, _room = warroom_tree
    broadcaster = DummyBroadcaster()
    event = _event("evt-live-dup")

    first = await ingest_live_orchestration_event(event, broadcaster, plans_dir=plans, warrooms_dir=warrooms, notification_processor=noop_notification)
    second = await ingest_live_orchestration_event(event, broadcaster, plans_dir=plans, warrooms_dir=warrooms, notification_processor=noop_notification)

    assert first["accepted"] is True
    assert second["accepted"] is False
    assert second["duplicate"] is True
    assert [msg["data"]["event_id"] for msg in broadcaster.normalized] == ["evt-live-dup"]
