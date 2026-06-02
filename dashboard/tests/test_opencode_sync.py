"""
Tests for dashboard.lib.settings.opencode_sync.

Covers:
- Sync writes correct provider block for gemini + byteplus
- Sync skips vertex mode (only gemini mode is synced)
- Sync removes provider block when key is deleted or provider disabled
- Sync preserves existing non-provider keys in opencode.json
- Atomic write safety
- SyncResult structure
"""

import json
from unittest.mock import MagicMock

import pytest

from dashboard.lib.settings import models_registry
from dashboard.lib.settings.models_registry import ModelEntry
from dashboard.lib.settings.opencode_sync import (
    sync_opencode_config,
    SyncResult,
    TargetResult,
    OPENCODE_SCHEMA,
)
from dashboard.models import (
    MasterSettings,
    ProvidersNamespace,
    ProviderSettings,
)


# Mixed gemini/vertex catalog used by sync tests that depend on gemini-mode
# models being available. The production _FALLBACK_CATALOG only carries
# vertex-mode entries; gemini-mode comes from the dynamic models.dev catalog
# at runtime. Injecting here keeps tests deterministic.
@pytest.fixture
def gemini_catalog(monkeypatch):
    entries = [
        ModelEntry(
            "gemini/gemini-3-flash-preview",
            "Gemini 3 Flash",
            "1M",
            "balanced",
            mode="gemini",
        ),
        ModelEntry(
            "gemini/gemini-3-pro-preview",
            "Gemini 3 Pro",
            "1M",
            "flagship",
            mode="gemini",
        ),
        ModelEntry(
            "gemini/gemini-3-flash-lite-preview",
            "Gemini 3 Flash Lite",
            "1M",
            "fast",
            mode="gemini",
        ),
        ModelEntry(
            "google-vertex/gemini-3.1-pro-preview",
            "Vertex Gemini 3.1 Pro",
            "1M",
            "flagship",
            mode="vertex",
        ),
        ModelEntry(
            "google-vertex-anthropic/claude-sonnet-4-6@default",
            "Vertex Claude Sonnet 4.6",
            "200K",
            "balanced",
            mode="vertex",
        ),
    ]
    monkeypatch.setitem(models_registry._FALLBACK_CATALOG, "Gemini", entries)
    return entries


# ── Helpers ───────────────────────────────────────────────────────────

def _make_settings(
    *,
    google_enabled=True,
    google_mode="gemini",
    google_explicit=True,
    google_project_id=None,
    google_vertex_location=None,
    byteplus_enabled=True,
    byteplus_explicit=True,
) -> MasterSettings:
    """Build a MasterSettings with specific provider state.

    When ``*_explicit=True`` (default), a ``ProviderSettings`` object is
    created even when disabled -- this simulates explicit config.
    When ``*_explicit=False``, the field is ``None`` (no config entry).
    """
    if google_explicit:
        google = ProviderSettings(
            enabled=google_enabled,
            deployment_mode=google_mode,
            project_id=google_project_id,
            vertex_location=google_vertex_location,
        )
    else:
        google = None

    if byteplus_explicit:
        bp = ProviderSettings(enabled=byteplus_enabled)
    else:
        bp = None

    providers = ProvidersNamespace(google=google, byteplus=bp)
    return MasterSettings(providers=providers)


def _make_vault(keys=None):
    """Build a mock SettingsVault with preset keys."""
    vault = MagicMock()
    key_store = keys or {}

    def _get(scope, key):
        return key_store.get(f"{scope}/{key}")

    vault.get.side_effect = _get
    return vault


def _sync(vault, settings, tmp_path, **kwargs):
    """Shortcut that always isolates both target files in tmp_path."""
    return sync_opencode_config(
        vault=vault,
        settings=settings,
        config_path=kwargs.pop("config_path", tmp_path / "opencode.json"),
        auth_path=kwargs.pop("auth_path", tmp_path / "auth.json"),
        **kwargs,
    )


# ── Sync writes provider blocks ──────────────────────────────────────

