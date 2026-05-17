"""
Tests for Settings API endpoints.

Covers:
- Happy path for all endpoints
- Authentication (401 for unauthenticated requests)
- Vault secret leakage prevention
- Pydantic validation (422 for invalid inputs)
- Event broadcasting on mutations
"""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from dashboard.api import app
from dashboard.auth import get_current_user
from dashboard.global_state import broadcaster
from dashboard.lib.settings.resolver import (
    SettingsResolver,
    reset_settings_resolver,
)
from dashboard.lib.settings.vault import reset_vault


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset all singletons before each test."""
    reset_settings_resolver()
    reset_vault()
    yield
    reset_settings_resolver()
    reset_vault()


@pytest.fixture
def client():
    """Create test client with auth bypass."""
    def override_auth():
        return {"username": "test-user"}

    app.dependency_overrides[get_current_user] = override_auth
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_client():
    """Create test client that requires auth."""
    return TestClient(app)


@pytest.fixture
def mock_broadcaster():
    """Mock broadcaster for testing event emission."""
    with patch.object(broadcaster, "broadcast", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def temp_config(tmp_path):
    """Create temp config and patch resolver to use it."""
    config_file = tmp_path / ".agents" / "config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)

    initial_config = {
        "version": "0.1.0",
        "runtime": {
            "poll_interval_seconds": 5,
            "max_concurrent_rooms": 10,
            "auto_approve_tools": False,
            "dynamic_pipelines": True,
        },
        "autonomy": {
            "idle_explore_enabled": False,
            "interval": 3600,
        },
        "providers": {},
        "manager": {
            "default_model": "gpt-4o",
        },
    }
    config_file.write_text(json.dumps(initial_config, indent=2))

    warrooms = tmp_path / ".war-rooms"
    warrooms.mkdir()

    plans_dir = config_file.parent / "plans"
    plans_dir.mkdir()

    from dashboard.lib.settings.vault import SettingsVault
    from dashboard.lib.settings.backends.base import VaultBackendType, VaultHealthStatus

    mock_backend = MagicMock()
    mock_backend.get.return_value = None
    mock_backend.list_keys.return_value = []
    mock_backend.delete.return_value = True
    mock_backend.backend_type = VaultBackendType.ENCRYPTED_FILE
    mock_backend.health.return_value = VaultHealthStatus(
        healthy=True,
        backend_type="encrypted_file",
        message="ok",
    )

    mock_vault = SettingsVault(backend=mock_backend)

    def _make_resolver():
        r = SettingsResolver(config_path=config_file)
        r.vault = mock_vault
        return r

    with patch(
        "dashboard.api_utils.AGENTS_DIR", config_file.parent
    ), patch(
        "dashboard.api_utils.WARROOMS_DIR", warrooms
    ), patch(
        "dashboard.api_utils.PLANS_DIR", plans_dir
    ), patch(
        "dashboard.lib.settings.resolver.get_settings_resolver", _make_resolver
    ), patch(
        "dashboard.lib.settings.get_settings_resolver", _make_resolver
    ), patch(
        "dashboard.routes.settings.get_settings_resolver", _make_resolver
    ), patch(
        "dashboard.routes.settings.get_vault", return_value=mock_vault
    ):
        yield config_file, mock_vault, mock_backend, warrooms


# ── Authentication Tests ───────────────────────────────────────────────────



def test_authenticated_request_accepted(client, temp_config):
    """Authenticated requests should be accepted."""
    response = client.get("/api/settings")
    assert response.status_code == 200


# ── GET Endpoints ───────────────────────────────────────────────────────────

def test_get_master_settings(client, temp_config):
    """GET /api/settings returns MasterSettings."""
    response = client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()

    # Check all 7 namespaces present
    for ns in ("providers", "roles", "runtime", "memory", "channels", "autonomy", "observability"):
        assert ns in data


def test_get_effective_settings(client, temp_config):
    """GET /api/settings/effective resolves role settings."""
    response = client.get("/api/settings/effective?role=manager")

    assert response.status_code == 200
    data = response.json()

    assert "effective" in data
    assert "provenance" in data
    assert isinstance(data["effective"], dict)
    assert isinstance(data["provenance"], dict)


def test_get_settings_schema(client, temp_config):
    """GET /api/settings/schema returns JSON schema."""
    response = client.get("/api/settings/schema")

    assert response.status_code == 200
    data = response.json()

    # Pydantic v2 puts the root schema as "title" + "properties";
    # nested models go into "$defs".
    assert "properties" in data
    assert "title" in data or "$defs" in data


# ── Mutation Endpoints ─────────────────────────────────────────────────────

def test_patch_global_namespace(client, temp_config, mock_broadcaster):
    """PUT /api/settings/{namespace} updates config and broadcasts."""
    config_file, _, _, _ = temp_config
    payload = {"max_concurrent_rooms": 100}
    response = client.put("/api/settings/runtime", json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    config = json.loads(config_file.read_text())
    assert config["manager"]["max_concurrent_rooms"] == 100
    assert "max_concurrent_rooms" not in config.get("runtime", {})

    # Verify broadcast was called
    mock_broadcaster.assert_called_once()
    call_args = mock_broadcaster.call_args
    assert call_args[0][0] == "settings_updated"
    assert call_args[0][1]["namespace"] == "runtime"


def test_patch_runtime_master_model_updates_active_singleton(
    client, temp_config, mock_broadcaster
):
    """PUT /settings/runtime must update the model used by active chats."""
    from dashboard import master_agent as ma

    ma._master_config.model = ma.DEFAULT_MODEL
    ma._master_config.provider = ma.DEFAULT_PROVIDER
    ma._master_config.is_explicit = False

    response = client.put(
        "/api/settings/runtime",
        json={"master_agent_model": "gemini-3.1-pro"},
    )

    assert response.status_code == 200
    model, provider = ma.get_model_and_provider()
    assert model == "gemini-3.1-pro"
    assert provider == "google"

    config_file, _, _, _ = temp_config
    config = json.loads(config_file.read_text())
    assert config["runtime"]["master_agent_model"] == "google/gemini-3.1-pro"


def test_patch_creates_new_namespace(client, temp_config, mock_broadcaster):
    """PUT with a namespace value creates/updates it in config."""
    config_file, _, _, _ = temp_config
    payload = {"idle_explore_enabled": True}
    response = client.put("/api/settings/autonomy", json=payload)

    assert response.status_code == 200

    config = json.loads(config_file.read_text())
    assert config["autonomy"]["idle_explore_enabled"] is True


def test_patch_invalid_namespace(client, temp_config):
    """PUT to invalid namespace returns 400."""
    payload = {"test": "value"}
    response = client.put("/api/settings/invalid_namespace", json=payload)

    assert response.status_code == 400


def test_reset_namespace(client, temp_config, mock_broadcaster):
    """POST /api/settings/reset/{namespace} removes namespace."""
    response = client.post("/api/settings/reset/runtime")

    assert response.status_code == 200
    mock_broadcaster.assert_called_once()
    call_args = mock_broadcaster.call_args
    assert call_args[0][0] == "settings_updated"


def test_patch_plan_role(client, temp_config, mock_broadcaster):
    """PUT /api/settings/plan/{plan_id}/role/{role} updates plan roles.json."""
    config_file, _, _, _ = temp_config
    plans_dir = config_file.parent / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / "plan-001.roles.json").write_text("{}")

    payload = {"default_model": "gpt-4o"}
    response = client.put(
        "/api/settings/plan/plan-001/role/engineer", json=payload
    )

    assert response.status_code == 200
    mock_broadcaster.assert_called_once()


def test_patch_room_role(client, temp_config, mock_broadcaster):
    """PUT /api/settings/room/{plan_id}/{task_ref}/role/{role} updates room config."""
    _, _, _, warrooms = temp_config
    room_dir = warrooms / "plan-001" / "task-001"
    room_dir.mkdir(parents=True)
    (room_dir / "config.json").write_text("{}")

    payload = {"temperature": 0.8}
    response = client.put(
        "/api/settings/room/plan-001/task-001/role/engineer", json=payload
    )

    assert response.status_code == 200
    mock_broadcaster.assert_called_once()


# ── Vault Management Tests ─────────────────────────────────────────────────

def test_vault_store_secret(client, temp_config):
    """POST /api/settings/vault/{scope}/{key} stores secret."""
    _, _, mock_backend, _ = temp_config

    payload = {"value": "sk-ant-test-secret"}
    response = client.post(
        "/api/settings/vault/providers/claude", json=payload
    )

    assert response.status_code == 200
    assert response.json()["is_set"] is True
    mock_backend.set.assert_called_once_with("providers", "claude", "sk-ant-test-secret")


def test_vault_list_keys_never_returns_values(client, temp_config):
    """GET /api/settings/vault/{scope} never returns secret values."""
    _, _, mock_backend, _ = temp_config
    mock_backend.list_keys.return_value = ["claude", "openai"]

    response = client.get("/api/settings/vault/providers")

    assert response.status_code == 200
    data = response.json()
    assert "keys" in data
    assert data["keys"]["claude"]["is_set"] is True
    assert "value" not in data["keys"]["claude"]


def test_vault_delete_secret(client, temp_config):
    """DELETE /api/settings/vault/{scope}/{key} removes secret."""
    _, _, mock_backend, _ = temp_config
    mock_backend.delete.return_value = True

    response = client.delete("/api/settings/vault/providers/claude")

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"


def test_vault_delete_not_found(client, temp_config):
    """DELETE returns 404 if secret not found."""
    _, _, mock_backend, _ = temp_config
    mock_backend.delete.return_value = False

    response = client.delete("/api/settings/vault/providers/nonexistent")

    assert response.status_code == 404


def test_vault_ref_not_dereferenced_in_master_settings(client, temp_config):
    """Master settings should preserve vault refs as strings."""
    config_file, _, _, _ = temp_config
    config = json.loads(config_file.read_text())
    config["providers"] = {
        "anthropic": {"api_key_ref": "${vault:providers/claude}"}
    }
    config_file.write_text(json.dumps(config))

    response = client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()
    anthropic = data.get("providers", {}).get("anthropic", {})
    if anthropic.get("api_key_ref"):
        assert "${vault:" in anthropic["api_key_ref"]


def test_effective_settings_masks_secrets(client, temp_config):
    """Effective settings should mask secrets as ***."""
    response = client.get("/api/settings/effective?role=manager")

    assert response.status_code == 200
    data = response.json()
    assert "effective" in data


# ── Validation Tests ───────────────────────────────────────────────────────

def test_validation_error_on_invalid_input(client, temp_config):
    """Invalid input should return 422 with field-level detail."""
    payload = {"max_concurrent_rooms": 99999}
    response = client.put("/api/settings/runtime", json=payload)
    assert response.status_code == 422


def test_validation_error_on_legacy_poll_interval_key(client, temp_config):
    """Legacy poll_interval key should be rejected."""
    payload = {"poll_interval": 10}
    response = client.put("/api/settings/runtime", json=payload)
    assert response.status_code == 422


def test_provider_test_endpoint(client, temp_config):
    """POST /api/settings/test/{provider} tests provider connection."""
    with patch("dashboard.routes.roles.test_model_connection") as mock_test:
        mock_test.return_value = {"status": "ok", "latency_ms": 123}

        _response = client.post("/api/settings/test/openai")
        mock_test.assert_called_once()


# ── Integration Test ───────────────────────────────────────────────────────

def test_vault_status_endpoint(client, temp_config):
    """GET /api/settings/vault/status returns backend info."""
    response = client.get("/api/settings/vault/status")
    assert response.status_code == 200
    data = response.json()
    assert "backend" in data
    assert "healthy" in data
    assert data["healthy"] is True
    assert "message" in data
    assert "details" in data


def test_full_settings_workflow(client, temp_config, mock_broadcaster):
    """Test complete workflow: get -> update -> verify -> reset."""
    config_file, _, _, _ = temp_config

    # 1. Get initial settings
    response = client.get("/api/settings")
    assert response.status_code == 200
    initial_runtime = response.json()["runtime"]

    # 2. Update runtime settings
    new_max = min(initial_runtime["max_concurrent_rooms"] + 10, 10000)
    payload = {"max_concurrent_rooms": new_max}
    response = client.put("/api/settings/runtime", json=payload)
    assert response.status_code == 200

    # 3. Verify update persisted on disk
    config = json.loads(config_file.read_text())
    assert config["manager"]["max_concurrent_rooms"] == new_max
    assert "max_concurrent_rooms" not in config.get("runtime", {})

    # 4. Reset namespace
    response = client.post("/api/settings/reset/runtime")
    assert response.status_code == 200

    # 5. Verify reset removed the namespace
    config = json.loads(config_file.read_text())
    assert "runtime" not in config


# ── Vault scope validation via API ─────────────────────────────────────

def test_vault_store_invalid_scope(client, temp_config):
    """POST to vault with invalid scope should raise ValueError (500)."""
    payload = {"value": "secret"}
    with pytest.raises(ValueError, match="Invalid scope"):
        client.post("/api/settings/vault/bad_scope/key", json=payload)


def test_vault_list_invalid_scope(client, temp_config):
    """GET vault with invalid scope should raise ValueError (500)."""
    with pytest.raises(ValueError, match="Invalid scope"):
        client.get("/api/settings/vault/bad_scope")


# ── Vault auto-sync on provider key change ─────────────────────────────

def test_vault_store_triggers_opencode_sync(client, temp_config):
    """POST to vault/providers/* should trigger opencode sync."""
    with patch("dashboard.routes.settings._try_opencode_sync") as mock_sync:
        payload = {"value": "sk-test"}
        response = client.post("/api/settings/vault/providers/gemini", json=payload)

    assert response.status_code == 200
    mock_sync.assert_called_once()


def test_vault_store_non_provider_skips_sync(client, temp_config):
    """POST to vault/channels/* should NOT trigger opencode sync."""
    with patch("dashboard.routes.settings._try_opencode_sync") as mock_sync:
        payload = {"value": "bot-token"}
        response = client.post("/api/settings/vault/channels/telegram", json=payload)

    assert response.status_code == 200
    mock_sync.assert_not_called()


def test_vault_delete_triggers_opencode_sync(client, temp_config):
    """DELETE vault/providers/* should trigger opencode sync."""
    _, _, mock_backend, _ = temp_config
    mock_backend.delete.return_value = True

    with patch("dashboard.routes.settings._try_opencode_sync") as mock_sync:
        response = client.delete("/api/settings/vault/providers/gemini")

    assert response.status_code == 200
    mock_sync.assert_called_once()


def test_vault_delete_non_provider_skips_sync(client, temp_config):
    """DELETE vault/channels/* should NOT trigger opencode sync."""
    _, _, mock_backend, _ = temp_config
    mock_backend.delete.return_value = True

    with patch("dashboard.routes.settings._try_opencode_sync") as mock_sync:
        response = client.delete("/api/settings/vault/channels/telegram")

    assert response.status_code == 200
    mock_sync.assert_not_called()


# ── OpenCode sync endpoint ─────────────────────────────────────────────

def test_opencode_sync_endpoint(client, temp_config):
    """POST /api/settings/opencode/sync returns SyncResult shape."""
    with patch("dashboard.routes.settings.sync_opencode_config") as mock_sync:
        from dashboard.lib.settings.opencode_sync import SyncResult
        mock_sync.return_value = SyncResult(
            synced=["gemini"], removed=[], skipped=["byteplus"],
            path="/tmp/opencode.json",
        )
        response = client.post("/api/settings/opencode/sync")

    assert response.status_code == 200
    data = response.json()
    assert data["synced"] == ["gemini"]
    assert data["removed"] == []
    assert data["skipped"] == ["byteplus"]
    assert data["path"] == "/tmp/opencode.json"
    assert data["error"] is None


def test_opencode_sync_endpoint_with_error(client, temp_config):
    """POST /api/settings/opencode/sync returns error field on failure."""
    with patch("dashboard.routes.settings.sync_opencode_config") as mock_sync:
        from dashboard.lib.settings.opencode_sync import SyncResult
        mock_sync.return_value = SyncResult(
            synced=[], removed=[], skipped=["gemini", "byteplus"],
            path="/tmp/opencode.json",
            error="Permission denied",
        )
        response = client.post("/api/settings/opencode/sync")

    assert response.status_code == 200
    data = response.json()
    assert data["error"] == "Permission denied"


# ── Models registry endpoint (config-driven) ──────────────────────────

def test_models_registry_returns_all_when_settings_fail(client, temp_config):
    """GET /api/models/registry returns a non-empty registry.

    The registry merges dynamic (models.dev) + static fallback.
    Dynamic keys may differ from static (e.g. 'OpenAI' vs 'GPT',
    'Anthropic' vs 'Claude').  We verify the response is non-empty
    and every provider entry contains valid model dicts.
    """
    response = client.get("/api/models/registry")

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    for provider, models in data.items():
        assert isinstance(models, list)
        if models:
            assert "id" in models[0]


# ── Knowledge Settings (CARRY-002 — ADR-15) ────────────────────────────


def test_get_knowledge_settings_returns_defaults(client, temp_config):
    """GET /api/settings/knowledge returns the KnowledgeSettings shape."""
    response = client.get("/api/settings/knowledge")

    assert response.status_code == 200
    data = response.json()
    # Shape check (defaults from KnowledgeSettings model)
    assert "knowledge_llm_model" in data
    assert "knowledge_embedding_model" in data
    assert "knowledge_embedding_dimension" in data
    # Dimension is read-only, fixed from OSTWIN_EMBEDDING_DIM env var.
    assert data["knowledge_embedding_dimension"] == 1024


def test_put_knowledge_settings_persists(client, temp_config, mock_broadcaster):
    """PUT /api/settings/knowledge persists and broadcasts."""
    payload = {
        "knowledge_llm_model": "claude-haiku-4-5",
        "knowledge_embedding_model": "qwen3-embedding:0.6b",
    }
    r = client.put("/api/settings/knowledge", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["knowledge_llm_model"] == "claude-haiku-4-5"
    assert body["knowledge_embedding_model"] == "qwen3-embedding:0.6b"
    # Dimension is read-only (ignored on write, always reflects env var).
    assert body["knowledge_embedding_dimension"] == 1024

    # Roundtrip: GET should return the new values.
    r2 = client.get("/api/settings/knowledge")
    assert r2.status_code == 200
    assert r2.json()["knowledge_llm_model"] == "claude-haiku-4-5"

    # Broadcaster fired with namespace=knowledge.
    mock_broadcaster.assert_called()
    call_args = mock_broadcaster.call_args
    assert call_args[0][0] == "settings_updated"
    assert call_args[0][1]["namespace"] == "knowledge"


def test_put_knowledge_settings_requires_auth(auth_client):
    """PUT /api/settings/knowledge without auth returns 401."""
    r = auth_client.put("/api/settings/knowledge", json={"knowledge_llm_model": "x"})
    assert r.status_code == 401


def test_get_knowledge_settings_requires_auth(auth_client):
    """GET /api/settings/knowledge without auth returns 401."""
    r = auth_client.get("/api/settings/knowledge")
    assert r.status_code == 401


def test_knowledge_settings_partial_payload_uses_defaults(client, temp_config):
    """PUT with only knowledge_llm_model populated → knowledge_embedding_model defaults to ''."""
    payload = {"knowledge_llm_model": "claude-sonnet-4-5-20251022"}
    r = client.put("/api/settings/knowledge", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["knowledge_llm_model"] == "claude-sonnet-4-5-20251022"
    assert body["knowledge_embedding_model"] == ""
    assert body["knowledge_embedding_dimension"] == 1024
