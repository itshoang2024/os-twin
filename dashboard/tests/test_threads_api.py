import pytest
from fastapi.testclient import TestClient
from dashboard.api import app
import dashboard.global_state as global_state
from dashboard.planning_thread_store import PlanningThreadStore
from unittest.mock import MagicMock, patch, AsyncMock

@pytest.fixture
def client(tmp_path):
    store = PlanningThreadStore(base_dir=tmp_path)
    global_state.planning_store = store
    
    # Mock authentication and startup to avoid DB lock issues
    from dashboard.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"sub": "test_user"}
    
    with patch("dashboard.api.startup_all", new_callable=AsyncMock):
        with TestClient(app) as c:
            yield c
        
    app.dependency_overrides.clear()

def test_create_thread(client):
    response = client.post("/api/plans/threads", json={"message": "Build a todo app"})
    assert response.status_code == 201
    data = response.json()
    assert "thread_id" in data
    assert data["thread_id"].startswith("pt-")
    assert data["title"] == "New Idea"

def test_list_threads(client):
    # Create thread first
    res = client.post("/api/plans/threads", json={"message": "Build a todo app"})
    thread_id = res.json()["thread_id"]
    
    response = client.get("/api/plans/threads")
    assert response.status_code == 200
    data = response.json()
    assert "threads" in data
    assert len(data["threads"]) == 1
    assert data["threads"][0]["id"] == thread_id

def test_get_thread(client):
    res = client.post("/api/plans/threads", json={"message": "Build a todo app"})
    thread_id = res.json()["thread_id"]
    
    response = client.get(f"/api/plans/threads/{thread_id}")
    assert response.status_code == 200
    data = response.json()
    assert "thread" in data
    assert "messages" in data
    assert len(data["messages"]) == 1
    assert data["messages"][0]["content"] == "Build a todo app"

def test_get_thread_not_found(client):
    response = client.get("/api/plans/threads/pt-invalid")
    assert response.status_code == 404

def test_promote_thread_not_found(client):
    response = client.post("/api/plans/threads/pt-invalid/promote", json={})
    assert response.status_code == 404

@patch("dashboard.routes.threads.synthesize_plan_from_thread", new_callable=AsyncMock)
def test_promote_thread(mock_synth, client):
    mock_synth.return_value = {
        "plan_id": "plan_abc",
        "url": "/plans/plan_abc",
        "title": "Todo App",
        "working_dir": "/tmp/proj",
        "filename": "plan_abc.md",
        "epic_count": 4,
        "worker_summary": "Drafted four epics.",
        "child_session_id": "ses_1",
    }

    res = client.post("/api/plans/threads", json={"message": "Build a todo app"})
    thread_id = res.json()["thread_id"]

    response = client.post(f"/api/plans/threads/{thread_id}/promote", json={"title": "Todo App"})
    assert response.status_code == 200
    data = response.json()
    assert data["plan_id"] == "plan_abc"
    assert "url" in data

    # Check thread status
    t_res = client.get(f"/api/plans/threads/{thread_id}")
    t_data = t_res.json()["thread"]
    assert t_data["status"] == "promoted"
    assert t_data["plan_id"] == data["plan_id"]

    # Try to promote again
    res2 = client.post(f"/api/plans/threads/{thread_id}/promote", json={"title": "Todo App"})
    assert res2.status_code == 400


@patch("dashboard.plan_agent.refine_plan", new_callable=AsyncMock)
@patch("dashboard.routes.plans.create_plan_on_disk")
@patch("dashboard.routes.threads.synthesize_plan_from_thread", new_callable=AsyncMock)
def test_promote_thread_creates_only_one_plan(mock_synth, mock_create_on_disk, mock_refine, client):
    """Regression: promote must not also call refine_plan + create_plan_on_disk
    (the old code path that produced a duplicate empty plan)."""
    mock_synth.return_value = {
        "plan_id": "plan_single",
        "url": "/plans/plan_single",
        "title": "Todo App",
        "working_dir": "/tmp/proj",
        "filename": "plan_single.md",
        "epic_count": 3,
        "worker_summary": "ok",
        "child_session_id": "ses_x",
    }

    res = client.post("/api/plans/threads", json={"message": "Build a todo app"})
    thread_id = res.json()["thread_id"]
    response = client.post(f"/api/plans/threads/{thread_id}/promote", json={"title": "Todo App"})

    assert response.status_code == 200
    mock_synth.assert_awaited_once()
    # The legacy duplicate-plan entry points must NOT be reached from promote_thread.
    assert mock_refine.await_count == 0, "refine_plan should not be called during promote"
    mock_create_on_disk.assert_not_called()


