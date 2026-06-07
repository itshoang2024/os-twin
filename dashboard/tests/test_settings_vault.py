"""
Tests for dashboard.lib.settings.vault.SettingsVault and the backend layer.

Covers:
- Scope validation
- CRUD operations (get/set/delete/list)
- Backend protocol compliance
- Health check
- Thread-safe singleton
- Factory auto-detection
"""

import os
import threading
import pytest
from unittest.mock import MagicMock, patch

from dashboard.lib.settings.vault import SettingsVault, get_vault, reset_vault
from dashboard.lib.settings.backends.base import (
    VaultBackend,
    VaultBackendType,
    VaultHealthStatus,
)
from dashboard.lib.settings.backends.encrypted_file import EncryptedFileBackend
from dashboard.lib.settings.backends.env import EnvBackend
from dashboard.lib.settings.backends.factory import create_backend


# ── Helpers ───────────────────────────────────────────────────────────────

def _mock_backend() -> MagicMock:
    """Create a mock that satisfies the VaultBackend protocol."""
    mock = MagicMock(spec=VaultBackend)
    mock.backend_type = VaultBackendType.KEYCHAIN
    mock.health.return_value = VaultHealthStatus(
        healthy=True,
        backend_type="keychain",
        message="ok",
    )
    mock.get.return_value = None
    mock.list_keys.return_value = []
    return mock


@pytest.fixture(autouse=True)
def _reset():
    """Reset the singleton between tests."""
    reset_vault()
    yield
    reset_vault()


# ── Scope validation ──────────────────────────────────────────────────────


def test_valid_scopes_are_accepted():
    mock = _mock_backend()
    vault = SettingsVault(backend=mock)
    for scope in ("providers", "channels", "tunnel", "auth"):
        vault.get(scope, "any-key")  # should not raise


def test_invalid_scope_raises():
    mock = _mock_backend()
    vault = SettingsVault(backend=mock)
    with pytest.raises(ValueError, match="Invalid scope"):
        vault.get("bad_scope", "key")


# ── set ───────────────────────────────────────────────────────────────────


def test_set_delegates_to_backend():
    mock = _mock_backend()
    vault = SettingsVault(backend=mock)
    vault.set("providers", "claude", "sk-ant-...")
    mock.set.assert_called_once_with("providers", "claude", "sk-ant-...")


def test_set_rejects_invalid_scope():
    vault = SettingsVault(backend=_mock_backend())
    with pytest.raises(ValueError, match="Invalid scope"):
        vault.set("nope", "key", "value")


# ── get ───────────────────────────────────────────────────────────────────


def test_get_delegates_to_backend():
    mock = _mock_backend()
    mock.get.return_value = "secret-value"
    vault = SettingsVault(backend=mock)
    assert vault.get("providers", "claude") == "secret-value"
    mock.get.assert_called_once_with("providers", "claude")


def test_get_returns_none_when_missing():
    mock = _mock_backend()
    mock.get.return_value = None
    vault = SettingsVault(backend=mock)
    assert vault.get("providers", "missing") is None


# ── delete ────────────────────────────────────────────────────────────────


def test_delete_returns_true_on_success():
    mock = _mock_backend()
    mock.delete.return_value = True
    vault = SettingsVault(backend=mock)
    assert vault.delete("providers", "claude") is True


def test_delete_returns_false_on_exception():
    mock = _mock_backend()
    mock.delete.side_effect = KeyError("not found")
    vault = SettingsVault(backend=mock)
    assert vault.delete("providers", "missing") is False


def test_delete_rejects_invalid_scope():
    vault = SettingsVault(backend=_mock_backend())
    with pytest.raises(ValueError, match="Invalid scope"):
        vault.delete("bad_scope", "key")


# ── list_keys ─────────────────────────────────────────────────────────────


def test_list_keys_returns_status_dict():
    mock = _mock_backend()
    mock.list_keys.return_value = ["claude", "openai"]
    vault = SettingsVault(backend=mock)
    result = vault.list_keys("providers")
    assert result == {"claude": {"is_set": True}, "openai": {"is_set": True}}


