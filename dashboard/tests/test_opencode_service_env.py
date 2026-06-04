from pathlib import Path

from dashboard.lib import opencode_service


def test_build_child_env_forces_claude_code_disable(monkeypatch, tmp_path):
    monkeypatch.setattr(
        opencode_service,
        "_load_env_via_bash",
        lambda _project_dir: {"OPENCODE_DISABLE_CLAUDE_CODE": "0"},
    )
    monkeypatch.setattr(opencode_service, "_isolate_cloudsdk_fallback", lambda _env: None)

    env = opencode_service._build_child_env(Path(tmp_path))

    assert env["OPENCODE_DISABLE_CLAUDE_CODE"] == "1"
    assert env["OSTWIN_PROJECT_DIR"] == str(tmp_path)
