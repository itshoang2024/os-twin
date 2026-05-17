"""Tests for Memory ↔ Knowledge Bridge (EPIC-007).

Tests cover:
1. Knowledge link parsing and validation
2. Bridge index operations
3. Query engine memory_links enrichment
4. MCP tool find_notes_by_knowledge_link
5. Degradation when bridge disabled
"""

import json
import os
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# =============================================================================
# Test KnowledgeLink parsing
# =============================================================================


class TestKnowledgeLinkParsing:
    """Tests for knowledge:// link parsing."""

    def test_parse_valid_knowledge_link(self):
        """Parse a valid knowledge:// link."""
        from dashboard.knowledge.knowledge_link import KnowledgeLink, KNOWLEDGE_LINK_PATTERN

        link = "knowledge://docs/abc123def456#0"
        parsed = KnowledgeLink.parse(link)

        assert parsed is not None
        assert parsed.namespace == "docs"
        assert parsed.file_hash == "abc123def456"
        assert parsed.chunk_idx == 0
        assert parsed.raw == link

    def test_parse_knowledge_link_with_high_chunk_idx(self):
        """Parse a knowledge link with a high chunk index."""
        from dashboard.knowledge.knowledge_link import KnowledgeLink

        link = "knowledge://api/feedbeefcafe#42"
        parsed = KnowledgeLink.parse(link)

        assert parsed is not None
        assert parsed.namespace == "api"
        assert parsed.file_hash == "feedbeefcafe"
        assert parsed.chunk_idx == 42

    def test_parse_invalid_knowledge_link_missing_chunk(self):
        """Reject a knowledge link without chunk index."""
        from dashboard.knowledge.knowledge_link import KnowledgeLink

        link = "knowledge://docs/abc123def456"
        parsed = KnowledgeLink.parse(link)

        assert parsed is None

    def test_parse_invalid_knowledge_link_missing_hash(self):
        """Reject a knowledge link with malformed hash."""
        from dashboard.knowledge.knowledge_link import KnowledgeLink

        link = "knowledge://docs/#0"
        parsed = KnowledgeLink.parse(link)

        assert parsed is None

    def test_parse_non_knowledge_link(self):
        """Return None for non-knowledge:// links."""
        from dashboard.knowledge.knowledge_link import KnowledgeLink

        link = "regular-uuid-string"
        parsed = KnowledgeLink.parse(link)

        assert parsed is None

    def test_parse_knowledge_link_with_underscores_in_namespace(self):
        """Parse a knowledge link with underscores in namespace."""
        from dashboard.knowledge.knowledge_link import KnowledgeLink

        link = "knowledge://my_docs/abc123#0"
        parsed = KnowledgeLink.parse(link)

        assert parsed is not None
        assert parsed.namespace == "my_docs"

    def test_knowledge_link_to_uri(self):
        """Convert KnowledgeLink back to URI."""
        from dashboard.knowledge.knowledge_link import KnowledgeLink

        link = KnowledgeLink(
            namespace="docs",
            file_hash="abc123",
            chunk_idx=5,
            raw="knowledge://docs/abc123#5",
        )

        assert link.to_uri() == "knowledge://docs/abc123#5"

    def test_is_knowledge_link_helper(self):
        """Test the is_knowledge_link helper function."""
        from dashboard.knowledge.knowledge_link import is_knowledge_link

        assert is_knowledge_link("knowledge://docs/abc#0") is True
        assert is_knowledge_link("knowledge://api/feed#42") is True
        assert is_knowledge_link("regular-uuid") is False
        assert is_knowledge_link("knowledge://invalid") is False

    def test_parse_knowledge_links_from_list(self):
        """Extract knowledge links from a mixed list."""
        from dashboard.knowledge.knowledge_link import parse_knowledge_links

        links = [
            "knowledge://docs/abc#0",
            "regular-memory-id",
            "knowledge://api/def#1",
            "another-regular-id",
        ]

        parsed = parse_knowledge_links(links)

        assert len(parsed) == 2
        assert parsed[0].namespace == "docs"
        assert parsed[1].namespace == "api"

    def test_categorize_links(self):
        """Categorize mixed links into memory IDs and knowledge links."""
        from dashboard.knowledge.knowledge_link import categorize_links

        links = [
            "knowledge://docs/abc#0",
            "mem-id-1",
            "knowledge://api/def#1",
            "mem-id-2",
        ]

        result = categorize_links(links)

        assert len(result["memory_ids"]) == 2
        assert "mem-id-1" in result["memory_ids"]
        assert "mem-id-2" in result["memory_ids"]
        assert len(result["knowledge_links"]) == 2


