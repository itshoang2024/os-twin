"""Hash strategy implementations for the Merkle tree.

Default is ``Sha256Hasher`` which truncates SHA-256 to 16 hex chars,
matching the format used by ``MemoryNote.compute_hash()``.
"""

from __future__ import annotations

import hashlib
from typing import List


class Sha256Hasher:
    """SHA-256 hasher truncated to 16 hex characters (64 bits).

    The caller (``MerkleTree``) prepends ``L:`` or ``D:`` prefixes to each
    part before passing them here, providing second-preimage protection
    per RFC 6962 (Certificate Transparency).

    This class satisfies the ``HashStrategy`` protocol.
    """

    def __call__(self, parts: List[str]) -> str:
        """Hash *parts* (already sorted by the caller) into a 16-char hex string."""
        combined = "\n".join(parts).encode("utf-8")
        return hashlib.sha256(combined).hexdigest()[:16]
