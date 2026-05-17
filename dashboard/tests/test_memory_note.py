"""Unit tests for MemoryNote — the canonical on-disk shape for a single memory.

Covers:
  - Construction and default values
  - Content hashing (compute_hash, refresh_hash, content_hash property)
  - Slugify and filepath generation
  - Markdown serialization / deserialization round-trip
  - Knowledge link and memory link extraction
  - Edge cases (empty fields, special characters, missing metadata)
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from dashboard.agentic_memory.memory_note import MemoryNote


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Construction & Defaults
# ═══════════════════════════════════════════════════════════════════════════════


class TestMemoryNoteConstruction:
    """Test MemoryNote construction and default values."""

    def test_basic_construction(self):
        note = MemoryNote(content="Hello world")
        assert note.content == "Hello world"
        assert note.id is not None
        assert note.name is None
        assert note.path is None
        assert note.keywords == []
        assert note.links == []
        assert note.backlinks == []
        assert note.context == "General"
        assert note.category == "Uncategorized"
        assert note.tags == []
        assert note.retrieval_count == 0
        assert note.evolution_history == []
        assert note.summary is None

    def test_custom_id(self):
        note = MemoryNote(content="test", id="my-custom-id")
        assert note.id == "my-custom-id"

    def test_auto_generated_id_is_uuid(self):
        note = MemoryNote(content="test")
        # UUID v4 format: 8-4-4-4-12 hex chars
        import re
        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            note.id,
        )

    def test_timestamp_auto_generated(self):
        note = MemoryNote(content="test")
        assert note.timestamp is not None
        assert len(note.timestamp) == 12  # YYYYMMDDHHMM

    def test_last_accessed_defaults_to_timestamp(self):
        note = MemoryNote(content="test")
        assert note.last_accessed == note.timestamp

    def test_last_modified_defaults_to_timestamp(self):
        note = MemoryNote(content="test")
        assert note.last_modified == note.timestamp

    def test_custom_timestamp(self):
        note = MemoryNote(content="test", timestamp="202401011200",
                          last_accessed="202401011200",
                          last_modified="202401011200")
        assert note.timestamp == "202401011200"
        assert note.last_accessed == "202401011200"
        assert note.last_modified == "202401011200"

    def test_explicit_last_modified(self):
        note = MemoryNote(content="test", timestamp="202401011200",
                          last_modified="202406151500")
        assert note.timestamp == "202401011200"
        assert note.last_modified == "202406151500"

    def test_kwargs_backlinks(self):
        note = MemoryNote(content="test", backlinks=["id-1", "id-2"])
        assert note.backlinks == ["id-1", "id-2"]

    def test_kwargs_category(self):
        note = MemoryNote(content="test", category="Engineering")
        assert note.category == "Engineering"

    def test_kwargs_evolution_history(self):
        history = [{"action": "strengthen", "ts": "20240101"}]
        note = MemoryNote(content="test", evolution_history=history)
        assert note.evolution_history == history

    def test_kwargs_content_hash(self):
        note = MemoryNote(content="test", content_hash="abc123")
        assert note._content_hash == "abc123"

    def test_all_fields_set(self):
        note = MemoryNote(
            content="Test content",
            id="test-id",
            name="Test Note",
            path="backend/database",
            keywords=["postgres", "sql"],
            links=["other-id"],
            retrieval_count=5,
            timestamp="202401011200",
            last_accessed="202406151500",
            last_modified="202406151500",
            context="Database design",
            tags=["database", "sql"],
            summary="A short summary",
            backlinks=["back-id"],
            category="Engineering",
            evolution_history=[],
        )
        assert note.content == "Test content"
        assert note.id == "test-id"
        assert note.name == "Test Note"
        assert note.path == "backend/database"
        assert note.keywords == ["postgres", "sql"]
        assert note.links == ["other-id"]
        assert note.retrieval_count == 5
        assert note.timestamp == "202401011200"
        assert note.context == "Database design"
        assert note.tags == ["database", "sql"]
        assert note.summary == "A short summary"
        assert note.backlinks == ["back-id"]
        assert note.category == "Engineering"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Content Hashing
# ═══════════════════════════════════════════════════════════════════════════════


class TestMemoryNoteHashing:
    """Test content hashing for consistency checks and deduplication."""

    def test_compute_hash_deterministic(self):
        note = MemoryNote(content="Hello", context="General", keywords=[], tags=[])
        h1 = note.compute_hash()
        h2 = note.compute_hash()
        assert h1 == h2

    def test_compute_hash_length(self):
        note = MemoryNote(content="Hello")
        h = note.compute_hash()
        assert len(h) == 16  # SHA-256 truncated to 16 hex chars

    def test_content_hash_property(self):
        note = MemoryNote(content="Hello")
        # Should auto-compute if not cached
        assert note.content_hash is not None
        assert len(note.content_hash) == 16

    def test_content_hash_cached(self):
        note = MemoryNote(content="Hello")
        h1 = note.content_hash
        # Change content — hash should NOT change (cached)
        note.content = "Goodbye"
        h2 = note.content_hash
        assert h1 == h2

    def test_refresh_hash(self):
        note = MemoryNote(content="Hello")
        h1 = note.content_hash
        note.content = "Goodbye"
        h2 = note.refresh_hash()
        assert h2 != h1
        assert note.content_hash == h2

    def test_hash_depends_on_content(self):
        note1 = MemoryNote(content="Hello")
        note2 = MemoryNote(content="World")
        assert note1.compute_hash() != note2.compute_hash()

    def test_hash_depends_on_context(self):
        note1 = MemoryNote(content="Hello", context="General")
        note2 = MemoryNote(content="Hello", context="Engineering")
        assert note1.compute_hash() != note2.compute_hash()

    def test_hash_depends_on_keywords(self):
        note1 = MemoryNote(content="Hello", keywords=["a"])
        note2 = MemoryNote(content="Hello", keywords=["b"])
        assert note1.compute_hash() != note2.compute_hash()

    def test_hash_depends_on_tags(self):
        note1 = MemoryNote(content="Hello", tags=["x"])
        note2 = MemoryNote(content="Hello", tags=["y"])
        assert note1.compute_hash() != note2.compute_hash()

    def test_hash_order_independent_keywords(self):
        """Hash should be the same regardless of keyword order."""
        note1 = MemoryNote(content="Hello", keywords=["a", "b"])
        note2 = MemoryNote(content="Hello", keywords=["b", "a"])
        assert note1.compute_hash() == note2.compute_hash()

    def test_hash_order_independent_tags(self):
        """Hash should be the same regardless of tag order."""
        note1 = MemoryNote(content="Hello", tags=["x", "y"])
        note2 = MemoryNote(content="Hello", tags=["y", "x"])
        assert note1.compute_hash() == note2.compute_hash()

    def test_hash_does_not_depend_on_id(self):
        """Hash should NOT depend on the note ID."""
        note1 = MemoryNote(content="Hello", id="id-1")
        note2 = MemoryNote(content="Hello", id="id-2")
        assert note1.compute_hash() == note2.compute_hash()

    def test_hash_does_not_depend_on_name(self):
        """Hash should NOT depend on the note name."""
        note1 = MemoryNote(content="Hello", name="Note A")
        note2 = MemoryNote(content="Hello", name="Note B")
        assert note1.compute_hash() == note2.compute_hash()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Slugify & Filepath
# ═══════════════════════════════════════════════════════════════════════════════


class TestMemoryNoteSlugify:
    """Test slugification and filepath generation."""

    def test_slugify_simple(self):
        assert MemoryNote._slugify("Hello World") == "hello-world"

    def test_slugify_special_chars(self):
        assert MemoryNote._slugify("Hello! @World#") == "hello-world"

    def test_slugify_multiple_spaces(self):
        assert MemoryNote._slugify("Hello   World") == "hello-world"

    def test_slugify_underscores(self):
        assert MemoryNote._slugify("Hello_World") == "hello-world"

    def test_slugify_leading_trailing_hyphens(self):
        assert MemoryNote._slugify("--Hello World--") == "hello-world"

    def test_slugify_empty_string(self):
        assert MemoryNote._slugify("") == ""

    def test_slugify_unicode(self):
        result = MemoryNote._slugify("Über Köln")
        assert "über" in result or "ber" in result  # depends on \w matching

    def test_filename_from_name(self):
        note = MemoryNote(content="test", name="My Note Title")
        assert note.filename == "my-note-title"

    def test_filename_falls_back_to_id(self):
        note = MemoryNote(content="test", id="abc-123")
        assert note.filename == "abc-123"

    def test_filename_empty_name_falls_back(self):
        note = MemoryNote(content="test", name="", id="xyz")
        assert note.filename == "xyz"

    def test_filepath_no_path(self):
        note = MemoryNote(content="test", name="My Note")
        assert note.filepath == "my-note.md"

    def test_filepath_with_path(self):
        note = MemoryNote(content="test", name="Container Basics", path="devops/kubernetes")
        assert note.filepath == os.path.join("devops", "kubernetes", "container-basics.md")

    def test_filepath_with_deep_path(self):
        note = MemoryNote(content="test", name="Auth", path="backend/middleware/auth")
        assert note.filepath == os.path.join("backend", "middleware", "auth", "auth.md")

    def test_filepath_with_leading_slash(self):
        note = MemoryNote(content="test", name="Auth", path="/backend/auth")
        assert "backend" in note.filepath
        assert "auth.md" in note.filepath

    def test_filepath_empty_path_segments_skipped(self):
        note = MemoryNote(content="test", name="Auth", path="backend//auth")
        # Double slashes should be handled
        assert "auth.md" in note.filepath

    def test_filepath_slugifies_path_segments(self):
        note = MemoryNote(content="test", name="Auth", path="BackEnd/Middle Ware")
        # "BackEnd" has no word boundary so \w matches as-is => "backend"
        assert "backend" in note.filepath
        assert "middle-ware" in note.filepath


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Markdown Serialization / Deserialization
# ═══════════════════════════════════════════════════════════════════════════════


class TestMemoryNoteMarkdown:
    """Test Markdown round-trip serialization."""

    def test_to_markdown_has_frontmatter(self):
        note = MemoryNote(content="Hello world", id="test-id", name="Test")
        md = note.to_markdown()
        assert md.startswith("---\n")
        assert "---\n" in md[4:]  # closing frontmatter

    def test_to_markdown_includes_content(self):
        note = MemoryNote(content="Hello world")
        md = note.to_markdown()
        assert "Hello world" in md

    def test_to_markdown_includes_all_fields(self):
        note = MemoryNote(
            content="Test",
            id="test-id",
            name="Test Note",
            path="dev/test",
            keywords=["k1", "k2"],
            tags=["t1"],
        )
        md = note.to_markdown()
        assert "test-id" in md
        assert "Test Note" in md
        assert "dev/test" in md

    def test_to_markdown_includes_summary_when_set(self):
        note = MemoryNote(content="Test", summary="Short summary")
        md = note.to_markdown()
        assert "summary" in md
        assert "Short summary" in md

    def test_to_markdown_omits_summary_when_none(self):
        note = MemoryNote(content="Test", summary=None)
        md = note.to_markdown()
        # "summary" key should NOT appear in frontmatter
        lines = md.split("---")[1].strip().split("\n")
        keys = [line.split(":")[0].strip() for line in lines if ": " in line]
        assert "summary" not in keys

    def test_from_markdown_round_trip(self):
        """Deserializing a serialized note should preserve all fields."""
        original = MemoryNote(
            content="Hello world",
            id="test-id",
            name="Test Note",
            path="dev/test",
            keywords=["k1", "k2"],
            links=["other-id"],
            retrieval_count=3,
            context="Engineering",
            tags=["t1", "t2"],
            summary="A short summary",
        )
        md = original.to_markdown()
        restored = MemoryNote.from_markdown(md)

        assert restored.content == original.content
        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.path == original.path
        assert restored.keywords == original.keywords
        assert restored.links == original.links
        assert restored.retrieval_count == original.retrieval_count
        assert restored.context == original.context
        assert restored.tags == original.tags
        assert restored.summary == original.summary

    def test_from_markdown_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid markdown format"):
            MemoryNote.from_markdown("Just content, no frontmatter")

    def test_from_markdown_tolerates_non_json_values(self):
        """Hand-written notes may have unquoted values — should be handled."""
        md = """---
