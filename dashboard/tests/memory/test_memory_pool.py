"""Unit tests for memory_pool.py.

Verifies:
- Slot creation and reuse (get_or_create)
- Idle sweep kills stale slots
- Eviction when max_instances reached (lru, oldest, none)
- kill_slot / kill_all lifecycle
- Path validation (allowed_paths)
- ML preload gating
- Stats reporting
- Thread safety under concurrent access

All tests use the ``patched_memory_system`` helper from tests/helpers.py
so no real ML imports, no network calls, and no heavy deps.
"""

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from dashboard.agentic_memory.pool_config import PoolConfig  # noqa: E402
from dashboard.agentic_memory.memory_pool import MemoryPool, MemorySlot  # noqa: E402


def _noop_preloader():
    """ML preloader that does nothing (tests don't need real ML)."""
    pass


def _fake_system_factory(persist_dir: str = "", **kwargs):
    """Factory that returns a lightweight mock instead of AgenticMemorySystem."""
    system = SimpleNamespace(
        memories={},
        persist_dir=persist_dir,
        sync_to_disk=MagicMock(return_value={"written": 0}),
        tree=MagicMock(return_value="(empty)"),
        search=MagicMock(return_value=[]),
        read=MagicMock(return_value=None),
        add_note=MagicMock(),
    )
    return system


def _pool_with_defaults(**overrides) -> MemoryPool:
    """Create a MemoryPool with test-friendly defaults."""
    defaults = dict(
        idle_timeout_s=0,  # no idle sweep by default in tests
        max_instances=10,
        eviction_policy="lru",
        ml_preload=False,  # skip ML preload
        ml_ready_timeout_s=1,
        sync_interval_s=3600,  # effectively disabled
        sync_on_kill=False,  # skip final sync for speed
        allowed_paths=None,
        sweep_interval_s=3600,  # effectively disabled
    )
    defaults.update(overrides)
    config = PoolConfig(**defaults)
    return MemoryPool(
        config=config,
        system_factory=_fake_system_factory,
        ml_preloader=_noop_preloader,
    )


class TestGetOrCreate(unittest.TestCase):
    """get_or_create must create new slots and reuse existing ones."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pool = _pool_with_defaults()

    def tearDown(self):
        self.pool.kill_all()

    def test_creates_new_slot(self):
        slot = self.pool.get_or_create(self.tmpdir)
        self.assertIsInstance(slot, MemorySlot)
        self.assertEqual(slot.persist_dir, os.path.realpath(self.tmpdir))
        self.assertEqual(self.pool.active_slots, 1)

    def test_reuses_existing_slot(self):
        slot1 = self.pool.get_or_create(self.tmpdir)
        slot2 = self.pool.get_or_create(self.tmpdir)
        self.assertIs(slot1, slot2)
        self.assertEqual(self.pool.active_slots, 1)

    def test_different_dirs_create_different_slots(self):
        dir2 = tempfile.mkdtemp()
        slot1 = self.pool.get_or_create(self.tmpdir)
        slot2 = self.pool.get_or_create(dir2)
        self.assertIsNot(slot1, slot2)
        self.assertEqual(self.pool.active_slots, 2)

    def test_updates_last_activity_on_reuse(self):
        slot = self.pool.get_or_create(self.tmpdir)
        old_activity = slot.last_activity
        time.sleep(0.01)
        self.pool.get_or_create(self.tmpdir)
        self.assertGreater(slot.last_activity, old_activity)

    def test_canonicalizes_path(self):
        """Symlinks / trailing slashes / .. resolve to the same slot."""
        slot1 = self.pool.get_or_create(self.tmpdir)
        slot2 = self.pool.get_or_create(self.tmpdir + "/")
        self.assertIs(slot1, slot2)


class TestTouch(unittest.TestCase):
    """touch() must update last_activity without creating slots."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pool = _pool_with_defaults()

    def tearDown(self):
        self.pool.kill_all()

    def test_updates_activity(self):
        slot = self.pool.get_or_create(self.tmpdir)
        old = slot.last_activity
        time.sleep(0.01)
        self.pool.touch(self.tmpdir)
        self.assertGreater(slot.last_activity, old)

    def test_noop_for_unknown_dir(self):
        # Should not raise
        self.pool.touch("/nonexistent/path")


