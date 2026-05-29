"""Tests for dashboard.plan_synthesis — single-step plan creation via ostwin-worker.

These tests are written BEFORE the implementation (TDD). They lock in the
contract that `synthesize_plan_from_thread` must:

  1. Allocate a skeleton plan on disk (one plan_id only).
  2. Fetch the *worker-mode* system prompt.
  3. POST /session to open a child session.
  4. POST /session/{child_id}/message with agent="ostwin-worker".
  5. Re-read the plan file, count epics, raise if zero (and clean up).
  6. Return the create_plan_on_disk dict augmented with epic_count + worker_summary.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def fake_plans_dir(tmp_path, monkeypatch):
    """Redirect PLANS_DIR (and plan_synthesis's reference to it) to a tmp dir."""
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    # The module reads PLANS_DIR via `from dashboard.api_utils import PLANS_DIR`,
    # so we have to patch it on the importing module after import too.
    import dashboard.api_utils as api_utils
    monkeypatch.setattr(api_utils, "PLANS_DIR", plans_dir)
    import dashboard.plan_synthesis as ps
    monkeypatch.setattr(ps, "PLANS_DIR", plans_dir)
    return plans_dir


def _skel_dict(plan_id: str, plans_dir: Path, working_dir: str = "/tmp/proj") -> dict:
    return {
        "plan_id": plan_id,
        "url": f"/plans/{plan_id}",
        "title": "Build a security website",
        "working_dir": working_dir,
        "filename": f"{plan_id}.md",
    }


@pytest.mark.asyncio
async def test_synthesize_creates_skeleton_and_spawns_worker(fake_plans_dir):
    """Happy path: worker writes a real plan with 3 epics, function returns plan_id + epic_count=3."""
    from dashboard import plan_synthesis as ps

    plan_id = "abc123def456"
    plan_file = fake_plans_dir / f"{plan_id}.md"

    # Skeleton stub: write the placeholder file as the real create_plan_on_disk would.
    def fake_create(*, title, content, working_dir, thread_id):
        plan_file.write_text("# Plan: skeleton\n\n> Status: draft\n")
        return _skel_dict(plan_id, fake_plans_dir, "/tmp/proj")

    # Worker stub: simulate ostwin-worker overwriting the file with real epics.
    async def fake_post(path, **kwargs):
        if path == "/session":
            return {"id": "ses_child_99"}
        if path == "/session/ses_child_99/message":
            plan_file.write_text(
                "# Plan: Security Website\n\n"
                "## EPIC-001 — Foundations\n\nfoo\n\n"
                "## EPIC-002 — Auth\n\nbar\n\n"
                "## EPIC-003 — Launch\n\nbaz\n"
            )
            return {
                "info": {},
                "parts": [
                    {"type": "text", "text": "Drafted 3 epics covering setup, auth, and launch."}
                ],
            }
        raise AssertionError(f"unexpected path: {path}")

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=fake_post)

    with patch("dashboard.plan_synthesis.create_plan_on_disk", side_effect=fake_create), \
         patch("dashboard.plan_synthesis.get_opencode_client", return_value=mock_client), \
         patch("dashboard.plan_synthesis.get_system_prompt", return_value="WORKER_PROMPT"):
        result = await ps.synthesize_plan_from_thread(
            thread_id="pt-1",
            chat_history=[{"role": "user", "content": "make me a security website"}],
            title="Build a security website",
        )

    assert result["plan_id"] == plan_id
    assert result["epic_count"] == 3
    assert "Drafted 3 epics" in result["worker_summary"]
    assert result["child_session_id"] == "ses_child_99"
    assert plan_file.exists()