# =============================================================================
# Test BridgeIndex
# =============================================================================


class TestBridgeIndex:
    """Tests for the BridgeIndex SQLite-backed reverse index."""

    @pytest.fixture
    def temp_bridge_config(self, tmp_path):
        """Create a temporary bridge config for testing."""
        from dashboard.knowledge.bridge import BridgeConfig

        return BridgeConfig(
            bridge_db_path=str(tmp_path / "_bridge.sqlite"),
            memory_persist_dir=str(tmp_path / ".memory"),
            enabled=True,
        )

    def test_bridge_creates_database(self, temp_bridge_config):
        """Bridge creates SQLite database on init."""
        from dashboard.knowledge.bridge import BridgeIndex

        bridge = BridgeIndex(config=temp_bridge_config)

        assert Path(temp_bridge_config.bridge_db_path).exists()
        bridge.close()

    def test_bridge_rebuild_scans_notes(self, temp_bridge_config):
        """Bridge rebuild scans memory notes for knowledge links."""
        from dashboard.knowledge.bridge import BridgeIndex

        # Create a test note with a knowledge link
        notes_dir = Path(temp_bridge_config.memory_persist_dir) / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)

        note_content = """---
id: test-note-123
name: Test Note
links: ["knowledge://docs/abc123#0", "knowledge://docs/abc123#1"]
---
This is a test note with knowledge links.
"""
        (notes_dir / "test-note.md").write_text(note_content)

        bridge = BridgeIndex(config=temp_bridge_config)
        result = bridge.rebuild()
        bridge.close()

        assert result["notes_scanned"] == 1
        assert result["links_found"] == 2
        assert result["errors"] == 0

    def test_bridge_lookup_returns_note_ids(self, temp_bridge_config):
        """Bridge lookup returns note IDs for a knowledge chunk."""
        from dashboard.knowledge.bridge import BridgeIndex

        # Create a test note with a knowledge link
        notes_dir = Path(temp_bridge_config.memory_persist_dir) / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)

        note_content = """---
id: note-with-link
name: Linked Note
links: ["knowledge://docs/abc123#0"]
---
This note links to a knowledge chunk.
"""
        (notes_dir / "linked-note.md").write_text(note_content)

        bridge = BridgeIndex(config=temp_bridge_config)
        bridge.rebuild()

        # Lookup by namespace, file_hash, chunk_idx
        note_ids = bridge.lookup("docs", "abc123", 0)

        assert len(note_ids) == 1
        assert "note-with-link" in note_ids

        bridge.close()

    def test_bridge_lookup_by_file_only(self, temp_bridge_config):
        """Bridge lookup returns all notes for a file (any chunk)."""
        from dashboard.knowledge.bridge import BridgeIndex

        # Create test notes with knowledge links to the same file
        notes_dir = Path(temp_bridge_config.memory_persist_dir) / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)

        note1 = """---
id: note-1
links: ["knowledge://docs/deadbeef#0"]
---
"""
        note2 = """---
id: note-2
links: ["knowledge://docs/deadbeef#5"]
---
"""
        (notes_dir / "note1.md").write_text(note1)
        (notes_dir / "note2.md").write_text(note2)

        bridge = BridgeIndex(config=temp_bridge_config)
        bridge.rebuild()

        # Lookup by file only (no chunk_idx)
        note_ids = bridge.lookup("docs", "deadbeef")

        assert len(note_ids) == 2
        assert "note-1" in note_ids
        assert "note-2" in note_ids

        bridge.close()

    def test_bridge_disabled_returns_empty(self, tmp_path):
        """Bridge returns empty results when disabled."""
        from dashboard.knowledge.bridge import BridgeConfig, BridgeIndex

        config = BridgeConfig(
            bridge_db_path=str(tmp_path / "_bridge.sqlite"),
            memory_persist_dir=str(tmp_path / ".memory"),
            enabled=False,
        )

        bridge = BridgeIndex(config=config)

        note_ids = bridge.lookup("docs", "abc123", 0)
        assert note_ids == []

        bridge.close()

    def test_bridge_needs_rebuild_detects_mtime(self, temp_bridge_config):
        """Bridge detects when memory notes have been modified."""
        from dashboard.knowledge.bridge import BridgeIndex
        import time

        notes_dir = Path(temp_bridge_config.memory_persist_dir) / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)

        bridge = BridgeIndex(config=temp_bridge_config)
        bridge.rebuild()

        # Initially doesn't need rebuild
        assert bridge.needs_rebuild() is False

        # Touch a note file
        time.sleep(0.1)  # Ensure mtime is different
        (notes_dir / "new-note.md").write_text("---\nid: new\n---\nNew note")

        # Now needs rebuild
        assert bridge.needs_rebuild() is True

        bridge.close()


