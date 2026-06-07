"""Tests for .docx and .xlsx ingestion through both MarkitdownReader and Ingestor.

Validates that the full parsing pipeline correctly handles:
- .docx files (Word documents with structured content)
- .xlsx files (Excel spreadsheets with tabular data)

Uses the fixture file at ``fixtures/plan.docx`` and a dynamically-created
test Excel file.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
DOCX_FIXTURE = FIXTURES_DIR / "plan.docx"


@pytest.fixture()
def xlsx_fixture(tmp_path: Path) -> Path:
    """Create a small .xlsx file for testing."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "TestSheet"
    ws.append(["Name", "Age", "City", "Score"])
    ws.append(["Alice", 30, "Hanoi", 95.5])
    ws.append(["Bob", 25, "HCMC", 88.0])
    ws.append(["Charlie", 35, "Da Nang", 92.3])
    out = tmp_path / "test_data.xlsx"
    wb.save(str(out))
    return out


# ---------------------------------------------------------------------------
# 1. Raw MarkItDown conversion
# ---------------------------------------------------------------------------


class TestMarkItDownRaw:
    """Verify that the raw MarkItDown library converts docx/xlsx to text."""

    def test_docx_converts(self) -> None:
        from markitdown import MarkItDown

        md = MarkItDown()
        result = md.convert(str(DOCX_FIXTURE))
        text = getattr(result, "text_content", None) or getattr(result, "text", None) or ""
        assert len(text) > 1000, f"Expected substantial text from docx, got {len(text)} chars"
        # Spot-check known content from the fixture
        assert "Digital Data Application Plan" in text or "Implementation Content" in text

    def test_xlsx_converts(self, xlsx_fixture: Path) -> None:
        from markitdown import MarkItDown

        md = MarkItDown()
        result = md.convert(str(xlsx_fixture))
        text = getattr(result, "text_content", None) or getattr(result, "text", None) or ""
        assert len(text) > 50, f"Expected tabular text from xlsx, got {len(text)} chars"
        assert "Alice" in text
        assert "Hanoi" in text
        # Should produce markdown table
        assert "|" in text


# ---------------------------------------------------------------------------
# 2. MarkitdownReader.read() (graph parser entry point)
# ---------------------------------------------------------------------------


class TestMarkitdownReaderRead:
    """Verify MarkitdownReader.read() produces Documents for docx/xlsx."""

    def test_docx_produces_documents(self) -> None:
        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        reader = MarkitdownReader()
        docs = reader.read({"url": str(DOCX_FIXTURE)})
        assert len(docs) > 0, "Expected at least one Document from docx"
        # Verify the document has expected metadata and content
        assert docs[0].metadata["filename"] == "plan.docx"
        # The fixture is large enough to produce multiple documents
        assert len(docs) >= 1, "Expected at least one chunk from docx"
        combined = " ".join(d.text for d in docs)
        assert "Digital Data Application Plan" in combined or "Implementation" in combined

    def test_xlsx_produces_documents(self, xlsx_fixture: Path) -> None:
        from dashboard.knowledge.graph.parsers.markitdown_reader import MarkitdownReader

        reader = MarkitdownReader()
        docs = reader.read({"url": str(xlsx_fixture)})
        assert len(docs) > 0, "Expected at least one Document from xlsx"
        assert "Alice" in docs[0].text
        assert docs[0].metadata["filename"] == "test_data.xlsx"


# ---------------------------------------------------------------------------
# 3. Ingestor._parse_file() (ingestion pipeline entry point)
# ---------------------------------------------------------------------------