def test_sync_writes_gemini_and_byteplus(tmp_path, gemini_catalog):
    config_path = tmp_path / "opencode.json"
    vault = _make_vault({
        "providers/google": "AIzaSy-test-key",
        "providers/byteplus": "bp-test-key",
    })
    settings = _make_settings(google_mode="gemini", byteplus_enabled=True)

    result = _sync(vault, settings, tmp_path, config_path=config_path)

    assert result.error is None
    assert "gemini" in result.synced
    assert "byteplus" in result.synced

    data = json.loads(config_path.read_text())
    assert data["$schema"] == OPENCODE_SCHEMA

    # Gemini block
    g = data["provider"]["gemini"]
    assert g["options"]["apiKey"] == "AIzaSy-test-key"
    assert "generativelanguage.googleapis.com" in g["options"]["baseURL"]
    assert len(g["models"]) > 0
    for model_val in g["models"].values():
        assert model_val["name"].startswith("gemini:")

    # BytePlus block
    bp = data["provider"]["byteplus"]
    assert bp["options"]["apiKey"] == "bp-test-key"
    assert "bytepluses.com" in bp["options"]["baseURL"]
    assert len(bp["models"]) > 0


def test_sync_only_gemini_when_byteplus_disabled(tmp_path):
    config_path = tmp_path / "opencode.json"
    vault = _make_vault({"providers/google": "key"})
    settings = _make_settings(google_mode="gemini", byteplus_enabled=False)

    result = _sync(vault, settings, tmp_path, config_path=config_path)

    assert "gemini" in result.synced

    data = json.loads(config_path.read_text())
    assert "gemini" in data["provider"]
    assert "byteplus" not in data["provider"]


# ── Vertex mode is NOT synced ────────────────────────────────────────

def test_sync_skips_gemini_when_vertex_mode(tmp_path):
    config_path = tmp_path / "opencode.json"
    vault = _make_vault({"providers/google": "key"})
    settings = _make_settings(google_mode="vertex")

    result = _sync(vault, settings, tmp_path, config_path=config_path)

    assert "gemini" not in result.synced
    assert "gemini" in result.skipped


def test_sync_skips_gemini_when_google_explicitly_disabled(tmp_path):
    config_path = tmp_path / "opencode.json"
    vault = _make_vault({"providers/google": "key"})
    settings = _make_settings(google_enabled=False, google_explicit=True)

    result = _sync(vault, settings, tmp_path, config_path=config_path)

    assert "gemini" not in result.synced


# ── Sync removes stale blocks ───────────────────────────────────────

def test_sync_removes_provider_when_key_deleted(tmp_path):
    config_path = tmp_path / "opencode.json"
    # Pre-populate with a gemini block
    config_path.write_text(json.dumps({
        "$schema": OPENCODE_SCHEMA,
        "provider": {
            "gemini": {
                "options": {"apiKey": "old-key", "baseURL": "https://example.com"},
                "models": {},
            }
        }
    }))

    vault = _make_vault({})  # no keys in vault
    settings = _make_settings(google_mode="gemini")

    result = _sync(vault, settings, tmp_path, config_path=config_path)

    assert "gemini" in result.removed
    data = json.loads(config_path.read_text())
    assert "gemini" not in data.get("provider", {})


def test_sync_removes_provider_when_explicitly_disabled(tmp_path):
    """When provider settings explicitly say enabled=False, remove even if vault has a key."""
    config_path = tmp_path / "opencode.json"
    config_path.write_text(json.dumps({
        "$schema": OPENCODE_SCHEMA,
        "provider": {
            "byteplus": {
                "options": {"apiKey": "old", "baseURL": "https://x"},
                "models": {},
            }
        }
    }))

    vault = _make_vault({"providers/byteplus": "key"})
    # Explicit settings with enabled=False
    settings = _make_settings(byteplus_enabled=False)

    result = _sync(vault, settings, tmp_path, config_path=config_path)

    # Provider has explicit settings with enabled=False, so it should be removed
    assert "byteplus" in result.removed


# ── Preserves existing keys ──────────────────────────────────────────

def test_sync_preserves_mcp_and_other_keys(tmp_path):
    config_path = tmp_path / "opencode.json"
    config_path.write_text(json.dumps({
        "$schema": OPENCODE_SCHEMA,
        "mcp": {"some-server": {"command": ["node", "server.js"]}},
        "model": "anthropic/claude-sonnet-4-6",
    }))

    vault = _make_vault({"providers/google": "key"})
    settings = _make_settings(google_mode="gemini", byteplus_enabled=False)

    _sync(vault, settings, tmp_path, config_path=config_path)

    data = json.loads(config_path.read_text())
    # MCP block preserved
    assert data["mcp"]["some-server"]["command"] == ["node", "server.js"]
    # model key preserved
    assert data["model"] == "anthropic/claude-sonnet-4-6"
    # Provider block added
    assert "gemini" in data["provider"]