# =============================================================================
# Test Query Engine enrichment
# =============================================================================


class TestQueryEngineEnrichment:
    """Tests for KnowledgeQueryEngine memory_links enrichment."""

    def test_chunk_hit_has_memory_links_field(self):
        """ChunkHit model includes memory_links field."""
        from dashboard.knowledge.query import ChunkHit

        chunk = ChunkHit(
            text="Sample text",
            score=0.85,
            file_path="/path/to/file.md",
            filename="file.md",
            chunk_index=0,
            total_chunks=1,
            file_hash="abc123",
        )

        assert hasattr(chunk, "memory_links")
        assert chunk.memory_links == []

    def test_chunk_hit_with_memory_links(self):
        """ChunkHit can store memory_links."""
        from dashboard.knowledge.query import ChunkHit

        chunk = ChunkHit(
            text="Sample text",
            score=0.85,
            file_hash="abc123",
            memory_links=["note-1", "note-2"],
        )

        assert chunk.memory_links == ["note-1", "note-2"]

    @patch("dashboard.knowledge.query._get_bridge_index")
    def test_enrich_memory_links_calls_bridge(self, mock_get_bridge):
        """_enrich_memory_links calls bridge.lookup for each chunk."""
        from dashboard.knowledge.query import KnowledgeQueryEngine, ChunkHit

        # Mock bridge
        mock_bridge = MagicMock()
        mock_bridge.lookup.return_value = ["note-1", "note-2"]
        mock_get_bridge.return_value = mock_bridge

        # Create engine with mocked deps (constructor: namespace, kuzu_graph, embedder, llm)
        engine = KnowledgeQueryEngine(
            namespace="docs",
            kuzu_graph=MagicMock(),
            embedder=MagicMock(),
            llm=MagicMock(),
        )

        chunks = [
            ChunkHit(text="A", score=0.9, file_hash="hash1", chunk_index=0),
            ChunkHit(text="B", score=0.8, file_hash="hash2", chunk_index=1),
        ]

        engine._enrich_memory_links(chunks)

        # Verify bridge was called
        assert mock_bridge.lookup.call_count == 2
        assert chunks[0].memory_links == ["note-1", "note-2"]

    @patch("dashboard.knowledge.query._get_bridge_index")
    def test_enrich_memory_links_handles_bridge_unavailable(self, mock_get_bridge):
        """_enrich_memory_links handles unavailable bridge gracefully."""
        from dashboard.knowledge.query import KnowledgeQueryEngine, ChunkHit

        # Bridge not available
        mock_get_bridge.return_value = None

        engine = KnowledgeQueryEngine(
            namespace="docs",
            kuzu_graph=MagicMock(),
            embedder=MagicMock(),
            llm=MagicMock(),
        )

        chunks = [
            ChunkHit(text="A", score=0.9, file_hash="hash1", chunk_index=0),
        ]

        # Should not raise
        engine._enrich_memory_links(chunks)

        # memory_links should remain empty
        assert chunks[0].memory_links == []


# =============================================================================
# Test MCP tool
# =============================================================================


