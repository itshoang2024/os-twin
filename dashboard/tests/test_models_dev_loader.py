"""
Tests for dashboard.lib.settings.models_dev_loader.

Covers:
- Provider discovery (auth.json, opencode.json, env vars)
- Google deployment mode detection (vertex vs gemini)
- Companion provider loading (google-vertex, google-vertex-anthropic)
- Custom model merging from opencode.json
- Source tagging (models.dev vs custom)
- configured_models.json structure
- Model registry output format
- Cache invalidation
"""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch

from dashboard.lib.settings.models_dev_loader import (
    _read_configured_providers,
    _read_google_deployment_mode,
    _build_configured_models,
    _COMPANION_PROVIDERS,
    get_available_providers,
    get_model_registry_from_configured,
    get_provider_logo_url,
    invalidate_cache,
    rebuild_configured_models_from_cache,
    _format_context_window,
    _classify_tier,
    get_context_limit,
    count_tokens,
    truncate_messages,
    truncate_messages_for_model,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def fake_auth_json(tmp_path):
    """Create a temporary auth.json with known providers."""
    auth = {
        "openai": {"type": "api", "key": "test-key-openai"},
        "anthropic": {"type": "api", "key": "test-key-anthropic"},
        "deepseek": {"type": "api", "key": "test-key-deepseek"},
    }
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(auth))
    return path


@pytest.fixture
def fake_opencode_json(tmp_path):
    """Create a temporary opencode.json with custom providers."""
    oc = {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "byteplus": {
                "options": {"apiKey": "test-bp-key", "baseURL": "https://ark.example.com/v3"},
                "models": {
                    "seed-2-0-pro": {"npm": "@ai-sdk/openai-compatible", "name": "byteplus:seed-2-0-pro"},
                },
            },
            "myprovider": {
                "options": {"apiKey": "my-key", "baseURL": "https://my.api/v1"},
                "models": {
                    "my-model-1": {"npm": "@ai-sdk/openai-compatible", "name": "myprovider:my-model-1"},
                },
            },
        },
    }
    path = tmp_path / "opencode.json"
    path.write_text(json.dumps(oc))
    return path


@pytest.fixture
def fake_raw_catalog():
    """A minimal models.dev catalog for testing."""
    return {
        "openai": {
            "name": "OpenAI",
            "doc": "https://docs.openai.com",
            "api": "https://api.openai.com/v1",
            "npm": "@ai-sdk/openai",
            "env": ["OPENAI_API_KEY"],
            "models": {
                "gpt-4.1": {
                    "name": "GPT-4.1",
                    "family": "gpt-4",
                    "reasoning": False,
                    "tool_call": True,
                    "cost": {"input": 2, "output": 8},
                    "limit": {"context": 1048576},
                },
                "o3": {
                    "name": "o3",
                    "family": "o-series",
                    "reasoning": True,
                    "tool_call": True,
                    "cost": {"input": 10, "output": 40},
                    "limit": {"context": 200000},
                },
            },
        },
        "anthropic": {
            "name": "Anthropic",
            "doc": "https://docs.anthropic.com",
            "api": "https://api.anthropic.com",
            "npm": "@ai-sdk/anthropic",
            "env": ["ANTHROPIC_API_KEY"],
            "models": {
                "claude-sonnet-4-6": {
                    "name": "Claude Sonnet 4.6",
                    "family": "claude",
                    "reasoning": False,
                    "cost": {"input": 3, "output": 15},
                    "limit": {"context": 200000},
                },
            },
        },
        "deepseek": {
            "name": "DeepSeek",
            "doc": "https://docs.deepseek.com",
            "api": "https://api.deepseek.com/v1",
            "npm": "@ai-sdk/openai-compatible",
            "env": ["DEEPSEEK_API_KEY"],
            "models": {
                "deepseek-r1": {
                    "name": "DeepSeek R1",
                    "family": "r-series",
                    "reasoning": True,
                    "cost": {"input": 0.55, "output": 2.19},
                    "limit": {"context": 65536},
                },
            },
        },
        "google": {
            "name": "Google",
            "models": {
                "gemini-2.5-pro": {"name": "Gemini 2.5 Pro", "cost": {"input": 1.25}, "limit": {"context": 1048576}},
            },
        },
        "google-vertex": {
            "name": "Vertex",
            "models": {
                "gemini-2.5-pro": {"name": "Gemini 2.5 Pro (Vertex)", "cost": {"input": 1.25}, "limit": {"context": 1048576}},
            },
        },
        "google-vertex-anthropic": {
            "name": "Vertex (Anthropic)",
            "models": {
                "claude-sonnet-4-6@default": {"name": "Claude Sonnet 4.6", "cost": {"input": 3}, "limit": {"context": 200000}},
            },
        },
    }


