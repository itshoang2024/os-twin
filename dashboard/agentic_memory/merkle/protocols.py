"""Protocols (interfaces) for the Merkle integrity subsystem.

Defines three runtime-checkable protocols following the same pattern
as ``EmbeddingFunction(Protocol)`` in ``retrievers.py``:

- ``HashStrategy`` — pluggable hash algorithm (Strategy pattern)
- ``ManifestRepository`` — persistence abstraction (Repository pattern)
- ``IntegrityProvider`` — facade interface consumed by ``AgenticMemorySystem`` (DIP)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Protocol, Set, runtime_checkable

if TYPE_CHECKING:
    from .tree import MerkleDiff


@runtime_checkable
class HashStrategy(Protocol):
    """Strategy for computing Merkle node hashes.

    Implementations must be **deterministic** and **order-independent**
    (callers pre-sort the input list).

    The ``L:`` / ``D:`` prefix convention for second-preimage protection
    (RFC 6962) is applied by the *caller* (``MerkleTree``), not by the hasher.
    """

    def __call__(self, parts: List[str]) -> str:
        """Hash a list of pre-sorted child descriptors into a hex string.

        Args:
            parts: Sorted list of strings, e.g.
                ``["D:dirname:child_hash", "L:file.md:leaf_hash"]``.

        Returns:
            Hex-encoded hash string (length is implementation-defined).
        """
        ...


@runtime_checkable
class ManifestRepository(Protocol):
    """Repository for persisting and loading Merkle manifests.

    Separates persistence concerns from tree logic so tests can
    inject an in-memory store.
    """

    def save(self, data: dict) -> None:
        """Persist manifest data (must be JSON-serializable)."""
        ...

    def load(self) -> Optional[dict]:
        """Load manifest data.  Returns ``None`` if not found or corrupted."""
        ...

    def exists(self) -> bool:
        """Check whether a persisted manifest exists."""
        ...


@runtime_checkable
class IntegrityProvider(Protocol):
    """Facade interface that ``AgenticMemorySystem`` depends on.

    This is the **only** Merkle-related type imported by the memory system.
    All implementation details (``MerkleTree``, ``DirtyTracker``,
    ``JsonManifestStore``) stay hidden behind this protocol.
    """

    def notify_save(self, note_id: str, filepath: str, content_hash: str) -> None:
        """Called after a note is written to disk."""
        ...

    def notify_delete(self, note_id: str, filepath: str) -> None:
        """Called after a note file is removed from disk."""
        ...

    def get_dirty_ids(self) -> Set[str]:
        """Return note IDs that changed since the last ``flush()``."""
        ...

    def flush(self) -> None:
        """Clear dirty tracking and persist the manifest."""
        ...

    def needs_merge(self) -> bool:
        """``True`` if any local mutation happened since the last flush."""
        ...

    @property
    def root_hash(self) -> str:
        """Current Merkle root hash (usable as a cache key)."""
        ...

    def build_from_notes(self, notes: Dict) -> str:
        """Full rebuild from ``{id: MemoryNote}`` dict.  Returns root hash."""
        ...

    def diff_against_disk(self, notes_dir: str) -> MerkleDiff:
        """Compare in-memory state against on-disk notes."""
        ...
