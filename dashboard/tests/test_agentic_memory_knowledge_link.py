"""Unit tests for agentic_memory.knowledge_link — knowledge:// link utilities.

These tests cover the agentic_memory module's own KnowledgeLink implementation
(which is the same code as dashboard.knowledge.knowledge_link but tested here
to ensure the agentic_memory copy is correct and fully covered).
"""

import pytest

from dashboard.agentic_memory.knowledge_link import (
    KnowledgeLink,
    KNOWLEDGE_LINK_PATTERN,
    parse_knowledge_links,
    is_knowledge_link,
    categorize_links,
)


class TestKnowledgeLinkParsing:
    """Tests for KnowledgeLink.parse()."""

    def test_parse_valid_link(self):
        link = KnowledgeLink.parse("knowledge://docs/abc123def456#0")
        assert link is not None
        assert link.namespace == "docs"
        assert link.file_hash == "abc123def456"
        assert link.chunk_idx == 0
        assert link.raw == "knowledge://docs/abc123def456#0"

    def test_parse_high_chunk_idx(self):
        link = KnowledgeLink.parse("knowledge://api/feedbeefcafe#42")
        assert link is not None
        assert link.chunk_idx == 42

    def test_parse_namespace_with_hyphens(self):
        link = KnowledgeLink.parse("knowledge://my-ns/abc#0")
        assert link is not None
        assert link.namespace == "my-ns"

    def test_parse_namespace_with_underscores(self):
        link = KnowledgeLink.parse("knowledge://my_ns/abc#0")
        assert link is not None
        assert link.namespace == "my_ns"

    def test_parse_missing_chunk_returns_none(self):
        assert KnowledgeLink.parse("knowledge://docs/abc123def456") is None

    def test_parse_missing_hash_returns_none(self):
        assert KnowledgeLink.parse("knowledge://docs/#0") is None

    def test_parse_non_knowledge_link_returns_none(self):
        assert KnowledgeLink.parse("regular-uuid-string") is None

    def test_parse_empty_string_returns_none(self):
        assert KnowledgeLink.parse("") is None

    def test_parse_malformed_returns_none(self):
        assert KnowledgeLink.parse("knowledge://") is None

    def test_to_uri(self):
        link = KnowledgeLink(
            namespace="docs", file_hash="abc123", chunk_idx=5,
            raw="knowledge://docs/abc123#5"
        )
        assert link.to_uri() == "knowledge://docs/abc123#5"

    def test_str(self):
        link = KnowledgeLink(
            namespace="docs", file_hash="abc123", chunk_idx=5,
            raw="knowledge://docs/abc123#5"
        )
        assert str(link) == "knowledge://docs/abc123#5"

    def test_frozen(self):
        link = KnowledgeLink(
            namespace="docs", file_hash="abc123", chunk_idx=0,
            raw="knowledge://docs/abc123#0"
        )
        with pytest.raises(AttributeError):
            link.namespace = "other"


class TestIsKnowledgeLink:
    """Tests for is_knowledge_link()."""

    def test_valid_link(self):
        assert is_knowledge_link("knowledge://docs/abc#0") is True

    def test_non_knowledge_link(self):
        assert is_knowledge_link("regular-uuid") is False

    def test_partial_knowledge_prefix(self):
        assert is_knowledge_link("knowledge://invalid") is False

    def test_empty_string(self):
        assert is_knowledge_link("") is False


class TestParseKnowledgeLinks:
    """Tests for parse_knowledge_links()."""

    def test_empty_list(self):
        assert parse_knowledge_links([]) == []

    def test_mixed_links(self):
        links = [
            "knowledge://docs/abc#0",
            "regular-memory-id",
            "knowledge://api/def#1",
        ]
        result = parse_knowledge_links(links)
        assert len(result) == 2
        assert result[0].namespace == "docs"
        assert result[1].namespace == "api"

    def test_only_memory_ids(self):
        links = ["id-1", "id-2"]
        assert parse_knowledge_links(links) == []


class TestCategorizeLinks:
    """Tests for categorize_links()."""

    def test_mixed_links(self):
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

    def test_only_memory_ids(self):
        result = categorize_links(["id-1", "id-2"])
        assert result["memory_ids"] == ["id-1", "id-2"]
        assert result["knowledge_links"] == []

    def test_only_knowledge_links(self):
        result = categorize_links(["knowledge://docs/abc#0"])
        assert result["memory_ids"] == []
        assert len(result["knowledge_links"]) == 1

    def test_empty_list(self):
        result = categorize_links([])
        assert result["memory_ids"] == []
        assert result["knowledge_links"] == []


class TestKnowledgeLinkPattern:
    """Tests for the KNOWLEDGE_LINK_PATTERN regex."""

    def test_matches_valid_link(self):
        m = KNOWLEDGE_LINK_PATTERN.match("knowledge://docs/abc123#0")
        assert m is not None
        assert m.group("namespace") == "docs"
        assert m.group("file_hash") == "abc123"
        assert m.group("chunk_idx") == "0"

    def test_no_match_for_invalid(self):
        assert KNOWLEDGE_LINK_PATTERN.match("knowledge://docs/abc") is None
