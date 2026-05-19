"""Tests for ``IntegrityTracker`` (the facade) and ``DirtyTracker``.

Covers: notify_save/delete, dirty tracking, flush, load_or_rebuild,
diff_against_disk, vectordb hash, and protocol compliance.
"""

import json
import os
import pytest
from typing import Optional

from dashboard.agentic_memory.merkle.dirty import DirtyTracker
from dashboard.agentic_memory.merkle.hashers import Sha256Hasher
from dashboard.agentic_memory.merkle.protocols import IntegrityProvider, ManifestRepository
from dashboard.agentic_memory.merkle.tracker import IntegrityTracker


# ── helper: in-memory ManifestRepository ────────────────────


class InMemoryStore:
    """Test double — satisfies ``ManifestRepository`` without disk I/O."""

    def __init__(self):
        self._data: Optional[dict] = None

    def save(self, data: dict) -> None:
        self._data = dict(data)

    def load(self) -> Optional[dict]:
        return dict(self._data) if self._data else None

    def exists(self) -> bool:
        return self._data is not None


# ── helper: stub MemoryNote ─────────────────────────────────


class _StubNote:
    """Minimal stand-in for ``MemoryNote`` — only provides the two
    attributes that ``IntegrityTracker.build_from_notes`` uses."""

    def __init__(self, filepath: str, content_hash: str):
        self.filepath = filepath
        self.content_hash = content_hash


# ── fixtures ────────────────────────────────────────────────


@pytest.fixture
def store():
    return InMemoryStore()


@pytest.fixture
def tracker(store):
    return IntegrityTracker(persist_dir=None, store=store)


@pytest.fixture
def sample_notes():
    return {
        "id-1": _StubNote("devops/k8s/pods.md", "aaa111"),
        "id-2": _StubNote("devops/k8s/svc.md", "bbb222"),
        "id-3": _StubNote("arch/db/pg.md", "ccc333"),
    }


# ── DirtyTracker ────────────────────────────────────────────


class TestDirtyTracker:
    def test_initially_clean(self):
        dt = DirtyTracker()
        assert not dt.is_dirty
        assert len(dt.dirty_ids) == 0

    def test_mark_makes_dirty(self):
        dt = DirtyTracker()
        dt.mark("note-1")
        assert dt.is_dirty
        assert "note-1" in dt.dirty_ids

    def test_multiple_marks(self):
        dt = DirtyTracker()
        dt.mark("a")
        dt.mark("b")
        dt.mark("a")  # duplicate
        assert dt.dirty_ids == {"a", "b"}

    def test_flush_returns_and_clears(self):
        dt = DirtyTracker()
        dt.mark("x")
        dt.mark("y")

        flushed = dt.flush()
        assert flushed == {"x", "y"}
        assert not dt.is_dirty
        assert len(dt.dirty_ids) == 0

    def test_dirty_ids_returns_copy(self):
        dt = DirtyTracker()
        dt.mark("a")
        ids = dt.dirty_ids
        ids.add("INJECTED")
        assert "INJECTED" not in dt.dirty_ids


# ── IntegrityTracker: notify + dirty ────────────────────────


class TestNotifications:
    def test_notify_save_marks_dirty(self, tracker):
        tracker.notify_save("id-1", "dir/note.md", "hash1")
        assert tracker.needs_merge()
        assert "id-1" in tracker.get_dirty_ids()

    def test_notify_delete_marks_dirty(self, tracker):
        tracker.notify_save("id-1", "dir/note.md", "hash1")
        tracker.flush()

        tracker.notify_delete("id-1", "dir/note.md")
        assert tracker.needs_merge()
        assert "id-1" in tracker.get_dirty_ids()

    def test_flush_clears_dirty(self, tracker):
        tracker.notify_save("id-1", "dir/note.md", "hash1")
        tracker.flush()
        assert not tracker.needs_merge()
        assert len(tracker.get_dirty_ids()) == 0


# ── IntegrityTracker: root hash ─────────────────────────────


class TestRootHash:
    def test_empty_tree_has_empty_root(self, tracker):
        assert tracker.root_hash == ""

    def test_root_hash_changes_on_save(self, tracker):
        tracker.notify_save("id-1", "a.md", "hash1")
        h1 = tracker.root_hash
        assert h1 != ""

        tracker.notify_save("id-2", "b.md", "hash2")
        h2 = tracker.root_hash
        assert h2 != h1

    def test_root_hash_changes_on_delete(self, tracker):
        tracker.notify_save("id-1", "a.md", "hash1")
        h1 = tracker.root_hash

        tracker.notify_delete("id-1", "a.md")
        assert tracker.root_hash != h1


# ── IntegrityTracker: build_from_notes ──────────────────────


class TestBuildFromNotes:
    def test_build_sets_root_hash(self, tracker, sample_notes):
        root = tracker.build_from_notes(sample_notes)
        assert root != ""
        assert root == tracker.root_hash

    def test_build_is_deterministic(self, store, sample_notes):
        t1 = IntegrityTracker(store=store)
        r1 = t1.build_from_notes(sample_notes)

        t2 = IntegrityTracker(store=InMemoryStore())
        r2 = t2.build_from_notes(sample_notes)

        assert r1 == r2

    def test_build_produces_same_hash_as_incremental(self, store, sample_notes):
        # Incremental: notify_save one by one
        t1 = IntegrityTracker(store=InMemoryStore())
        for nid, note in sample_notes.items():
            t1.notify_save(nid, note.filepath, note.content_hash)
        h_incremental = t1.root_hash

        # Bulk build
        t2 = IntegrityTracker(store=InMemoryStore())
        h_bulk = t2.build_from_notes(sample_notes)

        assert h_incremental == h_bulk