id: my-note
name: My Note
path: some/path
---
Content here."""
        note = MemoryNote.from_markdown(md)
        assert note.id == "my-note"
        assert note.name == "My Note"
        assert note.path == "some/path"

    def test_from_file(self, tmp_path):
        note = MemoryNote(content="File content", id="file-id", name="File Note")
        filepath = tmp_path / "test-note.md"
        filepath.write_text(note.to_markdown(), encoding="utf-8")

        loaded = MemoryNote.from_file(filepath)
        assert loaded.id == "file-id"
        assert loaded.content == "File content"

    def test_from_file_with_path(self, tmp_path):
        note = MemoryNote(
            content="Nested note",
            id="nested-id",
            name="Nested",
            path="backend/database",
        )
        dir_path = tmp_path / "backend" / "database"
        dir_path.mkdir(parents=True)
        filepath = dir_path / "nested.md"
        filepath.write_text(note.to_markdown(), encoding="utf-8")

        loaded = MemoryNote.from_file(filepath)
        assert loaded.path == "backend/database"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Knowledge Link & Memory Link Extraction
# ═══════════════════════════════════════════════════════════════════════════════


class TestMemoryNoteLinks:
    """Test knowledge:// link and memory ID link extraction."""

    def test_get_knowledge_links_empty(self):
        note = MemoryNote(content="test", links=[])
        assert note.get_knowledge_links() == []

    def test_get_knowledge_links_only_memory_ids(self):
        note = MemoryNote(content="test", links=["id-1", "id-2"])
        assert note.get_knowledge_links() == []

    def test_get_knowledge_links_with_knowledge_links(self):
        note = MemoryNote(
            content="test",
            links=["id-1", "knowledge://docs/abc123#0", "knowledge://api/def456#3"],
        )
        klinks = note.get_knowledge_links()
        assert len(klinks) == 2
        assert klinks[0].namespace == "docs"
        assert klinks[0].file_hash == "abc123"
        assert klinks[0].chunk_idx == 0
        assert klinks[1].namespace == "api"

    def test_get_memory_links_empty(self):
        note = MemoryNote(content="test", links=[])
        assert note.get_memory_links() == []

    def test_get_memory_links_only_memory_ids(self):
        note = MemoryNote(content="test", links=["id-1", "id-2"])
        assert note.get_memory_links() == ["id-1", "id-2"]

    def test_get_memory_links_filters_knowledge_links(self):
        note = MemoryNote(
            content="test",
            links=["id-1", "knowledge://docs/abc#0", "id-2"],
        )
        assert note.get_memory_links() == ["id-1", "id-2"]

    def test_get_memory_links_none_links(self):
        note = MemoryNote(content="test")
        note.links = None
        assert note.get_memory_links() == []

    def test_get_knowledge_links_none_links(self):
        note = MemoryNote(content="test")
        note.links = None
        assert note.get_knowledge_links() == []
