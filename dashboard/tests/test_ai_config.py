"""Unit tests for dashboard/ai/config.py.

Covers:
  - AIConfig.full_model() — purpose routing, bare model names
  - AIConfig.display_model() — provider/model display format
  - AIConfig.full_cloud_embedding_model() — bare embedding model
  - get_config() — singleton caching and settings-fallback-to-env
  - reset_config() — cache invalidation
  - _load_from_env() — env var mapping and defaults
  - _map_provider() — legacy provider name normalisation
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from dashboard.ai.config import AIConfig, _map_provider


# ---------------------------------------------------------------------------
# TestAIConfig — pure dataclass / method logic
# ---------------------------------------------------------------------------


class TestAIConfig:
    def test_full_model_default_purpose(self):
        """No purpose → completion_model (bare, no prefix)."""
        cfg = AIConfig(provider="google-vertex", completion_model="gemini-3-flash-preview")
        assert cfg.full_model() == "gemini-3-flash-preview"

    def test_full_model_knowledge_purpose_uses_override(self):
        cfg = AIConfig(
            provider="google",
            completion_model="flash",
            knowledge_model="claude-3-5-sonnet",
        )
        assert cfg.full_model("knowledge") == "claude-3-5-sonnet"

    def test_full_model_memory_purpose_uses_override(self):
        cfg = AIConfig(
            provider="google-vertex",
            completion_model="flash",
            memory_model="gemini-3-flash-lite",
        )
        assert cfg.full_model("memory") == "gemini-3-flash-lite"

    def test_full_model_falls_back_to_completion_when_no_override(self):
        """Unknown purpose (or None override) falls back to completion_model."""
        cfg = AIConfig(
            provider="google",
            completion_model="flash",
            knowledge_model=None,
        )
        assert cfg.full_model("knowledge") == "flash"

    def test_display_model_includes_provider_prefix(self):
        """display_model() should return 'provider/model' for API responses."""
        cfg = AIConfig(provider="google-vertex", completion_model="gemini-3-flash-preview")
        assert cfg.display_model() == "google-vertex/gemini-3-flash-preview"

    def test_display_model_with_purpose(self):
        cfg = AIConfig(
            provider="google",
            completion_model="flash",
            knowledge_model="claude-3-5-sonnet",
        )
        assert cfg.display_model("knowledge") == "google/claude-3-5-sonnet"

    def test_full_cloud_embedding_model_returns_bare_name(self):
        cfg = AIConfig(provider="google-vertex", cloud_embedding_model="text-embedding-005")
        assert cfg.full_cloud_embedding_model() == "text-embedding-005"


# ---------------------------------------------------------------------------
# TestMapProvider — legacy name normalisation
# ---------------------------------------------------------------------------


class TestMapProvider:
    def test_vertex_ai_maps_to_google_vertex(self):
        assert _map_provider("vertex_ai") == "google-vertex"

    def test_gemini_maps_to_google(self):
        assert _map_provider("gemini") == "google"

    def test_google_stays_google(self):
        assert _map_provider("google") == "google"

    def test_openai_stays_openai(self):
        assert _map_provider("openai") == "openai"

    def test_unknown_provider_passed_through(self):
        assert _map_provider("ollama") == "ollama"

    def test_case_insensitive(self):
        assert _map_provider("Vertex_AI") == "google-vertex"
        assert _map_provider("GEMINI") == "google"


# ---------------------------------------------------------------------------
# TestGetConfig — singleton caching
# ---------------------------------------------------------------------------


class TestGetConfig:
    @pytest.fixture(autouse=True)
    def reset_cache(self):
        from dashboard.ai import config as cfg_mod
        cfg_mod._config = None
        yield
        cfg_mod._config = None

    def test_returns_same_instance_on_repeated_calls(self):
        from dashboard.ai.config import get_config, reset_config

        reset_config()
        c1 = get_config()
        c2 = get_config()
        assert c1 is c2

    def test_reset_config_forces_reload(self):
        from dashboard.ai.config import get_config, reset_config

        reset_config()
        c1 = get_config()
        reset_config()
        c2 = get_config()
        # After reset, a new object is created
        assert c1 is not c2

    def test_falls_back_to_env_when_settings_unavailable(self, monkeypatch):
        """When settings raise, env-based config is returned without crashing."""
        monkeypatch.setenv("LLM_MODEL", "gemini-test-model")
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

        from dashboard.ai import config as cfg_mod
        cfg_mod._config = None

        with patch(
            "dashboard.ai.config._load_from_settings",
            side_effect=RuntimeError("settings DB unavailable"),
        ):
            cfg = cfg_mod.get_config()

        assert cfg.completion_model == "gemini-test-model"
        assert cfg.provider == "google"


# ---------------------------------------------------------------------------
# TestLoadFromEnv — env var mapping
# ---------------------------------------------------------------------------


class TestLoadFromEnv:
    def test_defaults_when_no_env_vars(self, monkeypatch):
        for key in (
            "GOOGLE_CLOUD_PROJECT",
            "LLM_MODEL",
            "LLM_CLOUD_EMBEDDING_MODEL",
            "LLM_LOCAL_EMBEDDING_MODEL",
            "VERTEX_LOCATION",
            "LLM_TIMEOUT",
            "LLM_MAX_RETRIES",
        ):
            monkeypatch.delenv(key, raising=False)

        from dashboard.ai.config import _load_from_env

        cfg = _load_from_env()
        assert cfg.provider == "google"
        assert cfg.completion_model == "gemini-3-flash-preview"
        assert cfg.cloud_embedding_model == "text-embedding-005"
        assert cfg.local_embedding_model == "qwen3-embedding:0.6b"
        assert cfg.timeout == 60
        assert cfg.max_retries == 2

    def test_vertex_detected_from_project_env(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-gcp-project")

        from dashboard.ai.config import _load_from_env

        cfg = _load_from_env()
        assert cfg.provider == "google-vertex"

    def test_no_vertex_specific_fields(self, monkeypatch):
        """After migration, AIConfig should NOT have vertex_project etc."""
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-gcp-project")

        from dashboard.ai.config import _load_from_env

        cfg = _load_from_env()
        assert not hasattr(cfg, "vertex_project")
        assert not hasattr(cfg, "vertex_location")
        assert not hasattr(cfg, "vertex_auth_mode")
        assert not hasattr(cfg, "vertex_claude_location")

    def test_custom_model_from_env(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "gemini-3-pro")
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

        from dashboard.ai.config import _load_from_env

        cfg = _load_from_env()
        assert cfg.completion_model == "gemini-3-pro"

    def test_custom_timeout_and_retries_from_env(self, monkeypatch):
        monkeypatch.setenv("LLM_TIMEOUT", "120")
        monkeypatch.setenv("LLM_MAX_RETRIES", "5")

        from dashboard.ai.config import _load_from_env

        cfg = _load_from_env()
        assert cfg.timeout == 120
        assert cfg.max_retries == 5
