import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import dashboard.api_utils as api_utils
from dashboard.api import app
from dashboard.auth import get_current_user
from dashboard.routes import plan_logs


@pytest.fixture
def client(tmp_path, monkeypatch):
    plans_dir = tmp_path / "plans"
    warrooms_dir = tmp_path / "warrooms"
    plans_dir.mkdir()
    warrooms_dir.mkdir()

    monkeypatch.setattr(api_utils, "PLANS_DIR", plans_dir)
    monkeypatch.setattr(api_utils, "WARROOMS_DIR", warrooms_dir)
    monkeypatch.setattr(plan_logs, "PLANS_DIR", plans_dir)
    monkeypatch.setattr(plan_logs, "WARROOMS_DIR", warrooms_dir)

    app.dependency_overrides[get_current_user] = lambda: {"sub": "test_user"}
    with patch("dashboard.api.startup_all", new_callable=AsyncMock):
        with TestClient(app) as c:
            yield c, plans_dir, warrooms_dir
    app.dependency_overrides.clear()


def _make_room(warrooms_dir, room_id: str, *, plan_id: str, epic_ref: str, status: str):
    room_dir = warrooms_dir / room_id
    room_dir.mkdir(parents=True)
    (room_dir / "config.json").write_text(json.dumps({"plan_id": plan_id, "task_ref": epic_ref}), encoding="utf-8")
    (room_dir / "task-ref").write_text(epic_ref, encoding="utf-8")
    (room_dir / "status").write_text(status, encoding="utf-8")
    return room_dir


def test_list_plan_logs_discovers_plan_scoped_log_files(client):
    c, plans_dir, warrooms_dir = client
    _make_room(warrooms_dir, "room-001", plan_id="planA", epic_ref="EPIC-001", status="developing")
    _make_room(warrooms_dir, "room-002", plan_id="planA", epic_ref="EPIC-002", status="pending")
    _make_room(warrooms_dir, "room-999", plan_id="otherPlan", epic_ref="EPIC-999", status="developing")
    plan_log_dir = plans_dir / "planA"
    plan_log_dir.mkdir()
    (plan_log_dir / "room-001.log").write_text("line one\nline two\n", encoding="utf-8")
    (plan_log_dir / "room-002.log").write_text("pending line\n", encoding="utf-8")
    (plans_dir / "planA.room-999.log").write_text("must not leak\n", encoding="utf-8")
    (warrooms_dir / "progress.json").write_text(json.dumps({
        "rooms": [
            {"room_id": "room-001", "task_ref": "EPIC-001", "status": "developing"},
            {"room_id": "room-002", "task_ref": "EPIC-002", "status": "pending"},
            {"room_id": "room-999", "task_ref": "EPIC-999", "status": "developing"},
        ]
    }), encoding="utf-8")

    response = c.get("/api/plans/planA/logs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["logs_dir"].endswith("/planA")
    assert [room["room_id"] for room in payload["rooms"]] == ["room-001", "room-002"]
    assert payload["rooms"][0]["exists"] is True
    assert payload["rooms"][0]["active"] is True
    assert payload["rooms"][1]["active"] is False


def test_list_plan_logs_active_only_follows_non_terminal_logs_and_filters_done(client):
    c, plans_dir, warrooms_dir = client
    _make_room(warrooms_dir, "room-001", plan_id="planA", epic_ref="EPIC-001", status="developing")
    _make_room(warrooms_dir, "room-002", plan_id="planA", epic_ref="EPIC-002", status="pending")
    _make_room(warrooms_dir, "room-003", plan_id="planA", epic_ref="EPIC-003", status="done")
    plan_log_dir = plans_dir / "planA"
    plan_log_dir.mkdir()
    (plan_log_dir / "room-001.log").write_text("active\n", encoding="utf-8")
    (plan_log_dir / "room-002.log").write_text("pending-but-writing\n", encoding="utf-8")
    (plan_log_dir / "room-003.log").write_text("done\n", encoding="utf-8")

    response = c.get("/api/plans/planA/logs?active_only=true")

    assert response.status_code == 200
    payload = response.json()
    assert [room["room_id"] for room in payload["rooms"]] == ["room-001", "room-002"]
    assert payload["rooms"][0]["active"] is True
    assert payload["rooms"][1]["active"] is False
    assert payload["rooms"][1]["followable"] is True


def test_stream_plan_logs_once_emits_init_tail_and_done(client):
    c, plans_dir, warrooms_dir = client
    _make_room(warrooms_dir, "room-001", plan_id="planA", epic_ref="EPIC-001", status="developing")
    (plans_dir / "planA").mkdir()
    (plans_dir / "planA" / "room-001.log").write_text("old line\nlatest line\n", encoding="utf-8")

    response = c.get("/api/plans/planA/logs/stream?once=true&tail_lines=1")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: init" in body
    assert "event: line" in body
    assert "event: done" in body
    assert "latest line" in body
    assert "old line" not in body


def test_list_plan_logs_discovers_direct_log_without_runtime_metadata(client, monkeypatch):
    c, plans_dir, _ = client
    monkeypatch.setattr(plan_logs, "resolve_runtime_plan_warrooms_dir", lambda plan_id: None)
    (plans_dir / "planA").mkdir()
    (plans_dir / "planA" / "room-001.log").write_text("log-only source\n", encoding="utf-8")

    response = c.get("/api/plans/planA/logs?active_only=true")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["rooms"][0]["room_id"] == "room-001"
    assert payload["rooms"][0]["status"] == "unknown"
    assert payload["rooms"][0]["followable"] is True


def test_stream_plan_logs_default_active_only_tails_pending_log_file(client):
    c, plans_dir, warrooms_dir = client
    _make_room(warrooms_dir, "room-001", plan_id="planA", epic_ref="EPIC-001", status="pending")
    (plans_dir / "planA").mkdir()
    (plans_dir / "planA" / "room-001.log").write_text("old line\ncurrent pending line\n", encoding="utf-8")

    response = c.get("/api/plans/planA/logs/stream?once=true&tail_lines=1")

    assert response.status_code == 200
    body = response.text
    assert "event: init" in body
    assert "event: line" in body
    assert "current pending line" in body


def test_plan_logs_reject_invalid_identifiers(client):
    c, _, _ = client

    response = c.get("/api/plans/../secret/logs")

    assert response.status_code in {404, 422}


def test_list_plan_logs_migrates_legacy_flat_log_files(client, monkeypatch):
    c, plans_dir, _ = client
    monkeypatch.setattr(plan_logs, "resolve_runtime_plan_warrooms_dir", lambda plan_id: None)
    legacy = plans_dir / "planA.room-001.log"
    legacy.write_text("legacy line\n", encoding="utf-8")

    response = c.get("/api/plans/planA/logs?active_only=true")

    assert response.status_code == 200
    canonical = plans_dir / "planA" / "room-001.log"
    assert canonical.exists()
    assert not legacy.exists()
    assert response.json()["rooms"][0]["exists"] is True


def test_get_plan_room_log_returns_full_content(client):
    c, plans_dir, warrooms_dir = client
    _make_room(warrooms_dir, "room-001", plan_id="planA", epic_ref="EPIC-001", status="developing")
    (plans_dir / "planA").mkdir()
    (plans_dir / "planA" / "room-001.log").write_text("first\nsecond\nthird\n", encoding="utf-8")

    response = c.get("/api/plans/planA/logs/room-001/content")

    assert response.status_code == 200
    payload = response.json()
    assert payload["room_id"] == "room-001"
    assert payload["content"] == "first\nsecond\nthird\n"
    assert payload["truncated"] is False
