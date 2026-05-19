"""IntegrityTracker — facade that coordinates Merkle tree, dirty
tracking, and manifest persistence.

This is the **only** class that ``AgenticMemorySystem`` interacts with.
It implements the ``IntegrityProvider`` protocol so the memory system
never needs to import any other Merkle-internal type.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional, Set

from .dirty import DirtyTracker
from .hashers import Sha256Hasher
from .protocols import HashStrategy, ManifestRepository
from .store import JsonManifestStore
from .tree import MerkleDiff, MerkleTree

logger = logging.getLogger(__name__)


class IntegrityTracker:
    """Facade coordinating ``MerkleTree``, ``DirtyTracker``, and a
    ``ManifestRepository``.

    All three collaborators are constructor-injected so tests can
    substitute in-memory doubles.

    Satisfies the ``IntegrityProvider`` protocol.
    """

    def __init__(
        self,
        persist_dir: Optional[str] = None,
        hasher: Optional[HashStrategy] = None,
        store: Optional[ManifestRepository] = None,
    ):
        self._persist_dir = persist_dir
        self._hasher: HashStrategy = hasher or Sha256Hasher()
        self._store: Optional[ManifestRepository] = store or (JsonManifestStore(persist_dir) if persist_dir else None)
        self._tree = MerkleTree(self._hasher)
        self._dirty = DirtyTracker()
        self._vectordb_root_hash: str = ""
        self._note_count: int = 0

    # ── IntegrityProvider: mutation notifications ───────────

    def notify_save(self, note_id: str, filepath: str, content_hash: str) -> None:
        """Called by ``AgenticMemorySystem._save_note()`` after a file write."""
        self._tree.update_leaf(filepath, content_hash)
        self._dirty.mark(note_id)

    def notify_delete(self, note_id: str, filepath: str) -> None:
        """Called by ``AgenticMemorySystem._delete_note_file()`` after a file remove."""
        self._tree.remove_leaf(filepath)
        self._dirty.mark(note_id)

    # ── IntegrityProvider: dirty tracking ───────────────────

    def get_dirty_ids(self) -> Set[str]:
        """Return note IDs changed since last flush."""
        return self._dirty.dirty_ids

    def needs_merge(self) -> bool:
        """``True`` if any mutation happened since last flush."""
        return self._dirty.is_dirty

    def flush(self) -> None:
        """Clear dirty state and persist the manifest."""
        self._dirty.flush()
        self._note_count = self._tree.leaf_count
        if self._store:
            self._store.save(
                {
                    "root_hash": self._tree.root_hash,
                    "note_count": self._note_count,
                    "tree": self._tree.tree_data,
                    "vectordb_root_hash": self._vectordb_root_hash,
                }
            )

    # ── IntegrityProvider: root hash ────────────────────────

    @property
    def root_hash(self) -> str:
        """Current Merkle root hash."""
        return self._tree.root_hash

    # ── IntegrityProvider: build / rebuild ──────────────────

    def build_from_notes(self, notes: Dict[str, Any]) -> str:
        """Full (re)build from a ``{id: MemoryNote}`` dict.

        Extracts ``filepath`` and ``content_hash`` from each note —
        the tree itself never touches ``MemoryNote`` directly.
        Returns the root hash.
        """
        leaves: Dict[str, str] = {}
        for note in notes.values():
            leaves[note.filepath] = note.content_hash
        root = self._tree.build(leaves)
        self._note_count = len(notes)
        return root

    def load_or_rebuild(self, notes: Dict[str, Any]) -> str:
        """Try loading the persisted manifest; rebuild if missing or stale.

        Returns the root hash.
        """
        if self._store:
            data = self._store.load()
            if data is not None and data.get("note_count") == len(notes):
                self._tree = MerkleTree.from_data(data["tree"], self._hasher)
                self._vectordb_root_hash = data.get("vectordb_root_hash", "")
                self._note_count = data.get("note_count", 0)
                logger.debug(
                    "Loaded Merkle manifest (%d notes, root=%s)",
                    self._note_count,
                    self._tree.root_hash,
                )
                return self._tree.root_hash

        # Manifest missing, corrupt, or note-count mismatch → full rebuild
        root = self.build_from_notes(notes)
        logger.info(
            "Rebuilt Merkle manifest (%d notes, root=%s)",
            self._note_count,
            root,
        )
        # Persist immediately so next boot is fast
        self.flush()
        return root

    # ── IntegrityProvider: diff against disk ────────────────

    def diff_against_disk(self, notes_dir: str) -> MerkleDiff:
        """Build a Merkle tree from on-disk note hashes and diff
        against the in-memory tree.

        Uses ``_extract_hash_from_frontmatter()`` for fast scanning —
        reads at most ~1 KB per file instead of fully parsing every note.
        """
        disk_leaves = self._scan_disk_hashes(notes_dir)
        disk_tree = MerkleTree(self._hasher)
        disk_tree.build(disk_leaves)
        return self._tree.diff(disk_tree)

    # ── vectordb integrity ──────────────────────────────────

    def compute_vectordb_hash(self, stored_hashes: Dict[str, str]) -> str:
        """Compute an aggregate hash of vectordb state.

        If this matches a previously stored value, the vectordb is
        consistent and the per-note check can be skipped.
        """
        parts = [f"{k}:{v}" for k, v in sorted(stored_hashes.items())]
        self._vectordb_root_hash = self._hasher(parts) if parts else ""
        return self._vectordb_root_hash

    @property
    def vectordb_root_hash(self) -> str:
        return self._vectordb_root_hash

    # ── internal helpers ────────────────────────────────────

    @staticmethod
    def _scan_disk_hashes(notes_dir: str) -> Dict[str, str]:
        """Walk *notes_dir* and extract ``content_hash`` from frontmatter.

        Returns ``{relative_filepath: content_hash}``.

        Only reads the first ~1 KB of each file — the ``content_hash``
        line is always near the top of the frontmatter block.
        """
        leaves: Dict[str, str] = {}
        if not os.path.isdir(notes_dir):
            return leaves

        for dirpath, _dirnames, filenames in os.walk(notes_dir):
            for filename in filenames:
                if not filename.endswith(".md"):
                    continue
                full = os.path.join(dirpath, filename)
                rel = os.path.relpath(full, notes_dir)
                h = IntegrityTracker._extract_hash_from_frontmatter(full)
                if h is not None:
                    leaves[rel] = h
        return leaves

    @staticmethod
    def _extract_hash_from_frontmatter(filepath: str) -> Optional[str]:
        """Read at most 1 KB to extract the ``content_hash`` field.

        Returns ``None`` if the file is unreadable or lacks the field.
        """
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                header = fh.read(1024)
            for line in header.split("\n"):
                if line.startswith("content_hash:"):
                    _, value = line.split(":", 1)
                    value = value.strip()
                    # Value is JSON-encoded in frontmatter (e.g. "abc123")
                    return json.loads(value)
        except Exception:
            pass
        return None
