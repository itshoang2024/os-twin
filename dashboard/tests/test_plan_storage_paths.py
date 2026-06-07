from pathlib import Path

import dashboard.api_utils as api_utils


def test_resolve_plans_dir_prefers_project_agents_plans(tmp_path):
    project_root = tmp_path / "project"
    agents_dir = project_root / ".agents"
    plans_dir = agents_dir / "plans"
    plans_dir.mkdir(parents=True)

    assert api_utils.resolve_plans_dir(project_root=project_root, agents_dir=agents_dir) == plans_dir


def test_resolve_plans_dir_falls_back_to_global_store_when_project_plans_missing(tmp_path):
    project_root = tmp_path / "project"
    agents_dir = project_root / ".agents"
    agents_dir.mkdir(parents=True)

    assert api_utils.resolve_plans_dir(project_root=project_root, agents_dir=agents_dir) == (
        Path.home() / ".ostwin" / ".agents" / "plans"
    )


def test_resolve_runtime_plan_warrooms_dir_ignores_markdown_working_dir_without_runtime_metadata(tmp_path, monkeypatch):
    plans_dir = tmp_path / ".agents" / "plans"
    plans_dir.mkdir(parents=True)
    warrooms_dir = tmp_path / ".war-rooms"
    warrooms_dir.mkdir()

    (plans_dir / "implementation_plan.md").write_text(
        "# Plan: Test\n\n## Config\n\nworking_dir: /tmp/project\n\n## EPIC-001 - One\n"
    )
    (warrooms_dir / "progress.json").write_text('{"total": 9}')

    monkeypatch.setattr(api_utils, "PLANS_DIR", plans_dir)
    monkeypatch.setattr(api_utils, "WARROOMS_DIR", warrooms_dir)

    assert api_utils.resolve_runtime_plan_warrooms_dir("implementation_plan") is None


def test_resolve_runtime_plan_warrooms_dir_uses_meta_warrooms_dir(tmp_path, monkeypatch):
    plans_dir = tmp_path / ".agents" / "plans"
    plans_dir.mkdir(parents=True)
    meta_warrooms_dir = tmp_path / "project" / ".war-rooms"
    meta_warrooms_dir.mkdir(parents=True)

    (plans_dir / "implementation_plan.meta.json").write_text(
        '{"plan_id":"implementation_plan","warrooms_dir":"%s","status":"launched"}' % meta_warrooms_dir.as_posix()
    )

    monkeypatch.setattr(api_utils, "PLANS_DIR", plans_dir)
    monkeypatch.setattr(api_utils, "WARROOMS_DIR", tmp_path / ".war-rooms")

    assert api_utils.resolve_runtime_plan_warrooms_dir("implementation_plan") == meta_warrooms_dir


def test_resolve_runtime_plan_warrooms_dir_uses_stamped_global_rooms(tmp_path, monkeypatch):
    plans_dir = tmp_path / ".agents" / "plans"
    plans_dir.mkdir(parents=True)
    warrooms_dir = tmp_path / ".war-rooms"
    room_dir = warrooms_dir / "room-001"
    room_dir.mkdir(parents=True)
    (room_dir / "config.json").write_text('{"plan_id":"implementation_plan","task_ref":"EPIC-001"}')

    monkeypatch.setattr(api_utils, "PLANS_DIR", plans_dir)
    monkeypatch.setattr(api_utils, "WARROOMS_DIR", warrooms_dir)

    assert api_utils.resolve_runtime_plan_warrooms_dir("implementation_plan") == warrooms_dir