class TestIngestorParseFile:
    """Verify Ingestor._parse_file() produces chunks for docx/xlsx."""

    @staticmethod
    def _make_file_entry(path: Path, ext: str) -> "FileEntry":
        from dashboard.knowledge.ingestion import FileEntry

        stat = path.stat()
        return FileEntry(
            path=str(path),
            size=stat.st_size,
            mtime=stat.st_mtime,
            extension=ext,
            content_hash="testhash",
        )

    def test_docx_produces_chunks(self) -> None:
        from dashboard.knowledge.ingestion import IngestOptions, Ingestor

        ingestor = Ingestor()
        fe = self._make_file_entry(DOCX_FIXTURE, ".docx")
        chunks = ingestor._parse_file(fe, IngestOptions())
        assert chunks, "Expected chunks from docx"
        combined = " ".join(c["text"] for c in chunks)
        assert "Digital Data Application Plan" in combined or "Implementation" in combined
        assert [c["metadata"]["chunk_index"] for c in chunks] == list(range(len(chunks)))
        assert {c["metadata"]["total_chunks"] for c in chunks} == {len(chunks)}
        # Verify chunk structure
        for c in chunks:
            assert "text" in c
            assert "metadata" in c
            assert c["metadata"]["extension"] == ".docx"
            assert c["metadata"]["filename"] == "plan.docx"

    def test_xlsx_produces_chunks(self, xlsx_fixture: Path) -> None:
        from dashboard.knowledge.ingestion import IngestOptions, Ingestor

        ingestor = Ingestor()
        fe = self._make_file_entry(xlsx_fixture, ".xlsx")
        chunks = ingestor._parse_file(fe, IngestOptions())
        assert len(chunks) >= 1, f"Expected at least one chunk from xlsx, got {len(chunks)}"
        combined = " ".join(c["text"] for c in chunks)
        assert "Alice" in combined
        assert "Hanoi" in combined

    def test_docx_metadata_completeness(self) -> None:
        from dashboard.knowledge.ingestion import IngestOptions, Ingestor

        ingestor = Ingestor()
        fe = self._make_file_entry(DOCX_FIXTURE, ".docx")
        chunks = ingestor._parse_file(fe, IngestOptions())
        assert chunks, "No chunks produced"
        meta = chunks[0]["metadata"]
        required_keys = {
            "file_path",
            "filename",
            "chunk_index",
            "total_chunks",
            "file_size",
            "mtime",
            "extension",
            "file_hash",
            "chunk_hash",
        }
        missing = required_keys - set(meta.keys())
        assert not missing, f"Missing metadata keys: {missing}"


# ---------------------------------------------------------------------------
# 4. Walk phase (extension filtering)
# ---------------------------------------------------------------------------


class TestWalkPhase:
    """Verify that _walk_folder picks up .docx and .xlsx files."""

    def test_walk_finds_docx(self) -> None:
        from dashboard.knowledge.ingestion import IngestOptions, Ingestor

        ingestor = Ingestor()
        files = list(ingestor._walk_folder(FIXTURES_DIR, IngestOptions()))
        extensions = {f.extension for f in files}
        assert ".docx" in extensions, f"Expected .docx in walked extensions, got {extensions}"

    def test_walk_finds_xlsx(self, xlsx_fixture: Path) -> None:
        from dashboard.knowledge.ingestion import IngestOptions, Ingestor

        ingestor = Ingestor()
        files = list(ingestor._walk_folder(xlsx_fixture.parent, IngestOptions()))
        extensions = {f.extension for f in files}
        assert ".xlsx" in extensions, f"Expected .xlsx in walked extensions, got {extensions}"


# ---------------------------------------------------------------------------
# 5. Config validation
# ---------------------------------------------------------------------------


class TestConfig:
    """Verify config includes docx/xlsx in supported extensions."""

    def test_docx_in_supported_extensions(self) -> None:
        from dashboard.knowledge.config import SUPPORTED_DOCUMENT_EXTENSIONS

        assert ".docx" in SUPPORTED_DOCUMENT_EXTENSIONS

    def test_xlsx_in_supported_extensions(self) -> None:
        from dashboard.knowledge.config import SUPPORTED_DOCUMENT_EXTENSIONS

        assert ".xlsx" in SUPPORTED_DOCUMENT_EXTENSIONS

    def test_doc_in_supported_extensions(self) -> None:
        from dashboard.knowledge.config import SUPPORTED_DOCUMENT_EXTENSIONS

        assert ".doc" in SUPPORTED_DOCUMENT_EXTENSIONS

    def test_xls_in_supported_extensions(self) -> None:
        from dashboard.knowledge.config import SUPPORTED_DOCUMENT_EXTENSIONS

        assert ".xls" in SUPPORTED_DOCUMENT_EXTENSIONS
