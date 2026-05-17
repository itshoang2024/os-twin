"""Unit tests for MemoryPool — manages multiple AgenticMemorySystem instances.

Covers:
  - Pool creation and configuration
  - get_or_create slot lifecycle
  - Slot eviction (LRU, oldest, none policies)
  - kill_slot and kill_all
  - Path validation (allowed_paths)
  - Stats and active_slots
  - ML preload behavior
  - Idle sweep behavior
"""

import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from dashboard.agentic_memory.pool_config import PoolConfig
from dashboard.agentic_memory.memory_pool import MemoryPool, MemorySlot


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_mock_system(memories=None):
    """Create a mock AgenticMemorySystem."""
    system = MagicMock()
    system.memories = memories or {}
    system.sync_to_disk.return_value = {"written": 0}
    system.retriever = MagicMock()
    system.retriever.close = MagicMock()
    return system


def _make_pool(**overrides):
    """Create a MemoryPool with mock system factory and disabled ML preload."""
    defaults = {
        "ml_preload": False,
        "idle_timeout_s": 0,  # disable idle sweep for tests
        "max_instances": 5,
        "eviction_policy": "lru",
        "sync_on_kill": False,
        "sweep_interval_s": 9999,
    }
    cfg = PoolConfig(**{**defaults, **overrides})

    created_systems = []

    def factory(persist_dir):
        system = _make_mock_system()
        created_systems.append((persist_dir, system))
        return system

    pool = MemoryPool(config=cfg, system_factory=factory)
    return pool, created_systems


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Pool Creation
# ═══════════════════════════════════════════════════════════════════════════════


class TestMemoryPoolCreation:
    """Test pool creation and configuration."""

    def test_pool_creation_with_defaults(self):
        pool, _ = _make_pool()
        assert pool.active_slots == 0

    def test_pool_creation_no_ml_preload(self):
        """ML preload disabled should set ml_ready immediately."""
        pool, _ = _make_pool(ml_preload=False)
        assert pool._ml_ready.is_set()

    def test_pool_creation_with_ml_preload(self):
        """ML preload enabled should start background thread."""
        preload_done = threading.Event()

        def slow_preload():
            preload_done.wait(timeout=5)

        cfg = PoolConfig(ml_preload=True, idle_timeout_s=0, sweep_interval_s=9999)
        pool = MemoryPool(config=cfg, ml_preloader=slow_preload)
        assert not pool._ml_ready.is_set()
        preload_done.set()
        pool.kill_all()


# ═══════════════════════════════════════════════════════════════════════════════
# 2. get_or_create Slot Lifecycle
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetOrCreate:
    """Test get_or_create slot lifecycle."""

    def test_creates_slot_on_first_access(self, tmp_path):
        pool, created = _make_pool()
        persist_dir = str(tmp_path / "mem1")
        slot = pool.get_or_create(persist_dir)
        assert slot is not None
        assert slot.system is not None
        assert pool.active_slots == 1

    def test_returns_same_slot_for_same_dir(self, tmp_path):
        pool, _ = _make_pool()
        persist_dir = str(tmp_path / "mem1")
        slot1 = pool.get_or_create(persist_dir)
        slot2 = pool.get_or_create(persist_dir)
        assert slot1 is slot2
        assert pool.active_slots == 1

    def test_creates_different_slots_for_different_dirs(self, tmp_path):
        pool, _ = _make_pool()
        slot1 = pool.get_or_create(str(tmp_path / "mem1"))
        slot2 = pool.get_or_create(str(tmp_path / "mem2"))
        assert slot1 is not slot2
        assert pool.active_slots == 2

    def test_touches_last_activity(self, tmp_path):
        pool, _ = _make_pool()
        persist_dir = str(tmp_path / "mem1")
        slot1 = pool.get_or_create(persist_dir)
        old_activity = slot1.last_activity
        time.sleep(0.01)
        slot2 = pool.get_or_create(persist_dir)
        assert slot2.last_activity >= old_activity

    def test_canonicalizes_path(self, tmp_path):
        pool, _ = _make_pool()
        real_dir = str(tmp_path / "mem1")
        os.makedirs(real_dir, exist_ok=True)
        slot1 = pool.get_or_create(real_dir)
        # Access with trailing slash or different relative form
        slot2 = pool.get_or_create(real_dir + "/")
        assert slot1 is slot2


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Slot Eviction
# ═══════════════════════════════════════════════════════════════════════════════


class TestEviction:
    """Test slot eviction policies."""

    def test_lru_eviction_when_full(self, tmp_path):
        pool, _ = _make_pool(max_instances=2, eviction_policy="lru")
        slot1 = pool.get_or_create(str(tmp_path / "mem1"))
        slot2 = pool.get_or_create(str(tmp_path / "mem2"))
        # Access slot1 to make it more recent
        time.sleep(0.01)
        pool.get_or_create(str(tmp_path / "mem1"))
        # Adding a third should evict slot2 (LRU)
        slot3 = pool.get_or_create(str(tmp_path / "mem3"))
        assert pool.active_slots == 2
        # slot2 should have been evicted
        dirs = list(pool._slots.keys())
        assert str(tmp_path / "mem2") not in [os.path.realpath(d) for d in dirs]

    def test_oldest_eviction_when_full(self, tmp_path):
        pool, _ = _make_pool(max_instances=2, eviction_policy="oldest")
        pool.get_or_create(str(tmp_path / "mem1"))
        time.sleep(0.01)
        pool.get_or_create(str(tmp_path / "mem2"))
        # Adding a third should evict mem1 (oldest)
        pool.get_or_create(str(tmp_path / "mem3"))
        assert pool.active_slots == 2

    def test_none_eviction_raises_when_full(self, tmp_path):
        pool, _ = _make_pool(max_instances=2, eviction_policy="none")
        pool.get_or_create(str(tmp_path / "mem1"))
        pool.get_or_create(str(tmp_path / "mem2"))
        with pytest.raises(RuntimeError, match="Memory pool is full"):
            pool.get_or_create(str(tmp_path / "mem3"))


