"""Integration tests for the FastMCP knowledge server (EPIC-006).

Validates:

1. ``mcp_server`` module imports cheaply (no kuzu / zvec / markitdown /
   anthropic loaded eagerly).
2. All 6 tools are registered on the FastMCP instance.
3. The ``/api/knowledge/mcp`` endpoint is mounted on the FastAPI app.
4. Each tool's body works when invoked directly (bypassing the JSON-RPC
   transport — separate concerns).
5. Error paths return structured ``{"error", "code"}`` dicts (no raises).
6. End-to-end lifecycle: create → import → poll → query → delete.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent / "fixtures" / "knowledge_sample"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_auth(monkeypatch: pytest.MonkeyPatch):
    """Force MCP into dev-mode (no auth) for the lifecycle tests."""
    monkeypatch.setenv("OSTWIN_DEV_MODE", "1")
    # Don't actually delete OSTWIN_API_KEY — conftest.py sets it for other
    # tests. Dev mode short-circuits the auth check anyway.
    yield


@pytest.fixture
def fresh_kb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated knowledge-base dir + reset the MCP service singleton."""
    kb = tmp_path / "kb"
    monkeypatch.setenv("OSTWIN_KNOWLEDGE_DIR", str(kb))

    # Service caches OSTWIN_KNOWLEDGE_DIR at construction time, so reset it.
    import dashboard.knowledge.mcp_server as srv

    srv._service = None
    yield kb
    srv._service = None


# ---------------------------------------------------------------------------
# 1) Lazy-import audit
# ---------------------------------------------------------------------------


def test_mcp_server_module_imports_cheaply() -> None:
    """Importing :mod:`dashboard.knowledge.mcp_server` must NOT pull heavy deps."""
    code = (
        "import sys\n"
        "from dashboard.knowledge.mcp_server import mcp\n"
        "heavy = ['kuzu', 'zvec', 'markitdown', 'anthropic', 'chromadb']\n"
        "loaded = [m for m in heavy if m in sys.modules]\n"
        "print('LOADED:' + ','.join(loaded))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path(__file__).resolve().parent.parent.parent),
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ},
    )
    assert proc.returncode == 0, proc.stderr
    last_line = proc.stdout.strip().splitlines()[-1]
    assert last_line.startswith("LOADED:")
    suffix = last_line[len("LOADED:"):]
    loaded = [m for m in suffix.split(",") if m]
    assert loaded == [], f"Heavy deps loaded eagerly: {loaded}"


# ---------------------------------------------------------------------------
# 2) Tool registration
# ---------------------------------------------------------------------------


def test_mcp_tools_registered() -> None:
    """All 7 tools are discoverable via :py:meth:`FastMCP.list_tools`."""
    import asyncio

    from dashboard.knowledge.mcp_server import mcp

    tools = asyncio.run(mcp.list_tools())
    tool_names = {t.name for t in tools}
    expected = {
        "knowledge_list_namespaces",
        "knowledge_create_namespace",
        "knowledge_delete_namespace",
        "knowledge_import_folder",
        "knowledge_get_import_status",
        "knowledge_query",
    }
    assert expected.issubset(tool_names), f"missing tools: {expected - tool_names}"


def test_mcp_tools_have_documented_descriptions() -> None:
    """Every tool's description is non-empty (becomes the LLM-facing prompt)."""
    import asyncio

    from dashboard.knowledge.mcp_server import mcp

    tools = asyncio.run(mcp.list_tools())
    for t in tools:
        assert t.description, f"tool {t.name!r} has empty description"
        # The brief mandates absolute-path documentation in
        # knowledge_import_folder. Verify the hint is in the description.
        if t.name == "knowledge_import_folder":
            assert "absolute" in t.description.lower()


def _captured_mcp_bearer_token() -> str | None:
    """Pull the MCP auth wrapper's expected ``Bearer ...`` token, if any.

    ``dashboard.api`` captures ``OSTWIN_API_KEY`` at import time into the
    module-level ``_expected_token`` and bakes it into the
    ``_MCPBearerAuth`` middleware. Tests can run with a different
    ``OSTWIN_API_KEY`` env var than what was captured at import (conftest
    autouse sets test-key per-test, but ``dashboard.api`` loads
    ``~/.ostwin/.env`` at module load time which may have a different
    key) — this helper returns the captured value so the handshake test
    can authenticate either way.

    Returns ``None`` if the MCP mount was attached without an auth wrapper
    (dev mode, or no key at import time).
    """
    import dashboard.api as api_mod

    return getattr(api_mod, "_expected_token", None)


