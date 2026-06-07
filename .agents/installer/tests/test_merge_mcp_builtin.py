#!/usr/bin/env python3
"""Tests for merge_mcp_builtin.py."""

import json
import tempfile
from pathlib import Path

import importlib.util


BUILTIN_BROWSER_NAME = "chrome-devtools"
NATIVE_BROWSER_COMMAND = ["obscura", "mcp"]


def _load_merge_module():
    """Load merge_mcp_builtin.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "merge_mcp_builtin",
        Path(__file__).parent.parent / "scripts" / "merge_mcp_builtin.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


class TestMergeMcpBuiltin:
    """Tests for merge_builtin function."""

    def test_adds_chrome_devtools_from_builtin(self):
        """Existing config gets chrome-devtools added from builtin."""
        module = _load_merge_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            builtin_path = Path(tmpdir) / "mcp-builtin.json"

            existing_config = {
                "mcp": {
                    "playwright": {
                        "type": "local",
                        "command": ["npx", "-y", "@playwright/mcp@latest"],
                        "environment": {}
                    }
                }
            }

            builtin_config = {
                "mcp": {
                    "chrome-devtools": {
                        "type": "local",
                        "command": NATIVE_BROWSER_COMMAND,
                        "environment": {"PATH": "{env:PATH}"}
                    },
                    "playwright": {
                        "type": "local",
                        "command": ["npx", "-y", "@playwright/mcp@latest"],
                        "environment": {"PATH": "{env:PATH}"}
                    }
                }
            }

            _write_json(config_path, existing_config)
            _write_json(builtin_path, builtin_config)

            module.merge_builtin(str(config_path), str(builtin_path))

            result = _read_json(config_path)

            assert "chrome-devtools" in result["mcp"]
            assert result["mcp"]["chrome-devtools"]["type"] == "local"

    def test_keeps_playwright(self):
        """Existing config keeps playwright."""
        module = _load_merge_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            builtin_path = Path(tmpdir) / "mcp-builtin.json"

            existing_config = {
                "mcp": {
                    "playwright": {
                        "type": "local",
                        "command": ["npx", "-y", "@playwright/mcp@latest"],
                        "environment": {}
                    }
                }
            }

            builtin_config = {
                "mcp": {
                    "playwright": {
                        "type": "local",
                        "command": ["npx", "-y", "@playwright/mcp@latest"],
                        "environment": {"PATH": "{env:PATH}"}
                    }
                }
            }

            _write_json(config_path, existing_config)
            _write_json(builtin_path, builtin_config)

            module.merge_builtin(str(config_path), str(builtin_path))

            result = _read_json(config_path)

            assert "playwright" in result["mcp"]

    def test_keeps_user_custom_server(self):
        """Existing config keeps unrelated user custom server."""
        module = _load_merge_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            builtin_path = Path(tmpdir) / "mcp-builtin.json"
            custom_server_path = str(Path(tmpdir) / "my-server.py")

            existing_config = {
                "mcp": {
                    "my-custom-server": {
                        "type": "local",
                        "command": ["python", custom_server_path],
                        "environment": {"MY_VAR": "secret"}
                    }
                }
            }

            builtin_config = {
                "mcp": {
                    "chrome-devtools": {
                        "type": "local",
                        "command": NATIVE_BROWSER_COMMAND,
                        "environment": {"PATH": "{env:PATH}"}
                    }
                }
            }

            _write_json(config_path, existing_config)
            _write_json(builtin_path, builtin_config)

            module.merge_builtin(str(config_path), str(builtin_path))

            result = _read_json(config_path)

            assert "my-custom-server" in result["mcp"]
            assert result["mcp"]["my-custom-server"]["command"] == ["python", custom_server_path]
            assert result["mcp"]["my-custom-server"]["environment"]["MY_VAR"] == "secret"

    def test_keeps_existing_server_with_builtin_name(self):
        """Existing servers are kept when they already use a builtin name."""
        module = _load_merge_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            builtin_path = Path(tmpdir) / "mcp-builtin.json"
            custom_tool_path = str(Path(tmpdir) / "my-chrome-tool")

            existing_config = {
                "mcp": {
                    BUILTIN_BROWSER_NAME: {
                        "type": "local",
                        "command": [custom_tool_path],
                        "environment": {"CUSTOM": "value"}
                    }
                }
            }

            builtin_config = {
                "mcp": {
                    "chrome-devtools": {
                        "type": "local",
                        "command": NATIVE_BROWSER_COMMAND,
                        "environment": {"PATH": "{env:PATH}"}
                    }
                }
            }

            _write_json(config_path, existing_config)
            _write_json(builtin_path, builtin_config)

            module.merge_builtin(str(config_path), str(builtin_path))

            result = _read_json(config_path)

            assert BUILTIN_BROWSER_NAME in result["mcp"]
            assert result["mcp"][BUILTIN_BROWSER_NAME]["command"] == [custom_tool_path]
            assert result["mcp"][BUILTIN_BROWSER_NAME]["environment"]["CUSTOM"] == "value"

    def test_updates_empty_environment_from_builtin(self):
        """Existing server with empty environment gets updated from builtin."""
        module = _load_merge_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            builtin_path = Path(tmpdir) / "mcp-builtin.json"

            existing_config = {
                "mcp": {
                    "playwright": {
                        "type": "local",
                        "command": ["npx", "-y", "@playwright/mcp@latest"],
                        "environment": {}
                    }
                }
            }

            builtin_config = {
                "mcp": {
                    "playwright": {
                        "type": "local",
                        "command": ["npx", "-y", "@playwright/mcp@latest"],
                        "environment": {"PATH": "{env:PATH}"}
                    }
                }
            }

            _write_json(config_path, existing_config)
            _write_json(builtin_path, builtin_config)

            module.merge_builtin(str(config_path), str(builtin_path))

            result = _read_json(config_path)

            assert result["mcp"]["playwright"]["environment"] == {"PATH": "{env:PATH}"}

    def test_adds_and_updates_in_one_run(self):
        """Adds missing builtins and updates empty environments in single merge."""
        module = _load_merge_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            builtin_path = Path(tmpdir) / "mcp-builtin.json"

            existing_config = {
                "mcp": {
                    "playwright": {
                        "type": "local",
                        "command": ["npx", "-y", "@playwright/mcp@latest"],
                        "environment": {}
                    }
                }
            }

            builtin_config = {
                "mcp": {
                    "chrome-devtools": {
                        "type": "local",
                        "command": NATIVE_BROWSER_COMMAND,
                        "environment": {"PATH": "{env:PATH}"}
                    },
                    "playwright": {
                        "type": "local",
                        "command": ["npx", "-y", "@playwright/mcp@latest"],
                        "environment": {"PATH": "{env:PATH}"}
                    }
                }
            }

            _write_json(config_path, existing_config)
            _write_json(builtin_path, builtin_config)

            module.merge_builtin(str(config_path), str(builtin_path))

            result = _read_json(config_path)

            assert "chrome-devtools" in result["mcp"]
            assert result["mcp"]["chrome-devtools"]["command"] == NATIVE_BROWSER_COMMAND
            assert result["mcp"]["playwright"]["environment"] == {"PATH": "{env:PATH}"}


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