def test_list_keys_empty_scope():
    mock = _mock_backend()
    mock.list_keys.return_value = []
    vault = SettingsVault(backend=mock)
    assert vault.list_keys("providers") == {}


# ── health ────────────────────────────────────────────────────────────────


def test_health_delegates_to_backend():
    mock = _mock_backend()
    vault = SettingsVault(backend=mock)
    health = vault.health()
    assert health.healthy is True
    assert health.backend_type == "keychain"


def test_backend_type_exposed():
    mock = _mock_backend()
    vault = SettingsVault(backend=mock)
    assert vault.backend_type == VaultBackendType.KEYCHAIN


# ── singleton ─────────────────────────────────────────────────────────────


def test_get_vault_singleton():
    mock = _mock_backend()
    v1 = get_vault(backend=mock)
    v2 = get_vault()
    assert v1 is v2


def test_reset_vault_clears_singleton():
    mock = _mock_backend()
    v1 = get_vault(backend=mock)
    reset_vault()
    mock2 = _mock_backend()
    v2 = get_vault(backend=mock2)
    assert v1 is not v2


def test_singleton_thread_safety():
    """Multiple threads calling get_vault() should get the same instance."""
    results = []

    def _get():
        results.append(id(get_vault(backend=_mock_backend())))

    threads = [threading.Thread(target=_get) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All threads should get the same instance id
    assert len(set(results)) == 1


# ── EncryptedFileBackend ──────────────────────────────────────────────────


def test_encrypted_file_roundtrip(tmp_path):
    path = tmp_path / "vault.enc"
    backend = EncryptedFileBackend(path=path)

    backend.set("providers", "test-key", "test-value")
    assert backend.get("providers", "test-key") == "test-value"
    assert backend.list_keys("providers") == ["test-key"]

    assert backend.delete("providers", "test-key") is True
    assert backend.get("providers", "test-key") is None
    assert backend.list_keys("providers") == []


def test_encrypted_file_delete_missing_returns_false(tmp_path):
    path = tmp_path / "vault.enc"
    backend = EncryptedFileBackend(path=path)
    assert backend.delete("providers", "nonexistent") is False


def test_encrypted_file_health(tmp_path):
    path = tmp_path / "vault.enc"
    backend = EncryptedFileBackend(path=path)
    health = backend.health()
    assert health.healthy is True
    assert backend.backend_type == VaultBackendType.ENCRYPTED_FILE


def test_encrypted_file_permissions(tmp_path):
    path = tmp_path / "vault.enc"
    backend = EncryptedFileBackend(path=path)
    backend.set("providers", "k", "v")
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600


# ── EnvBackend ────────────────────────────────────────────────────────────


def test_env_backend_get():
    backend = EnvBackend()
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=False):
        assert backend.get("providers", "claude") == "sk-test"
    # Google key is now under "providers/google"
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "gkey"}, clear=False):
        assert backend.get("providers", "google") == "gkey"
    # Test missing key by using a scope/key with no env mapping
    assert backend.get("providers", "nonexistent") is None
    # Also verify None returned when env var is explicitly unset
    with patch.dict(os.environ, {}, clear=True):
        assert backend.get("providers", "claude") is None


def test_env_backend_list_keys():
    backend = EnvBackend()
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test", "OPENAI_API_KEY": "sk-oa", "GOOGLE_API_KEY": "gk"}):
        keys = backend.list_keys("providers")
    assert "claude" in keys
    assert "openai" in keys
    assert "google" in keys


def test_env_backend_health():
    backend = EnvBackend()
    health = backend.health()
    assert health.healthy is True
    assert backend.backend_type == VaultBackendType.ENV


# ── Factory ───────────────────────────────────────────────────────────────


def test_factory_explicit_type():
    backend = create_backend(VaultBackendType.ENCRYPTED_FILE)
    assert backend.backend_type == VaultBackendType.ENCRYPTED_FILE


def test_factory_env_override():
    with patch.dict(os.environ, {"OSTWIN_VAULT_BACKEND": "env"}):
        backend = create_backend()
    assert backend.backend_type == VaultBackendType.ENV