class TestFindNotesByKnowledgeLink:
    """Tests for the find_notes_by_knowledge_link MCP tool.
    
    These tests verify the actual MCP tool implementation in mcp_server.py,
    mocking only the BridgeIndex dependency.
    """

    def test_find_notes_returns_matching_ids(self, tmp_path):
        """find_notes_by_knowledge_link returns matching note IDs."""
        import os
        from unittest.mock import patch, MagicMock
        
        # Enable the bridge
        os.environ["OSTWIN_KNOWLEDGE_MEMORY_BRIDGE"] = "1"
        os.environ["OSTWIN_BRIDGE_DB_PATH"] = str(tmp_path / "_bridge.sqlite")
        os.environ["MEMORY_PERSIST_DIR"] = str(tmp_path / ".memory")
        
        try:
            # Mock the BridgeIndex where it's used in mcp_server
            with patch("dashboard.knowledge.bridge.BridgeIndex") as MockBridgeIndex:
                mock_bridge = MagicMock()
                mock_bridge.lookup.return_value = ["note-1", "note-2"]
                mock_bridge.close = MagicMock()
                MockBridgeIndex.return_value = mock_bridge
                
                # Import and call the actual MCP tool
                from dashboard.knowledge.mcp_server import find_notes_by_knowledge_link
                
                result = find_notes_by_knowledge_link("docs", "abc123", 0)
                
                # Verify the result structure
                assert "note_ids" in result
                assert "count" in result
                assert result["count"] == 2
                assert "note-1" in result["note_ids"]
                assert "note-2" in result["note_ids"]
                
                # Verify BridgeIndex.lookup was called with correct args
                mock_bridge.lookup.assert_called_once_with("docs", "abc123", 0)
                mock_bridge.close.assert_called_once()
        finally:
            os.environ.pop("OSTWIN_KNOWLEDGE_MEMORY_BRIDGE", None)
            os.environ.pop("OSTWIN_BRIDGE_DB_PATH", None)
            os.environ.pop("MEMORY_PERSIST_DIR", None)

    def test_find_notes_without_chunk_idx(self, tmp_path):
        """find_notes_by_knowledge_link works without chunk_idx (returns all notes for file)."""
        import os
        from unittest.mock import patch, MagicMock
        
        os.environ["OSTWIN_KNOWLEDGE_MEMORY_BRIDGE"] = "1"
        os.environ["OSTWIN_BRIDGE_DB_PATH"] = str(tmp_path / "_bridge.sqlite")
        os.environ["MEMORY_PERSIST_DIR"] = str(tmp_path / ".memory")
        
        try:
            with patch("dashboard.knowledge.bridge.BridgeIndex") as MockBridgeIndex:
                mock_bridge = MagicMock()
                mock_bridge.lookup.return_value = ["note-1", "note-2", "note-3"]
                mock_bridge.close = MagicMock()
                MockBridgeIndex.return_value = mock_bridge
                
                from dashboard.knowledge.mcp_server import find_notes_by_knowledge_link
                
                # Call without chunk_idx
                result = find_notes_by_knowledge_link("docs", "abc123")
                
                assert result["count"] == 3
                
                # Verify lookup was called with chunk_idx=None
                mock_bridge.lookup.assert_called_once_with("docs", "abc123", None)
        finally:
            os.environ.pop("OSTWIN_KNOWLEDGE_MEMORY_BRIDGE", None)
            os.environ.pop("OSTWIN_BRIDGE_DB_PATH", None)
            os.environ.pop("MEMORY_PERSIST_DIR", None)

    def test_find_notes_bridge_disabled(self, tmp_path):
        """find_notes_by_knowledge_link returns error when bridge is disabled."""
        import os
        
        # Disable the bridge
        os.environ["OSTWIN_KNOWLEDGE_MEMORY_BRIDGE"] = "0"
        
        try:
            from dashboard.knowledge.mcp_server import find_notes_by_knowledge_link
            
            result = find_notes_by_knowledge_link("docs", "abc123", 0)
            
            # Should return an error
            assert "error" in result
            assert "code" in result
            assert result["code"] == "BRIDGE_DISABLED"
        finally:
            os.environ.pop("OSTWIN_KNOWLEDGE_MEMORY_BRIDGE", None)

    def test_find_notes_no_matches(self, tmp_path):
        """find_notes_by_knowledge_link returns empty list when no matches."""
        import os
        from unittest.mock import patch, MagicMock
        
        os.environ["OSTWIN_KNOWLEDGE_MEMORY_BRIDGE"] = "1"
        os.environ["OSTWIN_BRIDGE_DB_PATH"] = str(tmp_path / "_bridge.sqlite")
        os.environ["MEMORY_PERSIST_DIR"] = str(tmp_path / ".memory")
        
        try:
            with patch("dashboard.knowledge.bridge.BridgeIndex") as MockBridgeIndex:
                mock_bridge = MagicMock()
                mock_bridge.lookup.return_value = []  # No matches
                mock_bridge.close = MagicMock()
                MockBridgeIndex.return_value = mock_bridge
                
                from dashboard.knowledge.mcp_server import find_notes_by_knowledge_link
                
                result = find_notes_by_knowledge_link("other", "xyz", 0)
                
                assert result["count"] == 0
                assert result["note_ids"] == []
        finally:
            os.environ.pop("OSTWIN_KNOWLEDGE_MEMORY_BRIDGE", None)
            os.environ.pop("OSTWIN_BRIDGE_DB_PATH", None)
            os.environ.pop("MEMORY_PERSIST_DIR", None)

    def test_find_notes_handles_exception(self, tmp_path):
        """find_notes_by_knowledge_link handles exceptions gracefully."""
        import os
        from unittest.mock import patch
        
        os.environ["OSTWIN_KNOWLEDGE_MEMORY_BRIDGE"] = "1"
        os.environ["OSTWIN_BRIDGE_DB_PATH"] = str(tmp_path / "_bridge.sqlite")
        os.environ["MEMORY_PERSIST_DIR"] = str(tmp_path / ".memory")
        
        try:
            with patch("dashboard.knowledge.bridge.BridgeIndex") as MockBridgeIndex:
                # Simulate an exception during bridge creation
                MockBridgeIndex.side_effect = Exception("Bridge error")
                
                from dashboard.knowledge.mcp_server import find_notes_by_knowledge_link
                
                result = find_notes_by_knowledge_link("docs", "abc123", 0)
                
                # Should return an error
                assert "error" in result
                assert "code" in result
                assert result["code"] == "INTERNAL_ERROR"
        finally:
            os.environ.pop("OSTWIN_KNOWLEDGE_MEMORY_BRIDGE", None)
            os.environ.pop("OSTWIN_BRIDGE_DB_PATH", None)
            os.environ.pop("MEMORY_PERSIST_DIR", None)