@pytest.mark.asyncio
async def test_synthesize_uses_worker_mode_prompt(fake_plans_dir):
    """The system prompt must be fetched in mode='worker', not 'refine'."""
    from dashboard import plan_synthesis as ps

    plan_id = "p_worker_mode"
    plan_file = fake_plans_dir / f"{plan_id}.md"

    def fake_create(**_kwargs):
        plan_file.write_text("skel")
        return _skel_dict(plan_id, fake_plans_dir)

    async def fake_post(path, **kwargs):
        if path == "/session":
            return {"id": "ses_xyz"}
        plan_file.write_text("# Plan\n\n## EPIC-001 — Foo\n")
        return {"parts": [{"type": "text", "text": "ok"}]}

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=fake_post)

    captured = {}

    def fake_prompt(plans_dir, **kwargs):
        captured["mode"] = kwargs.get("mode")
        captured["plans_dir"] = plans_dir
        return "WORKER_PROMPT"

    with patch("dashboard.plan_synthesis.create_plan_on_disk", side_effect=fake_create), \
         patch("dashboard.plan_synthesis.get_opencode_client", return_value=mock_client), \
         patch("dashboard.plan_synthesis.get_system_prompt", side_effect=fake_prompt):
        await ps.synthesize_plan_from_thread(
            thread_id="pt-1", chat_history=[], title="T",
        )

    assert captured["mode"] == "worker"
    assert captured["plans_dir"] == fake_plans_dir


@pytest.mark.asyncio
async def test_synthesize_passes_correct_message_payload(fake_plans_dir):
    """The /session/{id}/message POST must carry agent=ostwin-worker, system prompt, and a text part."""
    from dashboard import plan_synthesis as ps

    plan_id = "p_payload"
    plan_file = fake_plans_dir / f"{plan_id}.md"

    def fake_create(**_kwargs):
        plan_file.write_text("skel")
        return _skel_dict(plan_id, fake_plans_dir, "/tmp/proj")

    async def fake_post(path, **kwargs):
        if path == "/session":
            return {"id": "ses_payload"}
        plan_file.write_text("# Plan\n\n## EPIC-001 — Foo\n")
        return {"parts": [{"type": "text", "text": "done"}]}

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=fake_post)

    with patch("dashboard.plan_synthesis.create_plan_on_disk", side_effect=fake_create), \
         patch("dashboard.plan_synthesis.get_opencode_client", return_value=mock_client), \
         patch("dashboard.plan_synthesis.get_system_prompt", return_value="SYS_PROMPT"):
        await ps.synthesize_plan_from_thread(
            thread_id="pt-1",
            chat_history=[
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi back"},
            ],
            title="Security Site",
        )

    # Two POSTs: /session, then /session/<id>/message
    calls = mock_client.post.await_args_list
    assert calls[0].args[0] == "/session"
    assert calls[1].args[0] == "/session/ses_payload/message"

    body = calls[1].kwargs.get("body") or (calls[1].args[1] if len(calls[1].args) > 1 else None)
    assert body is not None, f"expected body kwarg in {calls[1]}"
    assert body["agent"] == "ostwin-worker"
    assert body["system"] == "SYS_PROMPT"
    assert isinstance(body["parts"], list) and len(body["parts"]) == 1
    text = body["parts"][0]["text"]
    assert "hello" in text  # chat history included
    assert "hi back" in text
    assert plan_id in text  # task message references plan_id
    assert str(plan_file) in text  # task message references the file path


@pytest.mark.asyncio
async def test_synthesize_raises_and_cleans_up_when_no_epics(fake_plans_dir):
    """If the worker returns without writing any epics, the skeleton must be deleted."""
    from dashboard import plan_synthesis as ps

    plan_id = "p_empty"
    plan_file = fake_plans_dir / f"{plan_id}.md"
    meta_file = fake_plans_dir / f"{plan_id}.meta.json"
    roles_file = fake_plans_dir / f"{plan_id}.roles.json"

    def fake_create(**_kwargs):
        plan_file.write_text("# Plan: skeleton only\n")
        meta_file.write_text("{}")
        roles_file.write_text("{}")
        return _skel_dict(plan_id, fake_plans_dir)

    async def fake_post(path, **kwargs):
        if path == "/session":
            return {"id": "ses_empty"}
        # worker doesn't touch the file — no epics ever land
        return {"parts": [{"type": "text", "text": "sorry, I couldn't generate a plan"}]}

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=fake_post)

    with patch("dashboard.plan_synthesis.create_plan_on_disk", side_effect=fake_create), \
         patch("dashboard.plan_synthesis.get_opencode_client", return_value=mock_client), \
         patch("dashboard.plan_synthesis.get_system_prompt", return_value="P"):
        with pytest.raises(RuntimeError, match="no epics"):
            await ps.synthesize_plan_from_thread(
                thread_id="pt-1", chat_history=[], title="T",
            )

    # All three skeleton files must be removed to avoid leaving a phantom plan.
    assert not plan_file.exists()
    assert not meta_file.exists()
    assert not roles_file.exists()


