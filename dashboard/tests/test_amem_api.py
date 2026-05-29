"""Tests for Agentic Memory dashboard API routes.

Tests the /api/amem/{plan_id}/... endpoints that serve memory graph data,
note listings, individual notes, and statistics from the centralized
~/.ostwin/memory/{plan_id}/ directory.
"""

import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from dashboard.api import app
from dashboard.auth import get_current_user


# ── Auth mock ─────────────────────────────────────────────────────────


def mock_get_current_user():
    return {"user_id": "test_user"}


app.dependency_overrides[get_current_user] = mock_get_current_user


# ── Fixtures ──────────────────────────────────────────────────────────

SAMPLE_NOTE_SCHEMA = """# Video Platform: Database Schemas

**Tags**: #database, #schema, #postgresql
**Keywords**: users, videos, comments, likes, relational integrity
**Links**: api-contracts, system-architecture

## Problem Statement
Need a relational schema for a video-sharing platform supporting users,
video uploads, comments, and likes with full referential integrity.

## Schema
CREATE TABLE users (id UUID PRIMARY KEY, username VARCHAR(50), email VARCHAR(255));
CREATE TABLE videos (id UUID PRIMARY KEY, user_id UUID REFERENCES users(id), title VARCHAR(255));
CREATE TABLE comments (id UUID PRIMARY KEY, video_id UUID REFERENCES videos(id), content TEXT);
CREATE TABLE likes (id UUID PRIMARY KEY, video_id UUID REFERENCES videos(id), user_id UUID REFERENCES users(id));
"""

SAMPLE_NOTE_API = """# API Contracts — Video Platform

**Tags**: #api, #rest, #video
**Keywords**: REST, endpoints, authentication, pagination
**Links**: database-schemas

## Endpoints
POST /api/users/register
POST /api/users/login
POST /api/videos
GET /api/videos
GET /api/videos/:id
POST /api/videos/:id/comments
"""

SAMPLE_NOTE_DECISION = """# Architecture Decision: CDN Strategy

**Tags**: #architecture, #decision, #cdn
**Keywords**: CloudFront, S3, latency, caching

Chose CloudFront CDN over self-hosted Nginx for video delivery.
Why: automatic edge caching, lower egress costs, global PoPs.
Trade-off: vendor lock-in with AWS, but acceptable for current scale.
"""

SAMPLE_NOTE_MINIMAL = """# Minimal Note

Just a simple note with no metadata.
"""


def _make_memory_dir(memory_base: Path, plan_id: str) -> Path:
    """Create the centralized memory directory for a plan_id."""
    mem_dir = memory_base / plan_id
    return mem_dir


@pytest.fixture
def memory_workspace(tmp_path, monkeypatch):
    """Create a centralized memory directory structure with sample notes."""
    memory_base = tmp_path / "memory"
    memory_base.mkdir()
    monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_base)

    plan_id = "test-project.plan"
    mem_dir = _make_memory_dir(memory_base, plan_id)
    notes_dir = mem_dir / "notes"

    # architecture/database/
    (notes_dir / "architecture" / "database").mkdir(parents=True)
    (notes_dir / "architecture" / "database" / "database-schemas.md").write_text(SAMPLE_NOTE_SCHEMA, encoding="utf-8")

    # architecture/api/
    (notes_dir / "architecture" / "api").mkdir(parents=True)
    (notes_dir / "architecture" / "api" / "api-contracts.md").write_text(SAMPLE_NOTE_API, encoding="utf-8")

    # architecture/decisions/
    (notes_dir / "architecture" / "decisions").mkdir(parents=True)
    (notes_dir / "architecture" / "decisions" / "cdn-strategy.md").write_text(SAMPLE_NOTE_DECISION, encoding="utf-8")

    # misc/
    (notes_dir / "misc").mkdir(parents=True)
    (notes_dir / "misc" / "minimal-note.md").write_text(SAMPLE_NOTE_MINIMAL, encoding="utf-8")

    # Create vectordb (empty, just to prove it exists)
    (mem_dir / "vectordb" / "memories").mkdir(parents=True)

    return {
        "memory_dir": mem_dir,
        "notes_dir": notes_dir,
        "memory_base": memory_base,
        "plan_id": plan_id,
    }