# ── base_url override from settings ──────────────────────────────────

def test_sync_uses_custom_base_url(tmp_path):
    config_path = tmp_path / "opencode.json"
    vault = _make_vault({"providers/byteplus": "key"})
    settings = _make_settings(google_enabled=False, byteplus_enabled=True)
    # Set custom base_url
    settings.providers.byteplus.base_url = "https://custom.api.example.com/v1"

    _sync(vault, settings, tmp_path, config_path=config_path)

    data = json.loads(config_path.read_text())
    assert data["provider"]["byteplus"]["options"]["baseURL"] == "https://custom.api.example.com/v1"


# ── SyncResult structure ─────────────────────────────────────────────

def test_sync_result_fields(tmp_path):
    config_path = tmp_path / "opencode.json"
    vault = _make_vault({})
    settings = _make_settings(google_enabled=False, byteplus_enabled=False)

    result = _sync(vault, settings, tmp_path, config_path=config_path)

    assert isinstance(result, SyncResult)
    assert isinstance(result.synced, list)
    assert isinstance(result.removed, list)
    assert isinstance(result.skipped, list)
    assert isinstance(result.path, str)
    assert result.error is None


# ── Atomic write ─────────────────────────────────────────────────────

def test_sync_no_tmp_file_left(tmp_path):
    config_path = tmp_path / "opencode.json"
    vault = _make_vault({"providers/google": "key"})
    settings = _make_settings(google_mode="gemini", byteplus_enabled=False)

    _sync(vault, settings, tmp_path, config_path=config_path)

    assert config_path.exists()
    assert not config_path.with_suffix(".tmp").exists()


def test_sync_creates_parent_dirs(tmp_path):
    config_path = tmp_path / "deep" / "nested" / "opencode.json"
    vault = _make_vault({"providers/google": "key"})
    settings = _make_settings(google_mode="gemini", byteplus_enabled=False)

    _sync(vault, settings, tmp_path, config_path=config_path)

    assert config_path.exists()


# ── Vault exception handling ─────────────────────────────────────────

def test_sync_skips_provider_on_vault_exception(tmp_path):
    """If vault.get() throws, that provider is skipped."""
    config_path = tmp_path / "opencode.json"
    vault = MagicMock()
    vault.get.side_effect = RuntimeError("vault unavailable")
    settings = _make_settings(google_mode="gemini", byteplus_enabled=True)

    result = _sync(vault, settings, tmp_path, config_path=config_path)

    assert result.synced == []
    assert "gemini" in result.skipped
    assert "byteplus" in result.skipped


# ── Corrupt opencode.json ────────────────────────────────────────────

def test_sync_handles_corrupt_opencode_json(tmp_path):
    """Corrupt opencode.json should be replaced with fresh config."""
    config_path = tmp_path / "opencode.json"
    config_path.write_text("{{{bad json!!")

    vault = _make_vault({"providers/google": "key"})
    settings = _make_settings(google_mode="gemini", byteplus_enabled=False)

    result = _sync(vault, settings, tmp_path, config_path=config_path)

    assert result.error is None
    assert "gemini" in result.synced
    data = json.loads(config_path.read_text())
    assert data["$schema"] == OPENCODE_SCHEMA
    assert "gemini" in data["provider"]


# ── Idempotent sync ──────────────────────────────────────────────────

def test_sync_idempotent(tmp_path):
    """Running sync twice with same inputs produces identical output."""
    config_path = tmp_path / "opencode.json"
    vault = _make_vault({
        "providers/google": "key",
        "providers/byteplus": "bp-key",
    })
    settings = _make_settings(google_mode="gemini", byteplus_enabled=True)

    _sync(vault, settings, tmp_path, config_path=config_path)
    first = config_path.read_text()

    _sync(vault, settings, tmp_path, config_path=config_path)
    second = config_path.read_text()

    assert first == second


# ── Write error handling ─────────────────────────────────────────────

def test_sync_returns_error_on_write_failure(tmp_path):
    """If writing fails, SyncResult.error is populated."""
    # Make the target path a directory so writing fails
    config_path = tmp_path / "opencode.json"
    config_path.mkdir()

    vault = _make_vault({"providers/gemini": "key"})
    settings = _make_settings(google_mode="gemini", byteplus_enabled=False)

    result = _sync(vault, settings, tmp_path, config_path=config_path)

    assert result.error is not None
    assert result.synced == []


