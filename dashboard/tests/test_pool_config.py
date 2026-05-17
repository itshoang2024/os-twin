"""Unit tests for PoolConfig — configuration for the Memory Pool.

Covers:
  - Default values
  - Environment variable overrides
  - Dashboard Settings (config.json) overrides
  - Config file loading
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from dashboard.agentic_memory.pool_config import PoolConfig, load_pool_config


class TestPoolConfigDefaults:
    """Test PoolConfig default values."""

    def test_default_idle_timeout(self):
        cfg = PoolConfig()
        assert cfg.idle_timeout_s == 300

    def test_default_max_instances(self):
        cfg = PoolConfig()
        assert cfg.max_instances == 10

    def test_default_eviction_policy(self):
        cfg = PoolConfig()
        assert cfg.eviction_policy == "lru"

    def test_default_ml_preload(self):
        cfg = PoolConfig()
        assert cfg.ml_preload is True

    def test_default_ml_ready_timeout(self):
        cfg = PoolConfig()
        assert cfg.ml_ready_timeout_s == 30

    def test_default_sync_interval(self):
        cfg = PoolConfig()
        assert cfg.sync_interval_s == 60

    def test_default_sync_on_kill(self):
        cfg = PoolConfig()
        assert cfg.sync_on_kill is True

    def test_default_allowed_paths(self):
        cfg = PoolConfig()
        assert cfg.allowed_paths is None

    def test_default_sweep_interval(self):
        cfg = PoolConfig()
        assert cfg.sweep_interval_s == 30


class TestPoolConfigCustomValues:
    """Test PoolConfig with custom values."""

    def test_custom_idle_timeout(self):
        cfg = PoolConfig(idle_timeout_s=600)
        assert cfg.idle_timeout_s == 600

    def test_custom_max_instances(self):
        cfg = PoolConfig(max_instances=20)
        assert cfg.max_instances == 20

    def test_eviction_policy_none(self):
        cfg = PoolConfig(eviction_policy="none")
        assert cfg.eviction_policy == "none"

    def test_eviction_policy_oldest(self):
        cfg = PoolConfig(eviction_policy="oldest")
        assert cfg.eviction_policy == "oldest"

    def test_allowed_paths(self):
        cfg = PoolConfig(allowed_paths=["/data", "/tmp"])
        assert cfg.allowed_paths == ["/data", "/tmp"]


class TestLoadPoolConfig:
    """Test load_pool_config() with env var overrides."""

    def test_load_with_defaults(self):
        """Should load with defaults when no env vars or config files set."""
        # Clear any env vars that might be set
        env_vars = [
            "MEMORY_POOL_IDLE_TIMEOUT", "MEMORY_POOL_MAX_INSTANCES",
            "MEMORY_POOL_EVICTION", "MEMORY_POOL_ML_PRELOAD",
            "MEMORY_POOL_ML_TIMEOUT", "MEMORY_POOL_SYNC_INTERVAL",
            "MEMORY_POOL_SYNC_ON_KILL", "MEMORY_POOL_ALLOWED_PATHS",
            "MEMORY_POOL_SWEEP_INTERVAL",
        ]
        with patch.dict(os.environ, {}, clear=False):
            for var in env_vars:
                os.environ.pop(var, None)
            cfg = load_pool_config()
            assert isinstance(cfg, PoolConfig)

    def test_env_var_idle_timeout(self):
        with patch.dict(os.environ, {"MEMORY_POOL_IDLE_TIMEOUT": "600"}):
            cfg = load_pool_config()
            assert cfg.idle_timeout_s == 600

    def test_env_var_max_instances(self):
        with patch.dict(os.environ, {"MEMORY_POOL_MAX_INSTANCES": "20"}):
            cfg = load_pool_config()
            assert cfg.max_instances == 20

    def test_env_var_eviction_policy(self):
        with patch.dict(os.environ, {"MEMORY_POOL_EVICTION": "oldest"}):
            cfg = load_pool_config()
            assert cfg.eviction_policy == "oldest"

    def test_env_var_ml_preload_false(self):
        with patch.dict(os.environ, {"MEMORY_POOL_ML_PRELOAD": "false"}):
            cfg = load_pool_config()
            assert cfg.ml_preload is False

    def test_env_var_ml_preload_true(self):
        with patch.dict(os.environ, {"MEMORY_POOL_ML_PRELOAD": "true"}):
            cfg = load_pool_config()
            assert cfg.ml_preload is True

    def test_env_var_allowed_paths(self):
        with patch.dict(os.environ, {"MEMORY_POOL_ALLOWED_PATHS": "/data,/tmp"}):
            cfg = load_pool_config()
            assert cfg.allowed_paths == ["/data", "/tmp"]

    def test_env_var_allowed_paths_empty_becomes_none(self):
        with patch.dict(os.environ, {"MEMORY_POOL_ALLOWED_PATHS": ""}):
            cfg = load_pool_config()
            assert cfg.allowed_paths is None

    def test_env_var_sweep_interval(self):
        with patch.dict(os.environ, {"MEMORY_POOL_SWEEP_INTERVAL": "60"}):
            cfg = load_pool_config()
            assert cfg.sweep_interval_s == 60

    def test_settings_override(self, tmp_path):
        """Dashboard settings config.json should override defaults."""
        config_dir = tmp_path / ".ostwin" / ".agents"
        config_dir.mkdir(parents=True)
        config_path = config_dir / "config.json"
        config_path.write_text(json.dumps({
            "memory": {
                "pool_idle_timeout_s": 900,
                "pool_max_instances": 15,
            }
        }))

        with patch("dashboard.agentic_memory.pool_config.Path.home", return_value=tmp_path):
            # Need to clear env vars so they don't override
            with patch.dict(os.environ, {}, clear=False):
                for var in ["MEMORY_POOL_IDLE_TIMEOUT", "MEMORY_POOL_MAX_INSTANCES"]:
                    os.environ.pop(var, None)
                cfg = load_pool_config()
                assert cfg.idle_timeout_s == 900
                assert cfg.max_instances == 15
