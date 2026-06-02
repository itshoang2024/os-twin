from unittest.mock import AsyncMock, patch

import pytest

from dashboard.routes.chat import (
    _broadcast_plan_created_navigation,
    _extract_actions_from_tool_parts,
    _redirect_url_from_actions,
)


def test_extract_actions_adds_plan_route_from_create_tool_output():
    actions = _extract_actions_from_tool_parts(
        [
            {
                "tool": "ostwin_create_plan",
                "status": "completed",
                "output": '{"plan_id":"video-platform-clone"}\nPlan created.',
            }
        ]
    )

    assert len(actions) == 1
    assert actions[0].type == "plan_created"
    assert actions[0].plan_id == "video-platform-clone"
    assert actions[0].url == "/plans/video-platform-clone"
    assert _redirect_url_from_actions(actions) == "/plans/video-platform-clone"


def test_extract_actions_preserves_explicit_tool_url():
    actions = _extract_actions_from_tool_parts(
        [
            {
                "tool": "ostwin_create_plan",
                "status": "completed",
                "output": '{"plan_id":"custom","url":"/plans/custom?tab=epics"}\nPlan created.',
            }
        ]
    )

    assert actions[0].url == "/plans/custom?tab=epics"
    assert _redirect_url_from_actions(actions) == "/plans/custom?tab=epics"


@pytest.mark.asyncio
async def test_plan_created_broadcast_includes_dashboard_destination():
    actions = _extract_actions_from_tool_parts(
        [
            {
                "tool": "ostwin_create_plan",
                "status": "completed",
                "output": '{"plan_id":"created-plan"}',
            }
        ]
    )

    with patch("dashboard.global_state.broadcaster.broadcast", new_callable=AsyncMock) as mock_broadcast:
        await _broadcast_plan_created_navigation(
            actions,
            conversation_id="dashboard:u1",
            user_id="u1",
            platform="dashboard",
        )

    mock_broadcast.assert_awaited_once_with(
        "agent_plan_created",
        {
            "plan_id": "created-plan",
            "url": "/plans/created-plan",
            "conversation_id": "dashboard:u1",
            "user_id": "u1",
            "platform": "dashboard",
            "source": "master_agent",
        },
    )