# ── Both providers disabled ──────────────────────────────────────────

def test_sync_works_without_explicit_provider_settings(tmp_path):
    """When providers.google is None in settings but vault has a key, sync should still work."""
    config_path = tmp_path / "opencode.json"
    vault = _make_vault({
        "providers/google": "AIzaSy-real-key",
        "providers/byteplus": "bp-real-key",
    })
    # Settings with no explicit provider config (both None)
    settings = MasterSettings(providers=ProvidersNamespace())

    result = _sync(vault, settings, tmp_path, config_path=config_path)

    assert result.error is None
    assert "gemini" in result.synced
    assert "byteplus" in result.synced

    data = json.loads(config_path.read_text())
    assert data["provider"]["gemini"]["options"]["apiKey"] == "AIzaSy-real-key"
    assert data["provider"]["byteplus"]["options"]["apiKey"] == "bp-real-key"


def test_sync_respects_enabled_models(tmp_path, gemini_catalog):
    """When enabled_models is set, only those models appear in opencode.json."""
    config_path = tmp_path / "opencode.json"
    vault = _make_vault({
        "providers/google": "AIzaSy-key",
        "providers/byteplus": "bp-key",
    })
    settings = _make_settings(google_mode="gemini", byteplus_enabled=True)
    # Only enable one gemini model and one byteplus model
    settings.providers.google.enabled_models = ["gemini/gemini-3-flash-preview"]
    settings.providers.byteplus.enabled_models = ["byteplus/seed-2-0-pro-260328"]

    _sync(vault, settings, tmp_path, config_path=config_path)

    data = json.loads(config_path.read_text())
    gemini_models = data["provider"]["gemini"]["models"]
    assert len(gemini_models) == 1
    assert "gemini-3-flash-preview" in gemini_models

    bp_models = data["provider"]["byteplus"]["models"]
    assert len(bp_models) == 1
    assert "seed-2-0-pro-260328" in bp_models


def test_sync_empty_enabled_models_includes_all(tmp_path, gemini_catalog):
    """Empty enabled_models list means all models."""
    config_path = tmp_path / "opencode.json"
    vault = _make_vault({"providers/google": "key"})
    settings = _make_settings(google_mode="gemini", byteplus_enabled=False)
    settings.providers.google.enabled_models = []

    _sync(vault, settings, tmp_path, config_path=config_path)

    data = json.loads(config_path.read_text())
    # All gemini-mode entries from the injected catalog (3 entries)
    assert len(data["provider"]["gemini"]["models"]) == 3


def test_sync_all_disabled_removes_provider_block(tmp_path):
    """When all providers are disabled and was previously synced, provider block is cleaned."""
    config_path = tmp_path / "opencode.json"
    config_path.write_text(json.dumps({
        "$schema": OPENCODE_SCHEMA,
        "provider": {
            "gemini": {"options": {"apiKey": "old"}, "models": {}},
            "byteplus": {"options": {"apiKey": "old"}, "models": {}},
        },
        "model": "anthropic/claude-sonnet-4-6",
    }))

    vault = _make_vault({})
    settings = _make_settings(google_enabled=False, byteplus_enabled=False)

    _result = _sync(vault, settings, tmp_path, config_path=config_path)

    data = json.loads(config_path.read_text())
    # provider block should be gone entirely
    assert "provider" not in data
    # other keys preserved
    assert data["model"] == "anthropic/claude-sonnet-4-6"


# ═══════════════════════════════════════════════════════════════════════
# Vertex AI sync (google-vertex + google-vertex-anthropic)
# ═══════════════════════════════════════════════════════════════════════


def test_sync_writes_google_vertex_in_vertex_mode(tmp_path, gemini_catalog):
    """Vertex mode produces google-vertex + google-vertex-anthropic blocks."""
    config_path = tmp_path / "opencode.json"
    # Vault has no api key -- vertex doesn't need one (ADC / service account).
    vault = _make_vault({})
    settings = _make_settings(
        google_mode="vertex",
        google_project_id="my-gcp-project",
        google_vertex_location="us-central1",
        byteplus_enabled=False,
    )

    result = _sync(vault, settings, tmp_path, config_path=config_path)

    assert result.error is None
    assert "google-vertex" in result.synced
    assert "google-vertex-anthropic" in result.synced
    # The gemini API-mode provider must NOT appear in vertex mode.
    assert "gemini" not in result.synced

    data = json.loads(config_path.read_text())
    block = data["provider"]
    assert "google-vertex" in block
    assert "google-vertex-anthropic" in block
    assert "gemini" not in block


