from pathlib import Path
import json

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


def test_build_child_env_injects_github_copilot_token(monkeypatch, tmp_path):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps({"github-copilot": {"type": "oauth", "refresh": "gho_secret"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(opencode_service, "OPENCODE_AUTH_JSON", auth_path)
    monkeypatch.setattr(opencode_service, "_load_env_via_bash", lambda _project_dir: {})
    monkeypatch.setattr(opencode_service, "_isolate_cloudsdk_fallback", lambda _env: None)

    env = opencode_service._build_child_env(Path(tmp_path))

    assert env["GITHUB_COPILOT_TOKEN"] == "gho_secret"


def test_build_child_env_preserves_existing_github_copilot_token(monkeypatch, tmp_path):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps({"github-copilot": {"type": "oauth", "refresh": "gho_saved"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(opencode_service, "OPENCODE_AUTH_JSON", auth_path)
    monkeypatch.setattr(
        opencode_service,
        "_load_env_via_bash",
        lambda _project_dir: {"GITHUB_COPILOT_TOKEN": "already-set"},
    )
    monkeypatch.setattr(opencode_service, "_isolate_cloudsdk_fallback", lambda _env: None)

    env = opencode_service._build_child_env(Path(tmp_path))

    assert env["GITHUB_COPILOT_TOKEN"] == "already-set"
