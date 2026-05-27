"""Tests for ``JsonManifestStore``.

Covers: save/load round-trip, atomic writes, corruption recovery,
version mismatch rejection, and missing-file handling.
"""

import json
import os
import pytest

from dashboard.agentic_memory.merkle.store import JsonManifestStore


@pytest.fixture
def store(tmp_path):
    return JsonManifestStore(str(tmp_path))


@pytest.fixture
def sample_data():
    return {
        "root_hash": "abcdef1234567890",
        "note_count": 3,
        "tree": {
            "_hash": "abcdef1234567890",
            "dir": {"_hash": "1111222233334444", "note.md": "aaaa"},
        },
        "vectordb_root_hash": "vvvvvvvvvvvvvvvv",
    }


# ── round-trip ──────────────────────────────────────────────


class TestRoundTrip:
    def test_save_then_load(self, store, sample_data):
        store.save(sample_data)
        loaded = store.load()

        assert loaded is not None
        assert loaded["root_hash"] == sample_data["root_hash"]
        assert loaded["note_count"] == sample_data["note_count"]
        assert loaded["tree"] == sample_data["tree"]
        assert loaded["vectordb_root_hash"] == sample_data["vectordb_root_hash"]

    def test_load_includes_version_and_timestamp(self, store, sample_data):
        store.save(sample_data)
        loaded = store.load()

        assert loaded is not None
        assert "version" in loaded
        assert loaded["version"] == 1
        assert "generated_at" in loaded
        assert len(loaded["generated_at"]) == 14  # YYYYMMDDHHmmss

    def test_save_overwrites_previous(self, store, sample_data):
        store.save(sample_data)

        updated = dict(sample_data)
        updated["root_hash"] = "new_hash_value!!"
        store.save(updated)

        loaded = store.load()
        assert loaded is not None
        assert loaded["root_hash"] == "new_hash_value!!"


# ── missing file ────────────────────────────────────────────


class TestMissingFile:
    def test_load_returns_none_when_no_file(self, store):
        assert store.load() is None

    def test_exists_returns_false_when_no_file(self, store):
        assert store.exists() is False

    def test_exists_returns_true_after_save(self, store, sample_data):
        store.save(sample_data)
        assert store.exists() is True


# ── corruption recovery ─────────────────────────────────────


class TestCorruption:
    def test_load_returns_none_for_corrupt_json(self, store, tmp_path):
        path = tmp_path / "merkle_manifest.json"
        path.write_text("NOT VALID JSON {{{", encoding="utf-8")
        assert store.load() is None

    def test_load_returns_none_for_empty_file(self, store, tmp_path):
        path = tmp_path / "merkle_manifest.json"
        path.write_text("", encoding="utf-8")
        assert store.load() is None

    def test_load_returns_none_for_version_mismatch(self, store, tmp_path):
        path = tmp_path / "merkle_manifest.json"
        path.write_text(
            json.dumps({"version": 999, "root_hash": "x"}),
            encoding="utf-8",
        )
        assert store.load() is None


# ── atomic write safety ─────────────────────────────────────


class TestAtomicWrite:
    def test_no_tmp_file_remains_after_save(self, store, sample_data, tmp_path):
        store.save(sample_data)
        tmp_file = tmp_path / "merkle_manifest.json.tmp"
        assert not tmp_file.exists()

    def test_save_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        s = JsonManifestStore(str(nested))
        s.save({"root_hash": "test"})
        assert s.exists()


# ── edge cases ──────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_data_save_load(self, store):
        store.save({})
        loaded = store.load()
        assert loaded is not None
        assert "version" in loaded

    def test_unicode_in_data(self, store):
        store.save({"root_hash": "abc", "note": "Xin chao"})
        loaded = store.load()
        assert loaded is not None
        assert loaded["note"] == "Xin chao"
