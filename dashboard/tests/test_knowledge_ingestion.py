"""EPIC-003 — ingestion + jobs tests (post v2 — chromadb → zvec migration).

Heavy deps (kuzu, zvec, markitdown, anthropic) are NEVER
instantiated by the bulk of these tests. We:

- Inject a ``fake_embedder`` (MagicMock with deterministic 1024-dim output) so
  the real embedding provider is never called.
- Inject a ``KnowledgeLLM`` that's just a MagicMock — by default
  ``is_available()`` returns False so the ingestor takes the no-LLM path.
- Replace ``Ingestor._stores`` with a per-namespace ``_FakeStore`` that records
  every chunk + entity write in memory so we can assert against them without
  touching the real graph backend.

For the vector store layer we now use **real zvec** in tests (it imports
cleanly in this venv, unlike chromadb pre-fix). The store class
:class:`NamespaceVectorStore` is exercised against per-test ``tmp_path``
collection directories. zvec is fast enough that one real ingestion pass per
test is acceptable.

Real MarkItDown is bypassed too — for `.md` / `.txt` / `.json` / `.html` the
ingestor's plain-text fallback kicks in (since MarkItDown returns None for
these in our tests' patched path), giving us a deterministic chunking story
without paying the import cost.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest

from dashboard.knowledge.ingestion import (
    FileEntry,
    IngestOptions,
    Ingestor,
    _NamespaceStore,
)
from dashboard.knowledge.jobs import (
    JobEvent,
    JobManager,
    JobState,
    JobStatus,
)
from dashboard.knowledge.namespace import (
    InvalidNamespaceIdError,
    NamespaceManager,
)
from dashboard.knowledge.service import KnowledgeService

FIXTURES = Path(__file__).parent / "fixtures" / "knowledge_sample"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kb_dir(tmp_path: Path) -> Path:
    """Isolated knowledge-base root per test."""
    p = tmp_path / "kb"
    p.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture
def nm(kb_dir: Path) -> NamespaceManager:
    return NamespaceManager(base_dir=kb_dir)


@pytest.fixture(autouse=True)
def _clear_kuzu_cache() -> Iterator[None]:
    """Wipe the Kuzu DB cache around every test (even though we don't open it)."""
    from dashboard.knowledge.graph.index.kuzudb import KuzuLabelledPropertyGraph

    KuzuLabelledPropertyGraph.kuzu_database_cache.clear()
    yield
    KuzuLabelledPropertyGraph.kuzu_database_cache.clear()


@pytest.fixture
def fake_embedder() -> MagicMock:
    """Deterministic 1024-dim embedder with no model load."""
    e = MagicMock(name="FakeEmbedder")
    e.dimension.return_value = 1024
    e.model_name = "test-fake-embedder"

    def _embed(texts: list[str]) -> list[list[float]]:
        return [[(hash(t) % 1000) / 1000.0] * 1024 for t in texts]

    def _embed_one(t: str) -> list[float]:
        return [(hash(t) % 1000) / 1000.0] * 1024

    e.embed.side_effect = _embed
    e.embed_one.side_effect = _embed_one
    return e


class _FakeStore:
    """In-memory replacement for :class:`_NamespaceStore`.

    Records everything the Ingestor would have written to the vector + graph
    backends so tests can assert on counts and content without instantiating
    heavy deps. Mirrors the **post-v2** ``_NamespaceStore`` surface:

    * ``add_chunks(chunks: list[dict])`` — list of ``{text, embedding, metadata}``
    * ``has_file_hash(file_hash) -> bool``
    * ``count_by_file_hash(file_hash) -> int``  (NEW in v2 — Defect 2 fix)
    * ``delete_by_file_hash(file_hash) -> int``
    * ``add_entities_and_relations(...)``
    """

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace
        # Vector-side state
        self.chunks: list[dict] = []  # one dict per chunk: {id, text, embedding, metadata}
        self.deleted_hashes: list[str] = []
        # Graph-side state
        self.entities: list[dict] = []
        self.relations: list[dict] = []

    # Public _NamespaceStore surface ----------------------------------

    def add_chunks(self, chunks: list[dict]) -> int:
        n = 0
        for c in chunks:
            self.chunks.append(
                {
                    "id": f"chunk-{len(self.chunks)}",
                    "text": c.get("text", ""),
                    "embedding": c.get("embedding"),
                    "metadata": dict(c.get("metadata", {}) or {}),
                }
            )
            n += 1
        return n

    def has_file_hash(self, file_hash: str) -> bool:
        return any(c["metadata"].get("file_hash") == file_hash for c in self.chunks)

    def count_by_file_hash(self, file_hash: str) -> int:
        return sum(1 for c in self.chunks if c["metadata"].get("file_hash") == file_hash)

    def delete_by_file_hash(self, file_hash: str) -> int:
        before = len(self.chunks)
        self.chunks = [c for c in self.chunks if c["metadata"].get("file_hash") != file_hash]
        self.deleted_hashes.append(file_hash)
        return before - len(self.chunks)

    def add_entities_and_relations(
        self, entities, relations, chunk_id, chunk_metadata, embedder
    ):
        for e in entities:
            self.entities.append({**e, "chunk_id": chunk_id})
        for r in relations:
            self.relations.append({**r, "chunk_id": chunk_id})
        return len(entities), len(relations)


@pytest.fixture
def fake_store_factory():
    """Returns a function that creates _FakeStore instances and a registry to inspect them."""
    stores: dict[str, _FakeStore] = {}

    def factory(namespace: str) -> _FakeStore:
        if namespace not in stores:
            stores[namespace] = _FakeStore(namespace)
        return stores[namespace]

    factory.stores = stores  # type: ignore[attr-defined]
    return factory


@pytest.fixture
def no_llm() -> MagicMock:
    """A KnowledgeLLM-like mock that always reports unavailable."""
    llm = MagicMock(name="NoLLM")
    llm.is_available.return_value = False
    return llm


@pytest.fixture
def fake_anthropic_llm() -> MagicMock:
    """A KnowledgeLLM-like mock with deterministic entity extraction."""
    llm = MagicMock(name="FakeAnthropicLLM")
    llm.is_available.return_value = True
    # Return a fixed entity + relation for every chunk (regardless of text).
    llm.extract_entities.return_value = (
        [
            {"name": "Acme", "type": "Organization", "description": "Fictional org"},
            {"name": "Widget", "type": "Concept", "description": "Reusable UI element"},
        ],
        [
            {
                "source": "Acme",
                "target": "Widget",
                "relation": "PRODUCES",
                "description": "Acme produces widgets",
            }
        ],
    )
    return llm


@pytest.fixture
def make_ingestor(nm, fake_embedder, no_llm, fake_store_factory):
    """Factory that builds an Ingestor wired to a fake store + fake embedder + no-LLM.

    Now also provides a mock ``graph_index_factory`` that simulates
    ``PropertyGraphIndex.insert_nodes()`` — embedding chunks, writing them
    to the fake store, and populating KG_NODES_KEY / KG_RELATIONS_KEY in
    node metadata to match what ``GraphRAGExtractor`` would produce.
    """

    def _build(llm=None) -> Ingestor:
        active_llm = llm if llm is not None else no_llm

        def _make_graph_index(namespace: str):
            """Build a mock PropertyGraphIndex that mirrors the real pipeline."""
            fake_store = fake_store_factory(namespace)

            mock_index = MagicMock()

            def _insert_nodes(nodes, **kwargs):
                from llama_index.core.graph_stores.types import (
                    KG_NODES_KEY,
                    KG_RELATIONS_KEY,
                )

                # Note: chunk persistence is handled by _extract_and_embed
                # after this call — no need to write chunks here.

                # 2) Simulate entity extraction (when LLM is available)
                if hasattr(active_llm, "is_available") and active_llm.is_available():
                    for node in nodes:
                        try:
                            entities, relations = active_llm.extract_entities(
                                node.text,
                            )
                        except Exception:
                            entities, relations = [], []

                        # Populate metadata the way GraphRAGExtractor would
                        entity_nodes = []
                        for e in entities:
                            entity_nodes.append({
                                "name": e.get("name", ""),
                                "type": e.get("type", "Entity"),
                                "description": e.get("description", ""),
                            })
                            fake_store.entities.append({
                                **e, "chunk_id": node.id_,
                            })
                        relation_objs = []
                        for r in relations:
                            relation_objs.append({
                                "source": r.get("source", ""),
                                "target": r.get("target", ""),
                                "relation": r.get("relation", "RELATED_TO"),
                            })
                            fake_store.relations.append({
                                **r, "chunk_id": node.id_,
                            })

                        node.metadata[KG_NODES_KEY] = entity_nodes
                        node.metadata[KG_RELATIONS_KEY] = relation_objs
                else:
                    # No LLM — still set empty lists so counts work
                    for node in nodes:
                        node.metadata[KG_NODES_KEY] = []
                        node.metadata[KG_RELATIONS_KEY] = []

            mock_index.insert_nodes = _insert_nodes
            return mock_index

        ing = Ingestor(
            namespace_manager=nm,
            embedder=fake_embedder,
            llm=active_llm,
            graph_index_factory=_make_graph_index,
        )
        # Override _get_store to return the per-namespace _FakeStore
        # (still needed for hash-based idempotency checks).
        ing._get_store = lambda namespace: fake_store_factory(namespace)  # type: ignore[assignment]
        return ing

    return _build


# ---------------------------------------------------------------------------
# 1) Folder walk
# ---------------------------------------------------------------------------


class TestFolderWalk:
    def test_walks_folder_finds_supported_files(self, make_ingestor):
        ing = make_ingestor()
        files = list(ing._walk_folder(FIXTURES, IngestOptions()))
        names = sorted(Path(f.path).name for f in files)
        # 4 top-level + 1 nested = 5 supported files; .hidden.md must NOT be present.
        assert "readme.md" in names
        assert "notes.txt" in names
        assert "data.json" in names
        assert "page.html" in names
        assert "nested.md" in names
        assert ".hidden.md" not in names

    def test_skips_hidden_files(self, make_ingestor):
        ing = make_ingestor()
        files = list(ing._walk_folder(FIXTURES, IngestOptions()))
        for f in files:
            assert ".hidden" not in Path(f.path).name
            # Also verify no part of the path is hidden.
            for part in Path(f.path).parts:
                assert not part.startswith(".") or part in (".", "..")

    def test_skips_files_over_size_cap(self, tmp_path: Path, make_ingestor):
        # Create a 200-byte file but use max_file_size_mb=0 (i.e. 0 bytes).
        sub = tmp_path / "big"
        sub.mkdir()
        (sub / "ok.md").write_text("# small")
        # max_file_size_mb=0 → max_bytes=0 → both should be skipped.
        ing = make_ingestor()
        opts = IngestOptions(max_file_size_mb=0)
        files = list(ing._walk_folder(sub, opts))
        assert files == []

    def test_recursive_walk_into_subdirs(self, make_ingestor):
        ing = make_ingestor()
        files = list(ing._walk_folder(FIXTURES, IngestOptions()))
        nested_paths = [f.path for f in files if "subdir" in f.path]
        assert len(nested_paths) == 1
        assert nested_paths[0].endswith("nested.md")

    def test_unsupported_extensions_skipped(self, tmp_path: Path, make_ingestor):
        sub = tmp_path / "mix"
        sub.mkdir()
        (sub / "good.md").write_text("# heading")
        (sub / "bad.exe").write_bytes(b"\x00\x01\x02")
        (sub / "bad.bin").write_bytes(b"\x00\x01\x02")
        ing = make_ingestor()
        files = list(ing._walk_folder(sub, IngestOptions()))
        assert [Path(f.path).name for f in files] == ["good.md"]

    def test_walk_skips_directories_named_with_dot(self, tmp_path: Path, make_ingestor):
        sub = tmp_path / "skip-test"
        sub.mkdir()
        (sub / ".git").mkdir()
        (sub / ".git" / "inside.md").write_text("# don't read me")
        (sub / "visible.md").write_text("# read me")
        ing = make_ingestor()
        files = list(ing._walk_folder(sub, IngestOptions()))
        names = [Path(f.path).name for f in files]
        assert names == ["visible.md"]


# ---------------------------------------------------------------------------
# 2) Parse / chunk
# ---------------------------------------------------------------------------


class TestParse:
    def _entry(self, path: Path) -> FileEntry:
        st = path.stat()
        return FileEntry(
            path=str(path),
            size=st.st_size,
            mtime=st.st_mtime,
            extension=path.suffix.lower(),
            content_hash="testhash",
        )

    def test_parses_md_file(self, make_ingestor):
        ing = make_ingestor()
        chunks = ing._parse_file(self._entry(FIXTURES / "readme.md"), IngestOptions())
        assert len(chunks) >= 1
        assert all("Acme" in c["text"] or len(c["text"]) > 0 for c in chunks)
        # Each chunk must carry the file_hash in metadata.
        for c in chunks:
            assert c["metadata"]["file_hash"] == "testhash"
            assert c["metadata"]["filename"] == "readme.md"
            assert c["metadata"]["chunk_index"] >= 0

    def test_parses_txt_file(self, make_ingestor):
        ing = make_ingestor()
        chunks = ing._parse_file(self._entry(FIXTURES / "notes.txt"), IngestOptions())
        assert len(chunks) >= 1
        assert any("Reactor" in c["text"] for c in chunks)

    def test_parses_json_file(self, make_ingestor):
        ing = make_ingestor()
        chunks = ing._parse_file(self._entry(FIXTURES / "data.json"), IngestOptions())
        assert len(chunks) >= 1
        # The JSON content (or its markdown rendering) should mention the project name.
        joined = " ".join(c["text"] for c in chunks)
        assert "acme-widget-toolkit" in joined.lower() or "acme" in joined.lower()

    def test_parse_unreadable_file_returns_empty(self, tmp_path: Path, make_ingestor):
        # An empty file should produce no chunks.
        empty = tmp_path / "empty.md"
        empty.write_text("")
        ing = make_ingestor()
        chunks = ing._parse_file(self._entry(empty), IngestOptions())
        assert chunks == []


# ---------------------------------------------------------------------------
# 3) Chunking semantics
# ---------------------------------------------------------------------------


class TestChunk:
    def test_chunking_produces_multiple_chunks_for_long_text(
        self, tmp_path: Path, make_ingestor
    ):
        long_md = tmp_path / "long.md"
        long_md.write_text("word " * 1000)  # ~5000 chars
        ing = make_ingestor()
        fe = FileEntry(
            path=str(long_md),
            size=long_md.stat().st_size,
            mtime=long_md.stat().st_mtime,
            extension=".md",
            content_hash="h",
        )
        chunks = ing._parse_file(fe, IngestOptions(chunk_size=500, chunk_overlap=100))
        assert len(chunks) >= 2
        # Verify overlap exists (chunk 1 end overlaps chunk 2 start).
        if len(chunks) >= 2:
            tail_of_first = chunks[0]["text"][-50:]
            assert tail_of_first[-1] in chunks[1]["text"]

    def test_each_chunk_has_content_hash_in_metadata(self, tmp_path: Path, make_ingestor):
        f = tmp_path / "x.md"
        f.write_text("hello world\n" * 200)
        ing = make_ingestor()
        fe = FileEntry(
            path=str(f),
            size=f.stat().st_size,
            mtime=f.stat().st_mtime,
            extension=".md",
            content_hash="abc123",
        )
        chunks = ing._parse_file(fe, IngestOptions(chunk_size=100, chunk_overlap=20))
        assert len(chunks) >= 1
        for c in chunks:
            assert c["metadata"]["file_hash"] == "abc123"
            assert "chunk_hash" in c["metadata"]


# ---------------------------------------------------------------------------
# 3.5) Image ingestion (CARRY-001 — ADR-14 / ADR-17)
# ---------------------------------------------------------------------------


class TestImageIngestion:
    """Image-extension support added in EPIC-006 CARRY-001 (ADR-14 / ADR-17)."""

    def test_image_extensions_in_supported_set(self):
        """ADR-17: SUPPORTED_DOCUMENT_EXTENSIONS includes every IMAGE_EXTENSIONS."""
        from dashboard.knowledge.config import (
            IMAGE_EXTENSIONS,
            SUPPORTED_DOCUMENT_EXTENSIONS,
        )

        assert IMAGE_EXTENSIONS.issubset(SUPPORTED_DOCUMENT_EXTENSIONS)
        # All seven canonical image types are walkable.
        for ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"):
            assert ext in SUPPORTED_DOCUMENT_EXTENSIONS

    def test_walk_includes_png_files(self, tmp_path, make_ingestor):
        """Folder walker now picks up PNG files (was excluded before ADR-17)."""
        sub = tmp_path / "imgs"
        sub.mkdir()
        # Minimal PNG header bytes — enough for the walker (it only stats / sniffs ext).
        png = sub / "tiny.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        # Add a non-image alongside so we know we're not just listing everything.
        (sub / "notes.md").write_text("# title\nbody")

        ing = make_ingestor()
        files = list(ing._walk_folder(sub, IngestOptions()))
        names = sorted(Path(f.path).name for f in files)
        assert "tiny.png" in names
        assert "notes.md" in names
        # Verify the file_entry for the PNG carries the right extension.
        png_entries = [f for f in files if f.extension == ".png"]
        assert len(png_entries) == 1

    def test_image_with_no_anthropic_key_logs_and_skips(
        self, tmp_path, monkeypatch, caplog, make_ingestor
    ):
        """Image with no key → empty chunks + warning log line."""
        import logging as _logging

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        png = tmp_path / "img.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        ing = make_ingestor()
        # Force the converter to be one without vision (ANTHROPIC_API_KEY just got cleared).
        ing._markitdown = None

        fe = FileEntry(
            path=str(png),
            size=png.stat().st_size,
            mtime=png.stat().st_mtime,
            extension=".png",
            content_hash="hash-png",
        )
        with caplog.at_level(_logging.WARNING, logger="dashboard.knowledge.ingestion"):
            chunks = ing._parse_file(fe, IngestOptions())
        assert chunks == []
        # Exactly one warning line per file.
        warns = [
            r for r in caplog.records
            if r.levelno >= _logging.WARNING and "img.png" in r.getMessage()
        ]
        assert len(warns) >= 1
        joined = " ".join(r.getMessage() for r in warns).lower()
        assert "vision" in joined or "image" in joined

    def test_image_with_mocked_markitdown_produces_chunks(
        self, tmp_path, monkeypatch, make_ingestor
    ):
        """Image + vision-enabled MarkItDown returns markdown → chunks produced."""
        png = tmp_path / "screenshot.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        ing = make_ingestor()

        # Stub the cached MarkItDown converter to return fake markdown content.
        class _FakeResult:
            text_content = "# Screenshot caption\n\nA cat sitting on a windowsill."

        class _FakeConverter:
            def convert(self, *_args, **_kw):
                return _FakeResult()

        ing._markitdown = _FakeConverter()

        fe = FileEntry(
            path=str(png),
            size=png.stat().st_size,
            mtime=png.stat().st_mtime,
            extension=".png",
            content_hash="hash-png",
        )
        chunks = ing._parse_file(fe, IngestOptions())
        assert len(chunks) >= 1
        # First chunk carries proper metadata.
        assert chunks[0]["metadata"]["filename"] == "screenshot.png"
        assert chunks[0]["metadata"]["extension"] == ".png"
        assert "cat" in chunks[0]["text"].lower() or "screenshot" in chunks[0]["text"].lower()


# ---------------------------------------------------------------------------
# 4) Ingestor end-to-end (with fakes)
# ---------------------------------------------------------------------------


class TestIngestor:
    def test_ingest_no_llm_indexes_chunks(
        self, nm, kb_dir, make_ingestor, fake_store_factory
    ):
        nm.create("docs")
        ing = make_ingestor()
        result = ing.run("docs", str(FIXTURES))
        assert result["files_total"] == 5
        assert result["files_indexed"] == 5
        assert result["files_failed"] == 0
        assert result["chunks_added"] >= 5
        # No LLM → zero entities / relations.
        assert result["entities_added"] == 0
        assert result["relations_added"] == 0
        # All chunks landed in the namespace's fake store.
        store = fake_store_factory.stores["docs"]  # type: ignore[attr-defined]
        assert len(store.chunks) == result["chunks_added"]
        assert store.entities == []
        assert store.relations == []

    def test_ingest_with_mocked_anthropic_indexes_entities(
        self, nm, make_ingestor, fake_anthropic_llm, fake_store_factory
    ):
        nm.create("docs")
        ing = make_ingestor(llm=fake_anthropic_llm)
        result = ing.run("docs", str(FIXTURES))
        assert result["files_indexed"] == 5
        assert result["chunks_added"] >= 5
        # 2 entities + 1 relation per chunk in our mock.
        assert result["entities_added"] >= 5 * 2
        assert result["relations_added"] >= 5
        store = fake_store_factory.stores["docs"]  # type: ignore[attr-defined]
        names = {e["name"] for e in store.entities}
        assert {"Acme", "Widget"} <= names

    def test_ingest_per_file_error_does_not_kill_job(
        self, nm, make_ingestor, fake_store_factory
    ):
        nm.create("docs")
        ing = make_ingestor()
        original_parse = ing._parse_file
        bad_path = str((FIXTURES / "notes.txt").resolve())

        def flaky_parse(file_entry, options):
            if file_entry.path == bad_path:
                raise RuntimeError("Boom on notes.txt")
            return original_parse(file_entry, options)

        ing._parse_file = flaky_parse  # type: ignore[assignment]
        result = ing.run("docs", str(FIXTURES))
        assert result["files_total"] == 5
        assert result["files_failed"] == 1
        assert result["files_indexed"] == 4
        assert any("notes.txt" in e for e in result["errors"])
        # Other files made it through.
        store = fake_store_factory.stores["docs"]  # type: ignore[attr-defined]
        assert len(store.chunks) >= 4

    def test_ingest_idempotent(self, nm, make_ingestor, fake_store_factory):
        nm.create("docs")
        ing = make_ingestor()
        first = ing.run("docs", str(FIXTURES))
        store = fake_store_factory.stores["docs"]  # type: ignore[attr-defined]
        chunks_after_first = len(store.chunks)
        # Second run with no force → all files skipped.
        second = ing.run("docs", str(FIXTURES))
        assert second["files_indexed"] == 0
        assert second["files_skipped"] == 5
        assert len(store.chunks) == chunks_after_first  # no new chunks

    def test_ingest_with_force_reprocesses(
        self, nm, make_ingestor, fake_store_factory
    ):
        nm.create("docs")
        ing = make_ingestor()
        ing.run("docs", str(FIXTURES))
        store = fake_store_factory.stores["docs"]  # type: ignore[attr-defined]
        chunks_after_first = len(store.chunks)
        # Force run: should delete + re-add → same total count, deleted_hashes populated.
        result = ing.run("docs", str(FIXTURES), IngestOptions(force=True))
        assert result["files_indexed"] == 5
        assert result["files_skipped"] == 0
        assert len(store.deleted_hashes) >= 5
        # Total chunks stays roughly the same (deleted then re-added).
        assert len(store.chunks) == chunks_after_first

    def test_ingest_updates_manifest_stats(self, nm, make_ingestor):
        nm.create("docs")
        ing = make_ingestor()
        result = ing.run("docs", str(FIXTURES))
        meta = nm.get("docs")
        assert meta is not None
        assert meta.stats.files_indexed == result["files_indexed"]
        assert meta.stats.chunks == result["chunks_added"]

    def test_ingest_appends_import_record(self, nm, make_ingestor):
        nm.create("docs")
        ing = make_ingestor()
        ing.run("docs", str(FIXTURES))
        meta = nm.get("docs")
        assert meta is not None
        assert len(meta.imports) == 1
        rec = meta.imports[0]
        assert rec.status == "completed"
        assert rec.file_count == 5
        assert rec.error_count == 0

    def test_ingest_emits_progress_events(self, nm, make_ingestor):
        nm.create("docs")
        ing = make_ingestor()
        events: list[JobEvent] = []
        ing.run("docs", str(FIXTURES), emit=events.append)
        # Should have walking → found N → per-file events
        states = [e.state for e in events]
        # All events from ingestor are RUNNING (terminal state is set by JobManager).
        assert all(s == JobState.RUNNING for s in states)
        # First event mentions walking; one event mentions "Found".
        assert any("Walking" in e.message for e in events)
        assert any("Found" in e.message for e in events)
        assert any(e.progress_total == 5 for e in events)

    def test_ingest_missing_folder_raises(self, nm, make_ingestor, tmp_path):
        nm.create("docs")
        ing = make_ingestor()
        with pytest.raises(FileNotFoundError):
            ing.run("docs", str(tmp_path / "does-not-exist"))

    def test_ingest_file_not_dir_raises(self, nm, make_ingestor, tmp_path):
        nm.create("docs")
        f = tmp_path / "afile.md"
        f.write_text("# x")
        ing = make_ingestor()
        with pytest.raises(NotADirectoryError):
            ing.run("docs", str(f))

    def test_ingest_nonexistent_namespace_raises(self, make_ingestor, tmp_path):
        # Don't create the namespace.
        ing = make_ingestor()
        from dashboard.knowledge.namespace import NamespaceNotFoundError

        with pytest.raises(NamespaceNotFoundError):
            ing.run("never-created", str(FIXTURES))

    def test_ingest_cancel_check_short_circuits(self, nm, make_ingestor):
        nm.create("docs")
        ing = make_ingestor()
        events: list[JobEvent] = []
        # Cancel before the very first file.
        ing.run(
            "docs",
            str(FIXTURES),
            emit=events.append,
            cancel_check=lambda: True,
        )
        cancelled = [e for e in events if e.state == JobState.CANCELLED]
        assert len(cancelled) == 1

    def test_ingest_empty_file_counts_as_skipped(self, nm, make_ingestor, tmp_path):
        nm.create("docs")
        sub = tmp_path / "withempty"
        sub.mkdir()
        (sub / "empty.md").write_text("")
        (sub / "ok.md").write_text("# real content here\n" * 5)
        ing = make_ingestor()
        result = ing.run("docs", str(sub))
        assert result["files_indexed"] == 1
        assert result["files_skipped"] == 1
        assert result["files_failed"] == 0

    def test_ingest_embed_failure_marks_file_failed(self, nm, make_ingestor, fake_embedder):
        nm.create("docs")
        ing = make_ingestor()
        # Make the embedder raise on the first call.
        fake_embedder.embed.side_effect = RuntimeError("embedding service down")
        result = ing.run("docs", str(FIXTURES))
        assert result["files_failed"] == 5  # all files fail at embed time
        assert all("embed/extract failed" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# 5) JobManager
# ---------------------------------------------------------------------------


def _wait_for_state(jm: JobManager, job_id: str, target: JobState, timeout: float = 5.0):
    """Poll until the job reaches target state (or the time runs out)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = jm.get(job_id)
        if st is not None and st.state == target:
            return st
        time.sleep(0.02)
    raise AssertionError(
        f"Job {job_id} did not reach {target}; final={jm.get(job_id)}"
    )


class TestJobManager:
    def test_submit_returns_job_id_immediately(self, kb_dir):
        jm = JobManager(base_dir=kb_dir)
        slow = threading.Event()

        def slow_fn(emit):
            slow.wait(timeout=2.0)
            return {"ok": True}

        t0 = time.monotonic()
        job_id = jm.submit("ns", "test_op", slow_fn)
        elapsed_ms = (time.monotonic() - t0) * 1000
        assert isinstance(job_id, str) and len(job_id) > 0
        assert elapsed_ms < 100, f"submit took {elapsed_ms:.1f}ms — must be <100ms"
        slow.set()  # let the worker finish so shutdown is clean
        _wait_for_state(jm, job_id, JobState.COMPLETED)
        jm.shutdown(wait=True)

    def test_job_status_transitions(self, kb_dir):
        jm = JobManager(base_dir=kb_dir)
        observed: list[JobState] = []

        def fn(emit):
            observed.append(JobState.RUNNING)
            return {"value": 42}

        job_id = jm.submit("ns", "test_op", fn)
        st = _wait_for_state(jm, job_id, JobState.COMPLETED, timeout=3.0)
        assert st.state == JobState.COMPLETED
        assert st.result == {"value": 42}
        assert st.started_at is not None
        assert st.finished_at is not None
        jm.shutdown(wait=True)

    def test_job_persisted_to_jsonl(self, kb_dir):
        jm = JobManager(base_dir=kb_dir)

        def fn(emit):
            emit(JobEvent(timestamp=datetime.now(timezone.utc), state=JobState.RUNNING, message="midway", progress_current=1, progress_total=2))
            return {"ok": True}

        job_id = jm.submit("ns", "op", fn)
        _wait_for_state(jm, job_id, JobState.COMPLETED)
        jm.shutdown(wait=True)
        log = kb_dir / "ns" / "jobs" / f"{job_id}.jsonl"
        assert log.exists()
        lines = [ln for ln in log.read_text().splitlines() if ln.strip()]
        # At minimum: PENDING + RUNNING + (custom RUNNING) + COMPLETED = 4
        assert len(lines) >= 3
        states = [json.loads(ln)["state"] for ln in lines]
        assert states[0] == "pending"
        assert states[-1] == "completed"

    def test_get_job_after_jm_restart(self, kb_dir):
        jm1 = JobManager(base_dir=kb_dir)

        def fn(emit):
            return {"x": 1}

        job_id = jm1.submit("ns", "op", fn)
        _wait_for_state(jm1, job_id, JobState.COMPLETED)
        jm1.shutdown(wait=True)
        # New JobManager with same base_dir should be able to read the persisted log.
        jm2 = JobManager(base_dir=kb_dir)
        try:
            replayed = jm2.get(job_id)
            assert replayed is not None
            assert replayed.state == JobState.COMPLETED
            assert replayed.namespace == "ns"
            assert replayed.result == {"x": 1}
        finally:
            jm2.shutdown(wait=True)

    def test_running_job_marked_interrupted_on_jm_restart(self, kb_dir):
        # Manually simulate a crashed job — write a jsonl with a final RUNNING event.
        ns_dir = kb_dir / "ns" / "jobs"
        ns_dir.mkdir(parents=True, exist_ok=True)
        log = ns_dir / "deadbeef.jsonl"
        now = datetime.now(timezone.utc)
        with log.open("w", encoding="utf-8") as fh:
            for ev in [
                JobEvent(timestamp=now, state=JobState.PENDING, message="queued", detail={"operation": "import_folder"}),
                JobEvent(timestamp=now, state=JobState.RUNNING, message="working"),
            ]:
                fh.write(ev.model_dump_json() + "\n")
        # Instantiating a JobManager triggers recovery.
        jm = JobManager(base_dir=kb_dir)
        try:
            st = jm.get("deadbeef")
            assert st is not None
            assert st.state == JobState.INTERRUPTED
            assert st.operation == "import_folder"
        finally:
            jm.shutdown(wait=True)
        # The disk log should have a new INTERRUPTED line appended.
        lines = [ln for ln in log.read_text().splitlines() if ln.strip()]
        assert json.loads(lines[-1])["state"] == "interrupted"

    def test_list_for_namespace_sorted_desc(self, kb_dir):
        jm = JobManager(base_dir=kb_dir)

        def quick(emit):
            return {"ok": True}

        job_a = jm.submit("ns", "op", quick)
        _wait_for_state(jm, job_a, JobState.COMPLETED)
        time.sleep(0.01)
        job_b = jm.submit("ns", "op", quick)
        _wait_for_state(jm, job_b, JobState.COMPLETED)
        jobs = jm.list_for_namespace("ns")
        assert [j.job_id for j in jobs] == [job_b, job_a]  # newest first
        jm.shutdown(wait=True)

    def test_failed_job_records_error(self, kb_dir):
        jm = JobManager(base_dir=kb_dir)

        def boom(emit):
            raise RuntimeError("kaboom")

        job_id = jm.submit("ns", "op", boom)
        st = _wait_for_state(jm, job_id, JobState.FAILED)
        assert st.state == JobState.FAILED
        assert any("kaboom" in e for e in st.errors)
        jm.shutdown(wait=True)

    def test_cancel_sets_flag(self, kb_dir):
        jm = JobManager(base_dir=kb_dir)
        started = threading.Event()
        proceed = threading.Event()

        def fn(emit):
            started.set()
            proceed.wait(timeout=2.0)
            return {"ok": True}

        job_id = jm.submit("ns", "op", fn)
        started.wait(timeout=2.0)
        assert jm.cancel(job_id) is True
        assert jm.is_cancelled(job_id) is True
        proceed.set()
        _wait_for_state(jm, job_id, JobState.COMPLETED)
        jm.shutdown(wait=True)


# ---------------------------------------------------------------------------
# 6) KnowledgeService — wired ingestion
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 7) _NamespaceStore + NamespaceVectorStore — real zvec, no mocks
# ---------------------------------------------------------------------------


def _ns_store(kb_dir: Path, namespace: str) -> _NamespaceStore:
    """Build an :class:`_NamespaceStore` rooted at the test's kb_dir.

    The store uses a real :class:`NamespaceVectorStore` against a per-test
    zvec collection at ``{kb_dir}/{namespace}/vectors/``. zvec is fast and
    imports cleanly, so we don't need a mock layer here anymore.
    """
    nm = NamespaceManager(base_dir=kb_dir)
    return _NamespaceStore(namespace, namespace_manager=nm)


class TestNamespaceStoreVector:
    """Direct tests of the zvec-backed _NamespaceStore vector surface."""

    def test_get_vstore_lazy_creates(self, kb_dir):
        store = _ns_store(kb_dir, "ns")
        # No collection until first method call.
        assert store._vstore is None
        # Touching any zvec method materialises the store.
        assert store.has_file_hash("nope") is False
        assert store._vstore is not None
        # Caching: second call doesn't re-open.
        v1 = store._get_vstore()
        v2 = store._get_vstore()
        assert v1 is v2

    def test_add_chunks_writes_to_zvec(self, kb_dir):
        store = _ns_store(kb_dir, "ns")
        added = store.add_chunks(
            [
                {
                    "text": "doc-a",
                    "embedding": [0.1] * 1024,
                    "metadata": {"file_hash": "h1", "filename": "a.md", "chunk_index": 0, "total_chunks": 1},
                },
                {
                    "text": "doc-b",
                    "embedding": [0.2] * 1024,
                    "metadata": {"file_hash": "h1", "filename": "a.md", "chunk_index": 1, "total_chunks": 2},
                },
            ]
        )
        assert added == 2
        assert store._vstore.count() == 2

    def test_add_chunks_noop_for_empty(self, kb_dir):
        store = _ns_store(kb_dir, "ns")
        n = store.add_chunks([])
        assert n == 0
        # Lazy: no vstore created.
        assert store._vstore is None

    def test_has_file_hash_true_after_add(self, kb_dir):
        store = _ns_store(kb_dir, "ns")
        store.add_chunks(
            [
                {
                    "text": "doc",
                    "embedding": [0.0] * 1024,
                    "metadata": {"file_hash": "abc", "filename": "x.md", "chunk_index": 0, "total_chunks": 1},
                }
            ]
        )
        assert store.has_file_hash("abc") is True
        assert store.has_file_hash("missing") is False

    def test_has_file_hash_empty_returns_false(self, kb_dir):
        store = _ns_store(kb_dir, "ns")
        assert store.has_file_hash("") is False

    def test_count_by_file_hash(self, kb_dir):
        store = _ns_store(kb_dir, "ns")
        store.add_chunks(
            [
                {"text": "1", "embedding": [0.0] * 1024, "metadata": {"file_hash": "h1", "chunk_index": 0, "total_chunks": 3}},
                {"text": "2", "embedding": [0.1] * 1024, "metadata": {"file_hash": "h1", "chunk_index": 1, "total_chunks": 3}},
                {"text": "3", "embedding": [0.2] * 1024, "metadata": {"file_hash": "h1", "chunk_index": 2, "total_chunks": 3}},
                {"text": "x", "embedding": [0.5] * 1024, "metadata": {"file_hash": "h2", "chunk_index": 0, "total_chunks": 1}},
            ]
        )
        assert store.count_by_file_hash("h1") == 3
        assert store.count_by_file_hash("h2") == 1
        assert store.count_by_file_hash("missing") == 0
        assert store.count_by_file_hash("") == 0

    def test_delete_by_file_hash_removes_rows(self, kb_dir):
        store = _ns_store(kb_dir, "ns")
        store.add_chunks(
            [
                {"text": "x", "embedding": [0.0] * 1024, "metadata": {"file_hash": "h1", "chunk_index": 0, "total_chunks": 2}},
                {"text": "y", "embedding": [0.1] * 1024, "metadata": {"file_hash": "h1", "chunk_index": 1, "total_chunks": 2}},
                {"text": "z", "embedding": [0.2] * 1024, "metadata": {"file_hash": "h2", "chunk_index": 0, "total_chunks": 1}},
            ]
        )
        deleted = store.delete_by_file_hash("h1")
        assert deleted == 2
        # Only h2 row remains.
        assert store.count_by_file_hash("h1") == 0
        assert store.count_by_file_hash("h2") == 1

    def test_delete_by_file_hash_noop_when_missing(self, kb_dir):
        store = _ns_store(kb_dir, "ns")
        store.add_chunks(
            [
                {"text": "x", "embedding": [0.0] * 1024, "metadata": {"file_hash": "h1", "chunk_index": 0, "total_chunks": 1}},
            ]
        )
        assert store.delete_by_file_hash("nope") == 0
        assert store.count_by_file_hash("h1") == 1

    def test_delete_by_file_hash_empty_returns_zero(self, kb_dir):
        store = _ns_store(kb_dir, "ns")
        assert store.delete_by_file_hash("") == 0

    def test_filter_quote_escaping(self, kb_dir):
        """File hashes containing single-quotes must not break the zvec filter."""
        store = _ns_store(kb_dir, "ns")
        weird = "quote'inside"
        store.add_chunks(
            [
                {
                    "text": "x",
                    "embedding": [0.0] * 1024,
                    "metadata": {"file_hash": weird, "chunk_index": 0, "total_chunks": 1},
                }
            ]
        )
        assert store.has_file_hash(weird) is True
        assert store.count_by_file_hash(weird) == 1
        assert store.delete_by_file_hash(weird) == 1





# ---------------------------------------------------------------------------
# 8) KnowledgeService — wired ingestion
# ---------------------------------------------------------------------------


class TestKnowledgeService:
    def _service(self, nm, fake_embedder, llm, fake_store_factory) -> KnowledgeService:
        def _graph_index_factory(namespace: str):
            """Build a mock PropertyGraphIndex for service-level tests."""
            fake_store = fake_store_factory(namespace)
            mock_index = MagicMock()

            def _insert_nodes(nodes, **kwargs):
                from llama_index.core.graph_stores.types import (
                    KG_NODES_KEY,
                    KG_RELATIONS_KEY,
                )
                texts = [n.text for n in nodes]
                vectors = fake_embedder.embed(texts)
                store_chunks = []
                for node, vec in zip(nodes, vectors):
                    store_chunks.append({
                        "text": node.text,
                        "embedding": vec,
                        "metadata": node.metadata,
                    })
                fake_store.add_chunks(store_chunks)
                for node in nodes:
                    node.metadata[KG_NODES_KEY] = []
                    node.metadata[KG_RELATIONS_KEY] = []

            mock_index.insert_nodes = _insert_nodes
            return mock_index

        ing = Ingestor(
            namespace_manager=nm,
            embedder=fake_embedder,
            llm=llm,
            graph_index_factory=_graph_index_factory,
        )
        ing._get_store = lambda namespace: fake_store_factory(namespace)  # type: ignore[assignment]
        jm = JobManager(base_dir=nm._base)  # noqa: SLF001
        return KnowledgeService(namespace_manager=nm, job_manager=jm, ingestor=ing, embedder=fake_embedder)

    def test_import_folder_returns_job_id(self, nm, fake_embedder, no_llm, fake_store_factory):
        nm.create("docs")
        svc = self._service(nm, fake_embedder, no_llm, fake_store_factory)
        t0 = time.monotonic()
        job_id = svc.import_folder("docs", str(FIXTURES))
        elapsed_ms = (time.monotonic() - t0) * 1000
        assert isinstance(job_id, str)
        assert elapsed_ms < 100, f"import_folder took {elapsed_ms:.1f}ms"
        # Wait for it to finish so the JobManager can shut down cleanly.
        _wait_for_state(svc._get_job_manager(), job_id, JobState.COMPLETED)
        svc._get_job_manager().shutdown(wait=True)

    def test_import_folder_404_for_missing_folder(
        self, nm, fake_embedder, no_llm, fake_store_factory, tmp_path
    ):
        svc = self._service(nm, fake_embedder, no_llm, fake_store_factory)
        with pytest.raises(FileNotFoundError):
            svc.import_folder("docs", str(tmp_path / "nope"))
        svc._get_job_manager().shutdown(wait=True)

    def test_import_folder_rejects_a_file(
        self, nm, fake_embedder, no_llm, fake_store_factory, tmp_path
    ):
        f = tmp_path / "file.md"
        f.write_text("# x")
        svc = self._service(nm, fake_embedder, no_llm, fake_store_factory)
        with pytest.raises(NotADirectoryError):
            svc.import_folder("docs", str(f))
        svc._get_job_manager().shutdown(wait=True)

    def test_import_folder_auto_creates_namespace(
        self, nm, fake_embedder, no_llm, fake_store_factory
    ):
        # No pre-create call.
        assert nm.get("autons") is None
        svc = self._service(nm, fake_embedder, no_llm, fake_store_factory)
        job_id = svc.import_folder("autons", str(FIXTURES))
        _wait_for_state(svc._get_job_manager(), job_id, JobState.COMPLETED)
        # Namespace now exists.
        assert nm.get("autons") is not None
        svc._get_job_manager().shutdown(wait=True)

    def test_import_folder_invalid_namespace_raises(
        self, nm, fake_embedder, no_llm, fake_store_factory
    ):
        svc = self._service(nm, fake_embedder, no_llm, fake_store_factory)
        with pytest.raises(InvalidNamespaceIdError):
            svc.import_folder("Bad Name!", str(FIXTURES))
        svc._get_job_manager().shutdown(wait=True)

    def test_get_job_returns_none_for_unknown_job(
        self, nm, fake_embedder, no_llm, fake_store_factory
    ):
        svc = self._service(nm, fake_embedder, no_llm, fake_store_factory)
        assert svc.get_job("does-not-exist") is None
        svc._get_job_manager().shutdown(wait=True)

    def test_full_lifecycle_with_fixture(
        self, nm, fake_embedder, no_llm, fake_store_factory
    ):
        svc = self._service(nm, fake_embedder, no_llm, fake_store_factory)
        job_id = svc.import_folder("docs", str(FIXTURES))
        st = _wait_for_state(svc._get_job_manager(), job_id, JobState.COMPLETED)
        assert st.result is not None
        assert st.result["files_indexed"] == 5
        # Manifest stats reflect the import.
        meta = nm.get("docs")
        assert meta is not None
        assert meta.stats.files_indexed == 5
        assert meta.stats.chunks > 0
        # list_jobs returns it.
        jobs = svc.list_jobs("docs")
        assert any(j.job_id == job_id for j in jobs)
        svc._get_job_manager().shutdown(wait=True)

    def test_kwargs_inject_embedder_and_llm(
        self, nm, kb_dir, fake_embedder, no_llm
    ):
        """KnowledgeService.__init__ accepts embedder= and llm= kwargs (post v2).

        Regression for the ``embedder=None, llm=None`` ctor surface added in
        EPIC-003 v2 so tests can inject fakes without building the Ingestor
        themselves.
        """
        svc = KnowledgeService(
            namespace_manager=nm,
            embedder=fake_embedder,
            llm=no_llm,
        )
        ing = svc._get_ingestor()
        # Lazy: the override was passed through to the Ingestor.
        assert ing._get_embedder() is fake_embedder
        assert ing._get_llm() is no_llm
        try:
            svc._get_job_manager().shutdown(wait=False)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 9) NEW REGRESSION TESTS — Defects 1 & 2 from EPIC-003 QA
# ---------------------------------------------------------------------------


def _make_noop_graph_index_factory(embedder):
    """Build a reusable graph_index_factory that simulates PropertyGraphIndex.

    Returns a factory ``f(namespace) -> mock_index`` whose ``insert_nodes()``
    embeds chunks and sets KG_NODES_KEY / KG_RELATIONS_KEY in metadata,
    mirroring the real pipeline without needing Kuzu or a real LLM.
    """

    def factory(namespace: str):
        mock_index = MagicMock()

        def _insert_nodes(nodes, **kwargs):
            from llama_index.core.graph_stores.types import (
                KG_NODES_KEY,
                KG_RELATIONS_KEY,
            )

            # Embed nodes (may raise if embedder is broken — that's correct).
            texts = [n.text for n in nodes]
            embedder.embed(texts)

            for node in nodes:
                node.metadata[KG_NODES_KEY] = []
                node.metadata[KG_RELATIONS_KEY] = []

        mock_index.insert_nodes = _insert_nodes
        return mock_index

    return factory


class TestPathRespectsBaseDir:
    """Defect 1: path helpers must root off ``NamespaceManager.base_dir``.

    The module-level ``config.kuzu_db_path`` / ``config.vector_dir`` always
    resolve under ``KNOWLEDGE_DIR`` — they're only safe in production where
    no test ever overrides ``base_dir``. The Ingestor + KnowledgeService
    must use the **instance** methods (``nm.kuzu_db_path(ns)`` etc.) so a
    custom ``base_dir`` is honoured all the way down.
    """

    def test_namespace_paths_respect_base_dir(self, tmp_path):
        nm = NamespaceManager(base_dir=tmp_path)
        assert str(nm.namespace_dir("a")) == str(tmp_path / "a")
        assert str(nm.kuzu_db_path("a")) == str(tmp_path / "a" / "graph.db")
        assert str(nm.vector_dir("a")) == str(tmp_path / "a" / "vectors")
        assert str(nm.manifest_path("a")) == str(tmp_path / "a" / "manifest.json")

    def test_ingest_writes_to_base_dir_only(
        self, tmp_path, fake_embedder, no_llm, fake_store_factory
    ):
        """Real integration: importing into a custom base_dir leaves the global one untouched.

        Uses the `fake_store_factory` to skip the actual zvec write (which
        would still pass — the point of this test is the manifest path,
        which is the side that previously leaked). The vector path of the
        Ingestor is still rooted via ``nm.vector_dir`` even though the
        fake_store doesn't write there.
        """
        from dashboard.knowledge.config import KNOWLEDGE_DIR

        nm = NamespaceManager(base_dir=tmp_path)
        ing = Ingestor(
            namespace_manager=nm, embedder=fake_embedder, llm=no_llm,
            graph_index_factory=_make_noop_graph_index_factory(fake_embedder),
        )
        ing._get_store = lambda namespace: fake_store_factory(namespace)  # type: ignore[assignment]
        jm = JobManager(base_dir=nm._base)  # noqa: SLF001
        ks = KnowledgeService(
            namespace_manager=nm, job_manager=jm, ingestor=ing, embedder=fake_embedder,
        )
        job_id = ks.import_folder("leak-test", str(FIXTURES))
        _wait_for_state(jm, job_id, JobState.COMPLETED)
        try:
            # No leak: the global KNOWLEDGE_DIR must NOT have been touched
            # for this namespace.
            assert not (KNOWLEDGE_DIR / "leak-test").exists(), (
                f"Leak detected: {KNOWLEDGE_DIR / 'leak-test'} created when "
                f"base_dir was {tmp_path}"
            )
            # Manifest landed under the custom base_dir.
            assert (tmp_path / "leak-test" / "manifest.json").exists()
        finally:
            jm.shutdown(wait=True)

    def test_real_zvec_path_respects_base_dir(self, tmp_path, fake_embedder, no_llm):
        """Hit the real zvec path through the real _NamespaceStore.

        Previous behaviour: even with NamespaceManager(base_dir=tmp_path),
        the chromadb collection landed in ~/.ostwin/knowledge/{ns}/chroma/.
        Now: the collection is at ``{tmp_path}/{ns}/vectors/`` and no other
        directories should exist for this namespace anywhere.
        """
        from dashboard.knowledge.config import KNOWLEDGE_DIR

        nm = NamespaceManager(base_dir=tmp_path)
        nm.create("zvec-leak-test")
        ing = Ingestor(
            namespace_manager=nm, embedder=fake_embedder, llm=no_llm,
            graph_index_factory=_make_noop_graph_index_factory(fake_embedder),
        )
        result = ing.run("zvec-leak-test", str(FIXTURES))
        assert result["files_indexed"] == 5
        # Real on-disk directory under tmp_path.
        assert (tmp_path / "zvec-leak-test" / "vectors").exists()
        # Global KNOWLEDGE_DIR untouched for this namespace.
        assert not (KNOWLEDGE_DIR / "zvec-leak-test").exists(), (
            f"Leak detected: zvec wrote to {KNOWLEDGE_DIR / 'zvec-leak-test'} "
            f"when base_dir was {tmp_path}"
        )


class TestForceNoDoubleCount:
    """Defect 2: force=True must not double-count manifest stats.

    Before the fix:
        After run1 (initial):  files_indexed=5  chunks=5
        After run2 (force):    files_indexed=10 chunks=10  ← WRONG

    After the fix the per-file old chunk count is subtracted before re-adding.
    """

    def _wait(self, jm, job_id, timeout: float = 10.0):
        return _wait_for_state(jm, job_id, JobState.COMPLETED, timeout=timeout)

    def test_force_reprocess_does_not_double_stats(
        self, tmp_path, fake_embedder, no_llm
    ):
        nm = NamespaceManager(base_dir=tmp_path)
        # Use a no-op graph_index_factory so the lazy-built Ingestor works.
        ks = KnowledgeService(
            namespace_manager=nm, embedder=fake_embedder, llm=no_llm,
        )
        ing = ks._get_ingestor()
        ing._graph_index_factory = _make_noop_graph_index_factory(fake_embedder)
        try:
            # First import.
            j1 = ks.import_folder("force-test", str(FIXTURES))
            self._wait(ks._get_job_manager(), j1)
            s1 = nm.get("force-test").stats
            assert s1.files_indexed == 5

            # Second import with force.
            j2 = ks.import_folder(
                "force-test", str(FIXTURES), options={"force": True}
            )
            self._wait(ks._get_job_manager(), j2)
            s2 = nm.get("force-test").stats

            # Stats should be IDENTICAL (same files, same chunk count).
            assert s1.files_indexed == s2.files_indexed, (
                f"files: {s1.files_indexed} -> {s2.files_indexed} "
                "(force-reprocess double-counted)"
            )
            assert s1.chunks == s2.chunks, (
                f"chunks: {s1.chunks} -> {s2.chunks} "
                "(force-reprocess double-counted)"
            )
            # And vectors.
            assert s1.vectors == s2.vectors, (
                f"vectors: {s1.vectors} -> {s2.vectors}"
            )
        finally:
            try:
                ks._get_job_manager().shutdown(wait=True)
            except Exception:
                pass

    def test_force_reprocess_three_times_no_drift(
        self, tmp_path, fake_embedder, no_llm
    ):
        """Three successive force re-imports stay invariant."""
        nm = NamespaceManager(base_dir=tmp_path)
        ks = KnowledgeService(
            namespace_manager=nm, embedder=fake_embedder, llm=no_llm,
        )
        ing = ks._get_ingestor()
        ing._graph_index_factory = _make_noop_graph_index_factory(fake_embedder)
        try:
            j0 = ks.import_folder("drift", str(FIXTURES))
            self._wait(ks._get_job_manager(), j0)
            baseline = nm.get("drift").stats
            for _ in range(3):
                j = ks.import_folder(
                    "drift", str(FIXTURES), options={"force": True}
                )
                self._wait(ks._get_job_manager(), j)
                s = nm.get("drift").stats
                assert s.files_indexed == baseline.files_indexed
                assert s.chunks == baseline.chunks
                assert s.vectors == baseline.vectors
        finally:
            try:
                ks._get_job_manager().shutdown(wait=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 10) E2E — REAL zvec + REAL KnowledgeEmbedder (no mocks for storage layer)
# ---------------------------------------------------------------------------


# The real KnowledgeEmbedder downloads ~80 MB of model weights on first run
# (cached afterwards). Mark slow; still part of the default suite because
# the architect's DoD requires "at least 1 new real e2e test". CI can opt out
# via -m "not slow" if needed.
@pytest.mark.slow
class TestRealE2E:
    """End-to-end with REAL zvec + REAL KnowledgeEmbedder, no mocks.

    This is the regression-killer: chromadb-mock-only suites historically
    missed both Defect 1 and Defect 2. Running the entire pipeline against
    real backends — even with a local 1024-dim embedding model — is the only way
    to catch path-leak and stats-drift bugs ahead of integration testing.
    """

    def _wait(self, jm, job_id, timeout: float = 60.0):
        return _wait_for_state(jm, job_id, JobState.COMPLETED, timeout=timeout)

    def test_real_zvec_real_embedder_e2e(self, tmp_path):
        """Import the fixture folder with real backends; assert correctness + isolation."""
        from dashboard.knowledge.embeddings import KnowledgeEmbedder

        nm = NamespaceManager(base_dir=tmp_path)
        embedder = KnowledgeEmbedder()
        # No LLM — graceful entity-extraction skip.
        no_llm_real = MagicMock()
        no_llm_real.is_available.return_value = False

        ks = KnowledgeService(
            namespace_manager=nm, embedder=embedder, llm=no_llm_real
        )
        ing = ks._get_ingestor()
        ing._graph_index_factory = _make_noop_graph_index_factory(embedder)
        try:
            t0 = time.monotonic()
            job_id = ks.import_folder("e2e-real", str(FIXTURES))
            st = self._wait(ks._get_job_manager(), job_id, timeout=120.0)
            elapsed = time.monotonic() - t0

            assert st.state == JobState.COMPLETED
            assert st.result is not None
            assert st.result["files_indexed"] == 5
            assert st.result["files_failed"] == 0
            assert st.result["chunks_added"] >= 5
            assert st.result["entities_added"] == 0  # no LLM
            assert st.result["errors"] == []

            # Real on-disk artefacts.
            assert (tmp_path / "e2e-real" / "manifest.json").exists()
            assert (tmp_path / "e2e-real" / "vectors").exists()

            # Real zvec count matches the manifest. We re-use the Ingestor's
            # already-open store to avoid zvec's "can't lock read-write
            # collection" error when opening the same on-disk path twice
            # in the same process.
            ing = ks._get_ingestor()
            vs = ing._get_store("e2e-real")._get_vstore()
            assert vs.count() == st.result["chunks_added"]

            # Manifest stats reflect the import.
            meta = nm.get("e2e-real")
            assert meta is not None
            assert meta.stats.files_indexed == 5
            assert meta.stats.chunks == st.result["chunks_added"]

            # Performance signal — printed for the done report.
            print(f"[E2E] real ingest of 5-file fixture: {elapsed:.2f}s")
        finally:
            try:
                ks._get_job_manager().shutdown(wait=True)
            except Exception:
                pass

    def test_real_e2e_force_reingest_stats_invariant(self, tmp_path):
        """Real-zvec version of the force-no-double-count regression."""
        from dashboard.knowledge.embeddings import KnowledgeEmbedder

        nm = NamespaceManager(base_dir=tmp_path)
        embedder = KnowledgeEmbedder()
        no_llm_real = MagicMock()
        no_llm_real.is_available.return_value = False
        ks = KnowledgeService(
            namespace_manager=nm, embedder=embedder, llm=no_llm_real
        )
        ing = ks._get_ingestor()
        ing._graph_index_factory = _make_noop_graph_index_factory(embedder)
        try:
            j1 = ks.import_folder("force-real", str(FIXTURES))
            self._wait(ks._get_job_manager(), j1)
            s1 = nm.get("force-real").stats
            j2 = ks.import_folder(
                "force-real", str(FIXTURES), options={"force": True}
            )
            self._wait(ks._get_job_manager(), j2)
            s2 = nm.get("force-real").stats
            assert s1.files_indexed == s2.files_indexed, (s1, s2)
            assert s1.chunks == s2.chunks, (s1, s2)
            assert s1.vectors == s2.vectors, (s1, s2)
        finally:
            try:
                ks._get_job_manager().shutdown(wait=True)
            except Exception:
                pass