def test_factory_auto_detection():
    """AUTO should resolve to keychain on macOS, encrypted_file elsewhere."""
    import sys
    backend = create_backend(VaultBackendType.AUTO)
    if sys.platform == "darwin":
        assert backend.backend_type == VaultBackendType.KEYCHAIN
    else:
        assert backend.backend_type == VaultBackendType.ENCRYPTED_FILE


def test_factory_unknown_type_raises():
    with pytest.raises(ValueError, match="No registered backend"):
        create_backend(VaultBackendType.HASHICORP)


def test_factory_invalid_env_var_falls_back():
    """Invalid OSTWIN_VAULT_BACKEND falls back to auto-detect."""
    import sys
    with patch.dict(os.environ, {"OSTWIN_VAULT_BACKEND": "nonsense"}):
        backend = create_backend()
    expected = VaultBackendType.KEYCHAIN if sys.platform == "darwin" else VaultBackendType.ENCRYPTED_FILE
    assert backend.backend_type == expected


# ── EncryptedFileBackend: multi-scope ─────────────────────────────────

def test_encrypted_file_multi_scope_isolation(tmp_path):
    """Keys in different scopes don't interfere."""
    backend = EncryptedFileBackend(path=tmp_path / "v.enc")
    backend.set("providers", "key1", "val-providers")
    backend.set("channels", "key1", "val-channels")

    assert backend.get("providers", "key1") == "val-providers"
    assert backend.get("channels", "key1") == "val-channels"
    assert backend.list_keys("providers") == ["key1"]
    assert backend.list_keys("channels") == ["key1"]

    backend.delete("providers", "key1")
    assert backend.get("providers", "key1") is None
    assert backend.get("channels", "key1") == "val-channels"


def test_encrypted_file_overwrite(tmp_path):
    """Setting the same key twice overwrites the value."""
    backend = EncryptedFileBackend(path=tmp_path / "v.enc")
    backend.set("providers", "k", "v1")
    backend.set("providers", "k", "v2")
    assert backend.get("providers", "k") == "v2"
    assert backend.list_keys("providers") == ["k"]


def test_encrypted_file_corrupt_file(tmp_path):
    """Corrupt vault file should return empty data, not crash."""
    path = tmp_path / "v.enc"
    path.write_bytes(b"this-is-not-valid-encrypted-data")
    backend = EncryptedFileBackend(path=path)
    assert backend.get("providers", "k") is None
    assert backend.list_keys("providers") == []


def test_encrypted_file_empty_file(tmp_path):
    """Empty vault file should return empty data."""
    path = tmp_path / "v.enc"
    path.write_bytes(b"")
    backend = EncryptedFileBackend(path=path)
    assert backend.get("providers", "k") is None


def test_encrypted_file_nonexistent_scope(tmp_path):
    """Querying a scope that was never written returns empty."""
    backend = EncryptedFileBackend(path=tmp_path / "v.enc")
    backend.set("providers", "k", "v")
    assert backend.list_keys("never_used") == []
    assert backend.get("never_used", "k") is None


def test_encrypted_file_delete_cleans_empty_scope(tmp_path):
    """Deleting the last key in a scope removes the scope dict."""
    path = tmp_path / "v.enc"
    backend = EncryptedFileBackend(path=path)
    backend.set("providers", "only-key", "val")
    backend.delete("providers", "only-key")
    # Reload and verify the scope is gone from the JSON
    data = backend._load()
    assert "providers" not in data


def test_encrypted_file_health_reports_path(tmp_path):
    path = tmp_path / "v.enc"
    backend = EncryptedFileBackend(path=path)
    health = backend.health()
    assert health.details["path"] == str(path)
    assert health.details["encrypted"] == "True"


# ── EnvBackend: set / delete / edge cases ─────────────────────────────

def test_env_backend_set_with_mapped_key():
    """set() on a mapped key sets the env var in current process."""
    backend = EnvBackend()
    with patch.dict(os.environ, {}, clear=True):
        backend.set("providers", "claude", "test-key")
        assert os.environ.get("ANTHROPIC_API_KEY") == "test-key"


def test_env_backend_set_unmapped_key_raises():
    backend = EnvBackend()
    with pytest.raises(ValueError, match="No env-var mapping"):
        backend.set("providers", "unknown_provider", "val")