@patch("dashboard.routes.threads.synthesize_plan_from_thread", new_callable=AsyncMock)
def test_promote_thread_surfaces_synth_failure(mock_synth, client):
    mock_synth.side_effect = RuntimeError("worker produced no epics")

    res = client.post("/api/plans/threads", json={"message": "Build a todo app"})
    thread_id = res.json()["thread_id"]
    response = client.post(f"/api/plans/threads/{thread_id}/promote", json={"title": "Todo App"})

    assert response.status_code == 500
    assert "worker produced no epics" in response.json()["detail"]
    # Thread must remain un-promoted so the user can retry.
    t_res = client.get(f"/api/plans/threads/{thread_id}")
    assert t_res.json()["thread"]["status"] != "promoted"

@patch("dashboard.routes.threads.brainstorm_stream")
def test_stream_thread_message(mock_stream, client):
    async def mock_async_gen(*args, **kwargs):
        yield "Thinking..."
        yield " Here is an idea."
        
    mock_stream.side_effect = mock_async_gen
    
    res = client.post("/api/plans/threads", json={"message": "Build a todo app"})
    thread_id = res.json()["thread_id"]
    
    response = client.post(
        f"/api/plans/threads/{thread_id}/messages/stream", 
        json={"message": "What tech stack should I use?"}
    )
    assert response.status_code == 200
    
    # Get thread to check if assistant message was saved
    t_res = client.get(f"/api/plans/threads/{thread_id}")
    messages = t_res.json()["messages"]
    assert len(messages) == 3 # 1 user (create), 1 user (stream), 1 assistant (stream)
    assert messages[1]["content"] == "What tech stack should I use?"
    assert messages[2]["content"] == "Thinking... Here is an idea."


@pytest.mark.asyncio
async def test_auto_generate_title_uses_opencode_session_title(tmp_path):
    from dashboard.routes.threads import auto_generate_title
    from dashboard.master_agent import _session_registry

    old_store = global_state.planning_store
    store = PlanningThreadStore(base_dir=tmp_path)
    global_state.planning_store = store
    thread = store.create(title="New Idea")

    _session_registry._sessions[f"thread-{thread.id}"] = "ses_test"

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value={"id": "ses_test", "title": "Todo App Builder"})

    try:
        with patch("dashboard.routes.threads.asyncio.sleep", new_callable=AsyncMock), \
             patch("dashboard.master_agent.get_opencode_client", return_value=mock_client):
            await auto_generate_title(thread.id, "Build a todo app")
    finally:
        global_state.planning_store = old_store
        _session_registry.remove(f"thread-{thread.id}")

    mock_client.get.assert_awaited()
    call_args = mock_client.get.call_args
    assert call_args[0][0] == "/session/ses_test"

    updated = store.get(thread.id)
    assert updated.title == "Todo App Builder"


@pytest.mark.asyncio
async def test_auto_generate_title_skips_placeholder_then_uses_real_title(tmp_path):
    from dashboard.routes.threads import auto_generate_title
    from dashboard.master_agent import _session_registry

    old_store = global_state.planning_store
    store = PlanningThreadStore(base_dir=tmp_path)
    global_state.planning_store = store
    thread = store.create(title="New Idea")

    _session_registry._sessions[f"thread-{thread.id}"] = "ses_pending"

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=[
        {"id": "ses_pending", "title": "New session - 2026-05-13T09:00:00.000Z"},
        {"id": "ses_pending", "title": "Plan a beach trip"},
    ])

    try:
        with patch("dashboard.routes.threads.asyncio.sleep", new_callable=AsyncMock), \
             patch("dashboard.master_agent.get_opencode_client", return_value=mock_client):
            await auto_generate_title(thread.id, "Plan a beach trip")
    finally:
        global_state.planning_store = old_store
        _session_registry.remove(f"thread-{thread.id}")

    assert store.get(thread.id).title == "Plan a beach trip"
    assert mock_client.get.await_count == 2