def test_sync_vertex_uses_project_and_location(tmp_path, gemini_catalog):
    """Vertex options carry project + location, not apiKey/baseURL."""
    config_path = tmp_path / "opencode.json"
    vault = _make_vault({})
    settings = _make_settings(
        google_mode="vertex",
        google_project_id="my-gcp-project",
        google_vertex_location="us-central1",
        byteplus_enabled=False,
    )

    _sync(vault, settings, tmp_path, config_path=config_path)

    data = json.loads(config_path.read_text())
    for name in ("google-vertex", "google-vertex-anthropic"):
        opts = data["provider"][name]["options"]
        assert opts == {
            "project": "my-gcp-project",
            "location": "us-central1",
        }
        assert "apiKey" not in opts
        assert "baseURL" not in opts


def test_sync_vertex_defaults_location_to_global(tmp_path, gemini_catalog):
    """When vertex_location is unset, options use 'global'."""
    config_path = tmp_path / "opencode.json"
    vault = _make_vault({})
    settings = _make_settings(
        google_mode="vertex",
        google_project_id="my-gcp-project",
        byteplus_enabled=False,
    )

    _sync(vault, settings, tmp_path, config_path=config_path)

    data = json.loads(config_path.read_text())
    assert data["provider"]["google-vertex"]["options"]["location"] == "global"


def test_sync_skips_vertex_without_project_id(tmp_path, gemini_catalog):
    """Vertex requires a project_id; without one, sync skips cleanly."""
    config_path = tmp_path / "opencode.json"
    vault = _make_vault({})
    settings = _make_settings(
        google_mode="vertex",
        google_project_id=None,  # no project configured
        byteplus_enabled=False,
    )

    result = _sync(vault, settings, tmp_path, config_path=config_path)

    assert result.error is None
    assert "google-vertex" not in result.synced
    assert "google-vertex-anthropic" not in result.synced
    assert "google-vertex" in result.skipped
    assert "google-vertex-anthropic" in result.skipped

    data = json.loads(config_path.read_text())
    assert "google-vertex" not in data.get("provider", {})


def test_sync_removes_stale_vertex_when_project_id_cleared(
    tmp_path, gemini_catalog
):
    """If a previous sync wrote vertex but project_id is now empty, remove it."""
    config_path = tmp_path / "opencode.json"
    config_path.write_text(json.dumps({
        "$schema": OPENCODE_SCHEMA,
        "provider": {
            "google-vertex": {
                "options": {"project": "old", "location": "global"},
                "models": {},
            },
        },
    }))

    vault = _make_vault({})
    settings = _make_settings(
        google_mode="vertex",
        google_project_id="",
        byteplus_enabled=False,
    )

    result = _sync(vault, settings, tmp_path, config_path=config_path)

    assert "google-vertex" in result.removed
    data = json.loads(config_path.read_text())
    assert "google-vertex" not in data.get("provider", {})


def test_sync_skips_vertex_providers_in_gemini_mode(tmp_path, gemini_catalog):
    """Gemini mode must not produce vertex blocks even with a project_id."""
    config_path = tmp_path / "opencode.json"
    vault = _make_vault({"providers/google": "AIzaSy-key"})
    settings = _make_settings(
        google_mode="gemini",
        google_project_id="my-gcp-project",  # ignored in gemini mode
        byteplus_enabled=False,
    )

    result = _sync(vault, settings, tmp_path, config_path=config_path)

    assert "gemini" in result.synced
    assert "google-vertex" not in result.synced
    assert "google-vertex-anthropic" not in result.synced

    data = json.loads(config_path.read_text())
    assert "gemini" in data["provider"]
    assert "google-vertex" not in data["provider"]
    assert "google-vertex-anthropic" not in data["provider"]