# ---------------------------------------------------------------------------
# 3) Transport probe — the gate test for opencode interop
# ---------------------------------------------------------------------------


def test_mcp_endpoint_handshake_via_post() -> None:
    """POST a real MCP initialize request to /api/knowledge/mcp and confirm a JSON-RPC response.

    Doesn't require a real MCP client — uses ``TestClient`` directly so we
    test the raw HTTP transport. If this passes, opencode and other MCP
    clients can connect.

    Catches both:
      * D1 — FE catch-all shadowing the /api/knowledge/mcp mount (would
        return 200 SPA HTML on GET or 405 on POST).
      * D2 — FastMCP session manager task-group not initialised (would return
        500 with ``RuntimeError: Task group is not initialized``).
    """
    from dashboard.api import app

    # Use TestClient as a context manager so the FastAPI lifespan runs —
    # this is what kicks off the FastMCP session manager's task group via
    # the lifespan-forwarding hook in api.py. Without entering the
    # context, every POST to /api/knowledge/mcp/* returns 500 with
    # "Task group is not initialized".
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "qa-probe", "version": "0.1"},
        },
    }
    headers = {"accept": "application/json, text/event-stream"}
    # The MCP mount may be wrapped with bearer auth depending on whether
    # OSTWIN_DEV_MODE was set at app-import time (which can vary across
    # test orderings). The wrapper captures ``OSTWIN_API_KEY`` at module
    # import time — which may not match the current env var (conftest
    # autouse fixture sets test-key per-test, but ``dashboard.api``
    # imports ``~/.ostwin/.env`` at module load). Inspect the wrapper's
    # captured token directly so the test passes either way.
    captured_token = _captured_mcp_bearer_token()
    if captured_token:
        headers["Authorization"] = captured_token

    successful_path = None
    last_response = None
    with TestClient(app, raise_server_exceptions=False) as client:
        for path in (
            "/api/knowledge/mcp/",
            "/api/knowledge/mcp/mcp",
            "/api/knowledge/mcp",
        ):
            r = client.post(path, json=payload, headers=headers)
            last_response = r
            if r.status_code == 200 and ("jsonrpc" in r.text or "result" in r.text):
                successful_path = path
                break

    assert successful_path is not None, (
        f"No /api/knowledge/mcp path returned a JSON-RPC handshake. "
        f"Last status={last_response.status_code if last_response else 'n/a'}, "
        f"body={last_response.text[:500] if last_response else 'n/a'!r}"
    )
    # The response is either JSON or SSE format — parse loosely.
    body = last_response.text
    assert "jsonrpc" in body or "result" in body, (
        f"Unexpected response body from {successful_path}: {body[:500]}"
    )


def test_mcp_endpoint_not_shadowed_by_fe_catchall() -> None:
    """``GET /api/knowledge/mcp`` must NOT return SPA HTML.

    Direct regression test for D1. The FE catch-all must never serve
    ``index.html`` for the knowledge MCP mount path. The catch-all has a
    blanket ``api/`` prefix exception that already handles this — this
    test guards that the exception keeps working.

    A correct response is anything that is NOT an HTML SPA payload:
      * 405 / 406 / 404 from the MCP transport itself (acceptable — MCP
        rejects bare GET without proper headers)
      * Or a JSON / SSE body
    """
    from dashboard.api import app

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/knowledge/mcp")
    body = r.text
    # The bug signature is a 200 status with HTML body containing <!DOCTYPE
    # html> — that's the dashboard SPA index.html being served.
    is_spa_html = (
        r.status_code == 200
        and "<!DOCTYPE html>" in body
        and "_next" in body  # Next.js fingerprint
    )
    assert not is_spa_html, (
        f"GET /api/knowledge/mcp returned dashboard SPA HTML — FE catch-all "
        f"is shadowing the MCP mount (body[:200]={body[:200]!r})"
    )