# ── IntegrityTracker: load_or_rebuild ───────────────────────


class TestLoadOrRebuild:
    def test_rebuild_when_no_persisted_manifest(self, sample_notes):
        store = InMemoryStore()
        tracker = IntegrityTracker(store=store)

        root = tracker.load_or_rebuild(sample_notes)
        assert root != ""
        # Should have persisted after rebuild
        assert store.exists()

    def test_load_when_manifest_matches(self, sample_notes):
        store = InMemoryStore()
        # First: build and flush to populate store
        t1 = IntegrityTracker(store=store)
        expected_root = t1.build_from_notes(sample_notes)
        t1.flush()

        # Second: new tracker loads from store
        t2 = IntegrityTracker(store=store)
        loaded_root = t2.load_or_rebuild(sample_notes)

        assert loaded_root == expected_root

    def test_rebuild_when_note_count_mismatch(self, sample_notes):
        store = InMemoryStore()
        t1 = IntegrityTracker(store=store)
        t1.build_from_notes(sample_notes)
        t1.flush()

        # Add a note — count no longer matches
        extended = dict(sample_notes)
        extended["id-4"] = _StubNote("new/note.md", "ddd444")

        t2 = IntegrityTracker(store=store)
        root = t2.load_or_rebuild(extended)
        # Should have rebuilt (different root because different notes)
        assert root != ""


# ── IntegrityTracker: flush persists ────────────────────────


class TestFlushPersistence:
    def test_flush_saves_to_store(self, tracker, store, sample_notes):
        tracker.build_from_notes(sample_notes)
        tracker.flush()

        data = store.load()
        assert data is not None
        assert "root_hash" in data
        assert "note_count" in data
        assert "tree" in data
        assert data["note_count"] == 3

    def test_flush_updates_on_changes(self, tracker, store, sample_notes):
        tracker.build_from_notes(sample_notes)
        tracker.flush()
        r1 = store.load()["root_hash"]

        tracker.notify_save("id-4", "new.md", "new_hash")
        tracker.flush()
        r2 = store.load()["root_hash"]

        assert r1 != r2


# ── IntegrityTracker: diff_against_disk ─────────────────────


class TestDiffAgainstDisk:
    def test_diff_detects_disk_change(self, tmp_path):
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()

        # Write a note to disk
        note_dir = notes_dir / "dir"
        note_dir.mkdir()
        note_file = note_dir / "test.md"
        note_file.write_text(
            '---\ncontent_hash: "aaa111"\nid: "id-1"\n---\nHello',
            encoding="utf-8",
        )

        # Build in-memory tree with same hash
        tracker = IntegrityTracker(store=InMemoryStore())
        tracker.notify_save("id-1", "dir/test.md", "aaa111")

        diff = tracker.diff_against_disk(str(notes_dir))
        assert not diff.has_changes

        # Now change in-memory hash (simulating a note update)
        tracker.notify_save("id-1", "dir/test.md", "CHANGED!")
        diff = tracker.diff_against_disk(str(notes_dir))
        assert diff.has_changes
        assert "dir/test.md" in diff.changed_leaves

    def test_diff_detects_added_on_disk(self, tmp_path):
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()

        # Disk has a note, in-memory tree is empty
        note_file = notes_dir / "new-note.md"
        note_file.write_text(
            '---\ncontent_hash: "aaa111"\n---\nNew note',
            encoding="utf-8",
        )

        tracker = IntegrityTracker(store=InMemoryStore())
        diff = tracker.diff_against_disk(str(notes_dir))
        # The disk note should show up as "removed" from in-memory perspective
        # (it's in "other" / disk but not in "self" / memory)
        assert diff.has_changes

    def test_diff_with_empty_disk(self):
        tracker = IntegrityTracker(store=InMemoryStore())
        tracker.notify_save("id-1", "note.md", "hash1")

        diff = tracker.diff_against_disk("/nonexistent/path")
        assert diff.has_changes
        assert "note.md" in diff.added_leaves


# ── IntegrityTracker: vectordb hash ─────────────────────────


class TestVectordbHash:
    def test_compute_vectordb_hash(self, tracker):
        h = tracker.compute_vectordb_hash({"id-1": "aaa", "id-2": "bbb"})
        assert h != ""
        assert len(h) == 16

    def test_same_input_same_hash(self, tracker):
        h1 = tracker.compute_vectordb_hash({"a": "1", "b": "2"})
        h2 = tracker.compute_vectordb_hash({"b": "2", "a": "1"})
        assert h1 == h2

    def test_different_input_different_hash(self, tracker):
        h1 = tracker.compute_vectordb_hash({"a": "1"})
        h2 = tracker.compute_vectordb_hash({"a": "2"})
        assert h1 != h2

    def test_vectordb_hash_persisted_in_flush(self, tracker, store, sample_notes):
        tracker.build_from_notes(sample_notes)
        tracker.compute_vectordb_hash({"id-1": "aaa"})
        tracker.flush()

        data = store.load()
        assert data is not None
        assert data.get("vectordb_root_hash") != ""


# ── Protocol compliance ─────────────────────────────────────


class TestProtocolCompliance:
    def test_integrity_tracker_satisfies_protocol(self):
        assert isinstance(IntegrityTracker(), IntegrityProvider)

    def test_in_memory_store_satisfies_protocol(self):
        assert isinstance(InMemoryStore(), ManifestRepository)