def test_sync_vertex_writes_models_with_id_prefix(tmp_path, gemini_catalog):
    """Each vertex block holds only entries matching its id_prefix."""
    config_path = tmp_path / "opencode.json"
    vault = _make_vault({})
    settings = _make_settings(
        google_mode="vertex",
        google_project_id="my-gcp-project",
        byteplus_enabled=False,
    )

    _sync(vault, settings, tmp_path, config_path=config_path)

    data = json.loads(config_path.read_text())
    v_models = data["provider"]["google-vertex"]["models"]
    va_models = data["provider"]["google-vertex-anthropic"]["models"]

    # google-vertex bucket has the Gemini-on-Vertex entry only
    assert "gemini-3.1-pro-preview" in v_models
    assert v_models["gemini-3.1-pro-preview"]["npm"] == "@ai-sdk/google-vertex"
    # google-vertex-anthropic bucket has the Claude-on-Vertex entry only
    assert any(key.startswith("claude-sonnet-4-6") for key in va_models)
    assert all(
        val["name"].startswith("google-vertex-anthropic:")
        for val in va_models.values()
    )


def test_sync_skips_vertex_when_google_disabled(tmp_path, gemini_catalog):
    """enabled=False overrides deployment_mode for vertex too."""
    config_path = tmp_path / "opencode.json"
    vault = _make_vault({})
    settings = _make_settings(
        google_enabled=False,
        google_mode="vertex",
        google_project_id="my-gcp-project",
        byteplus_enabled=False,
    )

    result = _sync(vault, settings, tmp_path, config_path=config_path)

    assert "google-vertex" not in result.synced
    assert "google-vertex-anthropic" not in result.synced


# ═══════════════════════════════════════════════════════════════════════
# auth.json tests
# ═══════════════════════════════════════════════════════════════════════

def test_auth_json_writes_api_keys(tmp_path):
    """Vault keys for native providers are written to auth.json."""
    vault = _make_vault({
        "providers/anthropic": "sk-ant-real",
        "providers/openai": "sk-openai-real",
        "providers/xai": "xai-key",
    })
    settings = _make_settings(google_enabled=False, byteplus_enabled=False)

    result = _sync(vault, settings, tmp_path)
    auth = json.loads((tmp_path / "auth.json").read_text())

    assert auth["anthropic"] == {"type": "api", "key": "sk-ant-real"}
    assert auth["openai"] == {"type": "api", "key": "sk-openai-real"}
    assert auth["xai"] == {"type": "api", "key": "xai-key"}

    assert "anthropic" in result.synced
    assert "openai" in result.synced
    assert "xai" in result.synced
    assert result.auth_json is not None
    assert "anthropic" in result.auth_json.synced


def test_auth_json_preserves_openai_oauth_without_vault_key(tmp_path):
    """An OpenCode OAuth login should not be removed when vault has no key."""
    auth_path = tmp_path / "auth.json"
    oauth_entry = {
        "type": "oauth",
        "access": "access-token",
        "refresh": "refresh-token",
        "expires": 9999999999,
        "accountId": "acct-test",
    }
    auth_path.write_text(json.dumps({"openai": oauth_entry}))

    vault = _make_vault({})
    settings = _make_settings(google_enabled=False, byteplus_enabled=False)

    result = _sync(vault, settings, tmp_path, auth_path=auth_path)
    auth = json.loads(auth_path.read_text())

    assert auth["openai"] == oauth_entry
    assert "openai" not in result.auth_json.removed
    assert "openai" in result.auth_json.skipped


def test_auth_json_preserves_openai_oauth_over_stale_vault_key(tmp_path):
    """A stale dashboard vault key should not replace OpenCode OAuth auth."""
    auth_path = tmp_path / "auth.json"
    oauth_entry = {
        "type": "oauth",
        "access": "access-token",
        "refresh": "refresh-token",
        "expires": 9999999999,
        "accountId": "acct-test",
    }
    auth_path.write_text(json.dumps({"openai": oauth_entry}))

    vault = _make_vault({"providers/openai": "sk-stale-dashboard-key"})
    settings = _make_settings(google_enabled=False, byteplus_enabled=False)

    result = _sync(vault, settings, tmp_path, auth_path=auth_path)
    auth = json.loads(auth_path.read_text())

    assert auth["openai"] == oauth_entry
    assert "key" not in auth["openai"]
    assert "openai" not in result.auth_json.synced
    assert "openai" in result.auth_json.skipped


def test_auth_json_removes_stale_entries(tmp_path):
    """When a vault key is removed, the auth.json entry is deleted."""
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps({
        "anthropic": {"type": "api", "key": "old-key"},
        "deepseek": {"type": "api", "key": "old-ds"},
    }))

    vault = _make_vault({"providers/anthropic": "new-key"})  # deepseek removed
    settings = _make_settings(google_enabled=False, byteplus_enabled=False)

    result = _sync(vault, settings, tmp_path, auth_path=auth_path)
    auth = json.loads(auth_path.read_text())

    assert auth["anthropic"]["key"] == "new-key"
    assert "deepseek" not in auth
    assert "deepseek" in result.auth_json.removed


