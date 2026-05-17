"""Unit tests for dashboard.plan_lifecycle.

The module derives a plan's lifecycle from three on-disk signals — runner
PID liveness, ``progress.json`` heartbeat freshness, and per-room outcomes.
These tests exercise each of the five terminal states (draft / running /
stopped / completed / failed) by writing minimal fixtures to a tmp dir and
swapping in ``PLANS_DIR`` via monkeypatch.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dashboard import plan_lifecycle


# ── Helpers ──────────────────────────────────────────────────────────


def _isolate(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    """Point ``plan_lifecycle`` at a tmp PLANS_DIR + warrooms dir.

    Returns (plans_dir, warrooms_dir).
    """
    plans_dir = tmp_path / "plans"
    warrooms_dir = tmp_path / "warrooms"
    plans_dir.mkdir()
    warrooms_dir.mkdir()
    monkeypatch.setattr(plan_lifecycle, "PLANS_DIR", plans_dir)
    return plans_dir, warrooms_dir


def _write_meta(plans_dir: Path, plan_id: str, payload: dict) -> Path:
    f = plans_dir / f"{plan_id}.meta.json"
    f.write_text(json.dumps(payload))
    return f


def _write_progress(warrooms_dir: Path, payload: dict, *, mtime: float | None = None) -> Path:
    f = warrooms_dir / "progress.json"
    f.write_text(json.dumps(payload))
    if mtime is not None:
        os.utime(f, (mtime, mtime))
    return f


# ── _pid_alive ───────────────────────────────────────────────────────


class TestPidAlive:
    def test_none_pid_is_dead(self):
        assert plan_lifecycle._pid_alive(None) is False

    def test_zero_or_negative_pid_is_dead(self):
        assert plan_lifecycle._pid_alive(0) is False
        assert plan_lifecycle._pid_alive(-1) is False

    def test_current_process_is_alive(self):
        assert plan_lifecycle._pid_alive(os.getpid()) is True

    def test_unknown_pid_is_dead(self, monkeypatch):
        def raise_lookup(pid, sig):
            raise ProcessLookupError
        monkeypatch.setattr(plan_lifecycle.os, "kill", raise_lookup)
        assert plan_lifecycle._pid_alive(999999) is False

    def test_permission_error_means_alive(self, monkeypatch):
        # OS rejects signal-0 from us because the process is owned by another
        # user — but the process still exists.
        def raise_perm(pid, sig):
            raise PermissionError
        monkeypatch.setattr(plan_lifecycle.os, "kill", raise_perm)
        assert plan_lifecycle._pid_alive(1) is True

    def test_registered_handle_polls_zombie_dead(self, monkeypatch):
        """An exited-but-unreaped child must report dead via poll(), not via os.kill.

        ``os.kill(pid, 0)`` succeeds on zombies, which would otherwise leave
        crashed runners looking alive forever. Once registered, the Popen
        handle short-circuits that path.
        """
        class FakeProc:
            def __init__(self, exit_code):
                self._exit = exit_code
            def poll(self):
                return self._exit

        # Force os.kill to "succeed" to prove the registry path is what
        # actually reports death.
        monkeypatch.setattr(plan_lifecycle.os, "kill", lambda pid, sig: None)
        monkeypatch.setattr(plan_lifecycle, "_runner_handles", {})

        plan_lifecycle.register_runner(7777, FakeProc(exit_code=0))
        assert plan_lifecycle._pid_alive(7777) is False
        # Handle should be dropped after a dead poll() so we don't leak.
        assert 7777 not in plan_lifecycle._runner_handles

    def test_registered_handle_running_stays_alive(self, monkeypatch):
        class FakeProc:
            def poll(self):
                return None  # still running

        monkeypatch.setattr(plan_lifecycle, "_runner_handles", {})
        plan_lifecycle.register_runner(8888, FakeProc())
        assert plan_lifecycle._pid_alive(8888) is True
        assert 8888 in plan_lifecycle._runner_handles


# ── record_launch ────────────────────────────────────────────────────


class TestRecordLaunch:
    def test_persists_pid_and_timestamp(self, tmp_path, monkeypatch):
        plans_dir, _ = _isolate(monkeypatch, tmp_path)
        _write_meta(plans_dir, "p1", {"plan_id": "p1", "status": "draft"})

        plan_lifecycle.record_launch("p1", 4242)

        meta = json.loads((plans_dir / "p1.meta.json").read_text())
        assert meta["runner_pid"] == 4242
        assert meta["status"] == "running"
        # Must be a parseable ISO-8601 UTC timestamp
        datetime.fromisoformat(meta["launched_at"])

    def test_skips_when_meta_missing(self, tmp_path, monkeypatch, caplog):
        plans_dir, _ = _isolate(monkeypatch, tmp_path)
        plan_lifecycle.record_launch("nope", 1234)
        # No meta to write to; record_launch should no-op without raising.
        assert not (plans_dir / "nope.meta.json").exists()

    def test_overwrites_previous_pid(self, tmp_path, monkeypatch):
        plans_dir, _ = _isolate(monkeypatch, tmp_path)
        _write_meta(plans_dir, "p1", {"plan_id": "p1", "runner_pid": 111})
        plan_lifecycle.record_launch("p1", 222)
        meta = json.loads((plans_dir / "p1.meta.json").read_text())
        assert meta["runner_pid"] == 222


# ── derive_lifecycle ─────────────────────────────────────────────────


class TestDeriveLifecycle:
    def test_draft_when_no_meta(self, tmp_path, monkeypatch):
        _isolate(monkeypatch, tmp_path)
        result = plan_lifecycle.derive_lifecycle("ghost")
        assert result["state"] == "draft"
        assert result["runner_pid"] is None
        assert result["alive"] is False
        assert result["last_heartbeat_at"] is None

    def test_draft_when_meta_has_no_launch(self, tmp_path, monkeypatch):
        plans_dir, _ = _isolate(monkeypatch, tmp_path)
        _write_meta(plans_dir, "p1", {"plan_id": "p1", "status": "draft"})
        result = plan_lifecycle.derive_lifecycle("p1")
        assert result["state"] == "draft"

    def test_completed_when_all_rooms_passed(self, tmp_path, monkeypatch):
        plans_dir, warrooms = _isolate(monkeypatch, tmp_path)
        _write_meta(plans_dir, "p1", {
            "plan_id": "p1",
            "warrooms_dir": str(warrooms),
            "runner_pid": 1,
            "launched_at": "2026-05-16T10:00:00+00:00",
        })
        _write_progress(warrooms, {
            "rooms": [
                {"status": "passed"},
                {"status": "passed"},
            ],
        })
        result = plan_lifecycle.derive_lifecycle("p1")
        assert result["state"] == "completed"
        assert "2 room(s) passed" in result["reason"]

    def test_completed_dominates_even_if_pid_alive(self, tmp_path, monkeypatch):
        # All rooms passed — we don't care whether the runner is still up;
        # the work is done.
        plans_dir, warrooms = _isolate(monkeypatch, tmp_path)
        _write_meta(plans_dir, "p1", {
            "plan_id": "p1",
            "warrooms_dir": str(warrooms),
            "runner_pid": os.getpid(),
            "launched_at": "2026-05-16T10:00:00+00:00",
        })
        _write_progress(warrooms, {"rooms": [{"status": "passed"}]})
        result = plan_lifecycle.derive_lifecycle("p1")
        assert result["state"] == "completed"

    def test_running_when_pid_alive_and_heartbeat_fresh(self, tmp_path, monkeypatch):
        plans_dir, warrooms = _isolate(monkeypatch, tmp_path)
        _write_meta(plans_dir, "p1", {
            "plan_id": "p1",
            "warrooms_dir": str(warrooms),
            "runner_pid": os.getpid(),
            "launched_at": "2026-05-16T10:00:00+00:00",
        })
        _write_progress(warrooms, {"rooms": [{"status": "developing"}]})
        result = plan_lifecycle.derive_lifecycle("p1")
        assert result["state"] == "running"
        assert result["alive"] is True
        assert result["heartbeat_age_s"] is not None
        assert result["heartbeat_age_s"] <= plan_lifecycle.HEARTBEAT_TIMEOUT_S

    def test_running_when_pid_alive_but_heartbeat_stale(self, tmp_path, monkeypatch):
        # Process up but manager loop is wedged — surface running with a
        # "stale" reason rather than flapping to stopped.
        plans_dir, warrooms = _isolate(monkeypatch, tmp_path)
        _write_meta(plans_dir, "p1", {
            "plan_id": "p1",
            "warrooms_dir": str(warrooms),
            "runner_pid": os.getpid(),
            "launched_at": "2026-05-16T10:00:00+00:00",
        })
        stale_mtime = time.time() - (plan_lifecycle.HEARTBEAT_TIMEOUT_S + 30)
        _write_progress(warrooms, {"rooms": [{"status": "developing"}]}, mtime=stale_mtime)
        result = plan_lifecycle.derive_lifecycle("p1")
        assert result["state"] == "running"
        assert "stale" in result["reason"]

    def test_failed_when_pid_dead_and_a_room_failed_final(self, tmp_path, monkeypatch):
        plans_dir, warrooms = _isolate(monkeypatch, tmp_path)
        # Use a PID we know is gone — _pid_alive should report False via
        # the monkeypatched os.kill below.
        monkeypatch.setattr(plan_lifecycle.os, "kill", _fake_dead_pid)
        _write_meta(plans_dir, "p1", {
            "plan_id": "p1",
            "warrooms_dir": str(warrooms),
            "runner_pid": 999999,
            "launched_at": "2026-05-16T10:00:00+00:00",
        })
        _write_progress(warrooms, {
            "rooms": [
                {"status": "passed"},
                {"status": "failed-final"},
            ],
        })
        result = plan_lifecycle.derive_lifecycle("p1")
        assert result["state"] == "failed"
        assert "1 room(s) failed-final" in result["reason"]

    def test_stopped_when_pid_dead_and_no_failures(self, tmp_path, monkeypatch):
        plans_dir, warrooms = _isolate(monkeypatch, tmp_path)
        monkeypatch.setattr(plan_lifecycle.os, "kill", _fake_dead_pid)
        _write_meta(plans_dir, "p1", {
            "plan_id": "p1",
            "warrooms_dir": str(warrooms),
            "runner_pid": 999999,
            "launched_at": "2026-05-16T10:00:00+00:00",
        })
        _write_progress(warrooms, {
            "rooms": [
                {"status": "passed"},
                {"status": "developing"},  # not done, not failed
            ],
        })
        result = plan_lifecycle.derive_lifecycle("p1")
        assert result["state"] == "stopped"
        assert "1/2" in result["reason"]

    def test_stopped_when_progress_missing(self, tmp_path, monkeypatch):
        # Meta says it launched but progress.json never appeared and PID is
        # gone — we can't claim completed/failed, so stopped is the truthful
        # state.
        plans_dir, warrooms = _isolate(monkeypatch, tmp_path)
        monkeypatch.setattr(plan_lifecycle.os, "kill", _fake_dead_pid)
        _write_meta(plans_dir, "p1", {
            "plan_id": "p1",
            "warrooms_dir": str(warrooms),
            "runner_pid": 999999,
            "launched_at": "2026-05-16T10:00:00+00:00",
        })
        result = plan_lifecycle.derive_lifecycle("p1")
        assert result["state"] == "stopped"

    def test_returns_all_expected_keys(self, tmp_path, monkeypatch):
        plans_dir, _ = _isolate(monkeypatch, tmp_path)
        _write_meta(plans_dir, "p1", {"plan_id": "p1"})
        result = plan_lifecycle.derive_lifecycle("p1")
        for key in (
            "state", "reason", "runner_pid", "alive",
            "launched_at", "last_heartbeat_at", "heartbeat_age_s",
        ):
            assert key in result, f"missing key: {key}"

    def test_ignores_non_int_runner_pid(self, tmp_path, monkeypatch):
        # Defensive: someone hand-edits meta and stores a string. Should
        # be treated as no PID, not crash.
        plans_dir, _ = _isolate(monkeypatch, tmp_path)
        _write_meta(plans_dir, "p1", {"plan_id": "p1", "runner_pid": "not-a-pid"})
        result = plan_lifecycle.derive_lifecycle("p1")
        assert result["runner_pid"] is None
        assert result["alive"] is False


def _fake_dead_pid(pid, sig):
    raise ProcessLookupError
