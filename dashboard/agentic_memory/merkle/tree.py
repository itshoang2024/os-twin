"""Pure Merkle tree data structure and diff algorithm.

``MerkleTree`` is a stateless N-ary hash tree that mirrors a directory
hierarchy.  It has **no I/O, no persistence, and no side effects**.
The hash algorithm is injected via ``HashStrategy``.

``MerkleDiff`` is a frozen dataclass (Value Object) holding the result
of comparing two trees.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set

from .hashers import Sha256Hasher
from .protocols import HashStrategy


# ---------------------------------------------------------------------------
# Value Object — immutable diff result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MerkleDiff:
    """Immutable result of comparing two ``MerkleTree`` instances.

    Frozen dataclass ensures it cannot be mutated after creation.
    """

    changed_leaves: FrozenSet[str] = field(default_factory=frozenset)
    added_leaves: FrozenSet[str] = field(default_factory=frozenset)
    removed_leaves: FrozenSet[str] = field(default_factory=frozenset)
    unchanged_subtrees: FrozenSet[str] = field(default_factory=frozenset)

    @property
    def has_changes(self) -> bool:
        return bool(self.changed_leaves or self.added_leaves or self.removed_leaves)

    @property
    def all_changed(self) -> FrozenSet[str]:
        return self.changed_leaves | self.added_leaves | self.removed_leaves


# ---------------------------------------------------------------------------
# MerkleTree — pure data structure
# ---------------------------------------------------------------------------

# Sentinel for the per-node hash key inside the nested dict.
_HASH_KEY = "_hash"


class MerkleTree:
    """N-ary Merkle hash tree over a directory-like structure.

    Leaves are identified by their filepath (e.g. ``"devops/k8s/pod.md"``)
    and carry an opaque content-hash string.  Directory nodes aggregate
    their children's hashes via the injected ``HashStrategy``.

    The tree works exclusively with ``Dict[str, str]`` mappings
    (filepath -> content_hash).  It never imports or references
    ``MemoryNote``, enforcing the Dependency Inversion Principle.
    """

    def __init__(self, hasher: Optional[HashStrategy] = None):
        self._hasher: HashStrategy = hasher or Sha256Hasher()
        self._tree: dict = {}
        self._root_hash: str = ""

    # ── full (re)build ──────────────────────────────────────

    def build(self, leaves: Dict[str, str]) -> str:
        """Build the complete tree from ``{filepath: content_hash}``.

        Returns the root hash.  Order of *leaves* does not matter —
        children are sorted at each level.
        """
        raw: dict = {}
        for filepath, content_hash in leaves.items():
            parts = filepath.replace("\\", "/").split("/")
            node = raw
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = content_hash

        self._tree = self._hash_subtree(raw)
        self._root_hash = self._tree.get(_HASH_KEY, "")
        return self._root_hash

    # ── incremental updates ─────────────────────────────────

    def update_leaf(self, filepath: str, content_hash: str) -> str:
        """Insert or update a single leaf.  O(depth) re-hashes.

        Returns the new root hash.
        """
        parts = filepath.replace("\\", "/").split("/")
        stripped = self._strip_hashes(self._tree)
        self._set_leaf(stripped, parts, content_hash)
        self._tree = self._hash_subtree(stripped)
        self._root_hash = self._tree.get(_HASH_KEY, "")
        return self._root_hash

    def remove_leaf(self, filepath: str) -> str:
        """Remove a single leaf.  O(depth) re-hashes.

        Empty parent directories are pruned automatically.
        Returns the new root hash.
        """
        parts = filepath.replace("\\", "/").split("/")
        stripped = self._strip_hashes(self._tree)
        self._remove_at(stripped, parts)
        self._tree = self._hash_subtree(stripped)
        self._root_hash = self._tree.get(_HASH_KEY, "")
        return self._root_hash

    # ── diff ────────────────────────────────────────────────

    def diff(self, other: MerkleTree) -> MerkleDiff:
        """Compare *self* against *other*, pruning unchanged subtrees.

        Returns a ``MerkleDiff`` describing added / removed / changed
        leaves and which subtrees were skipped entirely.
        """
        changed: Set[str] = set()
        added: Set[str] = set()
        removed: Set[str] = set()
        unchanged: Set[str] = set()

        self._diff_recursive(self._tree, other._tree, "", changed, added, removed, unchanged)

        return MerkleDiff(
            changed_leaves=frozenset(changed),
            added_leaves=frozenset(added),
            removed_leaves=frozenset(removed),
            unchanged_subtrees=frozenset(unchanged),
        )

    # ── serialization ───────────────────────────────────────

    @property
    def root_hash(self) -> str:
        return self._root_hash

    @property
    def tree_data(self) -> dict:
        """Raw nested dict suitable for JSON serialization."""
        return self._tree

    @classmethod
    def from_data(cls, data: dict, hasher: Optional[HashStrategy] = None) -> MerkleTree:
        """Reconstruct a ``MerkleTree`` from a previously-serialized dict."""
        tree = cls(hasher=hasher)
        tree._tree = data
        tree._root_hash = data.get(_HASH_KEY, "")
        return tree

    @property
    def leaf_count(self) -> int:
        """Count all leaf nodes in the tree."""
        return self._count_leaves(self._tree)

    # ── private helpers ─────────────────────────────────────

    def _hash_subtree(self, node: dict) -> dict:
        """Recursively compute ``_hash`` for every directory node."""
        result: dict = {}
        hash_parts: List[str] = []

        for key in sorted(node.keys()):
            if key == _HASH_KEY:
                continue
            value = node[key]
            if isinstance(value, str):
                # Leaf — prefix with "L:" for second-preimage protection
                result[key] = value
                hash_parts.append(f"L:{key}:{value}")
            elif isinstance(value, dict):
                child = self._hash_subtree(value)
                result[key] = child
                hash_parts.append(f"D:{key}:{child[_HASH_KEY]}")

        result[_HASH_KEY] = self._hasher(hash_parts) if hash_parts else ""
        return result

    @staticmethod
    def _set_leaf(node: dict, parts: List[str], value: str) -> None:
        if len(parts) == 1:
            node[parts[0]] = value
            return
        child = node.setdefault(parts[0], {})
        if isinstance(child, str):
            # Was a leaf, now becoming a directory (edge case)
            node[parts[0]] = {}
            child = node[parts[0]]
        MerkleTree._set_leaf(child, parts[1:], value)

    @staticmethod
    def _remove_at(node: dict, parts: List[str]) -> None:
        if len(parts) == 1:
            node.pop(parts[0], None)
            return
        child = node.get(parts[0])
        if not isinstance(child, dict):
            return
        MerkleTree._remove_at(child, parts[1:])
        # Prune empty directories (only _hash key or nothing remaining)
        remaining = {k for k in child if k != _HASH_KEY}
        if not remaining:
            del node[parts[0]]

    @staticmethod
    def _strip_hashes(node: dict) -> dict:
        """Deep-copy *node* with all ``_hash`` keys removed."""
        result: dict = {}
        for k, v in node.items():
            if k == _HASH_KEY:
                continue
            result[k] = MerkleTree._strip_hashes(v) if isinstance(v, dict) else v
        return result

    def _diff_recursive(
        self,
        a: dict,
        b: dict,
        prefix: str,
        changed: Set[str],
        added: Set[str],
        removed: Set[str],
        unchanged: Set[str],
    ) -> None:
        a_keys = {k for k in a if k != _HASH_KEY}
        b_keys = {k for k in b if k != _HASH_KEY}

        # Keys only in *a* → added
        for key in sorted(a_keys - b_keys):
            path = os.path.join(prefix, key) if prefix else key
            val = a[key]
            if isinstance(val, str):
                added.add(path)
            else:
                self._collect_leaves(val, path, added)

        # Keys only in *b* → removed
        for key in sorted(b_keys - a_keys):
            path = os.path.join(prefix, key) if prefix else key
            val = b[key]
            if isinstance(val, str):
                removed.add(path)
            else:
                self._collect_leaves(val, path, removed)

        # Common keys — compare
        for key in sorted(a_keys & b_keys):
            a_val = a[key]
            b_val = b[key]
            path = os.path.join(prefix, key) if prefix else key

            if isinstance(a_val, str) and isinstance(b_val, str):
                if a_val != b_val:
                    changed.add(path)
            elif isinstance(a_val, dict) and isinstance(b_val, dict):
                if a_val.get(_HASH_KEY) == b_val.get(_HASH_KEY):
                    unchanged.add(path)  # prune — skip entire subtree
                else:
                    self._diff_recursive(a_val, b_val, path, changed, added, removed, unchanged)
            else:
                # Type mismatch: leaf became dir or vice-versa
                if isinstance(a_val, str):
                    added.add(path)
                else:
                    self._collect_leaves(a_val, path, added)
                if isinstance(b_val, str):
                    removed.add(path)
                else:
                    self._collect_leaves(b_val, path, removed)

    @staticmethod
    def _collect_leaves(node: dict, prefix: str, target: Set[str]) -> None:
        for key, val in node.items():
            if key == _HASH_KEY:
                continue
            path = os.path.join(prefix, key) if prefix else key
            if isinstance(val, str):
                target.add(path)
            elif isinstance(val, dict):
                MerkleTree._collect_leaves(val, path, target)

    @staticmethod
    def _count_leaves(node: dict) -> int:
        count = 0
        for key, val in node.items():
            if key == _HASH_KEY:
                continue
            if isinstance(val, str):
                count += 1
            elif isinstance(val, dict):
                count += MerkleTree._count_leaves(val)
        return count
