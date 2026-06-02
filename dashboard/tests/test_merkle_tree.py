"""Tests for ``MerkleTree`` and ``MerkleDiff``.

Covers: build, deterministic hashing, incremental update/remove,
diff with subtree pruning, serialization round-trip, leaf counting,
and second-preimage prefix differentiation.
"""

import os
import pytest

from dashboard.agentic_memory.merkle.hashers import Sha256Hasher
from dashboard.agentic_memory.merkle.tree import MerkleDiff, MerkleTree


# ── fixtures ────────────────────────────────────────────────


@pytest.fixture
def hasher():
    return Sha256Hasher()


@pytest.fixture
def sample_leaves():
    return {
        "devops/kubernetes/pod-basics.md": "aaa111",
        "devops/kubernetes/networking.md": "bbb222",
        "devops/cicd/pipeline.md": "ccc333",
        "architecture/database/postgres.md": "ddd444",
        "quicknote.md": "eee555",
    }


# ── build ───────────────────────────────────────────────────


class TestBuild:
    def test_empty_tree(self):
        t = MerkleTree()
        root = t.build({})
        assert root == ""
        assert t.leaf_count == 0

    def test_single_leaf(self):
        t = MerkleTree()
        root = t.build({"note.md": "abc123"})
        assert root != ""
        assert len(root) == 16  # SHA-256 truncated to 16 hex chars
        assert t.leaf_count == 1

    def test_multiple_leaves(self, sample_leaves):
        t = MerkleTree()
        root = t.build(sample_leaves)
        assert root != ""
        assert t.leaf_count == 5

    def test_deterministic_regardless_of_insertion_order(self, sample_leaves):
        t1 = MerkleTree()
        t1.build(sample_leaves)

        reversed_leaves = dict(reversed(list(sample_leaves.items())))
        t2 = MerkleTree()
        t2.build(reversed_leaves)

        assert t1.root_hash == t2.root_hash

    def test_different_content_produces_different_root(self, sample_leaves):
        t1 = MerkleTree()
        t1.build(sample_leaves)

        modified = dict(sample_leaves)
        modified["devops/kubernetes/pod-basics.md"] = "CHANGED"
        t2 = MerkleTree()
        t2.build(modified)

        assert t1.root_hash != t2.root_hash

    def test_hash_length_is_16(self, sample_leaves):
        t = MerkleTree()
        t.build(sample_leaves)
        assert len(t.root_hash) == 16

    def test_windows_path_separators_normalized(self):
        t1 = MerkleTree()
        t1.build({"dir/sub/note.md": "abc"})

        t2 = MerkleTree()
        t2.build({"dir\\sub\\note.md": "abc"})

        assert t1.root_hash == t2.root_hash


# ── incremental update ──────────────────────────────────────


class TestUpdateLeaf:
    def test_update_existing_leaf(self, sample_leaves):
        t = MerkleTree()
        t.build(sample_leaves)
        old_root = t.root_hash

        t.update_leaf("devops/kubernetes/pod-basics.md", "NEWVALUE")
        assert t.root_hash != old_root
        assert t.leaf_count == 5

    def test_add_new_leaf(self, sample_leaves):
        t = MerkleTree()
        t.build(sample_leaves)

        t.update_leaf("newdir/brand-new.md", "fff666")
        assert t.leaf_count == 6

    def test_update_produces_same_result_as_rebuild(self, sample_leaves):
        # Build, then update one leaf
        t1 = MerkleTree()
        t1.build(sample_leaves)
        t1.update_leaf("devops/kubernetes/pod-basics.md", "UPDATED")

        # Full rebuild with the updated value
        modified = dict(sample_leaves)
        modified["devops/kubernetes/pod-basics.md"] = "UPDATED"
        t2 = MerkleTree()
        t2.build(modified)

        assert t1.root_hash == t2.root_hash


# ── remove ──────────────────────────────────────────────────


class TestRemoveLeaf:
    def test_remove_existing_leaf(self, sample_leaves):
        t = MerkleTree()
        t.build(sample_leaves)
        old_root = t.root_hash

        t.remove_leaf("quicknote.md")
        assert t.root_hash != old_root
        assert t.leaf_count == 4

    def test_remove_cleans_up_empty_dirs(self):
        t = MerkleTree()
        t.build({"lonely/dir/only-child.md": "abc"})
        assert t.leaf_count == 1

        t.remove_leaf("lonely/dir/only-child.md")
        assert t.leaf_count == 0
        # The tree should be empty (just _hash key)
        data_keys = {k for k in t.tree_data if k != "_hash"}
        assert len(data_keys) == 0

    def test_remove_nonexistent_is_safe(self, sample_leaves):
        t = MerkleTree()
        t.build(sample_leaves)
        old_root = t.root_hash

        t.remove_leaf("does/not/exist.md")
        # Root hash may or may not change (empty dir pruning) but no crash
        assert t.leaf_count == 5

    def test_remove_produces_same_result_as_rebuild(self, sample_leaves):
        # Build full, then remove one
        t1 = MerkleTree()
        t1.build(sample_leaves)
        t1.remove_leaf("devops/cicd/pipeline.md")

        # Rebuild without that leaf
        reduced = {k: v for k, v in sample_leaves.items() if k != "devops/cicd/pipeline.md"}
        t2 = MerkleTree()
        t2.build(reduced)

        assert t1.root_hash == t2.root_hash


