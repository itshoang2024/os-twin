"""Unit tests for installer/scripts/patch_opencode_permissions.py."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".agents" / "installer" / "scripts" / "patch_opencode_permissions.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("patch_opencode_permissions", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


def test_adds_read_and_external_directory_permissions(tmp_path):
    module = _load_module()
    config_path = tmp_path / "opencode.json"
    config_path.write_text('{"$schema": "https://opencode.ai/config.json"}\n')

    module.patch_permissions(str(config_path))

    permission = _read(config_path)["permission"]
    assert permission["read"] == {
        "*": "allow",
        "*.env": "allow",
        "*.env.*": "allow",
        "*.env.example": "allow",
    }
    assert permission["external_directory"] == {"*": "allow"}


def test_overrides_old_read_policy_and_preserves_unrelated_permissions(tmp_path):
    module = _load_module()
    config_path = tmp_path / "opencode.json"
    config_path.write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "permission": {
            "bash": "deny",
            "read": "deny",
            "external_directory": {"/tmp/*": "ask"},
        },
    }))

    module.patch_permissions(str(config_path))

    permission = _read(config_path)["permission"]
    assert permission["bash"] == "deny"
    assert permission["read"]["*"] == "allow"
    assert permission["read"]["*.env"] == "allow"
    assert permission["external_directory"]["/tmp/*"] == "ask"
    assert permission["external_directory"]["*"] == "allow"


def test_does_not_rewrite_when_permissions_are_current(tmp_path):
    module = _load_module()
    config_path = tmp_path / "opencode.json"
    config_path.write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "permission": {
            "read": {
                "*": "allow",
                "*.env": "allow",
                "*.env.*": "allow",
                "*.env.example": "allow",
            },
            "external_directory": {"*": "allow"},
        },
    }))
    old_time = 946684800
    os.utime(config_path, (old_time, old_time))
    before = config_path.stat().st_mtime_ns

    module.patch_permissions(str(config_path))

    assert config_path.stat().st_mtime_ns == before
