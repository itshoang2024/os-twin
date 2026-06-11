"""Tests for generated OpenCode tool and agent definitions."""

import json

from dashboard import opencode_tools


def test_ostwin_config_allows_external_directories():
    config = opencode_tools._opencode_config()

    assert config["model"] == "opencode/big-pickle"
    assert config["permission"]["external_directory"] == {"*": "allow"}
    assert config["agent"]["ostwin"]["tools"]["read"] is False
    assert "model" not in config["agent"]["ostwin"]


def test_worker_agent_allows_external_directory_reads():
    body = opencode_tools._agent_ostwin_worker("google/gemini-test")

    assert "external_directory: allow" in body
    assert "read: allow" in body
    assert "write: allow" in body
    assert "model:" not in body


def test_generated_helpers_bound_worker_wait_time():
    helpers = opencode_tools._api_helpers()

    assert "OSTWIN_WORKER_TIMEOUT_SECONDS" in helpers
    assert "--max-time" in helpers
    assert "Worker session" in helpers
    assert 'ocFetch("/session", "POST", { parentID: ctx.sessionID }, "15")' in helpers
    assert 'const DEFAULT_OPENCODE_MODEL = "opencode/big-pickle"' in helpers
    assert "model: ocModelParam()" in helpers
    assert "finished without text" in helpers


def test_generated_helpers_load_ostwin_api_key_from_env_files():
    helpers = opencode_tools._api_helpers()

    assert 'readFileSync(path, "utf8")' in helpers
    assert 'envFileValue(readFileSync(path, "utf8"), "OSTWIN_API_KEY")' in helpers
    assert 'join(ostwinHome, ".env")' in helpers
    assert 'join(ostwinHome, ".env.sh")' in helpers
    assert "function apiKeyCandidates" in helpers
    assert "Dashboard rejected the available Ostwin API key(s)" in helpers


def test_get_memories_tool_uses_shared_dashboard_auth_helper():
    memories_tool = opencode_tools._tool_get_memories()

    assert "api(`/api/amem/${args.plan_id}${path}`)" in memories_tool
    assert "X-API-Key" not in memories_tool


def test_create_plan_tool_returns_dashboard_route_metadata():
    create_tool = opencode_tools._tool_create_plan()

    assert 'const planUrl = createRes.url || `/plans/${planId}`' in create_tool
    assert '"url":${JSON.stringify(planUrl)}' in create_tool


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
    assert config["model"] == "google/gemini-test"
    assert config["permission"]["external_directory"] == {"*": "allow"}
    assert config["permission"]["read"] == "deny"
    assert "model" not in config["agent"]["ostwin"]

    worker = (tmp_path / ".opencode/agent/ostwin-worker.md").read_text()
    assert "model:" not in worker
    assert "external_directory: allow" in worker

    refine_tool = (tmp_path / ".opencode/tools/ostwin_refine_plan.ts").read_text()
    assert "OSTWIN_WORKER_TIMEOUT_SECONDS" in refine_tool
    assert 'const DEFAULT_OPENCODE_MODEL = "google/gemini-test"' in refine_tool
    assert "--max-time" in refine_tool
    assert "curl -sf" not in refine_tool
