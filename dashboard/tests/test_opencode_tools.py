"""Tests for generated OpenCode tool and agent definitions."""

import json

from dashboard import opencode_tools


def test_ostwin_config_allows_external_directories():
    config = opencode_tools._opencode_config()

    assert config["permission"]["external_directory"] == {"*": "allow"}
    assert config["agent"]["ostwin"]["tools"]["read"] is False


def test_worker_agent_allows_external_directory_reads():
    body = opencode_tools._agent_ostwin_worker("google/gemini-test")

    assert "external_directory: allow" in body
    assert "read: allow" in body
    assert "write: allow" in body


def test_generated_helpers_bound_worker_wait_time():
    helpers = opencode_tools._api_helpers()

    assert "OSTWIN_WORKER_TIMEOUT_SECONDS" in helpers
    assert "--max-time" in helpers
    assert "Worker session" in helpers
    assert 'ocFetch("/session", "POST", { parentID: ctx.sessionID }, "15")' in helpers
    assert "finished without text" in helpers


def test_generate_all_writes_permission_and_timeout_contract(tmp_path):
    written = opencode_tools.generate_all(
        project_root=tmp_path,
        dashboard_port="3366",
        model="google/gemini-test",
    )

    written_paths = {p.relative_to(tmp_path).as_posix() for p in written}
    assert "opencode.json" in written_paths
    assert ".opencode/agent/ostwin-worker.md" in written_paths
    assert ".opencode/tools/ostwin_refine_plan.ts" in written_paths

    config = json.loads((tmp_path / "opencode.json").read_text())
    assert config["permission"]["external_directory"] == {"*": "allow"}
    assert config["permission"]["read"] == "deny"

    worker = (tmp_path / ".opencode/agent/ostwin-worker.md").read_text()
    assert "model: google/gemini-test" in worker
    assert "external_directory: allow" in worker

    refine_tool = (tmp_path / ".opencode/tools/ostwin_refine_plan.ts").read_text()
    assert "OSTWIN_WORKER_TIMEOUT_SECONDS" in refine_tool
    assert "--max-time" in refine_tool
    assert "curl -sf" not in refine_tool