def test_env_backend_delete_existing():
    backend = EnvBackend()
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
        assert backend.delete("providers", "claude") is True
        assert "ANTHROPIC_API_KEY" not in os.environ


def test_env_backend_delete_missing():
    backend = EnvBackend()
    with patch.dict(os.environ, {}, clear=True):
        assert backend.delete("providers", "claude") is False


def test_env_backend_delete_unmapped():
    backend = EnvBackend()
    assert backend.delete("providers", "unknown") is False


def test_env_backend_health_counts():
    backend = EnvBackend()
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x", "OPENAI_API_KEY": "y"}, clear=True):
        health = backend.health()
    assert health.details["set_count"] == "2"


# ── KeychainBackend (mocked subprocess) ───────────────────────────────

from dashboard.lib.settings.backends.keychain import KeychainBackend


def test_keychain_get_found():
    backend = KeychainBackend()
    with patch("dashboard.lib.settings.backends.keychain.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="my-secret\n", stderr=""
        )
        result = backend.get("providers", "claude")
    assert result == "my-secret"
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "find-generic-password" in args
    assert "ostwin-mcp/providers/claude" in args


def test_keychain_get_not_found():
    backend = KeychainBackend()
    with patch("dashboard.lib.settings.backends.keychain.subprocess.run") as mock_run:
        from subprocess import CalledProcessError
        mock_run.side_effect = CalledProcessError(44, "security")
        result = backend.get("providers", "missing")
    assert result is None


def test_keychain_set_calls_add():
    backend = KeychainBackend()
    with patch("dashboard.lib.settings.backends.keychain.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        backend.set("providers", "claude", "new-secret")
    # Should call delete first (to handle dupes), then add
    assert mock_run.call_count == 2
    add_call = mock_run.call_args_list[1][0][0]
    assert "add-generic-password" in add_call


def test_keychain_delete_success():
    backend = KeychainBackend()
    with patch("dashboard.lib.settings.backends.keychain.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert backend.delete("providers", "claude") is True


def test_keychain_delete_not_found():
    backend = KeychainBackend()
    with patch("dashboard.lib.settings.backends.keychain.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=44)
        assert backend.delete("providers", "missing") is False


def test_keychain_health_ok():
    backend = KeychainBackend()
    with patch("dashboard.lib.settings.backends.keychain.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='    "/Users/test/Library/Keychains/login.keychain-db"\n',
            stderr="",
        )
        health = backend.health()
    assert health.healthy is True
    assert health.backend_type == "keychain"


def test_keychain_health_fail():
    backend = KeychainBackend()
    with patch("dashboard.lib.settings.backends.keychain.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="no keychain")
        health = backend.health()
    assert health.healthy is False


def test_keychain_backend_type():
    backend = KeychainBackend()
    assert backend.backend_type == VaultBackendType.KEYCHAIN


def test_keychain_list_keys_parses_output():
    backend = KeychainBackend()
    dump_output = (
        '    0x00000007 <blob>="ostwin-mcp/providers/claude"\n'
        '    0x00000007 <blob>="ostwin-mcp/providers/openai"\n'
        '    0x00000007 <blob>="ostwin-mcp/channels/telegram"\n'
        '    0x00000007 <blob>="unrelated-service"\n'
    )
    with patch("dashboard.lib.settings.backends.keychain.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=dump_output)
        keys = backend.list_keys("providers")
    assert keys == ["claude", "openai"]


# ── SettingsVault: constructor with backend_type kwarg ────────────────

def test_vault_constructor_with_backend_type():
    """SettingsVault(backend_type=...) should create the right backend."""
    vault = SettingsVault(backend_type=VaultBackendType.ENCRYPTED_FILE)
    assert vault.backend_type == VaultBackendType.ENCRYPTED_FILE


def test_vault_constructor_backend_takes_priority():
    """Explicit backend arg takes priority over backend_type."""
    mock = _mock_backend()
    mock.backend_type = VaultBackendType.KEYCHAIN
    vault = SettingsVault(backend=mock, backend_type=VaultBackendType.ENCRYPTED_FILE)
    assert vault.backend_type == VaultBackendType.KEYCHAIN
