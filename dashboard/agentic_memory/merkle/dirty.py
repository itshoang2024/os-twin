"""Per-note dirty tracking for the integrity subsystem.

Replaces the system-wide ``self._dirty: bool`` flag in
``AgenticMemorySystem`` with per-note granularity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Set


@dataclass
class DirtyTracker:
    """Tracks which note IDs have been mutated since the last flush.

    Provides finer granularity than a single boolean flag:
    ``sync_to_disk()`` can write only the notes that actually changed.
    """

    _dirty_ids: Set[str] = field(default_factory=set)
    _has_mutations: bool = False

    def mark(self, note_id: str) -> None:
        """Record *note_id* as dirty."""
        self._dirty_ids.add(note_id)
        self._has_mutations = True

    def flush(self) -> Set[str]:
        """Return the dirty set and reset.

        Returns a **copy** so the caller can iterate safely while
        the tracker accepts new marks.
        """
        ids = self._dirty_ids.copy()
        self._dirty_ids.clear()
        self._has_mutations = False
        return ids

    @property
    def is_dirty(self) -> bool:
        """``True`` if at least one note was marked since the last flush."""
        return self._has_mutations

    @property
    def dirty_ids(self) -> Set[str]:
        """Snapshot of currently-dirty note IDs (defensive copy)."""
        return self._dirty_ids.copy()