# ── Provider discovery ────────────────────────────────────────────────

def test_reads_auth_json_providers(fake_auth_json):
    with patch("dashboard.lib.settings.models_dev_loader.AUTH_JSON_PATH", fake_auth_json):
        with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
            providers = _read_configured_providers()

    assert "openai" in providers
    assert "anthropic" in providers
    assert "deepseek" in providers
    assert providers["openai"]["source"] == "auth.json"
    assert providers["openai"]["has_key"] is True


def test_reads_auth_json_oauth_provider_over_vault(tmp_path):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps({
        "openai": {
            "type": "oauth",
            "access": "access-token",
            "refresh": "refresh-token",
            "expires": 9999999999,
            "accountId": "acct-test",
        }
    }))

    class FakeVault:
        def list_keys(self, scope):
            return {"openai": {"is_set": True}}

    env = {
        "OSTWIN_CONFIG_PATH": str(tmp_path / "missing-config.json"),
        "OSTWIN_VAULT_BACKEND": "env",
    }
    with patch("dashboard.lib.settings.models_dev_loader.AUTH_JSON_PATH", auth_path):
        with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
            with patch("dashboard.lib.settings.vault.get_vault", return_value=FakeVault()):
                with patch.dict(os.environ, env, clear=True):
                    providers = _read_configured_providers()

    assert providers["openai"]["type"] == "oauth"
    assert providers["openai"]["source"] == "auth.json"
    assert providers["openai"]["has_key"] is True


def test_reads_opencode_json_custom_providers(fake_opencode_json):
    with patch("dashboard.lib.settings.models_dev_loader.AUTH_JSON_PATH", Path("/nonexistent")):
        with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", fake_opencode_json):
            providers = _read_configured_providers()

    assert "byteplus" in providers
    assert "myprovider" in providers
    assert providers["byteplus"]["source"] == str(fake_opencode_json)
    assert providers["byteplus"]["type"] == "custom"


def test_auth_json_takes_precedence_over_opencode(fake_auth_json, fake_opencode_json):
    """If a provider appears in both, auth.json wins."""
    auth = {"byteplus": {"type": "api", "key": "auth-bp"}}
    fake_auth_json.write_text(json.dumps(auth))

    with patch("dashboard.lib.settings.models_dev_loader.AUTH_JSON_PATH", fake_auth_json):
        with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", fake_opencode_json):
            providers = _read_configured_providers()

    assert providers["byteplus"]["source"] == "auth.json"


def test_google_detected_from_env_vars(tmp_path):
    """Google is detected from GOOGLE_CLOUD_PROJECT even without auth.json."""
    with patch("dashboard.lib.settings.models_dev_loader.AUTH_JSON_PATH", Path("/nonexistent")):
        with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
            with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "my-project"}, clear=False):
                providers = _read_configured_providers()

    assert "google" in providers
    assert providers["google"]["type"] == "env"
    assert providers["google"]["source"] == "env"
    assert providers["google"]["has_key"] is True


def test_google_detected_from_api_key(tmp_path):
    with patch("dashboard.lib.settings.models_dev_loader.AUTH_JSON_PATH", Path("/nonexistent")):
        with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
            env = {"GOOGLE_API_KEY": "test-key"}
            with patch.dict(os.environ, env, clear=False):
                # Remove GOOGLE_CLOUD_PROJECT if set
                os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
                providers = _read_configured_providers()

    assert "google" in providers


