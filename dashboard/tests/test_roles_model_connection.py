import asyncio
import shutil
import subprocess


def test_model_connection_injects_copilot_token(monkeypatch):
    from dashboard.lib.settings import github_copilot_auth
    from dashboard.routes.roles import test_model_connection

    captured = {}

    def fake_run(cmd, capture_output, text, timeout, env):
        captured["cmd"] = cmd
        captured["env"] = env
        return subprocess.CompletedProcess(cmd, 0, stdout="YES\n", stderr="")

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/opencode")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(github_copilot_auth, "get_saved_github_copilot_token", lambda: "gho_test")

    result = asyncio.run(
        test_model_connection("github-copilot/gpt-4o-2024-08-06", user={})
    )

    assert result["status"] == "ok"
    assert captured["cmd"] == [
        "/usr/bin/opencode",
        "run",
        "just say YES",
        "--model",
        "github-copilot/gpt-4o-2024-08-06",
        "--dir",
        "/tmp",
    ]
    assert captured["env"]["GITHUB_COPILOT_TOKEN"] == "gho_test"
    assert captured["env"]["OPENCODE_DISABLE_CLAUDE_CODE"] == "1"
