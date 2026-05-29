import pytest

from dashboard.routes import memory_mcp


@pytest.fixture(autouse=True)
def clear_session_plan_ids():
    memory_mcp._session_plan_ids.clear()
    yield
    memory_mcp._session_plan_ids.clear()


def test_resolve_persist_dir_uses_memory_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_mcp, "MEMORY_BASE_DIR", tmp_path)

    persist_dir = memory_mcp._resolve_persist_dir("4ae61a301661")

    assert persist_dir == str(tmp_path / "memory-4ae61a301661")
    assert (tmp_path / "memory-4ae61a301661").is_dir()


def test_resolve_persist_dir_keeps_existing_legacy_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_mcp, "MEMORY_BASE_DIR", tmp_path)
    legacy = tmp_path / "4ae61a301661"
    legacy.mkdir()

    persist_dir = memory_mcp._resolve_persist_dir("4ae61a301661")

    assert persist_dir == str(legacy)


def test_resolve_persist_dir_accepts_memory_prefixed_plan_id(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_mcp, "MEMORY_BASE_DIR", tmp_path)

    persist_dir = memory_mcp._resolve_persist_dir("memory-4ae61a301661")

    assert persist_dir == str(tmp_path / "memory-4ae61a301661")
    assert (tmp_path / "memory-4ae61a301661").is_dir()


def test_resolve_persist_dir_prefers_current_dir_when_both_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_mcp, "MEMORY_BASE_DIR", tmp_path)
    legacy = tmp_path / "4ae61a301661"
    current = tmp_path / "memory-4ae61a301661"
    legacy.mkdir()
    current.mkdir()

    persist_dir = memory_mcp._resolve_persist_dir("4ae61a301661")

    assert persist_dir == str(current)


def test_get_memory_for_plan_routes_to_prefixed_persist_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_mcp, "MEMORY_BASE_DIR", tmp_path)
    seen_dirs = []
    system = object()

    class FakeSlot:
        log_handler = None

        def __init__(self):
            self.system = system

    class FakePool:
        def get_or_create(self, persist_dir):
            seen_dirs.append(persist_dir)
            return FakeSlot()

        def touch(self, persist_dir):
            seen_dirs.append(f"touch:{persist_dir}")

    monkeypatch.setattr(memory_mcp, "_get_pool", lambda: FakePool())
    token = memory_mcp._plan_id_ctx.set("4ae61a301661")
    try:
        resolved_system = memory_mcp._get_memory_for_plan()
    finally:
        memory_mcp._plan_id_ctx.reset(token)

    expected = str(tmp_path / "memory-4ae61a301661")
    assert resolved_system is system
    assert seen_dirs == [expected, f"touch:{expected}"]


@pytest.mark.asyncio
async def test_plan_id_binding_survives_mcp_session_requests():
    seen_plan_ids = []

    async def inner(scope, receive, send):
        seen_plan_ids.append(memory_mcp._plan_id_ctx.get())
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"mcp-session-id", b"session-1")],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    app = memory_mcp._PlanIdInjectingApp(inner)

    await app(
        {
            "type": "http",
            "method": "POST",
            "query_string": b"plan_id=4ae61a301661",
            "headers": [],
        },
        _empty_receive,
        _ignore_send,
    )

    await app(
        {
            "type": "http",
            "method": "POST",
            "query_string": b"",
            "headers": [(b"mcp-session-id", b"session-1")],
        },
        _empty_receive,
        _ignore_send,
    )

    assert seen_plan_ids == ["4ae61a301661", "4ae61a301661"]


@pytest.mark.asyncio
async def test_plan_id_can_be_supplied_by_header_without_query_string():
    seen_plan_ids = []

    async def inner(scope, receive, send):
        seen_plan_ids.append(memory_mcp._plan_id_ctx.get())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app = memory_mcp._PlanIdInjectingApp(inner)

    await app(
        {
            "type": "http",
            "method": "POST",
            "query_string": b"",
            "headers": [(b"x-ostwin-plan-id", b"4ae61a301661")],
        },
        _empty_receive,
        _ignore_send,
    )

    assert seen_plan_ids == ["4ae61a301661"]


@pytest.mark.asyncio
async def test_query_plan_id_overrides_stale_session_binding():
    memory_mcp._session_plan_ids["session-1"] = "stale-plan"
    seen_plan_ids = []

    async def inner(scope, receive, send):
        seen_plan_ids.append(memory_mcp._plan_id_ctx.get())
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"mcp-session-id", b"session-1")],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    app = memory_mcp._PlanIdInjectingApp(inner)

    await app(
        {
            "type": "http",
            "method": "POST",
            "query_string": b"plan_id=4ae61a301661",
            "headers": [(b"mcp-session-id", b"session-1")],
        },
        _empty_receive,
        _ignore_send,
    )

    assert seen_plan_ids == ["4ae61a301661"]
    assert memory_mcp._session_plan_ids["session-1"] == "4ae61a301661"


@pytest.mark.asyncio
async def test_delete_request_clears_session_plan_binding():
    memory_mcp._session_plan_ids["session-1"] = "4ae61a301661"
    seen_plan_ids = []

    async def inner(scope, receive, send):
        seen_plan_ids.append(memory_mcp._plan_id_ctx.get())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app = memory_mcp._PlanIdInjectingApp(inner)

    await app(
        {
            "type": "http",
            "method": "DELETE",
            "query_string": b"",
            "headers": [(b"mcp-session-id", b"session-1")],
        },
        _empty_receive,
        _ignore_send,
    )

    assert seen_plan_ids == ["4ae61a301661"]
    assert "session-1" not in memory_mcp._session_plan_ids


def test_header_value_is_case_insensitive():
    headers = [(b"MCP-Session-ID", b"session-1")]

    assert memory_mcp._header_value(headers, "mcp-session-id") == "session-1"


async def _empty_receive():
    return {"type": "http.request", "body": b"", "more_body": False}


async def _ignore_send(_message):
    return None
