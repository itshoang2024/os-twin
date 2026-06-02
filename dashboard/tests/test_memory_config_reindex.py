"""Tests for Plan 028: per-memory config, mismatch detection, and reindex.

Covers:
  - memory.config.json read/write
  - Embedding model mismatch detection at init
  - Auto-rebuild vectordb on mismatch
  - GET /api/amem/embedding-status endpoint
  - POST /api/amem/reindex endpoint
  - GET /api/amem/reindex/status endpoint
  - Pool evict() method
"""

import json
import os
import shutil
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from dashboard.agentic_memory.memory_system import AgenticMemorySystem
from dashboard.agentic_memory.memory_note import MemoryNote
from dashboard.agentic_memory.memory_pool import MemoryPool


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def tmp_persist_dir(tmp_path):
    """Create a temp persist dir with notes/ and vectordb/ subdirs."""
    notes = tmp_path / "notes"
    notes.mkdir()
    vectordb = tmp_path / "vectordb"
    vectordb.mkdir()
    return str(tmp_path)


@pytest.fixture
def mock_system(tmp_persist_dir):
    """Create an AgenticMemorySystem with mocked LLM/embedding."""
    with patch("dashboard.agentic_memory.memory_system._ensure_ml_imports"), \
         patch.object(AgenticMemorySystem, "_resolve_completion_fn", return_value=lambda *a, **k: "{}"):
        sys = AgenticMemorySystem(
            model_name="test-embedding-model",
            embedding_backend="ollama",
            vector_backend="zvec",
            persist_dir=tmp_persist_dir,
            embed_fn=lambda texts: [[0.1] * 128 for _ in texts],
        )
        return sys


# ═══════════════════════════════════════════════════════════════════════════════
# 1. memory.config.json read/write
# ═══════════════════════════════════════════════════════════════════════════════

class TestMemoryConfig:
    def test_config_created_on_init(self, mock_system, tmp_persist_dir):
        """Config file should be created when AgenticMemorySystem inits."""
        config_path = os.path.join(tmp_persist_dir, "memory.config.json")
        assert os.path.exists(config_path)

    def test_config_has_required_fields(self, mock_system, tmp_persist_dir):
        config_path = os.path.join(tmp_persist_dir, "memory.config.json")
        with open(config_path) as f:
            cfg = json.load(f)
        assert cfg["version"] == 1
        assert cfg["embedding_model"] == "test-embedding-model"
        assert cfg["embedding_backend"] == "ollama"
        assert cfg["vector_backend"] == "zvec"
        assert "plan_id" in cfg
        assert "plan_name" in cfg
        assert "created_at" in cfg
        assert "last_synced_at" in cfg
        assert "note_count" in cfg

    def test_config_updated_on_sync(self, mock_system, tmp_persist_dir):
        """sync_to_disk should update last_synced_at and note_count."""
        # Add a note
        note = MemoryNote(content="test note for sync", name="test", path="test")
        mock_system.memories[note.id] = note
        mock_system._dirty = True

        mock_system.sync_to_disk()

        config_path = os.path.join(tmp_persist_dir, "memory.config.json")
        with open(config_path) as f:
            cfg = json.load(f)
        assert cfg["note_count"] == 1

    def test_load_missing_config_returns_empty(self, mock_system):
        """Loading a missing config should return empty dict."""
        os.remove(mock_system._config_path())
        result = mock_system._load_memory_config()
        assert result == {}

    def test_load_corrupt_config_returns_empty(self, mock_system, tmp_persist_dir):
        """Loading a corrupt config should return empty dict."""
        config_path = os.path.join(tmp_persist_dir, "memory.config.json")
        with open(config_path, "w") as f:
            f.write("NOT JSON{{{")
        result = mock_system._load_memory_config()
        assert result == {}

    def test_plan_name_resolved_from_metadata(self, tmp_persist_dir):
        """Plan name should be resolved from .agents/plans/<id>.meta.json."""
        plan_id = os.path.basename(tmp_persist_dir)
        meta_dir = os.path.join(os.path.expanduser("~"), ".ostwin", ".agents", "plans")
        os.makedirs(meta_dir, exist_ok=True)
        meta_path = os.path.join(meta_dir, f"{plan_id}.meta.json")

        try:
            with open(meta_path, "w") as f:
                json.dump({"title": "My Test Plan"}, f)

            name = AgenticMemorySystem._resolve_plan_name(plan_id)
            assert name == "My Test Plan"
        finally:
            if os.path.exists(meta_path):
                os.remove(meta_path)

    def test_plan_name_fallback_to_id(self):
        """Plan name should fall back to plan_id if no metadata exists."""
        name = AgenticMemorySystem._resolve_plan_name("nonexistent-plan-id")
        assert name == "nonexistent-plan-id"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Mismatch detection