# =============================================================================
# Test bridge enabled/disabled
# =============================================================================


class TestBridgeToggle:
    """Tests for enabling/disabling the bridge."""

    def test_is_bridge_enabled_default_false(self):
        """Bridge is disabled by default."""
        import os

        # Clear env var if set
        old_val = os.environ.pop("OSTWIN_KNOWLEDGE_MEMORY_BRIDGE", None)

        try:
            # Reimport to get fresh value
            import importlib
            import dashboard.knowledge.bridge as bridge
            importlib.reload(bridge)

            from dashboard.knowledge.bridge import is_bridge_enabled
            assert is_bridge_enabled() is False
        finally:
            if old_val:
                os.environ["OSTWIN_KNOWLEDGE_MEMORY_BRIDGE"] = old_val

    def test_is_bridge_enabled_when_set(self):
        """Bridge is enabled when OSTWIN_KNOWLEDGE_MEMORY_BRIDGE=1."""
        import os

        old_val = os.environ.get("OSTWIN_KNOWLEDGE_MEMORY_BRIDGE")
        os.environ["OSTWIN_KNOWLEDGE_MEMORY_BRIDGE"] = "1"

        try:
            import importlib
            import dashboard.knowledge.bridge as bridge
            importlib.reload(bridge)

            from dashboard.knowledge.bridge import is_bridge_enabled
            assert is_bridge_enabled() is True
        finally:
            if old_val:
                os.environ["OSTWIN_KNOWLEDGE_MEMORY_BRIDGE"] = old_val
            else:
                os.environ.pop("OSTWIN_KNOWLEDGE_MEMORY_BRIDGE", None)


# =============================================================================
# Test integration scenarios
# =============================================================================


class TestBridgeIntegration:
    """Integration tests for the complete bridge flow."""

    @pytest.fixture
    def temp_setup(self, tmp_path):
        """Set up temporary directories for integration tests."""
        return {
            "bridge_db": str(tmp_path / "_bridge.sqlite"),
            "memory_dir": str(tmp_path / ".memory"),
        }

    def test_round_trip_note_to_chunk_to_note(self, temp_setup):
        """Complete round-trip: save note → query → backlink shown."""
        from dashboard.knowledge.bridge import BridgeIndex, BridgeConfig

        # Create a note with a knowledge link
        notes_dir = Path(temp_setup["memory_dir"]) / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)

        note_content = """---
id: my-note
name: Important Decision
links: ["knowledge://specs/abc123def456#0"]
---
We chose PostgreSQL for its JSONB support.
"""
        (notes_dir / "decision.md").write_text(note_content)

        # Build bridge
        config = BridgeConfig(
            bridge_db_path=temp_setup["bridge_db"],
            memory_persist_dir=temp_setup["memory_dir"],
            enabled=True,
        )

        bridge = BridgeIndex(config=config)
        bridge.rebuild()

        # Lookup by knowledge chunk
        note_ids = bridge.lookup("specs", "abc123def456", 0)

        assert len(note_ids) == 1
        assert "my-note" in note_ids

        bridge.close()

    def test_graceful_degradation_when_memory_unavailable(self, temp_setup):
        """Bridge returns empty list when memory directory doesn't exist."""
        from dashboard.knowledge.bridge import BridgeIndex, BridgeConfig

        config = BridgeConfig(
            bridge_db_path=temp_setup["bridge_db"],
            memory_persist_dir="/nonexistent/path",
            enabled=True,
        )

        bridge = BridgeIndex(config=config)
        bridge.rebuild()

        # Should not raise, returns empty
        note_ids = bridge.lookup("docs", "abc", 0)
        assert note_ids == []

        bridge.close()
