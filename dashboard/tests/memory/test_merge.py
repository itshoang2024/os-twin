"""Tests for the bidirectional merge_from_disk and updated sync_to_disk.

These tests use a FakeRetriever to avoid heavy ML imports (embeddings, zvec)
and LLM calls, keeping them fast and deterministic.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from dashboard.agentic_memory.memory_note import MemoryNote
from dashboard.agentic_memory.memory_system import AgenticMemorySystem


class FakeRetriever:
    """Minimal in-memory stand-in for ZvecRetriever / ChromaRetriever."""

    def __init__(self):
        self.docs = {}  # {doc_id: (document, metadata)}

    def add_document(self, document, metadata, doc_id):
        self.docs[doc_id] = (document, metadata)

    def has_document(self, doc_id):
        return doc_id in self.docs

    def existing_ids(self, doc_ids):
        return {did for did in doc_ids if did in self.docs}

    def get_stored_hashes(self, doc_ids):
        out = {}
        for did in doc_ids:
            if did in self.docs:
                _, metadata = self.docs[did]
                out[did] = metadata.get("content_hash") if metadata else None
        return out

    def delete_document(self, doc_id):
        self.docs.pop(doc_id, None)

    def clear(self):
        self.docs.clear()

    def search(self, query, k=5):
        return {"ids": [[]], "metadatas": [[]], "distances": [[]]}


def _make_system(persist_dir, conflict_resolution="last_modified"):
    """Build an AgenticMemorySystem with heavy init bypassed."""
    sys = object.__new__(AgenticMemorySystem)
    sys.memories = {}
    sys.persist_dir = persist_dir
    sys._notes_dir = os.path.join(persist_dir, "notes")
    sys._vector_dir = os.path.join(persist_dir, "vectordb")
    os.makedirs(sys._notes_dir, exist_ok=True)
    os.makedirs(sys._vector_dir, exist_ok=True)
    sys.retriever = FakeRetriever()
    sys.model_name = "gemini-embedding-001"
    sys.embedding_backend = "gemini"
    sys.vector_backend = "test"
    sys.context_aware_analysis = False
    sys.context_aware_tree = False
    sys.max_links = 3
    sys.similarity_weight = 0.8
    sys.decay_half_life_days = 30.0
    sys.conflict_resolution = conflict_resolution
    sys.evo_cnt = 0
    sys.evo_threshold = 5
    sys._completion_fn = None
    sys._embed_fn = lambda texts: [[0.0] * 768 for _ in texts]
    sys._evolution_system_prompt = ""
    sys._dirty = True
    return sys


def _write_note_to_disk(notes_dir, note):
    """Write a MemoryNote markdown file directly to notes_dir."""
    filepath = os.path.join(notes_dir, note.filepath)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(note.to_markdown())


class TestMergeFromDisk(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sys = _make_system(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    # ---- Case 1: disk-only notes are adopted ----

    def test_disk_only_note_added_to_memory(self):
        """A note on disk but not in memory should be added."""
        disk_note = MemoryNote(
            content="I exist only on disk",
            id="disk-only-001",
            name="Disk Only",
            path="test",
            timestamp="202601010000",
        )
        _write_note_to_disk(self.sys._notes_dir, disk_note)

        result = self.sys.merge_from_disk()

        self.assertEqual(result["added_from_disk"], 1)
        self.assertIn("disk-only-001", self.sys.memories)
        self.assertIn("disk-only-001", self.sys.retriever.docs)

    # ---- Case 2: memory-only notes are kept ----

    def test_memory_only_note_preserved(self):
        """A note in memory but not on disk should be kept (not deleted)."""
        mem_note = MemoryNote(
            content="I exist only in memory",
            id="mem-only-001",
            name="Memory Only",
        )
        self.sys.memories["mem-only-001"] = mem_note

        result = self.sys.merge_from_disk()

        self.assertEqual(result["memory_only"], 1)
        self.assertIn("mem-only-001", self.sys.memories)

    # ---- Case 3: identical notes are unchanged ----

    def test_identical_notes_unchanged(self):
        """Same content on both sides → no action."""
        note = MemoryNote(
            content="Same content everywhere",
            id="same-001",
            name="Same Note",
            timestamp="202601010000",
        )
        self.sys.memories["same-001"] = note
        _write_note_to_disk(self.sys._notes_dir, note)

        result = self.sys.merge_from_disk()

        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(result["added_from_disk"], 0)
        self.assertEqual(result["updated_from_disk"], 0)
        self.assertEqual(result["updated_from_memory"], 0)

    # ---- Case 4a: conflict → disk wins (disk is newer) ----

    def test_conflict_disk_wins_when_newer(self):
        """When content differs, the version with latest last_modified wins."""
        mem_note = MemoryNote(
            content="Old memory content",
            id="conflict-001",
            name="Conflict",
            last_modified="202601010000",
        )
        self.sys.memories["conflict-001"] = mem_note
        # Put a vector for the old version
        self.sys.retriever.add_document("old", {}, "conflict-001")

        disk_note = MemoryNote(
            content="Updated disk content",
            id="conflict-001",
            name="Conflict",
            last_modified="202601020000",  # newer
        )
        _write_note_to_disk(self.sys._notes_dir, disk_note)

        result = self.sys.merge_from_disk()

        self.assertEqual(result["updated_from_disk"], 1)
        self.assertEqual(self.sys.memories["conflict-001"].content, "Updated disk content")
        # Vector should have been re-added
        self.assertIn("conflict-001", self.sys.retriever.docs)

    # ---- Case 4b: conflict → memory wins (memory is newer) ----

    def test_conflict_memory_wins_when_newer(self):
        """When memory is newer, keep the in-memory version."""
        mem_note = MemoryNote(
            content="Fresh memory content",
            id="conflict-002",
            name="Conflict",
            last_modified="202601020000",  # newer
        )
        self.sys.memories["conflict-002"] = mem_note

        disk_note = MemoryNote(
            content="Stale disk content",
            id="conflict-002",
            name="Conflict",
            last_modified="202601010000",
        )
        _write_note_to_disk(self.sys._notes_dir, disk_note)

        result = self.sys.merge_from_disk()

        self.assertEqual(result["updated_from_memory"], 1)
        self.assertEqual(self.sys.memories["conflict-002"].content, "Fresh memory content")

    # ---- Case 4c: conflict tie → disk wins ----

    def test_conflict_tie_disk_wins(self):
        """When both have the same last_modified, disk wins."""
        same_ts = "202601010000"
        mem_note = MemoryNote(
            content="Memory version",
            id="tie-001",
            name="Tie",
            last_modified=same_ts,
        )
        self.sys.memories["tie-001"] = mem_note

        disk_note = MemoryNote(
            content="Disk version",
            id="tie-001",
            name="Tie",
            last_modified=same_ts,
        )
        _write_note_to_disk(self.sys._notes_dir, disk_note)

        result = self.sys.merge_from_disk()

        self.assertEqual(result["updated_from_disk"], 1)
        self.assertEqual(self.sys.memories["tie-001"].content, "Disk version")

    # ---- Multi-agent simulation ----

    def test_multi_agent_merge_scenario(self):
        """Simulate two agents: A has notes 1,2; disk has notes 2,3.
        Note 2 has a conflict (different content)."""
        # Agent A's in-memory state
        note1 = MemoryNote(
            content="Agent A created this",
            id="note-1",
            name="Note One",
            last_modified="202601010100",
        )
        note2_mem = MemoryNote(
            content="Agent A's version of note 2",
            id="note-2",
            name="Note Two",
            last_modified="202601010200",  # older
        )
        self.sys.memories["note-1"] = note1
        self.sys.memories["note-2"] = note2_mem

        # Agent B wrote note 2 (newer) and note 3 to disk
        note2_disk = MemoryNote(
            content="Agent B's version of note 2",
            id="note-2",
            name="Note Two",
            last_modified="202601010300",  # newer
        )
        note3 = MemoryNote(
            content="Agent B created this",
            id="note-3",
            name="Note Three",
            last_modified="202601010300",
        )
        _write_note_to_disk(self.sys._notes_dir, note2_disk)
        _write_note_to_disk(self.sys._notes_dir, note3)

        result = self.sys.merge_from_disk()

        # note-1: memory only (kept)
        self.assertIn("note-1", self.sys.memories)
        self.assertEqual(result["memory_only"], 1)

        # note-2: conflict, disk wins (newer)
        self.assertEqual(
            self.sys.memories["note-2"].content,
            "Agent B's version of note 2",
        )
        self.assertEqual(result["updated_from_disk"], 1)

        # note-3: disk only (adopted)
        self.assertIn("note-3", self.sys.memories)
        self.assertEqual(result["added_from_disk"], 1)

    # ---- Backwards compat: notes without last_modified ----

    def test_legacy_note_without_last_modified(self):
        """Old notes without last_modified should fallback to timestamp."""
        mem_note = MemoryNote(
            content="Legacy memory",
            id="legacy-001",
            name="Legacy",
            timestamp="202601010000",
        )
        # Simulate a pre-existing note without last_modified
        mem_note.last_modified = None
        self.sys.memories["legacy-001"] = mem_note

        disk_note = MemoryNote(
            content="Updated on disk",
            id="legacy-001",
            name="Legacy",
            timestamp="202601020000",
        )
        disk_note.last_modified = None
        _write_note_to_disk(self.sys._notes_dir, disk_note)

        result = self.sys.merge_from_disk()

        # disk timestamp is newer, disk should win
        self.assertEqual(result["updated_from_disk"], 1)
        self.assertEqual(self.sys.memories["legacy-001"].content, "Updated on disk")

    # ---- Vectordb consistency repair ----

    def test_missing_vector_repaired(self):
        """A note in memory with no vector should be re-embedded after merge."""
        note = MemoryNote(
            content="I have no vector",
            id="orphan-001",
            name="Orphan",
        )
        # Add to memories but NOT to retriever (simulates crash between
        # _save_note and retriever.add_document)
        self.sys.memories["orphan-001"] = note
        _write_note_to_disk(self.sys._notes_dir, note)

        self.assertFalse(self.sys.retriever.has_document("orphan-001"))

        result = self.sys.merge_from_disk()

        self.assertEqual(result["vectors_repaired"], 1)
        self.assertTrue(self.sys.retriever.has_document("orphan-001"))

    def test_no_repair_when_vector_exists(self):
        """Notes with existing vectors should not be re-embedded."""
        note = MemoryNote(
            content="I already have a vector",
            id="healthy-001",
            name="Healthy",
        )
        self.sys.memories["healthy-001"] = note
        self.sys.retriever.add_document("content", {"content_hash": note.content_hash}, "healthy-001")
        _write_note_to_disk(self.sys._notes_dir, note)

        result = self.sys.merge_from_disk()

        self.assertEqual(result["vectors_repaired"], 0)


class TestSyncToDisk(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sys = _make_system(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_sync_to_disk_merges_first(self):
        """sync_to_disk should pick up disk-only notes before writing."""
        # Agent A has note-1 in memory
        note1 = MemoryNote(
            content="Agent A's note",
            id="note-1",
            name="Note One",
        )
        self.sys.memories["note-1"] = note1

        # Agent B wrote note-2 to disk
        note2 = MemoryNote(
            content="Agent B's note",
            id="note-2",
            name="Note Two",
        )
        _write_note_to_disk(self.sys._notes_dir, note2)

        result = self.sys.sync_to_disk()

        # Both notes should now be in memory
        self.assertIn("note-1", self.sys.memories)
        self.assertIn("note-2", self.sys.memories)
        self.assertEqual(result["written"], 2)
        self.assertEqual(result["merge"]["added_from_disk"], 1)

    def test_sync_to_disk_does_not_delete_foreign_notes(self):
        """sync_to_disk should NOT remove files it doesn't own."""
        # Write a "foreign" note to disk (not in memory)
        foreign = MemoryNote(
            content="I belong to another agent",
            id="foreign-001",
            name="Foreign",
        )
        _write_note_to_disk(self.sys._notes_dir, foreign)

        # Agent has its own note in memory
        own = MemoryNote(
            content="My own note",
            id="own-001",
            name="Own",
        )
        self.sys.memories["own-001"] = own

        self.sys.sync_to_disk()

        # Foreign note should still exist on disk
        foreign_path = os.path.join(self.sys._notes_dir, foreign.filepath)
        self.assertTrue(os.path.exists(foreign_path))

    def test_sync_to_disk_writes_all_notes(self):
        """All in-memory notes should be written to disk."""
        for i in range(5):
            self.sys.memories[f"n-{i}"] = MemoryNote(
                content=f"Note {i}",
                id=f"n-{i}",
                name=f"Note {i}",
            )

        result = self.sys.sync_to_disk()
        self.assertEqual(result["written"], 5)

        # Verify files exist
        for i in range(5):
            note = self.sys.memories[f"n-{i}"]
            path = os.path.join(self.sys._notes_dir, note.filepath)
            self.assertTrue(os.path.exists(path))


