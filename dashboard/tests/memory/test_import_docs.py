"""Tests for import_docs — bulk importing .md files into the memory system.

Uses FakeRetriever and mocked LLM to avoid heavy ML imports.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from dashboard.agentic_memory.memory_note import MemoryNote
from dashboard.agentic_memory.memory_system import AgenticMemorySystem


class FakeRetriever:
    """Minimal in-memory stand-in for ZvecRetriever."""

    def __init__(self):
        self.docs = {}

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


def _make_system(persist_dir):
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
    sys.conflict_resolution = "last_modified"
    sys.evo_cnt = 0
    sys.evo_threshold = 5
    # Mock completion function so analyze_content returns deterministic results
    sys._completion_fn = MagicMock(
        return_value=(
            '{"name": "test-note", "path": "test", '
            '"keywords": ["k1", "k2"], "context": "Test context", '
            '"tags": ["tag1", "tag2"]}'
        )
    )
    sys._embed_fn = lambda texts: [[0.0] * 768 for _ in texts]
    sys._evolution_system_prompt = ""
    sys._dirty = False
    return sys


def _create_docs_dir(base_dir, files):
    """Create a docs/ directory with given files.

    Args:
        base_dir: Parent directory (persist_dir)
        files: dict of {relative_path: content}
    """
    docs_dir = os.path.join(base_dir, "docs")
    for rel_path, content in files.items():
        filepath = os.path.join(docs_dir, rel_path)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
    return docs_dir


class TestImportDocs(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sys = _make_system(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_imports_single_file(self):
        """A single .md file should be imported as a memory note."""
        docs_dir = _create_docs_dir(
            self.tmpdir,
            {
                "getting-started.md": "# Getting Started\n\nThis is the intro doc.",
            },
        )

        result = self.sys.import_docs(docs_dir)

        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(len(self.sys.memories), 1)

        # Check the imported note
        note = list(self.sys.memories.values())[0]
        self.assertEqual(note.content, "# Getting Started\n\nThis is the intro doc.")

    def test_preserves_directory_structure_as_path(self):
        """Subdirectory structure should become the note's path."""
        docs_dir = _create_docs_dir(
            self.tmpdir,
            {
                "backend/database/postgres-tips.md": "Use JSONB for flexible schemas.",
                "frontend/react/hooks.md": "useEffect runs after render.",
            },
        )

        result = self.sys.import_docs(docs_dir)

        self.assertEqual(result["imported"], 2)

        # Find notes by content
        notes = list(self.sys.memories.values())
        pg_note = [n for n in notes if "JSONB" in n.content][0]
        react_note = [n for n in notes if "useEffect" in n.content][0]

        # Name derived from filename, path from directory
        self.assertEqual(pg_note.name, "postgres-tips")
        self.assertEqual(react_note.name, "hooks")

    def test_renames_docs_dir_with_timestamp(self):
        """docs/ should be renamed to .docs_imported_<timestamp> after import."""
        docs_dir = _create_docs_dir(
            self.tmpdir,
            {
                "note.md": "Some content here.",
            },
        )

        result = self.sys.import_docs(docs_dir)

        # Original docs/ should not exist
        self.assertFalse(os.path.exists(docs_dir))
        # Renamed dir should exist
        self.assertTrue(os.path.exists(result["renamed_to"]))
        self.assertIn(".docs_imported_", result["renamed_to"])

    def test_skips_non_md_files(self):
        """Only .md files should be imported."""
        docs_dir = _create_docs_dir(
            self.tmpdir,
            {
                "readme.md": "Import this.",
                "config.json": '{"key": "value"}',
                "script.py": "print('hello')",
                "notes.txt": "Skip this too.",
            },
        )

        result = self.sys.import_docs(docs_dir)

        self.assertEqual(result["imported"], 1)
        self.assertEqual(len(self.sys.memories), 1)

    def test_skips_empty_files(self):
        """Empty .md files should be skipped."""
        docs_dir = _create_docs_dir(
            self.tmpdir,
            {
                "empty.md": "",
                "whitespace.md": "   \n\n  ",
                "real.md": "Real content here.",
            },
        )

        result = self.sys.import_docs(docs_dir)

        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["skipped"], 2)

    def test_skips_duplicate_content(self):
        """Files with content that already exists in memory should be skipped."""
        # Pre-populate memory with a note
        existing = MemoryNote(
            content="Already in memory",
            id="existing-001",
            name="Existing",
        )
        self.sys.memories["existing-001"] = existing

        docs_dir = _create_docs_dir(
            self.tmpdir,
            {
                "duplicate.md": "Already in memory",
                "new-note.md": "This is new content.",
            },
        )

        result = self.sys.import_docs(docs_dir)

        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["skipped"], 1)

    def test_concurrent_agent_skips_already_renamed(self):
        """If another agent already renamed docs/, import should return error."""
        docs_dir = os.path.join(self.tmpdir, "docs")
        # docs/ doesn't exist — another agent already renamed it

        result = self.sys.import_docs(docs_dir)

        self.assertIn("error", result)

    def test_no_docs_dir_returns_error(self):
        """Non-existent docs_dir should return error."""
        result = self.sys.import_docs("/nonexistent/path")
        self.assertIn("error", result)

    def test_llm_analysis_called_for_each_doc(self):
        """LLM should be called to generate tags/keywords/context."""
        docs_dir = _create_docs_dir(
            self.tmpdir,
            {
                "doc1.md": "First document content.",
                "doc2.md": "Second document content.",
            },
        )

        self.sys.import_docs(docs_dir)

        # LLM should have been called at least twice (once per doc)
        self.assertGreaterEqual(self.sys._completion_fn.call_count, 2)

    def test_notes_written_to_disk(self):
        """Imported notes should be persisted to notes/ on disk."""
        docs_dir = _create_docs_dir(
            self.tmpdir,
            {
                "architecture/overview.md": "System architecture overview.",
            },
        )

        self.sys.import_docs(docs_dir)

        # Check that a .md file was written to notes/
        notes_files = []
        for dirpath, _, filenames in os.walk(self.sys._notes_dir):
            for f in filenames:
                if f.endswith(".md"):
                    notes_files.append(os.path.join(dirpath, f))
        self.assertEqual(len(notes_files), 1)

    def test_notes_added_to_vectordb(self):
        """Imported notes should have vectors in the retriever."""
        docs_dir = _create_docs_dir(
            self.tmpdir,
            {
                "tip.md": "A useful tip for developers.",
            },
        )

        self.sys.import_docs(docs_dir)

        self.assertEqual(len(self.sys.retriever.docs), 1)


if __name__ == "__main__":
    unittest.main()