@pytest.fixture
def empty_memory_workspace(tmp_path, monkeypatch):
    """Create a centralized memory directory with empty notes/."""
    memory_base = tmp_path / "memory"
    memory_base.mkdir()
    monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_base)

    plan_id = "empty-project.plan"
    mem_dir = _make_memory_dir(memory_base, plan_id)
    (mem_dir / "notes").mkdir(parents=True)

    return {
        "memory_base": memory_base,
        "plan_id": plan_id,
    }


@pytest.fixture
def no_memory_workspace(tmp_path, monkeypatch):
    """Set up a plan_id with no centralized memory directory at all."""
    memory_base = tmp_path / "memory"
    memory_base.mkdir()
    monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_base)

    plan_id = "no-memory.plan"
    return {
        "memory_base": memory_base,
        "plan_id": plan_id,
    }


# ── Graph endpoint tests ─────────────────────────────────────────────


class TestMemoryGraph:
    """Tests for GET /api/amem/{plan_id}/graph"""

    def test_graph_returns_nodes_and_links(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        resp = client.get(f"/api/amem/{memory_workspace['plan_id']}/graph")
        assert resp.status_code == 200

        data = resp.json()
        assert "groups" in data
        assert "nodes" in data
        assert "links" in data
        assert "stats" in data

    def test_graph_has_correct_node_count(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{memory_workspace['plan_id']}/graph").json()
        assert data["stats"]["total_memories"] == 4

    def test_graph_nodes_have_required_fields(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{memory_workspace['plan_id']}/graph").json()
        required_fields = {
            "id",
            "title",
            "path",
            "pathLabel",
            "excerpt",
            "tags",
            "keywords",
            "groupId",
            "color",
        }

        for node in data["nodes"]:
            for field in required_fields:
                assert field in node, f"Node missing field: {field}"

    def test_graph_groups_from_directory_structure(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{memory_workspace['plan_id']}/graph").json()
        group_ids = {g["id"] for g in data["groups"]}
        assert "architecture" in group_ids
        assert "misc" in group_ids

    def test_graph_links_between_notes(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{memory_workspace['plan_id']}/graph").json()
        assert isinstance(data["links"], list)

    def test_graph_groups_have_colors(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{memory_workspace['plan_id']}/graph").json()
        for group in data["groups"]:
            assert "color" in group
            assert group["color"].startswith("#")

    def test_graph_empty_memory(self, empty_memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", empty_memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{empty_memory_workspace['plan_id']}/graph").json()
        assert data["stats"]["total_memories"] == 0
        assert data["nodes"] == []
        assert data["links"] == []
        assert data["groups"] == []

    def test_graph_no_memory_dir_returns_404(self, no_memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", no_memory_workspace["memory_base"])
        client = TestClient(app)

        resp = client.get(f"/api/amem/{no_memory_workspace['plan_id']}/graph")
        assert resp.status_code == 404

    def test_graph_nonexistent_plan_returns_404(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        resp = client.get("/api/amem/nonexistent-plan/graph")
        assert resp.status_code == 404


# ── Notes list endpoint tests ────────────────────────────────────────


class TestMemoryNotesList:
    """Tests for GET /api/amem/{plan_id}/notes"""

    def test_list_notes_returns_all(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{memory_workspace['plan_id']}/notes").json()
        assert len(data) == 4

    def test_list_notes_excludes_content(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{memory_workspace['plan_id']}/notes").json()
        for note in data:
            assert "content" not in note

    def test_list_notes_has_metadata(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{memory_workspace['plan_id']}/notes").json()
        for note in data:
            assert "id" in note
            assert "title" in note
            assert "path" in note
            assert "tags" in note

    def test_list_notes_parses_tags(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{memory_workspace['plan_id']}/notes").json()
        schema_note = next((n for n in data if n["id"] == "database-schemas"), None)
        assert schema_note is not None
        assert "database" in schema_note["tags"]
        assert "schema" in schema_note["tags"]

    def test_list_notes_parses_keywords(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{memory_workspace['plan_id']}/notes").json()
        schema_note = next((n for n in data if n["id"] == "database-schemas"), None)
        assert schema_note is not None
        assert "users" in schema_note["keywords"]

    def test_list_notes_empty(self, empty_memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", empty_memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{empty_memory_workspace['plan_id']}/notes").json()
        assert data == []


# ── Single note endpoint tests ───────────────────────────────────────


class TestMemoryNoteDetail:
    """Tests for GET /api/amem/{plan_id}/notes/{note_id}"""

    def test_get_note_by_id(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        resp = client.get(f"/api/amem/{memory_workspace['plan_id']}/notes/database-schemas")
        assert resp.status_code == 200

        data = resp.json()
        assert data["id"] == "database-schemas"
        assert "content" in data
        assert "CREATE TABLE" in data["content"]

    def test_get_note_has_title_from_h1(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{memory_workspace['plan_id']}/notes/database-schemas").json()
        assert data["title"] == "Video Platform: Database Schemas"

    def test_get_note_has_links(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{memory_workspace['plan_id']}/notes/database-schemas").json()
        assert "api-contracts" in data["links"]
        assert "system-architecture" in data["links"]

    def test_get_note_nonexistent_returns_404(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        resp = client.get(f"/api/amem/{memory_workspace['plan_id']}/notes/does-not-exist")
        assert resp.status_code == 404

    def test_get_note_minimal_has_defaults(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{memory_workspace['plan_id']}/notes/minimal-note").json()
        assert data["title"] == "Minimal Note"
        assert data["tags"] == []
        assert data["keywords"] == []
        assert data["links"] == []


# ── Stats endpoint tests ─────────────────────────────────────────────


class TestMemoryStats:
    """Tests for GET /api/amem/{plan_id}/stats"""

    def test_stats_returns_counts(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{memory_workspace['plan_id']}/stats").json()
        assert data["total_notes"] == 4
        assert data["total_tags"] > 0
        assert data["total_keywords"] > 0

    def test_stats_includes_all_tags(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{memory_workspace['plan_id']}/stats").json()
        assert "database" in data["tags"]
        assert "api" in data["tags"]
        assert "architecture" in data["tags"]

    def test_stats_includes_paths(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{memory_workspace['plan_id']}/stats").json()
        assert len(data["paths"]) > 0

    def test_stats_includes_memory_dir(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{memory_workspace['plan_id']}/stats").json()
        assert "memory_dir" in data
        assert memory_workspace["plan_id"] in data["memory_dir"]

    def test_stats_empty_memory(self, empty_memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", empty_memory_workspace["memory_base"])
        client = TestClient(app)

        data = client.get(f"/api/amem/{empty_memory_workspace['plan_id']}/stats").json()
        assert data["total_notes"] == 0
        assert data["total_tags"] == 0
        assert data["tags"] == []

    def test_stats_no_memory_returns_404(self, no_memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", no_memory_workspace["memory_base"])
        client = TestClient(app)

        resp = client.get(f"/api/amem/{no_memory_workspace['plan_id']}/stats")
        assert resp.status_code == 404


# ── Plan resolution tests ────────────────────────────────────────────


class TestPlanResolution:
    """Tests for _resolve_memory_dir — resolving centralized memory from plan_id."""

    def test_resolves_from_centralized_dir(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        resp = client.get(f"/api/amem/{memory_workspace['plan_id']}/stats")
        assert resp.status_code == 200

    def test_nonexistent_plan_returns_404(self, memory_workspace, monkeypatch):
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_workspace["memory_base"])
        client = TestClient(app)

        resp = client.get("/api/amem/this-plan-does-not-exist/graph")
        assert resp.status_code == 404

    def test_resolve_memory_dir_accepts_memory_prefixed_plan_id(
        self, tmp_path, monkeypatch
    ):
        from dashboard.routes import amem

        memory_base = tmp_path / "memory"
        monkeypatch.setattr(amem, "MEMORY_BASE_DIR", memory_base)
        current = memory_base / "memory-4ae61a301661"
        current.mkdir(parents=True)

        assert amem._resolve_memory_dir("memory-4ae61a301661") == current

    def test_resolve_memory_dir_prefers_current_over_legacy(
        self, tmp_path, monkeypatch
    ):
        from dashboard.routes import amem

        memory_base = tmp_path / "memory"
        monkeypatch.setattr(amem, "MEMORY_BASE_DIR", memory_base)
        legacy = memory_base / "4ae61a301661"
        current = memory_base / "memory-4ae61a301661"
        legacy.mkdir(parents=True)
        current.mkdir(parents=True)

        assert amem._resolve_memory_dir("4ae61a301661") == current

    def test_resolve_memory_dir_falls_back_to_working_dir_memory(
        self, tmp_path, monkeypatch
    ):
        from dashboard.routes import amem

        memory_base = tmp_path / "memory"
        plans_dir = tmp_path / "plans"
        working_dir = tmp_path / "project"
        project_memory = working_dir / ".memory"
        memory_base.mkdir()
        plans_dir.mkdir()
        project_memory.mkdir(parents=True)
        plan_id = "4ae61a301661"
        (plans_dir / f"{plan_id}.meta.json").write_text(
            json.dumps({"working_dir": str(working_dir)}),
            encoding="utf-8",
        )
        monkeypatch.setattr(amem, "MEMORY_BASE_DIR", memory_base)
        monkeypatch.setattr(amem, "PLANS_DIR", plans_dir)

        assert amem._resolve_memory_dir(plan_id) == project_memory.resolve()


# ── Note parsing edge cases ──────────────────────────────────────────


class TestNoteParsing:
    """Tests for note parsing edge cases in _load_notes."""

    def test_note_without_h1_uses_filename(self, tmp_path, monkeypatch):
        """Notes without a # heading use the filename as title."""
        memory_base = tmp_path / "memory"
        memory_base.mkdir()
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_base)

        plan_id = "test.plan"
        mem_dir = memory_base / plan_id
        notes_dir = mem_dir / "notes"
        notes_dir.mkdir(parents=True)
        (notes_dir / "no-heading.md").write_text("Just content, no heading.", encoding="utf-8")

        client = TestClient(app)

        data = client.get(f"/api/amem/{plan_id}/notes").json()
        assert len(data) == 1
        assert data[0]["title"] == "No Heading"

    def test_note_with_empty_tags(self, tmp_path, monkeypatch):
        """Notes with **Tags**: but empty value."""
        memory_base = tmp_path / "memory"
        memory_base.mkdir()
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_base)

        plan_id = "test.plan"
        mem_dir = memory_base / plan_id
        notes_dir = mem_dir / "notes"
        notes_dir.mkdir(parents=True)
        (notes_dir / "empty-tags.md").write_text("# Test\n\n**Tags**: \n\nContent here.", encoding="utf-8")

        client = TestClient(app)

        data = client.get(f"/api/amem/{plan_id}/notes").json()
        assert len(data) == 1
        assert isinstance(data[0]["tags"], list)

    def test_non_md_files_ignored(self, tmp_path, monkeypatch):
        """Only .md files are loaded, other files are ignored."""
        memory_base = tmp_path / "memory"
        memory_base.mkdir()
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_base)

        plan_id = "test.plan"
        mem_dir = memory_base / plan_id
        notes_dir = mem_dir / "notes"
        notes_dir.mkdir(parents=True)
        (notes_dir / "note.md").write_text("# Real Note\nContent.", encoding="utf-8")
        (notes_dir / "data.json").write_text('{"not": "a note"}', encoding="utf-8")
        (notes_dir / "image.png").write_bytes(b"\x89PNG")

        client = TestClient(app)

        data = client.get(f"/api/amem/{plan_id}/notes").json()
        assert len(data) == 1
        assert data[0]["id"] == "note"

    def test_deeply_nested_notes(self, tmp_path, monkeypatch):
        """Notes in deeply nested directories are found."""
        memory_base = tmp_path / "memory"
        memory_base.mkdir()
        monkeypatch.setattr("dashboard.routes.amem.MEMORY_BASE_DIR", memory_base)

        plan_id = "test.plan"
        deep_dir = memory_base / plan_id / "notes" / "a" / "b" / "c"
        deep_dir.mkdir(parents=True)
        (deep_dir / "deep-note.md").write_text("# Deep\nContent.", encoding="utf-8")

        client = TestClient(app)

        data = client.get(f"/api/amem/{plan_id}/notes").json()
        assert len(data) == 1
        assert data[0]["path"] == "a/b/c"


# ── Merkle tree endpoint ─────────────────────────────────────────────


class TestMerkleEndpoint:
    """Tests for ``GET /api/amem/{plan_id}/merkle``."""

    def test_merkle_returns_404_when_no_manifest(self, memory_workspace):
        """Should return 404 when no merkle_manifest.json exists."""
        client = TestClient(app)
        plan_id = memory_workspace["plan_id"]
        resp = client.get(f"/api/amem/{plan_id}/merkle")
        assert resp.status_code == 404
        assert "No Merkle manifest" in resp.json()["detail"]

    def test_merkle_returns_correct_shape(self, memory_workspace):
        """Should return a properly transformed d3-hierarchy shape."""
        client = TestClient(app)
        plan_id = memory_workspace["plan_id"]

        manifest = {
            "version": 1,
            "root_hash": "aaaa1111bbbb2222",
            "generated_at": "20260518150000",
            "note_count": 2,
            "vectordb_root_hash": "cccc3333dddd4444",
            "tree": {
                "_hash": "aaaa1111bbbb2222",
                "devops": {
                    "_hash": "eeee5555ffff6666",
                    "pod-basics.md": "1111aaaa2222bbbb",
                },
                "unfiled-note.md": "9999xxxx0000yyyy",
            },
        }
        manifest_path = memory_workspace["memory_dir"] / "merkle_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        resp = client.get(f"/api/amem/{plan_id}/merkle")
        assert resp.status_code == 200
        data = resp.json()

        assert data["root_hash"] == "aaaa1111bbbb2222"
        assert data["note_count"] == 2
        assert data["generated_at"] == "20260518150000"
        assert data["vectordb_root_hash"] == "cccc3333dddd4444"

        tree = data["tree"]
        assert tree["name"] == "(root)"
        assert tree["type"] == "dir"
        assert tree["hash"] == "aaaa1111bbbb2222"

    def test_merkle_tree_has_correct_children(self, memory_workspace):
        """Should correctly transform directories and leaves."""
        client = TestClient(app)
        plan_id = memory_workspace["plan_id"]

        manifest = {
            "version": 1,
            "root_hash": "root_hash_value!",
            "generated_at": "20260518160000",
            "note_count": 3,
            "vectordb_root_hash": "",
            "tree": {
                "_hash": "root_hash_value!",
                "alpha": {
                    "_hash": "alpha_hash_val!!",
                    "note-a.md": "leaf_hash_a_val!",
                    "note-b.md": "leaf_hash_b_val!",
                },
                "standalone.md": "standalone_hash!",
            },
        }
        manifest_path = memory_workspace["memory_dir"] / "merkle_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        data = client.get(f"/api/amem/{plan_id}/merkle").json()
        tree = data["tree"]

        # Root should have 2 children: "alpha" dir and "standalone.md" leaf
        children = tree["children"]
        assert len(children) == 2

        # Children are sorted by name
        assert children[0]["name"] == "alpha"
        assert children[0]["type"] == "dir"
        assert children[0]["hash"] == "alpha_hash_val!!"
        assert len(children[0]["children"]) == 2

        assert children[1]["name"] == "standalone.md"
        assert children[1]["type"] == "leaf"
        assert children[1]["hash"] == "standalone_hash!"
        assert len(children[1]["children"]) == 0

    def test_merkle_leaves_have_correct_type(self, memory_workspace):
        """All .md keys should become type=leaf, dict keys should become type=dir."""
        client = TestClient(app)
        plan_id = memory_workspace["plan_id"]

        manifest = {
            "version": 1,
            "root_hash": "r",
            "generated_at": "20260518170000",
            "note_count": 1,
            "tree": {
                "_hash": "r",
                "deep": {
                    "_hash": "d1",
                    "nested": {
                        "_hash": "d2",
                        "leaf.md": "lh",
                    },
                },
            },
        }
        manifest_path = memory_workspace["memory_dir"] / "merkle_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        data = client.get(f"/api/amem/{plan_id}/merkle").json()
        # Navigate: root -> deep -> nested -> leaf.md
        deep = data["tree"]["children"][0]
        assert deep["type"] == "dir"
        nested = deep["children"][0]
        assert nested["type"] == "dir"
        leaf = nested["children"][0]
        assert leaf["type"] == "leaf"
        assert leaf["name"] == "leaf.md"
        assert leaf["hash"] == "lh"

    def test_merkle_nonexistent_plan_returns_404(self, memory_workspace):
        """A plan_id with no memory dir should return 404."""
        client = TestClient(app)
        resp = client.get("/api/amem/nonexistent-plan/merkle")
        assert resp.status_code == 404