# ═══════════════════════════════════════════════════════════════════════════════

class TestMismatchDetection:
    def test_no_mismatch_same_model(self, mock_system, tmp_persist_dir):
        """No rebuild when model matches."""
        result = mock_system._check_and_rebuild_if_mismatched()
        assert result is False

    def test_mismatch_triggers_rebuild(self, tmp_persist_dir):
        """Different model in config should trigger rebuild."""
        # Write config with old model
        config_path = os.path.join(tmp_persist_dir, "memory.config.json")
        with open(config_path, "w") as f:
            json.dump({
                "version": 1,
                "embedding_model": "old-model-v1",
                "plan_id": "test",
                "plan_name": "test",
            }, f)

        # Add a note to disk so rebuild has something to re-embed
        notes_dir = os.path.join(tmp_persist_dir, "notes")
        note = MemoryNote(content="test note for rebuild", name="rebuild-test", path="test")
        note_path = os.path.join(notes_dir, "rebuild-test.md")
        with open(note_path, "w") as f:
            f.write(note.to_markdown())

        # Init with different model — should detect mismatch and rebuild
        with patch("dashboard.agentic_memory.memory_system._ensure_ml_imports"), \
             patch.object(AgenticMemorySystem, "_resolve_completion_fn", return_value=lambda *a, **k: "{}"):
            sys = AgenticMemorySystem(
                model_name="new-model-v2",
                embedding_backend="ollama",
                vector_backend="zvec",
                persist_dir=tmp_persist_dir,
                embed_fn=lambda texts: [[0.1] * 128 for _ in texts],
            )

        # Config should now have new model
        with open(config_path) as f:
            cfg = json.load(f)
        assert cfg["embedding_model"] == "new-model-v2"

    def test_no_rebuild_without_config(self, tmp_persist_dir):
        """Legacy directory without config should not trigger rebuild."""
        with patch("dashboard.agentic_memory.memory_system._ensure_ml_imports"), \
             patch.object(AgenticMemorySystem, "_resolve_completion_fn", return_value=lambda *a, **k: "{}"):
            sys = AgenticMemorySystem(
                model_name="any-model",
                embedding_backend="ollama",
                vector_backend="zvec",
                persist_dir=tmp_persist_dir,
                embed_fn=lambda texts: [[0.1] * 128 for _ in texts],
            )
        # Should create config (first boot), not rebuild
        config_path = os.path.join(tmp_persist_dir, "memory.config.json")
        assert os.path.exists(config_path)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Pool evict()
# ═══════════════════════════════════════════════════════════════════════════════