def test_google_not_detected_without_env():
    class EmptyVault:
        def list_keys(self, scope):
            return {}

    with patch("dashboard.lib.settings.models_dev_loader.AUTH_JSON_PATH", Path("/nonexistent")):
        with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
            with patch("dashboard.lib.settings.vault.get_vault", return_value=EmptyVault()):
                with patch.dict(
                    os.environ,
                    {"OSTWIN_CONFIG_PATH": "/nonexistent/config.json"},
                    clear=True,
                ):
                    providers = _read_configured_providers()

    assert "google" not in providers


def test_provider_config_detects_google_vertex_without_env(tmp_path):
    """Provider settings should populate runtime models even before OpenCode sync."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "providers": {
            "google": {
                "enabled": True,
                "deployment_mode": "vertex",
                "project_id": "test-project",
                "vertex_auth_mode": "oauth",
            }
        }
    }))

    env = {"OSTWIN_CONFIG_PATH": str(config_path), "OSTWIN_VAULT_BACKEND": "env"}
    with patch("dashboard.lib.settings.models_dev_loader.AUTH_JSON_PATH", Path("/nonexistent")):
        with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
            with patch.dict(os.environ, env, clear=True):
                providers = _read_configured_providers()

    assert providers["google"]["source"] == "settings"
    assert providers["google"]["deployment_mode"] == "vertex"


def test_disabled_provider_config_suppresses_vault_key(tmp_path):
    """A dismissed dynamic provider should stay hidden even if a vault key exists."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "providers": {
            "deepseek": {"enabled": False}
        }
    }))

    class FakeVault:
        def list_keys(self, scope):
            return {"deepseek": {"is_set": True}}

    env = {"OSTWIN_CONFIG_PATH": str(config_path), "OSTWIN_VAULT_BACKEND": "env"}
    with patch("dashboard.lib.settings.models_dev_loader.AUTH_JSON_PATH", Path("/nonexistent")):
        with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
            with patch("dashboard.lib.settings.vault.get_vault", return_value=FakeVault()):
                with patch.dict(os.environ, env, clear=True):
                    providers = _read_configured_providers()

    assert "deepseek" not in providers