@pytest.mark.asyncio
async def test_synthesize_raises_and_cleans_up_on_session_create_failure(fake_plans_dir):
    """If POST /session fails, the skeleton plan files must still be cleaned up."""
    from dashboard import plan_synthesis as ps

    plan_id = "p_fail"
    plan_file = fake_plans_dir / f"{plan_id}.md"
    meta_file = fake_plans_dir / f"{plan_id}.meta.json"

    def fake_create(**_kwargs):
        plan_file.write_text("skel")
        meta_file.write_text("{}")
        return _skel_dict(plan_id, fake_plans_dir)

    async def fake_post(path, **kwargs):
        raise RuntimeError("opencode server unreachable")

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=fake_post)

    with patch("dashboard.plan_synthesis.create_plan_on_disk", side_effect=fake_create), \
         patch("dashboard.plan_synthesis.get_opencode_client", return_value=mock_client), \
         patch("dashboard.plan_synthesis.get_system_prompt", return_value="P"):
        with pytest.raises(RuntimeError, match="opencode server unreachable"):
            await ps.synthesize_plan_from_thread(
                thread_id="pt-1", chat_history=[], title="T",
            )

    assert not plan_file.exists()
    assert not meta_file.exists()


@pytest.mark.asyncio
async def test_synthesize_indexes_epics_with_supported_kwargs_only(fake_plans_dir, monkeypatch):
    """Regression: index_epic only accepts (epic_ref, plan_id, title, body, room_id,
    working_dir, status). Splatting the full dict from _parse_plan_epics — which
    also contains task_ref/depends_on — raises TypeError that gets swallowed by
    the per-epic try/except, so the plan ends up with zero indexed epics.
    Lock the call shape so the bug can't sneak back.
    """
    from dashboard import plan_synthesis as ps
    import dashboard.global_state as global_state
    import inspect

    plan_id = "p_idx_epics"
    plan_file = fake_plans_dir / f"{plan_id}.md"

    def fake_create(**_kwargs):
        plan_file.write_text("skel")
        return _skel_dict(plan_id, fake_plans_dir, working_dir="/tmp/proj")

    async def fake_post(path, **kwargs):
        if path == "/session":
            return {"id": "ses_idx"}
        plan_file.write_text(
            "# Plan: Indexing test\n\n"
            "## Config\n\nworking_dir: /tmp/proj\n\n"
            "## Epic: EPIC-001 — Foundations\n\nbody one\ndepends_on: []\n\n"
            "## Epic: EPIC-002 — Auth\n\nbody two\ndepends_on: []\n"
        )
        return {"parts": [{"type": "text", "text": "ok"}]}

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=fake_post)

    # Use a real spec so unsupported kwargs (task_ref, depends_on) raise TypeError.
    from dashboard.zvec_store import OSTwinStore
    mock_store = MagicMock()
    mock_store.index_epic = MagicMock(spec=OSTwinStore.index_epic)
    monkeypatch.setattr(global_state, "store", mock_store)

    with patch("dashboard.plan_synthesis.create_plan_on_disk", side_effect=fake_create), \
         patch("dashboard.plan_synthesis.get_opencode_client", return_value=mock_client), \
         patch("dashboard.plan_synthesis.get_system_prompt", return_value="P"):
        result = await ps.synthesize_plan_from_thread(
            thread_id="pt-1", chat_history=[], title="Indexing test",
        )

    assert result["epic_count"] == 2
    # Both epics must have been indexed (not silently dropped by swallowed TypeError).
    assert mock_store.index_epic.call_count == 2

    # Verify call kwargs match index_epic's signature exactly — no task_ref, no depends_on.
    accepted = set(inspect.signature(OSTwinStore.index_epic).parameters) - {"self"}
    for call in mock_store.index_epic.call_args_list:
        passed_keys = set(call.kwargs)
        unsupported = passed_keys - accepted
        assert not unsupported, f"index_epic called with unsupported kwargs: {unsupported}"
        assert call.kwargs["plan_id"] == plan_id
        assert call.kwargs["epic_ref"].startswith("EPIC-")