class TestLastModifiedField(unittest.TestCase):
    def test_roundtrip_preserves_last_modified(self):
        """last_modified should survive to_markdown → from_markdown."""
        note = MemoryNote(
            content="Test content",
            id="rt-001",
            last_modified="202603151430",
        )
        restored = MemoryNote.from_markdown(note.to_markdown())
        self.assertEqual(restored.last_modified, "202603151430")

    def test_defaults_to_timestamp_when_missing(self):
        """Old notes without last_modified should default to timestamp."""
        note = MemoryNote(
            content="Old note",
            timestamp="202601010000",
        )
        self.assertEqual(note.last_modified, "202601010000")

    def test_save_note_touches_last_modified(self):
        """_save_note should update last_modified to current time."""
        tmpdir = tempfile.mkdtemp()
        try:
            sys = _make_system(tmpdir)
            note = MemoryNote(
                content="Touch test",
                id="touch-001",
                name="Touch",
                last_modified="202601010000",
            )
            old_modified = note.last_modified
            sys._save_note(note, touch_modified=True)
            self.assertNotEqual(note.last_modified, old_modified)
            self.assertGreater(note.last_modified, old_modified)
        finally:
            shutil.rmtree(tmpdir)

    def test_save_note_preserves_when_no_touch(self):
        """_save_note(touch_modified=False) should keep last_modified."""
        tmpdir = tempfile.mkdtemp()
        try:
            sys = _make_system(tmpdir)
            note = MemoryNote(
                content="Preserve test",
                id="preserve-001",
                name="Preserve",
                last_modified="202601010000",
            )
            sys._save_note(note, touch_modified=False)
            self.assertEqual(note.last_modified, "202601010000")
        finally:
            shutil.rmtree(tmpdir)


