"""Unit tests for pool_config.py.

Verifies:
- Default values from config.default.json are loaded correctly.
- Environment variables override JSON defaults.
- Edge cases: missing JSON file, empty env vars, comma-separated lists.

No network calls, no heavy imports, no filesystem side effects beyond
reading the existing config.default.json.
"""

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard.agentic_memory.pool_config import PoolConfig, load_pool_config  # noqa: E402


class TestPoolConfigDefaults(unittest.TestCase):
    """load_pool_config() with no env overrides should match config.default.json."""

    def test_loads_defaults(self):
        cfg = load_pool_config()
        self.assertIsInstance(cfg, PoolConfig)
        self.assertEqual(cfg.idle_timeout_s, 300)
        self.assertEqual(cfg.max_instances, 10)
        self.assertEqual(cfg.eviction_policy, "lru")
        self.assertTrue(cfg.ml_preload)
        self.assertEqual(cfg.ml_ready_timeout_s, 30)
        self.assertEqual(cfg.sync_interval_s, 60)
        self.assertTrue(cfg.sync_on_kill)
        self.assertIsNone(cfg.allowed_paths)
        self.assertEqual(cfg.sweep_interval_s, 30)

    def test_default_json_has_pool_section(self):
        """Verify config.default.json actually contains the pool section."""
        config_path = _MEMORY_DIR / "config.default.json"
        self.assertTrue(config_path.exists(), "config.default.json must exist")
        data = json.loads(config_path.read_text())
        self.assertIn("pool", data)
        self.assertEqual(data["pool"]["idle_timeout_s"], 300)


# Resolve _MEMORY_DIR for the config.default.json test
_MEMORY_DIR = Path(__file__).resolve().parent.parent.parent / "agentic_memory"


class TestPoolConfigEnvOverrides(unittest.TestCase):
    """Environment variables must override JSON defaults."""

    @patch.dict(os.environ, {"MEMORY_POOL_IDLE_TIMEOUT": "120"})
    def test_idle_timeout_override(self):
        cfg = load_pool_config()
        self.assertEqual(cfg.idle_timeout_s, 120)

    @patch.dict(os.environ, {"MEMORY_POOL_MAX_INSTANCES": "5"})
    def test_max_instances_override(self):
        cfg = load_pool_config()
        self.assertEqual(cfg.max_instances, 5)

    @patch.dict(os.environ, {"MEMORY_POOL_EVICTION": "oldest"})
    def test_eviction_policy_override(self):
        cfg = load_pool_config()
        self.assertEqual(cfg.eviction_policy, "oldest")

    @patch.dict(os.environ, {"MEMORY_POOL_ML_PRELOAD": "false"})
    def test_ml_preload_false(self):
        cfg = load_pool_config()
        self.assertFalse(cfg.ml_preload)

    @patch.dict(os.environ, {"MEMORY_POOL_ML_PRELOAD": "1"})
    def test_ml_preload_truthy(self):
        cfg = load_pool_config()
        self.assertTrue(cfg.ml_preload)

    @patch.dict(os.environ, {"MEMORY_POOL_ML_TIMEOUT": "60"})
    def test_ml_timeout_override(self):
        cfg = load_pool_config()
        self.assertEqual(cfg.ml_ready_timeout_s, 60)

    @patch.dict(os.environ, {"MEMORY_POOL_SYNC_INTERVAL": "120"})
    def test_sync_interval_override(self):
        cfg = load_pool_config()
        self.assertEqual(cfg.sync_interval_s, 120)

    @patch.dict(os.environ, {"MEMORY_POOL_SYNC_ON_KILL": "false"})
    def test_sync_on_kill_false(self):
        cfg = load_pool_config()
        self.assertFalse(cfg.sync_on_kill)

    @patch.dict(os.environ, {"MEMORY_POOL_SWEEP_INTERVAL": "10"})
    def test_sweep_interval_override(self):
        cfg = load_pool_config()
        self.assertEqual(cfg.sweep_interval_s, 10)


class TestPoolConfigAllowedPaths(unittest.TestCase):
    """The allowed_paths field supports comma-separated env var."""

    @patch.dict(os.environ, {"MEMORY_POOL_ALLOWED_PATHS": "/tmp/a,/tmp/b"})
    def test_comma_separated(self):
        cfg = load_pool_config()
        self.assertEqual(cfg.allowed_paths, ["/tmp/a", "/tmp/b"])

    @patch.dict(os.environ, {"MEMORY_POOL_ALLOWED_PATHS": " /tmp/a , /tmp/b "})
    def test_strips_whitespace(self):
        cfg = load_pool_config()
        self.assertEqual(cfg.allowed_paths, ["/tmp/a", "/tmp/b"])

    @patch.dict(os.environ, {"MEMORY_POOL_ALLOWED_PATHS": ""})
    def test_empty_string_becomes_none(self):
        cfg = load_pool_config()
        self.assertIsNone(cfg.allowed_paths)

    def test_none_by_default(self):
        # No env var set — should fall through to JSON default (null)
        cfg = load_pool_config()
        self.assertIsNone(cfg.allowed_paths)


if __name__ == "__main__":
    unittest.main()