# ── diff ────────────────────────────────────────────────────


class TestDiff:
    def test_identical_trees_no_changes(self, sample_leaves):
        t1 = MerkleTree()
        t1.build(sample_leaves)
        t2 = MerkleTree()
        t2.build(sample_leaves)

        diff = t1.diff(t2)
        assert not diff.has_changes
        assert len(diff.unchanged_subtrees) > 0

    def test_one_changed_leaf(self, sample_leaves):
        t1 = MerkleTree()
        t1.build(sample_leaves)

        modified = dict(sample_leaves)
        modified["devops/kubernetes/pod-basics.md"] = "CHANGED"
        t2 = MerkleTree()
        t2.build(modified)

        diff = t2.diff(t1)
        assert diff.has_changes
        assert "devops/kubernetes/pod-basics.md" in diff.changed_leaves
        assert len(diff.added_leaves) == 0
        assert len(diff.removed_leaves) == 0

    def test_unchanged_subtree_pruned(self, sample_leaves):
        t1 = MerkleTree()
        t1.build(sample_leaves)

        # Only change something in devops/kubernetes — architecture should be pruned
        modified = dict(sample_leaves)
        modified["devops/kubernetes/pod-basics.md"] = "CHANGED"
        t2 = MerkleTree()
        t2.build(modified)

        diff = t2.diff(t1)
        assert "architecture" in diff.unchanged_subtrees

    def test_added_leaf(self, sample_leaves):
        t1 = MerkleTree()
        t1.build(sample_leaves)

        extended = dict(sample_leaves)
        extended["newdir/added.md"] = "new_hash"
        t2 = MerkleTree()
        t2.build(extended)

        diff = t2.diff(t1)
        assert "newdir/added.md" in diff.added_leaves

    def test_removed_leaf(self, sample_leaves):
        t1 = MerkleTree()
        t1.build(sample_leaves)

        reduced = {k: v for k, v in sample_leaves.items() if k != "quicknote.md"}
        t2 = MerkleTree()
        t2.build(reduced)

        diff = t2.diff(t1)
        assert "quicknote.md" in diff.removed_leaves

    def test_all_changed_union(self, sample_leaves):
        t1 = MerkleTree()
        t1.build(sample_leaves)

        modified = dict(sample_leaves)
        modified["devops/kubernetes/pod-basics.md"] = "CHANGED"
        modified["brand-new.md"] = "added_hash"
        del modified["quicknote.md"]
        t2 = MerkleTree()
        t2.build(modified)

        diff = t2.diff(t1)
        all_c = diff.all_changed
        assert "devops/kubernetes/pod-basics.md" in all_c
        assert "brand-new.md" in all_c
        assert "quicknote.md" in all_c

    def test_diff_with_empty_tree(self, sample_leaves):
        t1 = MerkleTree()
        t1.build(sample_leaves)

        empty = MerkleTree()
        empty.build({})

        diff = t1.diff(empty)
        assert len(diff.added_leaves) == 5
        assert len(diff.removed_leaves) == 0


# ── serialization round-trip ────────────────────────────────


class TestSerialization:
    def test_round_trip(self, sample_leaves):
        t = MerkleTree()
        t.build(sample_leaves)
        data = t.tree_data

        restored = MerkleTree.from_data(data)
        assert restored.root_hash == t.root_hash
        assert restored.leaf_count == t.leaf_count

    def test_from_data_with_custom_hasher(self, sample_leaves, hasher):
        t = MerkleTree(hasher=hasher)
        t.build(sample_leaves)

        restored = MerkleTree.from_data(t.tree_data, hasher=hasher)
        assert restored.root_hash == t.root_hash


# ── second preimage protection ──────────────────────────────


class TestSecondPreimage:
    def test_leaf_and_dir_with_same_name_produce_different_hashes(self):
        """A leaf named "foo.md" and a directory named "foo.md" must hash
        differently because the hasher receives "L:foo.md:..." vs
        "D:foo.md:..." prefixes."""
        t1 = MerkleTree()
        t1.build({"foo.md": "abc123"})

        t2 = MerkleTree()
        t2.build({"foo.md/nested.md": "abc123"})

        assert t1.root_hash != t2.root_hash


# ── MerkleDiff value object ────────────────────────────────


class TestMerkleDiff:
    def test_frozen(self):
        diff = MerkleDiff()
        with pytest.raises(AttributeError):
            diff.changed_leaves = frozenset(["x"])  # type: ignore[misc]

    def test_empty_diff_has_no_changes(self):
        diff = MerkleDiff()
        assert not diff.has_changes
        assert len(diff.all_changed) == 0

    def test_has_changes_when_changed(self):
        diff = MerkleDiff(changed_leaves=frozenset(["a.md"]))
        assert diff.has_changes

    def test_has_changes_when_added(self):
        diff = MerkleDiff(added_leaves=frozenset(["b.md"]))
        assert diff.has_changes

    def test_has_changes_when_removed(self):
        diff = MerkleDiff(removed_leaves=frozenset(["c.md"]))
        assert diff.has_changes