class TestFilepathCollision(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sys = _make_system(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_collision_same_hash_skips_write(self):
        """Two notes with same filepath and same hash = true duplicate, skip."""
        note_a = MemoryNote(
            content="Identical content",
            id="aaa",
            name="Tips",
            path="db",
            context="General",
            keywords=[],
            tags=[],
        )
        note_b = MemoryNote(
            content="Identical content",
            id="bbb",
            name="Tips",
            path="db",
            context="General",
            keywords=[],
            tags=[],
        )
        # Same hash
        self.assertEqual(note_a.content_hash, note_b.content_hash)

        self.sys._save_note(note_a)
        filepath = os.path.join(self.sys._notes_dir, note_a.filepath)

        # note_b writes to same path — should be skipped (duplicate)
        self.sys._save_note(note_b)

        # File should still contain note_a's ID
        with open(filepath, "r") as f:
            self.assertIn("aaa", f.read())

    def test_collision_different_hash_newer_wins(self):
        """Two notes with same filepath but different hash — last_modified wins."""
        note_old = MemoryNote(
            content="Old content",
            id="old-id",
            name="Tips",
            path="db",
            last_modified="202601010000",
        )
        note_new = MemoryNote(
            content="New content",
            id="new-id",
            name="Tips",
            path="db",
            last_modified="202601020000",
        )

        # Write old note first
        self.sys._save_note(note_old, touch_modified=False)
        filepath = os.path.join(self.sys._notes_dir, note_old.filepath)

        # Write newer note — should overwrite
        self.sys._save_note(note_new, touch_modified=False)
        with open(filepath, "r") as f:
            content = f.read()
        self.assertIn("new-id", content)
        self.assertIn("New content", content)

    def test_collision_existing_is_newer_keeps_existing(self):
        """When existing file is newer, new write is rejected."""
        note_existing = MemoryNote(
            content="I am newer on disk",
            id="exist-id",
            name="Tips",
            path="db",
            last_modified="202601020000",
        )
        note_incoming = MemoryNote(
            content="I am older trying to write",
            id="incoming-id",
            name="Tips",
            path="db",
            last_modified="202601010000",
        )

        self.sys._save_note(note_existing, touch_modified=False)
        filepath = os.path.join(self.sys._notes_dir, note_existing.filepath)

        # Incoming is older — should be rejected
        self.sys._save_note(note_incoming, touch_modified=False)
        with open(filepath, "r") as f:
            content = f.read()
        self.assertIn("exist-id", content)
        self.assertNotIn("incoming-id", content)

    def test_same_id_overwrites_normally(self):
        """Updating the same note (same UUID) should overwrite in place."""
        note = MemoryNote(
            content="Version 1",
            id="same-001",
            name="Same Note",
        )
        self.sys._save_note(note)

        note.content = "Version 2"
        self.sys._save_note(note)

        filepath = os.path.join(self.sys._notes_dir, note.filepath)
        with open(filepath, "r") as f:
            content = f.read()
        self.assertIn("Version 2", content)
        self.assertNotIn("Version 1", content)


class TestContentHash(unittest.TestCase):
    def test_hash_deterministic(self):
        """Same content/metadata should always produce same hash."""
        note = MemoryNote(
            content="Test content",
            keywords=["a", "b"],
            tags=["x"],
            context="Testing",
        )
        h1 = note.compute_hash()
        h2 = note.compute_hash()
        self.assertEqual(h1, h2)

    def test_hash_changes_with_content(self):
        note = MemoryNote(content="Version 1")
        h1 = note.content_hash
        note.content = "Version 2"
        note.refresh_hash()
        self.assertNotEqual(h1, note.content_hash)

    def test_hash_changes_with_tags(self):
        note = MemoryNote(content="Same", tags=["a"])
        h1 = note.content_hash
        note.tags = ["a", "b"]
        note.refresh_hash()
        self.assertNotEqual(h1, note.content_hash)

    def test_hash_roundtrip(self):
        """Hash should survive to_markdown → from_markdown."""
        note = MemoryNote(content="Roundtrip", tags=["test"])
        original_hash = note.content_hash
        restored = MemoryNote.from_markdown(note.to_markdown())
        self.assertEqual(restored.content_hash, original_hash)

    def test_hash_order_independent(self):
        """Keyword/tag order shouldn't affect hash (sorted internally)."""
        note_a = MemoryNote(content="X", keywords=["b", "a"], tags=["y", "x"])
        note_b = MemoryNote(content="X", keywords=["a", "b"], tags=["x", "y"])
        self.assertEqual(note_a.compute_hash(), note_b.compute_hash())

    def test_legacy_note_without_hash(self):
        """Old notes without content_hash should compute it on access."""
        note = MemoryNote(content="Old note")
        note._content_hash = None
        h = note.content_hash  # should auto-compute
        self.assertIsNotNone(h)
        self.assertEqual(len(h), 16)


if __name__ == "__main__":
    unittest.main()
