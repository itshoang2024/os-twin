"""Unit tests for AgenticMemorySystem — core memory operations.

Covers:
  - System initialization (in-memory mode, with mocked retriever)
  - add_note / read / update / delete lifecycle
  - Link management (add_link, remove_link, backlinks)
  - Search (time decay, re-ranking)
  - Disk persistence (sync_to_disk, merge_from_disk)
  - Conflict resolution (last_modified, LLM)
  - Clear and tree operations
  - _coerce_str_list helper
  - Dirty flag optimization
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dashboard.agentic_memory.memory_note import MemoryNote


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_mock_retriever():
    """Create a mock retriever that tracks added documents."""
    retriever = MagicMock()
    retriever._docs = {}  # track added docs by id

    def add_doc(document, metadata, doc_id):
        retriever._docs[doc_id] = {"document": document, "metadata": metadata}

    def delete_doc(doc_id):
        retriever._docs.pop(doc_id, None)

    def search(query, k=5):
        return {"ids": [[]], "metadatas": [[]], "distances": [[]]}

    def get_stored_hashes(doc_ids):
        result = {}
        for did in doc_ids:
            if did in retriever._docs:
                result[did] = retriever._docs[did]["metadata"].get("content_hash")
        return result

    retriever.add_document.side_effect = add_doc
    retriever.delete_document.side_effect = delete_doc
    retriever.search.side_effect = search
    retriever.get_stored_hashes.side_effect = get_stored_hashes
    retriever.flush_gc = MagicMock()
    return retriever


def _create_system(**kwargs):
    """Create an AgenticMemorySystem with fully mocked deps (no real API calls)."""
    from dashboard.agentic_memory.memory_system import AgenticMemorySystem

    mock_completion = MagicMock(return_value=json.dumps({
        "name": "test-note",
        "path": "test/path",
        "keywords": ["test"],
        "context": "Testing",
        "tags": ["unit-test"],
    }))
    mock_embed = MagicMock(return_value=[[0.1] * 384])
    persist_dir = kwargs.pop("persist_dir", None)
    mock_retriever = _make_mock_retriever()

    with patch.object(AgenticMemorySystem, "_create_retriever", return_value=mock_retriever):
        with patch("dashboard.agentic_memory.memory_system._ensure_ml_imports"):
            system = AgenticMemorySystem(
                persist_dir=persist_dir,
                completion_fn=mock_completion,
                embed_fn=mock_embed,
                vector_backend="chroma",
                evo_threshold=9999,
                **kwargs,
            )
    return system


# ═══════════════════════════════════════════════════════════════════════════════
# 1. System Initialization
# ═══════════════════════════════════════════════════════════════════════════════


class TestSystemInit:
    """Test AgenticMemorySystem initialization."""

    def test_in_memory_mode(self):
        system = _create_system()
        assert system.memories == {}
        assert system.persist_dir is None

    def test_similarity_weight_clamped(self):
        system = _create_system(similarity_weight=1.5)
        assert system.similarity_weight == 1.0

        system2 = _create_system(similarity_weight=-0.5)
        assert system2.similarity_weight == 0.0

    def test_decay_half_life_clamped(self):
        system = _create_system(decay_half_life_days=0.001)
        # Minimum is 0.01 (enforced by max(0.01, ...))
        assert system.decay_half_life_days == 0.01

    def test_persisted_mode_creates_dirs(self, tmp_path):
        system = _create_system(persist_dir=str(tmp_path))
        assert os.path.isdir(os.path.join(str(tmp_path), "notes"))
        assert os.path.isdir(os.path.join(str(tmp_path), "vectordb"))


# ═══════════════════════════════════════════════════════════════════════════════
# 2. CRUD Lifecycle
# ═══════════════════════════════════════════════════════════════════════════════


class TestCRUDLifecycle:
    """Test add_note, read, update, delete lifecycle."""

    def test_add_note_returns_id(self):
        system = _create_system()
        note_id = system.add_note("Hello world", skip_evolution=True)
        assert note_id is not None
        assert isinstance(note_id, str)

    def test_read_note(self):
        system = _create_system()
        note_id = system.add_note("Hello world", skip_evolution=True)
        note = system.read(note_id)
        assert note is not None
        assert note.content == "Hello world"

    def test_read_nonexistent_returns_none(self):
        system = _create_system()
        assert system.read("nonexistent-id") is None

    def test_update_note(self):
        system = _create_system()
        note_id = system.add_note("Original content", skip_evolution=True)
        result = system.update(note_id, content="Updated content")
        assert result is True
        note = system.read(note_id)
        assert note.content == "Updated content"

    def test_update_nonexistent_returns_false(self):
        system = _create_system()
        assert system.update("nonexistent-id", content="x") is False

    def test_update_with_skip_content(self):
        """Updating fields other than content should not trigger re-analysis."""
        system = _create_system()
        note_id = system.add_note("Original content", skip_evolution=True)
        result = system.update(note_id, retrieval_count=5)
        assert result is True
        note = system.read(note_id)
        assert note.retrieval_count == 5

    def test_delete_note(self):
        system = _create_system()
        note_id = system.add_note("To be deleted", skip_evolution=True)
        assert system.read(note_id) is not None
        result = system.delete(note_id)
        assert result is True
        assert system.read(note_id) is None

    def test_delete_nonexistent_returns_false(self):
        system = _create_system()
        assert system.delete("nonexistent-id") is False

    def test_clear_all_notes(self):
        system = _create_system()
        system.add_note("Note 1", skip_evolution=True)
        system.add_note("Note 2", skip_evolution=True)
        assert len(system.memories) == 2
        result = system.clear()
        assert result["cleared"] == 2
        assert len(system.memories) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Link Management
# ═══════════════════════════════════════════════════════════════════════════════


class TestLinkManagement:
    """Test add_link, remove_link, and backlink auto-management."""

    def test_add_link(self):
        system = _create_system()
        id1 = system.add_note("Note 1", skip_evolution=True)
        id2 = system.add_note("Note 2", skip_evolution=True)
        system.add_link(id1, id2)
        note1 = system.read(id1)
        note2 = system.read(id2)
        assert id2 in note1.links
        assert id1 in note2.backlinks

    def test_remove_link(self):
        system = _create_system()
        id1 = system.add_note("Note 1", skip_evolution=True)
        id2 = system.add_note("Note 2", skip_evolution=True)
        system.add_link(id1, id2)
        system.remove_link(id1, id2)
        note1 = system.read(id1)
        note2 = system.read(id2)
        assert id2 not in note1.links
        assert id1 not in note2.backlinks

    def test_add_link_nonexistent_note_ignored(self):
        system = _create_system()
        id1 = system.add_note("Note 1", skip_evolution=True)
        system.add_link(id1, "nonexistent-id")
        system.add_link("nonexistent-id", id1)

    def test_remove_link_nonexistent_note_ignored(self):
        system = _create_system()
        id1 = system.add_note("Note 1", skip_evolution=True)
        system.remove_link(id1, "nonexistent-id")
        system.remove_link("nonexistent-id", id1)

    def test_add_duplicate_link_ignored(self):
        system = _create_system()
        id1 = system.add_note("Note 1", skip_evolution=True)
        id2 = system.add_note("Note 2", skip_evolution=True)
        system.add_link(id1, id2)
        system.add_link(id1, id2)  # duplicate
        note1 = system.read(id1)
        assert note1.links.count(id2) == 1

    def test_delete_removes_links(self):
        system = _create_system()
        id1 = system.add_note("Note 1", skip_evolution=True)
        id2 = system.add_note("Note 2", skip_evolution=True)
        id3 = system.add_note("Note 3", skip_evolution=True)
        system.add_link(id1, id2)
        system.add_link(id3, id2)
        system.delete(id2)
        note1 = system.read(id1)
        note3 = system.read(id3)
        assert id2 not in note1.links
        assert id2 not in note3.links


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Time Decay Scoring
# ═══════════════════════════════════════════════════════════════════════════════


class TestTimeDecayScoring:
    """Test _compute_time_decay_score."""

    def test_fresh_note_high_score(self):
        system = _create_system()
        now = datetime.now().strftime("%Y%m%d%H%M")
        score = system._compute_time_decay_score(1.0, now)
        assert score > 0.9

    def test_old_note_lower_score(self):
        system = _create_system()
        old_ts = "202001011200"
        score = system._compute_time_decay_score(1.0, old_ts)
        assert score < 1.0

    def test_similarity_weight_dominates(self):
        system = _create_system(similarity_weight=1.0)
        old_ts = "202001011200"
        score = system._compute_time_decay_score(0.8, old_ts)
        assert abs(score - 0.8) < 0.001

    def test_recency_only(self):
        system = _create_system(similarity_weight=0.0)
        now = datetime.now().strftime("%Y%m%d%H%M")
        score = system._compute_time_decay_score(0.5, now)
        assert score > 0.9

    def test_invalid_timestamp_treated_as_fresh(self):
        system = _create_system()
        score = system._compute_time_decay_score(1.0, "invalid")
        assert score > 0.9


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Disk Persistence
# ═══════════════════════════════════════════════════════════════════════════════


class TestDiskPersistence:
    """Test sync_to_disk and merge_from_disk."""

    def test_sync_writes_note_files(self, tmp_path):
        system = _create_system(persist_dir=str(tmp_path))
        system.add_note("Persist me", skip_evolution=True)
        result = system.sync_to_disk()
        assert result["written"] >= 1

        notes_dir = os.path.join(str(tmp_path), "notes")
        md_files = list(Path(notes_dir).rglob("*.md"))
        assert len(md_files) >= 1

    def test_merge_from_disk_picks_up_new_files(self, tmp_path):
        system = _create_system(persist_dir=str(tmp_path))
        system.add_note("Existing note", skip_evolution=True)
        system.sync_to_disk()

        # Write a new note directly to disk
        notes_dir = os.path.join(str(tmp_path), "notes")
        new_note = MemoryNote(
            content="Disk-only note",
            id="disk-note-id",
            name="Disk Note",
        )
        filepath = os.path.join(notes_dir, new_note.filepath)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_note.to_markdown())

        result = system.merge_from_disk()
        assert result["added_from_disk"] == 1
        assert system.read("disk-note-id") is not None

    def test_merge_detects_unchanged(self, tmp_path):
        system = _create_system(persist_dir=str(tmp_path))
        system.add_note("Unchanged note", skip_evolution=True)
        system.sync_to_disk()
        result = system.merge_from_disk()
        assert result["unchanged"] >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Conflict Resolution
# ═══════════════════════════════════════════════════════════════════════════════


class TestConflictResolution:
    """Test _resolve_conflict with different strategies."""

    def test_last_modified_newer_wins(self):
        system = _create_system(conflict_resolution="last_modified")
        note_a = MemoryNote(content="A", id="a", last_modified="202406151500")
        note_b = MemoryNote(content="B", id="b", last_modified="202401011200")
        winner = system._resolve_conflict(note_a, note_b)
        assert winner.id == "a"

    def test_last_modified_tie_goes_to_a(self):
        system = _create_system(conflict_resolution="last_modified")
        note_a = MemoryNote(content="A", id="a", last_modified="202406151500")
        note_b = MemoryNote(content="B", id="b", last_modified="202406151500")
        winner = system._resolve_conflict(note_a, note_b)
        assert winner.id == "a"

    def test_llm_fallback_to_last_modified(self):
        """LLM conflict resolution falls back to last_modified on failure."""
        system = _create_system(conflict_resolution="llm")
        note_a = MemoryNote(content="A", id="a", last_modified="202406151500")
        note_b = MemoryNote(content="B", id="b", last_modified="202401011200")
        winner = system._resolve_conflict(note_a, note_b)
        assert winner is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Tree & Directory Operations
# ═══════════════════════════════════════════════════════════════════════════════


class TestTreeOperations:
    """Test tree() rendering and directory structure."""

    def test_empty_tree(self):
        system = _create_system()
        assert system.tree() == "(empty)"

    def test_tree_with_notes(self):
        system = _create_system()
        system.add_note("Note 1", skip_evolution=True, name="Note 1", path="dir1")
        system.add_note("Note 2", skip_evolution=True, name="Note 2", path="dir2")
        tree = system.tree()
        assert len(tree) > 0

    def test_render_tree(self):
        from dashboard.agentic_memory.memory_system import AgenticMemorySystem
        node = {"a": {"x.md": {}}, "b": {"y.md": {}}}
        lines = AgenticMemorySystem._render_tree(node)
        assert len(lines) == 4


# ═══════════════════════════════════════════════════════════════════════════════
# 8. _coerce_str_list Helper
# ═══════════════════════════════════════════════════════════════════════════════


class TestCoerceStrList:
    """Test _coerce_str_list static method."""

    def test_strings_passthrough(self):
        from dashboard.agentic_memory.memory_system import AgenticMemorySystem
        result = AgenticMemorySystem._coerce_str_list(["a", "b"])
        assert result == ["a", "b"]

    def test_dict_values_extracted(self):
        from dashboard.agentic_memory.memory_system import AgenticMemorySystem
        result = AgenticMemorySystem._coerce_str_list([{"tag": "value"}])
        assert result == ["value"]

    def test_mixed_types(self):
        from dashboard.agentic_memory.memory_system import AgenticMemorySystem
        result = AgenticMemorySystem._coerce_str_list(["a", 123, True])
        assert result == ["a", "123", "True"]

    def test_empty_list(self):
        from dashboard.agentic_memory.memory_system import AgenticMemorySystem
        assert AgenticMemorySystem._coerce_str_list([]) == []


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Filepath Collision Handling
# ═══════════════════════════════════════════════════════════════════════════════


class TestFilepathCollision:
    """Test _save_note collision handling."""

    def test_same_id_overwrites(self, tmp_path):
        system = _create_system(persist_dir=str(tmp_path))
        note = MemoryNote(content="v1", id="same-id", name="same-name")
        system._save_note(note, touch_modified=False)

        note.content = "v2"
        system._save_note(note, touch_modified=False)

        notes_dir = os.path.join(str(tmp_path), "notes")
        md_files = list(Path(notes_dir).rglob("*.md"))
        assert len(md_files) == 1

    def test_different_id_same_hash_skips_duplicate(self, tmp_path):
        system = _create_system(persist_dir=str(tmp_path))
        note1 = MemoryNote(content="Same content", id="id-1", name="note-a")
        note1.refresh_hash()
        system._save_note(note1, touch_modified=False)

        note2 = MemoryNote(content="Same content", id="id-2", name="note-a")
        note2.refresh_hash()
        system._save_note(note2, touch_modified=False)

        notes_dir = os.path.join(str(tmp_path), "notes")
        md_files = list(Path(notes_dir).rglob("*.md"))
        assert len(md_files) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Dirty Flag & Sync Optimization
# ═══════════════════════════════════════════════════════════════════════════════


class TestDirtyFlag:
    """Test dirty flag and sync-to-disk optimization (F12)."""

    def test_add_note_sets_dirty(self):
        system = _create_system()
        assert system._dirty is False
        system.add_note("test", skip_evolution=True)
        assert system._dirty is True

    def test_sync_to_disk_clears_dirty(self, tmp_path):
        system = _create_system(persist_dir=str(tmp_path))
        system.add_note("test", skip_evolution=True)
        assert system._dirty is True
        system.sync_to_disk()
        assert system._dirty is False

    def test_no_changes_skips_merge(self, tmp_path):
        system = _create_system(persist_dir=str(tmp_path))
        system.add_note("test", skip_evolution=True)
        system.sync_to_disk()
        result = system.sync_to_disk()
        assert result["merge"].get("skipped") is True


# ═══════════════════════════════════════════════════════════════════════════════
# 11. _build_note_metadata
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildNoteMetadata:
    """Test _build_note_metadata helper."""

    def test_includes_all_fields(self):
        from dashboard.agentic_memory.memory_system import AgenticMemorySystem
        note = MemoryNote(
            content="test",
            id="test-id",
            keywords=["k1"],
            tags=["t1"],
            context="Engineering",
        )
        meta = AgenticMemorySystem._build_note_metadata(note)
        assert meta["id"] == "test-id"
        assert meta["content"] == "test"
        assert meta["keywords"] == ["k1"]
        assert meta["tags"] == ["t1"]
        assert meta["context"] == "Engineering"
        assert "content_hash" in meta