@pytest.mark.asyncio
async def test_synthesize_cleanup_removes_zvec_entry_and_assets(fake_plans_dir, monkeypatch):
    """On failure, the zvec index entry inserted by create_plan_on_disk must be
    removed (else a phantom draft lingers in plan lists/search), and any copied
    thread-asset directory must be deleted too.
    """
    from dashboard import plan_synthesis as ps
    import dashboard.global_state as global_state

    plan_id = "p_phantom"
    plan_file = fake_plans_dir / f"{plan_id}.md"
    meta_file = fake_plans_dir / f"{plan_id}.meta.json"
    assets_dir = fake_plans_dir / "assets" / plan_id

    def fake_create(**_kwargs):
        plan_file.write_text("skel")
        meta_file.write_text("{}")
        assets_dir.mkdir(parents=True, exist_ok=True)
        (assets_dir / "uploaded.png").write_bytes(b"fake-image-bytes")
        return _skel_dict(plan_id, fake_plans_dir)

    async def fake_post(path, **kwargs):
        if path == "/session":
            return {"id": "ses_phantom"}
        # Worker doesn't touch the file — synthesis must raise + cleanup
        return {"parts": [{"type": "text", "text": "I gave up"}]}

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=fake_post)

    mock_store = MagicMock()
    monkeypatch.setattr(global_state, "store", mock_store)

    with patch("dashboard.plan_synthesis.create_plan_on_disk", side_effect=fake_create), \
         patch("dashboard.plan_synthesis.get_opencode_client", return_value=mock_client), \
         patch("dashboard.plan_synthesis.get_system_prompt", return_value="P"):
        with pytest.raises(RuntimeError, match="no epics"):
            await ps.synthesize_plan_from_thread(
                thread_id="pt-1", chat_history=[], title="T",
            )

    # Disk: files + asset dir gone
    assert not plan_file.exists()
    assert not meta_file.exists()
    assert not assets_dir.exists()
    # Zvec: phantom draft must be removed so it doesn't linger in plan lists/search
    mock_store.delete_plan.assert_called_once_with(plan_id)


@pytest.mark.asyncio
async def test_synthesize_aggregates_text_parts_into_worker_summary(fake_plans_dir):
    """Multiple text parts in the worker response must be joined into worker_summary."""
    from dashboard import plan_synthesis as ps

    plan_id = "p_parts"
    plan_file = fake_plans_dir / f"{plan_id}.md"

    def fake_create(**_kwargs):
        plan_file.write_text("skel")
        return _skel_dict(plan_id, fake_plans_dir)

    async def fake_post(path, **kwargs):
        if path == "/session":
            return {"id": "ses_parts"}
        plan_file.write_text("# Plan\n\n## EPIC-001 — A\n\n## EPIC-002 — B\n")
        return {
            "parts": [
                {"type": "text", "text": "First sentence."},
                {"type": "tool", "tool": "write", "result": "ok"},  # non-text — ignored
                {"type": "text", "text": "Second sentence."},
            ],
        }

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=fake_post)

    with patch("dashboard.plan_synthesis.create_plan_on_disk", side_effect=fake_create), \
         patch("dashboard.plan_synthesis.get_opencode_client", return_value=mock_client), \
         patch("dashboard.plan_synthesis.get_system_prompt", return_value="P"):
        result = await ps.synthesize_plan_from_thread(
            thread_id="pt-1", chat_history=[], title="T",
        )

    assert "First sentence." in result["worker_summary"]
    assert "Second sentence." in result["worker_summary"]
    assert result["epic_count"] == 2
