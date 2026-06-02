import json
from pathlib import Path

import pytest

from dashboard.routes import mcp
from dashboard.routes.mcp import McpServerConfig


def test_http_server_normalizes_bare_host():
    config = McpServerConfig(
        name="remote-server",
        type="http",
        httpUrl="example.com/mcp",
    )

    config.normalize()

    assert config.type == "remote"
    assert config.url == "https://example.com/mcp"


def test_http_server_keeps_explicit_scheme():
    config = McpServerConfig(
        name="remote-server",
        type="http",
        httpUrl="http://localhost:8080/sse",
    )

    config.normalize()

    assert config.url == "http://localhost:8080/sse"


def test_http_server_uses_http_for_bare_localhost():
    config = McpServerConfig(
        name="local-server",
        type="http",
        httpUrl="localhost:8080/sse",
    )

    config.normalize()

    assert config.url == "http://localhost:8080/sse"


def test_http_server_uses_http_for_bare_loopback_ip():
    config = McpServerConfig(
        name="local-server",
        type="http",
        httpUrl="127.0.0.1:8080/mcp",
    )

    config.normalize()

    assert config.url == "http://127.0.0.1:8080/mcp"


@pytest.mark.asyncio
async def test_add_server_syncs_managed_opencode_config(tmp_path, monkeypatch):
    home_config = tmp_path / ".agents" / "mcp" / "config.json"
    managed_config = tmp_path / ".opencode" / "opencode.json"

    def fake_sync(config_path, output_path, roles_dir):
        data = json.loads(Path(config_path).read_text())
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"mcp": data["mcp"]}, indent=2) + "\n")

    monkeypatch.setattr(mcp, "OSTWIN_HOME", tmp_path)
    monkeypatch.setattr(mcp, "HOME_CONFIG_FILE", home_config)
    monkeypatch.setattr(mcp, "sync_opencode_mcp_config", fake_sync)

    result = await mcp.add_mcp_server(
        McpServerConfig(name="remote-server", type="http", httpUrl="example.com/mcp"),
        user={"user_id": "test"},
    )

    assert result["opencode_path"] == str(managed_config)
    assert json.loads(home_config.read_text())["mcp"]["remote-server"]["url"] == "https://example.com/mcp"
    assert json.loads(managed_config.read_text())["mcp"]["remote-server"]["url"] == "https://example.com/mcp"


@pytest.mark.asyncio
async def test_remove_server_syncs_managed_opencode_config(tmp_path, monkeypatch):
    home_config = tmp_path / ".agents" / "mcp" / "config.json"
    home_config.parent.mkdir(parents=True)
    home_config.write_text(json.dumps({
        "mcp": {
            "remote-server": {"type": "remote", "url": "https://example.com/mcp"},
            "keep-server": {"type": "remote", "url": "https://keep.example.com/mcp"},
        }
    }))
    managed_config = tmp_path / ".opencode" / "opencode.json"

    def fake_sync(config_path, output_path, roles_dir):
        data = json.loads(Path(config_path).read_text())
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"mcp": data["mcp"]}, indent=2) + "\n")

    monkeypatch.setattr(mcp, "OSTWIN_HOME", tmp_path)
    monkeypatch.setattr(mcp, "HOME_CONFIG_FILE", home_config)
    monkeypatch.setattr(mcp, "sync_opencode_mcp_config", fake_sync)

    result = await mcp.remove_mcp_server("remote-server", user={"user_id": "test"})

    assert result["opencode_path"] == str(managed_config)
    assert "remote-server" not in json.loads(home_config.read_text())["mcp"]
    managed_mcp = json.loads(managed_config.read_text())["mcp"]
    assert "remote-server" not in managed_mcp
    assert "keep-server" in managed_mcp