def test_auth_json_preserves_unknown_entries(tmp_path):
    """Entries not in AUTH_JSON_PROVIDERS are preserved."""
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps({
        "custom-provider": {"type": "api", "key": "custom"},
    }))

    vault = _make_vault({"providers/anthropic": "key"})
    settings = _make_settings(google_enabled=False, byteplus_enabled=False)

    _sync(vault, settings, tmp_path, auth_path=auth_path)
    auth = json.loads(auth_path.read_text())

    assert auth["custom-provider"] == {"type": "api", "key": "custom"}
    assert "anthropic" in auth


def test_auth_json_and_opencode_json_both_synced(tmp_path):
    """Both targets should be synced in a single call."""
    vault = _make_vault({
        "providers/google": "gemini-key",
        "providers/anthropic": "ant-key",
        "providers/openai": "oai-key",
    })
    settings = _make_settings(google_mode="gemini", byteplus_enabled=False)

    result = _sync(vault, settings, tmp_path)

    # opencode.json has gemini
    oc = json.loads((tmp_path / "opencode.json").read_text())
    assert "gemini" in oc["provider"]

    # auth.json has anthropic + openai
    auth = json.loads((tmp_path / "auth.json").read_text())
    assert auth["anthropic"]["key"] == "ant-key"
    assert auth["openai"]["key"] == "oai-key"

    # Combined result
    assert "gemini" in result.synced
    assert "anthropic" in result.synced
    assert "openai" in result.synced
    assert result.opencode_json.path.endswith("opencode.json")
    assert result.auth_json.path.endswith("auth.json")


def test_auth_json_azure_dual_auth(tmp_path):
    """Azure uses AUTH_JSON (api key).  ENV part is not file-synced."""
    vault = _make_vault({"providers/azure": "azure-secret"})
    settings = _make_settings(google_enabled=False, byteplus_enabled=False)

    result = _sync(vault, settings, tmp_path)
    auth = json.loads((tmp_path / "auth.json").read_text())

    assert auth["azure"] == {"type": "api", "key": "azure-secret"}
    assert "azure" in result.auth_json.synced


def test_auth_json_skips_on_vault_exception(tmp_path):
    """If vault throws, auth.json providers are skipped."""
    vault = MagicMock()
    vault.get.side_effect = RuntimeError("boom")
    settings = _make_settings(google_enabled=False, byteplus_enabled=False)

    result = _sync(vault, settings, tmp_path)

    assert result.auth_json.synced == []
    assert len(result.auth_json.skipped) > 0


def test_auth_json_corrupt_file_handled(tmp_path):
    """Corrupt auth.json is replaced with fresh entries."""
    auth_path = tmp_path / "auth.json"
    auth_path.write_text("not json at all!!!")

    vault = _make_vault({"providers/openai": "key"})
    settings = _make_settings(google_enabled=False, byteplus_enabled=False)

    result = _sync(vault, settings, tmp_path, auth_path=auth_path)
    auth = json.loads(auth_path.read_text())

    assert auth["openai"]["key"] == "key"
    assert result.auth_json.error is None


def test_auth_json_idempotent(tmp_path):
    """Running sync twice produces identical auth.json."""
    vault = _make_vault({
        "providers/anthropic": "key",
        "providers/xai": "xk",
    })
    settings = _make_settings(google_enabled=False, byteplus_enabled=False)

    _sync(vault, settings, tmp_path)
    first = (tmp_path / "auth.json").read_text()

    _sync(vault, settings, tmp_path)
    second = (tmp_path / "auth.json").read_text()

    assert first == second


def test_sync_result_has_per_target_breakdown(tmp_path):
    """SyncResult must expose opencode_json and auth_json sub-results."""
    vault = _make_vault({"providers/google": "key", "providers/openai": "ok"})
    settings = _make_settings(google_mode="gemini", byteplus_enabled=False)

    result = _sync(vault, settings, tmp_path)

    assert isinstance(result.opencode_json, TargetResult)
    assert isinstance(result.auth_json, TargetResult)
    assert "gemini" in result.opencode_json.synced
    assert "openai" in result.auth_json.synced