def test_enabled_provider_config_ignores_stale_dismissed_flag(tmp_path):
    """Primary provider cards can leave dismissed=true; enabled should win."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "providers": {
            "google": {
                "enabled": True,
                "dismissed": True,
                "deployment_mode": "vertex",
                "project_id": "test-project",
                "vertex_auth_mode": "oauth",
            }
        }
    }))

    env = {"OSTWIN_CONFIG_PATH": str(config_path), "OSTWIN_VAULT_BACKEND": "env"}
    with patch("dashboard.lib.settings.models_dev_loader.AUTH_JSON_PATH", Path("/nonexistent")):
        with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
            with patch.dict(os.environ, env, clear=True):
                providers = _read_configured_providers()

    assert "google" in providers
    assert providers["google"]["deployment_mode"] == "vertex"


# ── Deployment mode ───────────────────────────────────────────────────

def test_deployment_mode_read_from_config(tmp_path):
    config = {"providers": {"google": {"deployment_mode": "gemini"}}}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))

    with patch.dict(os.environ, {"OSTWIN_CONFIG_PATH": str(config_path)}, clear=False):
        mode = _read_google_deployment_mode()
    assert mode == "gemini"


def test_deployment_mode_defaults_to_vertex_with_gcp_project():
    with patch("dashboard.api_utils.AGENTS_DIR", Path("/nonexistent")):
        with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "proj"}, clear=False):
            mode = _read_google_deployment_mode()
    assert mode == "vertex"


# ── Build configured models ──────────────────────────────────────────

def test_build_filters_to_configured_providers(fake_raw_catalog):
    providers = {
        "openai": {"type": "api", "source": "auth.json", "has_key": True},
    }
    result = _build_configured_models(fake_raw_catalog, providers)
    assert "openai" in result["providers"]
    assert "anthropic" not in result["providers"]
    assert "deepseek" not in result["providers"]


def test_build_tags_models_dev_source(fake_raw_catalog):
    providers = {"openai": {"type": "api", "source": "auth.json", "has_key": True}}
    with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
        result = _build_configured_models(fake_raw_catalog, providers)
    for mid, mdata in result["providers"]["openai"]["models"].items():
        assert mdata["source"] == "models.dev"


def test_openai_oauth_filters_to_opencode_models(fake_raw_catalog):
    fake_raw_catalog["openai"]["models"]["gpt-5.3-codex"] = {
        "name": "GPT-5.3 Codex",
        "family": "gpt-5",
        "reasoning": True,
        "tool_call": True,
        "cost": {"input": 1},
        "limit": {"context": 272000},
    }
    providers = {"openai": {"type": "oauth", "source": "auth.json", "has_key": True}}

    with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
        with patch(
            "dashboard.lib.settings.models_dev_loader._list_opencode_models",
            return_value={"openai/gpt-5.3-codex", "gpt-5.3-codex"},
        ):
            result = _build_configured_models(fake_raw_catalog, providers)

    models = result["providers"]["openai"]["models"]
    assert set(models) == {"gpt-5.3-codex"}


def test_github_copilot_oauth_adds_opencode_only_models():
    raw_catalog = {
        "github-copilot": {
            "id": "github-copilot",
            "name": "GitHub Copilot",
            "models": {
                "gpt-5.4": {"id": "gpt-5.4", "name": "GPT-5.4"},
                "claude-opus-4.6": {"id": "claude-opus-4.6", "name": "Claude Opus 4.6"},
            },
        }
    }
    providers = {"github-copilot": {"type": "oauth", "source": "auth.json", "has_key": True}}

    with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
        with patch(
            "dashboard.lib.settings.models_dev_loader._live_github_copilot_models",
            return_value=set(),
        ):
            with patch(
                "dashboard.lib.settings.models_dev_loader._list_opencode_models",
                return_value={
                    "github-copilot/gpt-5.4",
                    "gpt-5.4",
                    "github-copilot/claude-opus-4.6-fast",
                    "claude-opus-4.6-fast",
                },
            ):
                result = _build_configured_models(raw_catalog, providers)

    models = result["providers"]["github-copilot"]["models"]
    assert sorted(models) == ["claude-opus-4.6-fast", "gpt-5.4"]
    assert models["claude-opus-4.6-fast"]["source"] == "opencode"


def test_build_includes_custom_models_from_opencode(fake_raw_catalog, fake_opencode_json):
    providers = {
        "byteplus": {"type": "custom", "source": "opencode.json", "has_key": True},
    }
    with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", fake_opencode_json):
        result = _build_configured_models(fake_raw_catalog, providers)

    assert "byteplus" in result["providers"]
    models = result["providers"]["byteplus"]["models"]
    assert "seed-2-0-pro" in models
    assert models["seed-2-0-pro"]["source"] == "custom"


def test_build_skips_provider_not_in_any_source(fake_raw_catalog):
    providers = {"nonexistent": {"type": "api", "source": "auth.json", "has_key": True}}
    with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
        result = _build_configured_models(fake_raw_catalog, providers)
    assert "nonexistent" not in result["providers"]


# ── Companion providers (Vertex) ─────────────────────────────────────

def test_vertex_mode_loads_companions(fake_raw_catalog):
    providers = {
        "google": {"type": "env", "source": "env", "has_key": True, "deployment_mode": "vertex"},
    }
    with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
        result = _build_configured_models(fake_raw_catalog, providers)

    models = result["providers"]["google"]["models"]
    # Base google model
    assert "gemini-2.5-pro" in models
    # Vertex companions are exposed as separate top-level providers so the UI
    # groups them independently.
    assert "google-vertex" in result["providers"]
    assert "gemini-2.5-pro" in result["providers"]["google-vertex"]["models"]
    assert (
        result["providers"]["google-vertex"]["models"]["gemini-2.5-pro"]["companion_provider"]
        == "google-vertex"
    )
    assert "google-vertex-anthropic" in result["providers"]
    assert (
        "claude-sonnet-4-6@default"
        in result["providers"]["google-vertex-anthropic"]["models"]
    )
    assert (
        result["providers"]["google-vertex-anthropic"]["models"]["claude-sonnet-4-6@default"]["companion_provider"]
        == "google-vertex-anthropic"
    )


def test_gemini_mode_skips_companions(fake_raw_catalog):
    providers = {
        "google": {"type": "env", "source": "env", "has_key": True, "deployment_mode": "gemini"},
    }
    with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
        result = _build_configured_models(fake_raw_catalog, providers)

    models = result["providers"]["google"]["models"]
    assert "gemini-2.5-pro" in models
    assert not any("google-vertex" in mid for mid in models)


def test_companion_providers_mapping_structure():
    assert "google" in _COMPANION_PROVIDERS
    assert "vertex" in _COMPANION_PROVIDERS["google"]
    assert "gemini" in _COMPANION_PROVIDERS["google"]
    assert "google-vertex" in _COMPANION_PROVIDERS["google"]["vertex"]
    assert "google-vertex-anthropic" in _COMPANION_PROVIDERS["google"]["vertex"]
    assert _COMPANION_PROVIDERS["google"]["gemini"] == []


# ── Source tagging ────────────────────────────────────────────────────

def test_source_propagates_to_registry(fake_raw_catalog):
    providers = {"openai": {"type": "api", "source": "auth.json", "has_key": True}}
    with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
        result = _build_configured_models(fake_raw_catalog, providers)

    # Patch cache for get_model_registry_from_configured
    with patch("dashboard.lib.settings.models_dev_loader._cached_models", result):
        registry = get_model_registry_from_configured()

    openai_models = registry.get("OpenAI", [])
    assert len(openai_models) >= 1
    for m in openai_models:
        assert m["source"] == "models.dev"
        assert m["provider_id"] == "openai"


# ── Utility functions ─────────────────────────────────────────────────

def test_format_context_window():
    assert _format_context_window(200000) == "200K"
    assert _format_context_window(1048576) == "1048.58K" or "1" in _format_context_window(1048576)
    assert _format_context_window(1000000) == "1M"
    assert _format_context_window(2000000) == "2M"
    assert _format_context_window(500) == "500"


def test_classify_tier():
    assert _classify_tier({"reasoning": True, "cost": {"input": 1}}) == "reasoning"
    assert _classify_tier({"reasoning": False, "cost": {"input": 15}}) == "flagship"
    assert _classify_tier({"reasoning": False, "cost": {"input": 3}}) == "balanced"
    assert _classify_tier({"reasoning": False, "cost": {"input": 0.5}}) == "fast"
    assert _classify_tier({"reasoning": False, "cost": {}}) == "unknown"


def test_provider_logo_url():
    assert get_provider_logo_url("anthropic") == "https://models.dev/logos/anthropic.svg"
    assert get_provider_logo_url("openai") == "https://models.dev/logos/openai.svg"


def test_available_providers_uses_raw_catalog(fake_raw_catalog):
    with patch("dashboard.lib.settings.models_dev_loader._read_cached_raw", return_value=fake_raw_catalog):
        with patch("dashboard.lib.settings.models_dev_loader._read_configured_providers", return_value={"openai": {}}):
            providers = get_available_providers()

    openai = next(p for p in providers if p["id"] == "openai")
    anthropic = next(p for p in providers if p["id"] == "anthropic")
    assert openai["already_configured"] is True
    assert anthropic["already_configured"] is False
    assert openai["model_count"] == 2


# ── Cache ─────────────────────────────────────────────────────────────

def test_invalidate_cache_clears_memory():
    import dashboard.lib.settings.models_dev_loader as loader
    loader._cached_models = {"test": True}
    loader._cached_timestamp = 999.0
    invalidate_cache()
    assert loader._cached_models is None
    assert loader._cached_timestamp == 0.0


def test_rebuild_configured_models_from_cache_picks_up_oauth_openai(tmp_path, fake_raw_catalog):
    auth_path = tmp_path / "auth.json"
    raw_path = tmp_path / "models_dev_raw.json"
    configured_path = tmp_path / "configured_models.json"
    raw_path.write_text(json.dumps(fake_raw_catalog))
    auth_path.write_text(json.dumps({"openai": {"type": "oauth", "access": "token"}}))

    class EmptyVault:
        def list_keys(self, scope):
            return {}

    with patch("dashboard.lib.settings.models_dev_loader.AUTH_JSON_PATH", auth_path):
        with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
            with patch("dashboard.lib.settings.models_dev_loader._HOME_RAW_PATH", raw_path):
                with patch("dashboard.lib.settings.models_dev_loader.CONFIGURED_MODELS_PATH", configured_path):
                    with patch("dashboard.lib.settings.vault.get_vault", return_value=EmptyVault()):
                        with patch(
                            "dashboard.lib.settings.models_dev_loader._list_opencode_models",
                            return_value={"openai/gpt-4.1", "gpt-4.1"},
                        ):
                            with patch.dict(
                                os.environ,
                                {"OSTWIN_CONFIG_PATH": "/nonexistent/config.json", "OSTWIN_VAULT_BACKEND": "env"},
                                clear=True,
                            ):
                                result = rebuild_configured_models_from_cache()

    assert "openai" in result["configured_provider_ids"]
    assert "openai" in result["providers"]


def test_rebuild_configured_models_from_cache_picks_up_github_copilot(tmp_path):
    from dashboard.lib.settings.models_dev_loader import rebuild_configured_models_from_cache

    auth_path = tmp_path / "auth.json"
    raw_path = tmp_path / "models_dev_raw.json"
    configured_path = tmp_path / "configured_models.json"

    auth_path.write_text(json.dumps({"github-copilot": {"type": "oauth", "access": "token"}}))
    raw_path.write_text(
        json.dumps(
            {
                "github-copilot": {
                    "id": "github-copilot",
                    "name": "GitHub Copilot",
                    "models": {
                        "gpt-5.2": {
                            "id": "gpt-5.2",
                            "name": "GPT-5.2",
                            "limit": {"context": 400000},
                        }
                    },
                }
            }
        )
    )

    with patch("dashboard.lib.settings.models_dev_loader.AUTH_JSON_PATH", auth_path):
        with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
            with patch("dashboard.lib.settings.models_dev_loader.USER_OPENCODE_CONFIG_PATH", Path("/nonexistent")):
                with patch("dashboard.lib.settings.models_dev_loader._HOME_RAW_PATH", raw_path):
                    with patch("dashboard.lib.settings.models_dev_loader.CONFIGURED_MODELS_PATH", configured_path):
                        with patch(
                            "dashboard.lib.settings.models_dev_loader._live_github_copilot_models",
                            return_value=set(),
                        ):
                            with patch(
                                "dashboard.lib.settings.models_dev_loader._list_opencode_models",
                                return_value={"github-copilot/gpt-5.2", "gpt-5.2"},
                            ):
                                result = rebuild_configured_models_from_cache()

    assert "github-copilot" in result["configured_provider_ids"]
    assert result["providers"]["github-copilot"]["models"]["gpt-5.2"]["name"] == "GPT-5.2"
    assert configured_path.exists()


def test_github_copilot_native_reflects_live_copilot_models(monkeypatch):
    from dashboard.lib.settings import models_dev_loader as loader

    raw_catalog = {
        "github-copilot": {
            "id": "github-copilot",
            "name": "GitHub Copilot",
            "models": {
                "gpt-5.2": {"id": "gpt-5.2", "name": "GPT-5.2"},
                "claude-sonnet-4.5": {"id": "claude-sonnet-4.5", "name": "Claude Sonnet 4.5"},
                "gpt-3.5-turbo": {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo"},
            },
        }
    }
    configured = {
        "github-copilot": {"type": "oauth", "source": "auth.json", "has_key": True},
    }
    # Live Copilot entitlement: only these two models, plus one not in the
    # catalog that must still be surfaced as an opencode-sourced entry.
    monkeypatch.setattr(
        loader,
        "_live_github_copilot_models",
        lambda: {"gpt-5.2", "claude-sonnet-4.5", "o4-mini"},
    )
    # OpenCode discovery must NOT be consulted when the live list is available.
    monkeypatch.setattr(
        loader,
        "_list_opencode_models",
        lambda provider_id: {"github-copilot/gpt-3.5-turbo", "gpt-3.5-turbo"},
    )

    result = loader._build_configured_models(raw_catalog, configured)

    assert "github-copilot" in result["configured_provider_ids"]
    assert "github-copilot-oauth" not in result["configured_provider_ids"]
    # Native github-copilot reflects the live entitlement, not the full catalog.
    assert sorted(result["providers"]["github-copilot"]["models"].keys()) == [
        "claude-sonnet-4.5",
        "gpt-5.2",
        "o4-mini",
    ]
    assert result["providers"]["github-copilot"]["models"]["o4-mini"]["source"] == "opencode"


# ── configured_models structure ───────────────────────────────────────

def test_configured_models_has_required_keys(fake_raw_catalog):
    providers = {"openai": {"type": "api", "source": "auth.json", "has_key": True}}
    with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
        result = _build_configured_models(fake_raw_catalog, providers)

    assert "loaded_at" in result
    assert "source" in result
    assert "configured_provider_ids" in result
    assert "providers" in result
    assert "openai" in result["configured_provider_ids"]

    p = result["providers"]["openai"]
    assert p["id"] == "openai"
    assert p["name"] == "OpenAI"
    assert p["logo_url"].endswith("openai.svg")
    assert "models" in p

    m = p["models"]["gpt-4.1"]
    assert m["id"] == "gpt-4.1"
    assert m["name"] == "GPT-4.1"
    assert m["cost"]["input"] == 2
    assert m["limit"]["context"] == 1048576
    assert m["source"] == "models.dev"


# ── count_tokens ──────────────────────────────────────────────────────


class TestCountTokens:
    def test_empty_messages(self):
        assert count_tokens([]) == 2

    def test_single_message(self):
        msgs = [{"role": "user", "content": "Hello world"}]
        n = count_tokens(msgs)
        assert n > 0

    def test_fallback_no_tiktoken(self):
        with patch.dict("sys.modules", {"tiktoken": None}):
            msgs = [{"role": "user", "content": "a" * 100}]
            n = count_tokens(msgs)
        assert n == (len("user") + 100) // 4


# ── get_context_limit ─────────────────────────────────────────────────


class TestGetContextLimit:
    def setup_method(self):
        get_context_limit.cache_clear()

    def teardown_method(self):
        get_context_limit.cache_clear()

    def test_returns_catalog_limits(self, fake_raw_catalog):
        providers = {"openai": {"type": "api", "source": "auth.json", "has_key": True}}
        with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
            result = _build_configured_models(fake_raw_catalog, providers)

        with patch("dashboard.lib.settings.models_dev_loader._cached_models", result):
            get_context_limit.cache_clear()
            ctx, out = get_context_limit("openai", "gpt-4.1")
        assert ctx == 1048576

    def test_returns_zero_for_unknown(self):
        get_context_limit.cache_clear()
        ctx, out = get_context_limit("nonexistent", "no-model")
        assert ctx == 0
        assert out == 0

    def test_slash_split_model_id(self, fake_raw_catalog):
        providers = {"openai": {"type": "api", "source": "auth.json", "has_key": True}}
        with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
            result = _build_configured_models(fake_raw_catalog, providers)

        with patch("dashboard.lib.settings.models_dev_loader._cached_models", result):
            get_context_limit.cache_clear()
            ctx, out = get_context_limit("unknown", "openai/gpt-4.1")
        assert ctx == 1048576

    def test_ollama_provider_calls_show(self):
        with patch("dashboard.lib.settings.models_dev_loader.show_ollama_model", return_value={"context_length": 32768}):
            get_context_limit.cache_clear()
            ctx, out = get_context_limit("ollama", "gemma3:1b")
        assert ctx == 32768
        assert out == 2048

    def test_ollama_fallback_default(self):
        with patch("dashboard.lib.settings.models_dev_loader.show_ollama_model", return_value={}):
            get_context_limit.cache_clear()
            ctx, out = get_context_limit("ollama", "unknown-model")
        assert ctx == 32768


# ── truncate_messages ─────────────────────────────────────────────────


class TestTruncateMessages:
    def test_no_truncation_when_under_limit(self):
        msgs = [{"role": "user", "content": "short"}]
        result = truncate_messages(msgs, context_limit=10000)
        assert result == msgs

    def test_truncates_content_not_messages(self):
        long_content = "x" * 5000
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": long_content},
        ]
        result = truncate_messages(msgs, context_limit=200, model="gpt-4o")
        assert len(result) == 2
        assert result[0]["content"] == "You are helpful."
        assert len(result[1]["content"]) < len(long_content)

    def test_preserves_system_message(self):
        long_content = "x" * 5000
        msgs = [
            {"role": "system", "content": long_content},
            {"role": "user", "content": "hi"},
        ]
        result = truncate_messages(msgs, context_limit=200, model="gpt-4o")
        assert len(result) == 2
        assert result[1]["content"] == "hi"

    def test_zero_context_limit_returns_unchanged(self):
        msgs = [{"role": "user", "content": "hello"}]
        result = truncate_messages(msgs, context_limit=0)
        assert result == msgs

    def test_trims_last_non_system_first(self):
        msgs = [
            {"role": "user", "content": "first"},
            {"role": "user", "content": "x" * 5000},
        ]
        result = truncate_messages(msgs, context_limit=200, model="gpt-4o")
        assert result[0]["content"] == "first"
        assert len(result[1]["content"]) < 5000

    def test_does_not_remove_messages(self):
        msgs = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "a" * 3000},
            {"role": "assistant", "content": "b" * 3000},
        ]
        result = truncate_messages(msgs, context_limit=200, model="gpt-4o")
        assert len(result) == 3


# ── truncate_messages_for_model ────────────────────────────────────────


class TestTruncateMessagesForModel:
    def setup_method(self):
        get_context_limit.cache_clear()

    def teardown_method(self):
        get_context_limit.cache_clear()

    def test_returns_unchanged_when_no_context_limit(self):
        with patch("dashboard.lib.settings.models_dev_loader.get_context_limit", return_value=(0, 0)):
            msgs = [{"role": "user", "content": "hello"}]
            result = truncate_messages_for_model(msgs, "unknown", "no-model")
        assert result == msgs

    def test_strips_provider_prefix_from_model(self, fake_raw_catalog):
        providers = {"openai": {"type": "api", "source": "auth.json", "has_key": True}}
        with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
            catalog = _build_configured_models(fake_raw_catalog, providers)

        with patch("dashboard.lib.settings.models_dev_loader._cached_models", catalog):
            get_context_limit.cache_clear()
            long_msg = [{"role": "user", "content": "x" * 50000}]
            result = truncate_messages_for_model(long_msg, "openai", "openai/gpt-4.1")
        assert len(result) == 1
        assert len(result[0]["content"]) < 50000

    def test_ollama_fallback(self):
        with patch("dashboard.lib.settings.models_dev_loader.get_context_limit", return_value=(0, 0)):
            with patch("dashboard.lib.settings.models_dev_loader.show_ollama_model", return_value={"context_length": 256}):
                msgs = [{"role": "user", "content": "x" * 5000}]
                result = truncate_messages_for_model(msgs, "ollama", "gemma3:1b")
        assert len(result) == 1
        assert len(result[0]["content"]) < 5000

    def test_truncation_respects_buffer(self, fake_raw_catalog):
        providers = {"openai": {"type": "api", "source": "auth.json", "has_key": True}}
        with patch("dashboard.lib.settings.models_dev_loader.OPENCODE_CONFIG_PATH", Path("/nonexistent")):
            catalog = _build_configured_models(fake_raw_catalog, providers)

        with patch("dashboard.lib.settings.models_dev_loader._cached_models", catalog):
            get_context_limit.cache_clear()
            ctx, _ = get_context_limit("openai", "o3")
            target = int(ctx * 0.9)
            msgs = [{"role": "user", "content": "x" * (ctx * 10)}]
            result = truncate_messages_for_model(msgs, "openai", "o3")
            final_tokens = count_tokens(
                [{"role": m["role"], "content": m["content"]} for m in result], "o3"
            )
            assert final_tokens <= target + 10