class TestKillSlot(unittest.TestCase):
    """kill_slot() must remove the slot and optionally sync."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_removes_slot(self):
        pool = _pool_with_defaults()
        pool.get_or_create(self.tmpdir)
        self.assertEqual(pool.active_slots, 1)
        result = pool.kill_slot(self.tmpdir)
        self.assertTrue(result)
        self.assertEqual(pool.active_slots, 0)

    def test_returns_false_for_unknown(self):
        pool = _pool_with_defaults()
        self.assertFalse(pool.kill_slot("/no/such/dir"))

    def test_sync_on_kill_when_enabled(self):
        pool = _pool_with_defaults(sync_on_kill=True)
        slot = pool.get_or_create(self.tmpdir)
        pool.kill_slot(self.tmpdir)
        slot.system.sync_to_disk.assert_called_once()

    def test_no_sync_when_disabled(self):
        pool = _pool_with_defaults(sync_on_kill=False)
        slot = pool.get_or_create(self.tmpdir)
        pool.kill_slot(self.tmpdir)
        slot.system.sync_to_disk.assert_not_called()


class TestKillAll(unittest.TestCase):
    """kill_all() must clear every slot."""

    def test_kills_all_slots(self):
        pool = _pool_with_defaults()
        dirs = [tempfile.mkdtemp() for _ in range(3)]
        for d in dirs:
            pool.get_or_create(d)
        self.assertEqual(pool.active_slots, 3)
        pool.kill_all()
        self.assertEqual(pool.active_slots, 0)


class TestIdleSweep(unittest.TestCase):
    """The background sweep must kill slots idle beyond the timeout."""

    def test_sweep_kills_idle_slot(self):
        pool = _pool_with_defaults(idle_timeout_s=1, sweep_interval_s=3600)
        tmpdir = tempfile.mkdtemp()
        pool.get_or_create(tmpdir)
        self.assertEqual(pool.active_slots, 1)

        # Artificially age the slot
        canonical = os.path.realpath(tmpdir)
        with pool._lock:
            pool._slots[canonical].last_activity = time.monotonic() - 10

        # Trigger one sweep pass directly (don't wait for the thread)
        pool._sweep_once(timeout=1)
        self.assertEqual(pool.active_slots, 0)

    def test_sweep_spares_active_slot(self):
        pool = _pool_with_defaults(idle_timeout_s=60, sweep_interval_s=3600)
        tmpdir = tempfile.mkdtemp()
        pool.get_or_create(tmpdir)

        pool._sweep_once(timeout=60)
        self.assertEqual(pool.active_slots, 1)
        pool.kill_all()


class TestEviction(unittest.TestCase):
    """When max_instances is reached, eviction must free a slot."""

    def test_lru_evicts_least_recently_used(self):
        pool = _pool_with_defaults(max_instances=2, eviction_policy="lru")
        d1, d2, d3 = (tempfile.mkdtemp() for _ in range(3))

        pool.get_or_create(d1)
        time.sleep(0.01)
        pool.get_or_create(d2)
        time.sleep(0.01)
        # d1 has the oldest last_activity — should be evicted
        pool.get_or_create(d3)
        # Give eviction thread a moment to clean up
        time.sleep(0.1)

        self.assertLessEqual(pool.active_slots, 2)
        # d1 should be gone
        canonical_d1 = os.path.realpath(d1)
        with pool._lock:
            self.assertNotIn(canonical_d1, pool._slots)
        pool.kill_all()

    def test_oldest_evicts_oldest_created(self):
        pool = _pool_with_defaults(max_instances=2, eviction_policy="oldest")
        d1, d2, d3 = (tempfile.mkdtemp() for _ in range(3))

        pool.get_or_create(d1)
        time.sleep(0.01)
        pool.get_or_create(d2)
        time.sleep(0.01)
        # Touch d1 so it's recently used but still oldest by creation
        pool.touch(d1)
        pool.get_or_create(d3)
        time.sleep(0.1)

        canonical_d1 = os.path.realpath(d1)
        with pool._lock:
            self.assertNotIn(canonical_d1, pool._slots)
        pool.kill_all()

    def test_none_policy_raises_when_full(self):
        pool = _pool_with_defaults(max_instances=1, eviction_policy="none")
        d1 = tempfile.mkdtemp()
        d2 = tempfile.mkdtemp()

        pool.get_or_create(d1)
        with self.assertRaises(RuntimeError) as ctx:
            pool.get_or_create(d2)
        self.assertIn("full", str(ctx.exception).lower())
        pool.kill_all()


class TestAllowedPaths(unittest.TestCase):
    """allowed_paths must restrict which persist_dirs are accepted."""

    def test_rejects_disallowed_path(self):
        pool = _pool_with_defaults(allowed_paths=["/allowed/only"])
        with self.assertRaises(ValueError) as ctx:
            pool.get_or_create("/tmp/evil/.memory")
        self.assertIn("not under any allowed path", str(ctx.exception))
        pool.kill_all()

    def test_accepts_allowed_path(self):
        allowed_dir = tempfile.mkdtemp()
        pool = _pool_with_defaults(allowed_paths=[allowed_dir])
        slot = pool.get_or_create(allowed_dir)
        self.assertIsNotNone(slot)
        pool.kill_all()

    def test_no_restriction_when_none(self):
        pool = _pool_with_defaults(allowed_paths=None)
        tmpdir = tempfile.mkdtemp()
        slot = pool.get_or_create(tmpdir)
        self.assertIsNotNone(slot)
        pool.kill_all()


class TestMLPreload(unittest.TestCase):
    """ML preload must gate slot creation until ready."""

    def test_ml_ready_set_after_preload(self):
        pool = _pool_with_defaults()
        # With ml_preload=False, _ml_ready is set immediately
        self.assertTrue(pool._ml_ready.is_set())

    def test_ml_preload_runs_in_background(self):
        called = threading.Event()

        def slow_preloader():
            called.set()

        config = PoolConfig(
            ml_preload=True,
            ml_ready_timeout_s=5,
            idle_timeout_s=0,
            max_instances=10,
            eviction_policy="lru",
            sync_interval_s=3600,
            sync_on_kill=False,
            sweep_interval_s=3600,
        )
        pool = MemoryPool(
            config=config,
            system_factory=_fake_system_factory,
            ml_preloader=slow_preloader,
        )
        called.wait(timeout=2)
        self.assertTrue(called.is_set())
        # _ml_ready is set by _run_ml_preload after the preloader returns
        pool._ml_ready.wait(timeout=2)
        self.assertTrue(pool._ml_ready.is_set())
        pool.kill_all()


class TestStats(unittest.TestCase):
    """stats() must report pool state accurately."""

    def test_empty_pool_stats(self):
        pool = _pool_with_defaults()
        s = pool.stats()
        self.assertTrue(s["ml_ready"])
        self.assertEqual(s["active_slots"], 0)
        self.assertEqual(s["slots"], [])
        self.assertEqual(s["config"]["idle_timeout_s"], 0)

    def test_stats_with_slots(self):
        pool = _pool_with_defaults()
        d1 = tempfile.mkdtemp()
        pool.get_or_create(d1)
        s = pool.stats()
        self.assertEqual(s["active_slots"], 1)
        self.assertEqual(len(s["slots"]), 1)
        slot_info = s["slots"][0]
        self.assertEqual(slot_info["persist_dir"], os.path.realpath(d1))
        self.assertIn("idle_seconds", slot_info)
        self.assertIn("notes_count", slot_info)
        pool.kill_all()


class TestConcurrency(unittest.TestCase):
    """Concurrent get_or_create calls must not create duplicate slots."""

    def test_concurrent_same_dir(self):
        pool = _pool_with_defaults()
        tmpdir = tempfile.mkdtemp()
        results = []
        errors = []

        def worker():
            try:
                slot = pool.get_or_create(tmpdir)
                results.append(id(slot))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(len(errors), 0, f"Errors: {errors}")
        # All threads should get the same slot object
        self.assertEqual(len(set(results)), 1, "All threads should share one slot")
        self.assertEqual(pool.active_slots, 1)
        pool.kill_all()


class TestSyncThread(unittest.TestCase):
    """Each slot must get its own sync thread."""

    def test_sync_thread_starts(self):
        pool = _pool_with_defaults(sync_interval_s=3600)
        tmpdir = tempfile.mkdtemp()
        slot = pool.get_or_create(tmpdir)
        self.assertIsNotNone(slot.sync_thread)
        self.assertTrue(slot.sync_thread.is_alive())
        pool.kill_all()

    def test_sync_thread_stops_on_kill(self):
        pool = _pool_with_defaults(sync_interval_s=3600)
        tmpdir = tempfile.mkdtemp()
        slot = pool.get_or_create(tmpdir)
        sync_thread = slot.sync_thread
        pool.kill_slot(tmpdir)
        self.assertTrue(slot.sync_stop.is_set())
        sync_thread.join(timeout=2)
        self.assertFalse(sync_thread.is_alive())


if __name__ == "__main__":
    unittest.main()
