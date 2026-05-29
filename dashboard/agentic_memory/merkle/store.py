"""JSON-file-based ``ManifestRepository`` implementation.

Handles **atomic writes** (write-to-temp + ``os.replace``) to prevent
corruption from process crashes mid-write.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Schema version — bump when the manifest format changes in a
# backward-incompatible way.  ``load()`` rejects mismatches so the
# caller rebuilds from scratch.
_VERSION = 1


class JsonManifestStore:
    """Persist and load a Merkle manifest as a single JSON file.

    Implements the ``ManifestRepository`` protocol.

    File location: ``<persist_dir>/merkle_manifest.json``
    """

    def __init__(self, persist_dir: str):
        self._path = os.path.join(persist_dir, "merkle_manifest.json")

    # ── ManifestRepository implementation ───────────────────

    def save(self, data: dict) -> None:
        """Atomically write *data* to disk.

        Strategy: write to a temporary file in the same directory,
        then ``os.replace`` (atomic on POSIX, near-atomic on Windows).
        """
        payload = {
            "version": _VERSION,
            "generated_at": datetime.now().strftime("%Y%m%d%H%M%S"),
            **data,
        }
        tmp = self._path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self._path)
        except OSError:
            logger.exception("Failed to save Merkle manifest to %s", self._path)
            # Clean up the temp file if replace failed
            try:
                os.remove(tmp)
            except OSError:
                pass

    def load(self) -> Optional[dict]:
        """Load the manifest.

        Returns ``None`` if the file is missing, unreadable, corrupt,
        or has an incompatible schema version.
        """
        if not os.path.exists(self._path):
            return None
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("version") != _VERSION:
                logger.warning(
                    "Merkle manifest version mismatch (expected %d, got %s) — rebuilding",
                    _VERSION,
                    data.get("version"),
                )
                return None
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Corrupt Merkle manifest at %s: %s — rebuilding", self._path, exc)
            return None

    def exists(self) -> bool:
        """Check whether a manifest file exists on disk."""
        return os.path.exists(self._path)