# ═══════════════════════════════════════════════════════════════════════════════
# 4. kill_slot and kill_all
# ═══════════════════════════════════════════════════════════════════════════════


class TestKillOperations:
    """Test kill_slot and kill_all."""

    def test_kill_slot_removes_it(self, tmp_path):
        pool, _ = _make_pool()
        persist_dir = str(tmp_path / "mem1")
        pool.get_or_create(persist_dir)
        assert pool.active_slots == 1
        result = pool.kill_slot(persist_dir)
        assert result is True
        assert pool.active_slots == 0

    def test_kill_nonexistent_slot_returns_false(self, tmp_path):
        pool, _ = _make_pool()
        result = pool.kill_slot(str(tmp_path / "nonexistent"))
        assert result is False

    def test_kill_all_removes_all_slots(self, tmp_path):
        pool, _ = _make_pool()
        pool.get_or_create(str(tmp_path / "mem1"))
        pool.get_or_create(str(tmp_path / "mem2"))
        assert pool.active_slots == 2
        pool.kill_all()
        assert pool.active_slots == 0

    def test_kill_slot_with_sync(self, tmp_path):
        pool, created = _make_pool(sync_on_kill=True)
        persist_dir = str(tmp_path / "mem1")
        pool.get_or_create(persist_dir)
        # Find the system that was created
        _, system = created[0]
        pool.kill_slot(persist_dir)
        system.sync_to_disk.assert_called()


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Path Validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestPathValidation:
    """Test allowed_paths validation."""

    def test_allowed_paths_accepts_valid(self, tmp_path):
        allowed = str(tmp_path / "data")
        os.makedirs(allowed, exist_ok=True)
        pool, _ = _make_pool(allowed_paths=[allowed])
        slot = pool.get_or_create(os.path.join(allowed, "mem1"))
        assert slot is not None

    def test_allowed_paths_rejects_invalid(self, tmp_path):
        allowed = str(tmp_path / "data")
        os.makedirs(allowed, exist_ok=True)
        pool, _ = _make_pool(allowed_paths=[allowed])
        with pytest.raises(ValueError, match="not under any allowed path"):
            pool.get_or_create(str(tmp_path / "other" / "mem1"))

    def test_no_allowed_paths_accepts_any(self, tmp_path):
        pool, _ = _make_pool(allowed_paths=None)
        slot = pool.get_or_create(str(tmp_path / "anywhere" / "mem1"))
        assert slot is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Stats & Touch
# ═══════════════════════════════════════════════════════════════════════════════


class TestStatsAndTouch:
    """Test stats() and touch() methods."""

    def test_stats_empty_pool(self):
        pool, _ = _make_pool()
        stats = pool.stats()
        assert stats["active_slots"] == 0
        assert stats["ml_ready"] is True
        assert stats["slots"] == []

    def test_stats_with_slots(self, tmp_path):
        pool, _ = _make_pool()
        pool.get_or_create(str(tmp_path / "mem1"))
        stats = pool.stats()
        assert stats["active_slots"] == 1
        assert len(stats["slots"]) == 1
        slot_info = stats["slots"][0]
        assert "persist_dir" in slot_info
        assert "notes_count" in slot_info
        assert "idle_seconds" in slot_info

    def test_touch_updates_activity(self, tmp_path):
        pool, _ = _make_pool()
        persist_dir = str(tmp_path / "mem1")
        slot = pool.get_or_create(persist_dir)
        old_activity = slot.last_activity
        time.sleep(0.01)
        pool.touch(persist_dir)
        assert slot.last_activity > old_activity

    def test_touch_nonexistent_does_not_raise(self, tmp_path):
        pool, _ = _make_pool()
        pool.touch(str(tmp_path / "nonexistent"))  # should not raise


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Idle Sweep
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdleSweep:
    """Test idle sweep behavior."""

    def test_idle_sweep_kills_stale_slots(self, tmp_path):
        pool, _ = _make_pool(idle_timeout_s=1, sweep_interval_s=9999)
        persist_dir = str(tmp_path / "mem1")
        pool.get_or_create(persist_dir)
        assert pool.active_slots == 1

        # Simulate idle by setting last_activity to past
        with pool._lock:
            slot = pool._slots.get(os.path.realpath(persist_dir))
            if slot:
                slot.last_activity = time.monotonic() - 100  # 100s ago

        # Run sweep manually
        pool._sweep_once(timeout=0.5)
        assert pool.active_slots == 0

    def test_idle_sweep_keeps_active_slots(self, tmp_path):
        pool, _ = _make_pool(idle_timeout_s=3600, sweep_interval_s=9999)
        persist_dir = str(tmp_path / "mem1")
        pool.get_or_create(persist_dir)
        pool._sweep_once(timeout=3600)
        assert pool.active_slots == 1