def test_mcp_full_lifecycle_via_real_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real MCP client over streamable HTTP. The gate test for opencode interop.

    Spawns a real uvicorn subprocess and connects with the official
    ``streamablehttp_client`` from ``mcp[cli]``. If this passes, opencode's
    streamable-HTTP transport will work too.

    This test is somewhat slow (~5-10s) and can be flaky in CI environments
    where uvicorn boot is slow, so it's gated behind ``OSTWIN_RUN_SUBPROCESS_MCP_TEST=1``.
    The in-process ``test_mcp_endpoint_handshake_via_post`` above already
    proves the transport works end-to-end with TestClient.
    """
    if os.environ.get("OSTWIN_RUN_SUBPROCESS_MCP_TEST") != "1":
        pytest.skip(
            "Subprocess MCP integration test is opt-in; set "
            "OSTWIN_RUN_SUBPROCESS_MCP_TEST=1 to run."
        )

    import asyncio
    import socket

    monkeypatch.setenv("OSTWIN_DEV_MODE", "1")
    monkeypatch.delenv("OSTWIN_API_KEY", raising=False)
    monkeypatch.setenv("OSTWIN_KNOWLEDGE_DIR", str(tmp_path))

    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()

    project_root = str(Path(__file__).resolve().parent.parent.parent)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "dashboard.api:app",
            "--port",
            str(port),
            "--log-level",
            "error",
        ],
        cwd=project_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env={
            **os.environ,
            "OSTWIN_DEV_MODE": "1",
            "OSTWIN_KNOWLEDGE_DIR": str(tmp_path),
        },
    )

    async def _run_client():
        from mcp import ClientSession  # noqa: WPS433
        from mcp.client.streamable_http import streamablehttp_client  # noqa: WPS433

        url = f"http://127.0.0.1:{port}/api/knowledge/mcp/"
        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                return names

    try:
        # Wait for the server to be ready.
        import urllib.request
        import urllib.error

        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/status", timeout=1
                    ) as resp:
                    if resp.status < 500:
                        break
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                pass
            time.sleep(0.3)
        else:
            stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
            pytest.fail(f"uvicorn did not start within 30s: {stderr[:500]}")

        names = asyncio.run(_run_client())
        expected_tools = {
            "knowledge_list_namespaces",
            "knowledge_create_namespace",
            "knowledge_delete_namespace",
            "knowledge_import_folder",
            "knowledge_get_import_status",
            "knowledge_query",
        }
        assert expected_tools.issubset(names), f"missing tools: {expected_tools - names}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------------------
# 4) Direct tool invocation (validates tool body without MCP transport)
# ---------------------------------------------------------------------------


def test_invoke_list_namespaces_directly(fresh_kb) -> None:
    """Direct Python call of the decorated tool returns a well-formed dict."""
    import asyncio

    from dashboard.knowledge.mcp_server import knowledge_list_namespaces

    result = asyncio.run(knowledge_list_namespaces())
    assert isinstance(result, dict)
    # Either {namespaces: []} or {error, code} — both are well-formed
    # responses (the tool body never raises).
    assert "namespaces" in result or "error" in result


def test_invoke_create_then_list(fresh_kb) -> None:
    """Create a namespace then list it back."""
    import asyncio

    from dashboard.knowledge.mcp_server import (
        knowledge_create_namespace,
        knowledge_list_namespaces,
    )

    r = asyncio.run(knowledge_create_namespace("direct-create-test"))
    assert r.get("name") == "direct-create-test", f"unexpected: {r}"

    listing = asyncio.run(knowledge_list_namespaces())
    names = [n["name"] for n in listing.get("namespaces", [])]
    assert "direct-create-test" in names


# ---------------------------------------------------------------------------
# 5) Error paths — every tool returns structured errors, never raises
# ---------------------------------------------------------------------------


def test_create_namespace_invalid_name_returns_structured_error(fresh_kb) -> None:
    import asyncio

    from dashboard.knowledge.mcp_server import knowledge_create_namespace

    result = asyncio.run(knowledge_create_namespace("Bad Name!"))
    assert "error" in result
    assert result["code"] == "INVALID_NAMESPACE_ID"


def test_create_namespace_duplicate_returns_structured_error(fresh_kb) -> None:
    import asyncio

    from dashboard.knowledge.mcp_server import knowledge_create_namespace

    asyncio.run(knowledge_create_namespace("dup-test"))
    result = asyncio.run(knowledge_create_namespace("dup-test"))
    assert "error" in result
    assert result["code"] == "NAMESPACE_EXISTS"


def test_import_folder_rejects_relative_path(fresh_kb) -> None:
    import asyncio

    from dashboard.knowledge.mcp_server import knowledge_import_folder

    result = asyncio.run(knowledge_import_folder("test-ns", "relative/path"))
    assert "error" in result
    assert result["code"] == "INVALID_FOLDER_PATH"


def test_import_folder_rejects_missing_folder(fresh_kb) -> None:
    import asyncio

    from dashboard.knowledge.mcp_server import knowledge_import_folder

    result = asyncio.run(knowledge_import_folder("test-ns", "/tmp/nonexistent-12345-mcp-test"))
    assert "error" in result
    assert result["code"] == "FOLDER_NOT_FOUND"


def test_import_folder_rejects_file_instead_of_dir(fresh_kb, tmp_path: Path) -> None:
    import asyncio

    from dashboard.knowledge.mcp_server import knowledge_import_folder

    f = tmp_path / "not-a-dir.txt"
    f.write_text("hi")
    result = asyncio.run(knowledge_import_folder("test-ns", str(f)))
    assert "error" in result
    assert result["code"] == "NOT_A_DIRECTORY"


def test_query_unknown_namespace_returns_structured_error(fresh_kb) -> None:
    import asyncio

    from dashboard.knowledge.mcp_server import knowledge_query

    result = asyncio.run(knowledge_query("never-created-mcp-12345", "x"))
    assert "error" in result
    assert result["code"] == "NAMESPACE_NOT_FOUND"


def test_query_invalid_mode_returns_structured_error(fresh_kb) -> None:
    import asyncio

    from dashboard.knowledge.mcp_server import (
        knowledge_create_namespace,
        knowledge_query,
    )

    asyncio.run(knowledge_create_namespace("mode-test"))
    result = asyncio.run(knowledge_query("mode-test", "x", mode="bogus"))
    assert "error" in result
    assert result["code"] == "BAD_REQUEST"


def test_get_status_unknown_job_returns_structured_error(fresh_kb) -> None:
    import asyncio

    from dashboard.knowledge.mcp_server import knowledge_get_import_status

    result = asyncio.run(knowledge_get_import_status("any-ns", "fake-job-uuid"))
    assert "error" in result
    assert result["code"] == "JOB_NOT_FOUND"




def test_delete_nonexistent_namespace_returns_false(fresh_kb) -> None:
    """Deleting a missing namespace returns ``{deleted: False}`` (NOT an error)."""
    import asyncio

    from dashboard.knowledge.mcp_server import knowledge_delete_namespace

    result = asyncio.run(knowledge_delete_namespace("never-existed-12345"))
    assert result == {"deleted": False}


# ---------------------------------------------------------------------------
# 6) End-to-end lifecycle (real ingest)
# ---------------------------------------------------------------------------


def test_full_import_query_lifecycle(fresh_kb) -> None:
    """End-to-end: create → import (real fixture folder) → poll → query → delete."""
    import asyncio

    from dashboard.knowledge.mcp_server import (
        knowledge_create_namespace,
        knowledge_delete_namespace,
        knowledge_get_import_status,
        knowledge_import_folder,
        knowledge_query,
    )

    ns = "lifecycle-test"
    r = asyncio.run(knowledge_create_namespace(ns))
    assert r.get("name") == ns, f"unexpected: {r}"

    r = asyncio.run(knowledge_import_folder(ns, str(FIXTURES.resolve())))
    assert r.get("job_id"), f"unexpected: {r}"
    job_id = r["job_id"]
    assert r.get("status") == "submitted"

    # Poll for completion (real ingest with real zvec).
    deadline = time.time() + 90
    status = None
    while time.time() < deadline:
        status = asyncio.run(knowledge_get_import_status(ns, job_id))
        if status.get("state") in ("completed", "failed", "cancelled", "interrupted"):
            break
        time.sleep(0.3)
    assert status is not None
    assert status.get("state") == "completed", f"job didn't finish cleanly: {status}"

    # Query the freshly-ingested namespace.
    qr = asyncio.run(knowledge_query(ns, "test", mode="raw", top_k=3))
    assert "chunks" in qr, f"unexpected: {qr}"
    assert isinstance(qr["chunks"], list)

    # Cleanup.
    rd = asyncio.run(knowledge_delete_namespace(ns))
    assert rd.get("deleted") is True


def test_summarized_mode_graceful_without_anthropic_key(
    fresh_kb, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``mode="summarized"`` without ANTHROPIC_API_KEY → warnings, no crash."""
    import asyncio

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from dashboard.knowledge.mcp_server import (
        knowledge_create_namespace,
        knowledge_query,
    )

    ns = "summ-graceful"
    asyncio.run(knowledge_create_namespace(ns))
    qr = asyncio.run(knowledge_query(ns, "anything", mode="summarized", top_k=3))
    # Empty namespace + no LLM → still a valid result, never an error.
    assert "chunks" in qr, f"unexpected: {qr}"
    # Result includes warnings array; either llm_unavailable or empty-ns-related warnings.
    assert "warnings" in qr