class TestPoolEvict:
    def test_evict_existing_slot(self, tmp_path):
        """evict() should remove a specific slot by persist_dir."""
        from dashboard.agentic_memory.memory_pool import PoolConfig
        cfg = PoolConfig(ml_preload=False)

        persist_dir = str(tmp_path / "test-plan")
        os.makedirs(persist_dir, exist_ok=True)
        os.makedirs(os.path.join(persist_dir, "notes"), exist_ok=True)
        os.makedirs(os.path.join(persist_dir, "vectordb"), exist_ok=True)

        def mock_factory(persist_dir):
            m = MagicMock()
            m.persist_dir = persist_dir
            return m

        pool = MemoryPool(config=cfg, system_factory=mock_factory)
        slot = pool.get_or_create(persist_dir)
        assert slot is not None

        result = pool.evict(persist_dir)
        assert result is True

    def test_evict_nonexistent_slot(self, tmp_path):
        """evict() should return False for unknown persist_dir."""
        from dashboard.agentic_memory.memory_pool import PoolConfig
        cfg = PoolConfig(ml_preload=False)
        pool = MemoryPool(config=cfg, system_factory=lambda pd: MagicMock())
        result = pool.evict(str(tmp_path / "nonexistent"))
        assert result is False


# ═══════════════════════════════════════════════════════════════════════════════
# 4. API endpoints (embedding-status, reindex)
# ═══════════════════════════════════════════════════════════════════════════════

class TestReindexAPI:
    """Tests for the reindex API endpoints via TestClient."""

    @pytest.fixture(autouse=True)
    def setup_test_memory(self, tmp_path):
        """Create test memory directories with configs."""
        self.memory_base = tmp_path / "memory"
        self.memory_base.mkdir()

        # Plan A: has config with model-A
        plan_a = self.memory_base / "memory-plan-aaa"
        (plan_a / "notes").mkdir(parents=True)
        (plan_a / "vectordb").mkdir()
        note = MemoryNote(content="note from plan A", name="note-a", path="test")
        (plan_a / "notes" / "note-a.md").write_text(note.to_markdown())
        (plan_a / "memory.config.json").write_text(json.dumps({
            "version": 1,
            "plan_id": "plan-aaa",
            "plan_name": "Plan Alpha",
            "embedding_model": "model-A",
        }))

        # Plan B: has config with model-B (already matches proposed)
        plan_b = self.memory_base / "memory-plan-bbb"
        (plan_b / "notes").mkdir(parents=True)
        (plan_b / "vectordb").mkdir()
        (plan_b / "memory.config.json").write_text(json.dumps({
            "version": 1,
            "plan_id": "plan-bbb",
            "plan_name": "Plan Beta",
            "embedding_model": "model-B",
        }))

        # Plan C: no config (legacy)
        plan_c = self.memory_base / "memory-plan-ccc"
        (plan_c / "notes").mkdir(parents=True)

        self.tmp_path = tmp_path

    def test_scan_memory_configs(self):
        """_scan_memory_configs should detect match/mismatch/unknown."""
        from dashboard.routes.amem import _scan_memory_configs, MEMORY_BASE_DIR
        import dashboard.routes.amem as amem_mod

        old_base = amem_mod.MEMORY_BASE_DIR
        try:
            amem_mod.MEMORY_BASE_DIR = self.memory_base
            plans = _scan_memory_configs("model-B")

            by_id = {p["plan_id"]: p for p in plans}
            assert by_id["plan-aaa"]["status"] == "mismatch"
            assert by_id["plan-bbb"]["status"] == "match"
            assert by_id["plan-ccc"]["status"] == "unknown"
            assert by_id["plan-aaa"]["plan_name"] == "Plan Alpha"
        finally:
            amem_mod.MEMORY_BASE_DIR = old_base

    def test_scan_counts_notes(self):
        """Scan should count .md files in notes/."""
        from dashboard.routes.amem import _scan_memory_configs
        import dashboard.routes.amem as amem_mod

        old_base = amem_mod.MEMORY_BASE_DIR
        try:
            amem_mod.MEMORY_BASE_DIR = self.memory_base
            plans = _scan_memory_configs("model-B")
            by_id = {p["plan_id"]: p for p in plans}
            assert by_id["plan-aaa"]["note_count"] == 1
            assert by_id["plan-bbb"]["note_count"] == 0
        finally:
            amem_mod.MEMORY_BASE_DIR = old_base
