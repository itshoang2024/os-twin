"""Merkle integrity subsystem for Agentic Memory.

Public API re-exports — consuming code should only need::

    from dashboard.agentic_memory.merkle import (
        IntegrityTracker,
        IntegrityProvider,
        MerkleDiff,
    )
"""

from .protocols import IntegrityProvider
from .tracker import IntegrityTracker
from .tree import MerkleDiff

__all__ = [
    "IntegrityProvider",
    "IntegrityTracker",
    "MerkleDiff",
]
