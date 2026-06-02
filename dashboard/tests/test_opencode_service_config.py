import json

from dashboard.lib import opencode_service


def test_merge_managed_opencode_config_preserves_server_agent(tmp_path, monkeypatch):
    managed_config = tmp_path / ".opencode" / "opencode.json"
    managed_config.parent.mkdir(parents=True)
    managed_config.write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "mcp": {"memory": {"type": "local", "command": ["python", "server.py"]}},
        "tools": {"github*": False},
        "provider": {
            "gemini": {
                "options": {"apiKey": "key", "baseURL": "https://example.test"},
                "models": {},
            }
        },
        "agent": {
            "engineer": {"tools": {"memory*": True}},
            "ostwin": {"model": "managed/model"},
        },
        "permission": {
            "read": {"*": "allow"},
            "external_directory": {"*": "allow"},
        },
    }))

    server_dir = tmp_path / "opencode_server"
    server_dir.mkdir()
    runtime_config = server_dir / "opencode.json"
    runtime_config.write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "agent": {
            "ostwin": {
                "model": "local/model",
                "tools": {"ostwin_*": True},
            },
        },
        "permission": {
            "read": "deny",
            "ostwin_*": "allow",
        },
    }))

    monkeypatch.setattr(opencode_service, "MANAGED_OPENCODE_CONFIG", managed_config)

    opencode_service._merge_managed_opencode_config(server_dir)

    merged = json.loads(runtime_config.read_text())
    assert merged["mcp"] == {"memory": {"type": "local", "command": ["python", "server.py"]}}
    assert merged["tools"] == {"github*": False}
    assert "gemini" in merged["provider"]
    assert merged["agent"]["engineer"] == {"tools": {"memory*": True}}
    assert merged["agent"]["ostwin"]["model"] == "local/model"
    assert merged["agent"]["ostwin"]["tools"] == {"ostwin_*": True}
    assert merged["permission"]["read"] == "deny"
    assert merged["permission"]["external_directory"] == {"*": "allow"}
