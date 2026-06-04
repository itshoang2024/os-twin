# Plan 021: Merkle Tree Integration for Memory Sync & Integrity

**Status:** Draft
**Date:** 2026-05-18
**Depends on:** Plan 019 (consolidation to dashboard), Plan 020 (batch mode prerequisite for Epic 3)

---

## Problem

The Agentic Memory system has six O(N) operations that scale linearly with note count:

| Operation | Current cost | Where |
|-----------|-------------|-------|
| `sync_to_disk()` — writes **every** note | O(N) disk writes | `memory_system.py:1338` |
| `merge_from_disk()` — reads **every** `.md` file | O(N) disk reads + parses | `memory_system.py:1158` |
| Vectordb consistency check — fetches **all** stored hashes | O(N) hash comparisons | `memory_system.py:1214` |
| Dashboard graph endpoint — re-walks disk on every request | O(N) per HTTP request | `routes/amem.py:312` |
| Dashboard stats endpoint — re-walks disk on every request | O(N) per HTTP request | `routes/amem.py:496` |
| `_dirty` flag — system-wide, not per-subtree | All-or-nothing merge | `memory_system.py:1330` |

At 50 notes these are negligible. At 500+ notes (realistic after weeks of multi-agent operation), auto-sync every 60 seconds means **500 file writes every minute** even when nothing changed.

### Root cause

There is no mechanism to know **which subtrees changed** without reading everything. The system has per-note content hashes (`MemoryNote.compute_hash()`) but no aggregation of these hashes up the directory tree.

### What already exists (building blocks)

1. **Per-note SHA-256 hash** — `compute_hash()` at `memory_note.py:110` covers content+context+keywords+tags, truncated to 16 hex chars
2. **Hierarchical filepath** — `note.filepath` yields paths like `devops/kubernetes/container-basics.md`, giving us a natural tree topology
3. **`_build_filepath_tree()`** — `memory_system.py:576` already builds a nested dict from note filepaths (used by `tree()` command)
4. **Hash stored in vectordb metadata** — `_build_note_metadata()` at `memory_system.py:810` includes `content_hash` in vectordb writes
5. **Hash persisted in frontmatter** — `to_markdown()` at `memory_note.py:182` writes `content_hash` to disk

The gap: no **directory-level hash aggregation** that rolls leaf hashes up to a single root hash.

---

## Goal

Add a Merkle Tree overlay to the memory system that:
1. Reduces `sync_to_disk()` writes from O(N) to O(changed)
2. Reduces `merge_from_disk()` reads from O(N) to O(log N) detection + O(changed) reads
3. Enables O(1) cache validation for dashboard endpoints
4. Provides per-subtree dirty detection replacing the system-wide `_dirty` flag
5. Lays groundwork for cross-plan deduplication via root hash comparison

All without changing the public MCP tool interface or breaking existing tests.

---

## Non-goals

- Replacing `MemoryNote.compute_hash()` — the existing leaf hash is reused as-is
- Cryptographic security guarantees — this is integrity/consistency, not adversarial security
- Changing the on-disk note format (markdown with frontmatter stays the same)
- Modifying vector search or evolution logic (those are orthogonal)
- Full Git-like content-addressable storage (too complex, wrong problem)

---

## Architecture & Design Patterns

### Architectural audit of current codebase

The existing `agentic_memory` package uses:

| Pattern | Where | Formality |
|---------|-------|-----------|
| **Strategy** (implicit) | Retriever selection via `vector_backend` string | Duck-typed, no ABC/Protocol |
| **Strategy** (implicit) | Conflict resolution via `conflict_resolution` string | `if/else` branch in `_resolve_conflict()` |
| **Factory Method** | `_create_retriever()`, `_create_embedding_function()` | Concrete imports inside factory |
| **Flyweight/Multiton** | `_embedding_cache` in `retrievers.py` | Thread-safe, keyed by `(backend, model)` |
| **Protocol** | `EmbeddingFunction` in `retrievers.py` | Only formal interface in the package |
| **Constructor DI** | `completion_fn`, `embed_fn` in `AgenticMemorySystem` | Optional with self-resolution fallback |
| **Value Object** | `KnowledgeLink` | Frozen dataclass |
| **Composite** | `MemoryConfig` | Six nested dataclasses |
| **Object Pool** | `MemoryPool` | Full lifecycle pool with LRU eviction |

**Key anti-patterns to avoid reinforcing:**
1. `AgenticMemorySystem` is a 2017-line God Object — don't add more responsibility to it
2. Retrievers lack a formal interface — 11 duck-typed methods with `hasattr()` checks
3. No type annotations on `self.retriever` attribute

### Design principles for Merkle integration

1. **SRP (Single Responsibility)** — Decompose into focused classes, each with one reason to change
2. **DIP (Dependency Inversion)** — `AgenticMemorySystem` depends on a `Protocol`, not concrete Merkle classes
3. **OCP (Open/Closed)** — Hash algorithm is pluggable via Strategy pattern without modifying tree logic
4. **ISP (Interface Segregation)** — Separate interfaces for tree operations vs. persistence vs. diffing
5. **Consistency** — Follow existing patterns: `Protocol` for interfaces (like `EmbeddingFunction`), `@dataclass` for data, constructor DI for collaborators

### Class decomposition (5 classes, 3 protocols)

```
                    ┌───────────────────────┐
                    │  AgenticMemorySystem   │
                    │  (existing, modified)  │
                    │                        │
                    │  self._integrity:      │
                    │    IntegrityTracker     │─ ─ ─ constructor DI
                    └───────────┬────────────┘
                                │ uses
                    ┌───────────▼────────────┐
                    │    IntegrityTracker     │ ← Facade / Mediator
                    │    (new, ~120 lines)    │
                    │                        │
                    │  Coordinates:           │
                    │  - MerkleTree           │
                    │  - DirtyTracker         │
                    │  - ManifestStore        │
                    └──┬────────┬─────────┬──┘
                       │        │         │
          ┌────────────▼──┐ ┌───▼──────┐ ┌▼──────────────┐
          │  MerkleTree    │ │  Dirty   │ │ ManifestStore  │
          │  (new, ~200)   │ │  Tracker │ │ (new, ~80)     │
          │                │ │ (new,~50)│ │                │
          │ build()        │ │ mark()   │ │ save(tree)     │
          │ update_leaf()  │ │ flush()  │ │ load() -> tree │
          │ remove_leaf()  │ │ dirty()  │ │                │
          │ diff(other)    │ │ ids()    │ │ Implements:    │
          │                │ │          │ │ ManifestRepo   │
          │ Uses:          │ └──────────┘ └────────────────┘
          │ HashStrategy   │
          └───────┬────────┘
                  │ uses
          ┌───────▼────────┐
          │  HashStrategy   │ ← Strategy pattern
          │  (Protocol)     │
          │                 │
          │  __call__(parts)│
          │    -> str       │
          │                 │
          ├─────────────────┤
          │ Sha256Hasher    │ ← default implementation
          │ (truncated 16)  │
          └─────────────────┘
```

### Protocols (interfaces)

```python
# In merkle_manifest.py

from typing import Protocol, runtime_checkable, Dict, Set, Optional


@runtime_checkable
class HashStrategy(Protocol):
    """Strategy for computing Merkle node hashes.

    Follows the existing EmbeddingFunction(Protocol) pattern in retrievers.py.
    Implementations must be deterministic and order-independent (inputs are pre-sorted).
    """

    def __call__(self, parts: list[str]) -> str:
        """Hash a list of pre-sorted child descriptors into a single hash string.

        Args:
            parts: Sorted list of strings like ["D:dirname:child_hash", "L:file.md:leaf_hash"]

        Returns:
            Hex string hash (length determined by implementation).
        """
        ...


@runtime_checkable
class ManifestRepository(Protocol):
    """Repository for persisting and loading Merkle manifests.

    Follows the Repository pattern — separates persistence concerns
    from the tree logic. Enables testing with in-memory stores.
    """

    def save(self, data: dict) -> None:
        """Persist manifest data."""
        ...

    def load(self) -> Optional[dict]:
        """Load manifest data. Returns None if not found or corrupted."""
        ...

    def exists(self) -> bool:
        """Check if a persisted manifest exists."""
        ...


@runtime_checkable
class IntegrityProvider(Protocol):
    """Interface that AgenticMemorySystem depends on for integrity tracking.

    This is the only protocol visible to the memory system.
    Keeps the Merkle implementation details hidden behind this facade.
    """

    def notify_save(self, note_id: str, filepath: str, content_hash: str) -> None:
        """Called after a note is saved to disk."""
        ...

    def notify_delete(self, note_id: str, filepath: str) -> None:
        """Called after a note is deleted from disk."""
        ...

    def get_dirty_ids(self) -> Set[str]:
        """Return the set of note IDs that changed since last flush."""
        ...

    def flush(self) -> None:
        """Clear dirty tracking and persist manifest."""
        ...

    def needs_merge(self) -> bool:
        """True if any local mutation happened since last flush."""
        ...

    @property
    def root_hash(self) -> str:
        """Current Merkle root hash (for cache keys)."""
        ...

    def build_from_notes(self, notes: Dict) -> str:
        """Full rebuild from a notes dict. Returns root hash."""
        ...

    def diff_against_disk(self, notes_dir: str) -> "MerkleDiff":
        """Compare in-memory state against disk state."""
        ...
```

### Concrete classes

#### 1. `Sha256Hasher` — default hash strategy (~20 lines)

```python
class Sha256Hasher:
    """SHA-256 hasher truncated to 16 hex chars.

    Matches the existing MemoryNote.compute_hash() output format.
    Implements the Certificate Transparency L:/D: prefix convention.
    """

    def __call__(self, parts: list[str]) -> str:
        combined = "\n".join(parts).encode("utf-8")
        return hashlib.sha256(combined).hexdigest()[:16]
```

Swappable: `Xxh128Hasher` could be added later for speed (xxhash is ~10x faster than SHA-256 for non-cryptographic use).

#### 2. `MerkleTree` — pure tree logic (~200 lines)

```python
class MerkleTree:
    """N-ary Merkle hash tree over a directory-like structure.

    Pure data structure — no I/O, no persistence, no side effects.
    Receives a HashStrategy via constructor injection.
    """

    def __init__(self, hasher: HashStrategy = None):
        self._hasher = hasher or Sha256Hasher()
        self._tree: dict = {}
        self._root_hash: str = ""

    def build(self, leaves: Dict[str, str]) -> str:
        """Build tree from {filepath: content_hash} mapping. Returns root hash."""
        ...

    def update_leaf(self, filepath: str, content_hash: str) -> str:
        """Update one leaf, recompute path to root. O(depth). Returns new root hash."""
        ...

    def remove_leaf(self, filepath: str) -> str:
        """Remove one leaf, recompute path to root. O(depth). Returns new root hash."""
        ...

    def diff(self, other: "MerkleTree") -> "MerkleDiff":
        """Compare two trees, pruning unchanged subtrees. Returns MerkleDiff."""
        ...

    @property
    def root_hash(self) -> str: ...

    @property
    def tree_data(self) -> dict:
        """Raw tree dict for serialization."""
        ...

    @classmethod
    def from_data(cls, data: dict, hasher: HashStrategy = None) -> "MerkleTree":
        """Reconstruct from serialized tree dict (loaded from manifest)."""
        ...
```

**Key**: `build()` accepts `Dict[str, str]` (filepath -> content_hash), NOT `Dict[str, MemoryNote]`. The tree never imports or knows about `MemoryNote` — it only works with strings. This follows DIP: the tree depends on an abstraction (filepath+hash pairs), not on a concrete note class.

#### 3. `DirtyTracker` — per-note mutation tracking (~50 lines)

```python
@dataclass
class DirtyTracker:
    """Tracks which note IDs have been mutated since last flush.

    Replaces the system-wide `self._dirty: bool` flag with
    per-note granularity. Follows the Value Object pattern.
    """

    _dirty_ids: Set[str] = field(default_factory=set)
    _has_mutations: bool = False

    def mark(self, note_id: str) -> None:
        """Mark a note as dirty."""
        self._dirty_ids.add(note_id)
        self._has_mutations = True

    def flush(self) -> Set[str]:
        """Return and clear all dirty IDs."""
        ids = self._dirty_ids.copy()
        self._dirty_ids.clear()
        self._has_mutations = False
        return ids

    @property
    def is_dirty(self) -> bool:
        return self._has_mutations

    @property
    def dirty_ids(self) -> Set[str]:
        return self._dirty_ids.copy()
```

#### 4. `JsonManifestStore` — file-based persistence (~80 lines)

```python
class JsonManifestStore:
    """JSON file-based ManifestRepository implementation.

    Implements ManifestRepository protocol.
    Handles atomic writes (write-to-temp + rename) to prevent corruption.
    """

    VERSION = 1

    def __init__(self, persist_dir: str):
        self._path = os.path.join(persist_dir, "merkle_manifest.json")

    def save(self, data: dict) -> None:
        """Atomic write: temp file + os.replace() to prevent partial writes."""
        payload = {
            "version": self.VERSION,
            "generated_at": datetime.now().strftime("%Y%m%d%H%M%S"),
            **data,
        }
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self._path)  # atomic on POSIX

    def load(self) -> Optional[dict]:
        """Load and validate. Returns None on missing/corrupt/version-mismatch."""
        if not os.path.exists(self._path):
            return None
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("version") != self.VERSION:
                return None
            return data
        except (json.JSONDecodeError, OSError):
            return None

    def exists(self) -> bool:
        return os.path.exists(self._path)
```

**Improvement over original plan**: Atomic writes via `os.replace()` prevent manifest corruption from process crashes mid-write.

#### 5. `IntegrityTracker` — facade coordinating the pieces (~120 lines)

```python
class IntegrityTracker:
    """Facade that coordinates MerkleTree, DirtyTracker, and ManifestStore.

    This is the only class that AgenticMemorySystem interacts with.
    Implements the IntegrityProvider protocol.

    Constructor injection for all collaborators enables testing
    with in-memory stores and mock hashers.
    """

    def __init__(
        self,
        persist_dir: Optional[str] = None,
        hasher: HashStrategy = None,
        store: ManifestRepository = None,
    ):
        self._hasher = hasher or Sha256Hasher()
        self._store = store or (JsonManifestStore(persist_dir) if persist_dir else None)
        self._tree = MerkleTree(self._hasher)
        self._dirty = DirtyTracker()
        self._vectordb_root_hash: str = ""

    # ── IntegrityProvider implementation ────────────────────

    def notify_save(self, note_id: str, filepath: str, content_hash: str) -> None:
        self._tree.update_leaf(filepath, content_hash)
        self._dirty.mark(note_id)

    def notify_delete(self, note_id: str, filepath: str) -> None:
        self._tree.remove_leaf(filepath)
        self._dirty.mark(note_id)

    def get_dirty_ids(self) -> Set[str]:
        return self._dirty.dirty_ids

    def flush(self) -> None:
        self._dirty.flush()
        if self._store:
            self._store.save({
                "root_hash": self._tree.root_hash,
                "note_count": ...,
                "tree": self._tree.tree_data,
                "vectordb_root_hash": self._vectordb_root_hash,
            })

    def needs_merge(self) -> bool:
        return self._dirty.is_dirty

    @property
    def root_hash(self) -> str:
        return self._tree.root_hash

    def build_from_notes(self, notes: Dict) -> str:
        leaves = {n.filepath: n.content_hash for n in notes.values()}
        return self._tree.build(leaves)

    def diff_against_disk(self, notes_dir: str) -> MerkleDiff:
        disk_leaves = self._scan_disk_hashes(notes_dir)
        disk_tree = MerkleTree(self._hasher)
        disk_tree.build(disk_leaves)
        return self._tree.diff(disk_tree)

    # ── Vectordb integrity ──────────────────────────────────

    def compute_vectordb_hash(self, stored_hashes: Dict[str, str]) -> str:
        parts = [f"{k}:{v}" for k, v in sorted(stored_hashes.items())]
        self._vectordb_root_hash = self._hasher(parts)
        return self._vectordb_root_hash

    @property
    def vectordb_root_hash(self) -> str:
        return self._vectordb_root_hash

    # ── Boot: load or rebuild ───────────────────────────────

    def load_or_rebuild(self, notes: Dict) -> str:
        """Try loading persisted manifest; rebuild if missing/stale."""
        if self._store:
            data = self._store.load()
            if data and data.get("note_count") == len(notes):
                self._tree = MerkleTree.from_data(data["tree"], self._hasher)
                self._vectordb_root_hash = data.get("vectordb_root_hash", "")
                return self._tree.root_hash
        return self.build_from_notes(notes)
```

### Dependency injection into AgenticMemorySystem

The integration follows the same pattern as `completion_fn` and `embed_fn`:

```python
class AgenticMemorySystem:
    def __init__(
        self,
        # ... existing params ...
        integrity: IntegrityProvider = None,     # NEW: optional DI
    ):
        # ... existing init ...

        # Integrity tracking (Merkle tree + dirty tracking)
        if integrity is not None:
            self._integrity = integrity
        else:
            self._integrity = IntegrityTracker(
                persist_dir=self.persist_dir
            )
```

This means:
- **Production**: auto-creates `IntegrityTracker` with default `Sha256Hasher` and `JsonManifestStore`
- **Tests**: inject a mock `IntegrityProvider` or an `IntegrityTracker` with in-memory store
- **Custom hash**: `IntegrityTracker(hasher=Xxh128Hasher())` — no changes to `AgenticMemorySystem`

### Integration points (minimal surface area)

Only **4 call sites** in `AgenticMemorySystem` need modification:

```python
# 1. _save_note() — after writing the file (1 line added):
self._integrity.notify_save(note.id, note.filepath, note.content_hash)

# 2. _delete_note_file() — after removing the file (1 line added):
self._integrity.notify_delete(memory_id, note.filepath)

# 3. sync_to_disk() — replace the write loop:
dirty_ids = self._integrity.get_dirty_ids()
for note_id in dirty_ids:
    note = self.memories.get(note_id)
    if note:
        self._save_note(note, touch_modified=False)
self._integrity.flush()

# 4. _load_notes() — after loading, bootstrap the manifest:
self._integrity.load_or_rebuild(self.memories)
```

The memory system never imports `MerkleTree`, `DirtyTracker`, or `JsonManifestStore` — it only depends on `IntegrityProvider`. This is the Dependency Inversion Principle in action.

### Pattern summary

| Pattern | Class | Purpose |
|---------|-------|---------|
| **Strategy** | `HashStrategy` protocol + `Sha256Hasher` | Pluggable hash algorithm |
| **Repository** | `ManifestRepository` protocol + `JsonManifestStore` | Separates persistence from logic |
| **Facade** | `IntegrityTracker` | Single entry point coordinating 3 internal collaborators |
| **Protocol** (DIP) | `IntegrityProvider` | Decouples `AgenticMemorySystem` from Merkle implementation |
| **Value Object** | `MerkleDiff` | Immutable diff result |
| **Constructor DI** | `integrity: IntegrityProvider = None` | Optional injection with self-resolution fallback |
| **Atomic persistence** | `JsonManifestStore.save()` | Write-to-temp + `os.replace()` prevents corruption |
| **Template Method** | `MerkleTree._hash_tree()` | Delegates actual hashing to injected `HashStrategy` |

### File organization

```
dashboard/agentic_memory/
├── merkle/                         # NEW package (keeps merkle_manifest.py from growing)
│   ├── __init__.py                 # Re-exports: IntegrityTracker, IntegrityProvider, MerkleDiff
│   ├── protocols.py                # HashStrategy, ManifestRepository, IntegrityProvider (~60 lines)
│   ├── tree.py                     # MerkleTree + MerkleDiff (~200 lines)
│   ├── tracker.py                  # IntegrityTracker facade (~120 lines)
│   ├── dirty.py                    # DirtyTracker dataclass (~50 lines)
│   ├── hashers.py                  # Sha256Hasher (+ future Xxh128Hasher) (~30 lines)
│   └── store.py                    # JsonManifestStore (~80 lines)
├── memory_system.py                # MODIFIED: +4 call sites, +1 constructor param
├── memory_note.py                  # UNCHANGED
├── retrievers.py                   # UNCHANGED
├── config.py                       # UNCHANGED
└── ...
```

Total new code: ~540 lines across 7 files (vs. original plan's ~300 lines in 1 monolithic file).
More files, but each is focused, testable, and independently replaceable.

---

## Design

### Merkle Tree topology

The tree structure mirrors the existing note directory hierarchy:

```
Root Hash: sha256(hash("devops") + hash("architecture") + hash("unfiled"))
├── devops/
│   Hash: sha256(hash("kubernetes") + hash("cicd"))
│   ├── kubernetes/
│   │   Hash: sha256(hash("container-basics") + hash("pod-networking"))
│   │   ├── container-basics.md  → leaf hash: abc123def456789a
│   │   └── pod-networking.md    → leaf hash: def456abc789012b
│   └── cicd/
│       Hash: sha256(hash("pipeline-design"))
│       └── pipeline-design.md   → leaf hash: 789abc012def345c
├── architecture/
│   Hash: sha256(hash("database"))
│   └── database/
│       Hash: sha256(hash("postgres-indexing"))
│       └── postgres-indexing.md → leaf hash: e1f2g3h4i5j6k7l8
└── unfiled/
    Hash: sha256(hash("quick-note"))
    └── quick-note.md            → leaf hash: m9n0o1p2q3r4s5t6
```

**Key design decisions:**

1. **N-ary tree, not binary** — matches the actual directory structure (variable children per node). This is how ZFS and Cassandra use Merkle trees for anti-entropy.
2. **Leaf hash = existing `content_hash`** — no new computation needed for leaves; reuses the existing SHA-256 (16 hex chars) from `MemoryNote.compute_hash()`
3. **Directory hash = SHA-256 of sorted children hashes** — `sha256(sorted([child_name + ":" + child_hash for child in children]))`, truncated to 16 hex chars for consistency
4. **Manifest file** — persisted as `<persist_dir>/merkle_manifest.json` alongside `notes/` and `vectordb/`
5. **Second preimage protection** — leaf hashes are prefixed with `"L:"` and directory hashes with `"D:"` before hashing, following the Certificate Transparency RFC 6962 pattern

### Manifest file format

```json
{
  "version": 1,
  "root_hash": "a3f8c1d2e4b7f9a0",
  "generated_at": "20260518143022",
  "note_count": 5,
  "tree": {
    "_hash": "a3f8c1d2e4b7f9a0",
    "devops": {
      "_hash": "b7d2e4f1c9a3e8d0",
      "kubernetes": {
        "_hash": "c9f1a3b7d2e4f8c1",
        "container-basics.md": "abc123def456789a",
        "pod-networking.md": "def456abc789012b"
      },
      "cicd": {
        "_hash": "d1e2f3a4b5c6d7e8",
        "pipeline-design.md": "789abc012def345c"
      }
    },
    "architecture": {
      "_hash": "e1f2g3h4i5j6k7l8",
      "database": {
        "_hash": "f9a0b1c2d3e4f5a6",
        "postgres-indexing.md": "e1f2g3h4i5j6k7l8"
      }
    },
    "unfiled": {
      "_hash": "a0b1c2d3e4f5a6b7",
      "quick-note.md": "m9n0o1p2q3r4s5t6"
    }
  },
  "vectordb_root_hash": "x1y2z3w4v5u6t7s8"
}
```

**Conventions:**
- Keys ending in `.md` are **leaf nodes** (value = content_hash)
- Keys starting with `_` are **metadata** (`_hash` = this directory's aggregate hash)
- All other keys are **directory nodes** (value = nested object)
- `vectordb_root_hash` = SHA-256 of sorted `{note_id: content_hash}` pairs from the vectordb, enabling independent integrity checks

### Class implementations

> The full class designs for `MerkleTree`, `DirtyTracker`, `JsonManifestStore`, `IntegrityTracker`,
> and all three protocols (`HashStrategy`, `ManifestRepository`, `IntegrityProvider`) are specified
> in the **Architecture & Design Patterns** section above. The code samples there are the
> authoritative reference for implementation.

Below is the `MerkleDiff` value object and the diff algorithm, which is the most complex piece:

```python
# In merkle/tree.py

@dataclass(frozen=True)
class MerkleDiff:
    """Immutable result of comparing two MerkleTree instances.

    Value Object pattern — identity is based on content, not reference.
    Frozen dataclass ensures it cannot be accidentally mutated after creation.
    """
    changed_leaves: frozenset[str] = field(default_factory=frozenset)
    added_leaves: frozenset[str] = field(default_factory=frozenset)
    removed_leaves: frozenset[str] = field(default_factory=frozenset)
    unchanged_subtrees: frozenset[str] = field(default_factory=frozenset)

    @property
    def has_changes(self) -> bool:
        return bool(self.changed_leaves or self.added_leaves or self.removed_leaves)

    @property
    def all_changed(self) -> frozenset[str]:
        return self.changed_leaves | self.added_leaves | self.removed_leaves
```

The diff algorithm walks both trees simultaneously, pruning unchanged subtrees:

```python
# In MerkleTree.diff()

    def _diff_recursive(
        self, a: dict, b: dict, prefix: str, diff: "MerkleDiff"
    ):
        """Walk both trees simultaneously, pruning unchanged subtrees."""
        a_keys = {k for k in a if k != "_hash"}
        b_keys = {k for k in b if k != "_hash"}

        # Added (in a but not b)
        for key in sorted(a_keys - b_keys):
            val = a[key]
            if isinstance(val, str):
                diff.added_leaves.add(os.path.join(prefix, key) if prefix else key)
            else:
                self._collect_all_leaves(val, os.path.join(prefix, key), diff.added_leaves)

        # Removed (in b but not a)
        for key in sorted(b_keys - a_keys):
            val = b[key]
            if isinstance(val, str):
                diff.removed_leaves.add(os.path.join(prefix, key) if prefix else key)
            else:
                self._collect_all_leaves(val, os.path.join(prefix, key), diff.removed_leaves)

        # Common: compare hashes
        for key in sorted(a_keys & b_keys):
            a_val = a[key]
            b_val = b[key]
            path = os.path.join(prefix, key) if prefix else key

            if isinstance(a_val, str) and isinstance(b_val, str):
                # Both leaves
                if a_val != b_val:
                    diff.changed_leaves.add(path)
                # else: unchanged leaf
            elif isinstance(a_val, dict) and isinstance(b_val, dict):
                # Both directories: compare subtree hash
                if a_val.get("_hash") == b_val.get("_hash"):
                    diff.unchanged_subtrees.add(path)  # PRUNE — skip entire subtree
                else:
                    self._diff_recursive(a_val, b_val, path, diff)
            else:
                # Type mismatch (leaf became dir or vice versa)
                if isinstance(a_val, str):
                    diff.added_leaves.add(path)
                else:
                    self._collect_all_leaves(a_val, path, diff.added_leaves)
                if isinstance(b_val, str):
                    diff.removed_leaves.add(path)
                else:
                    self._collect_all_leaves(b_val, path, diff.removed_leaves)

    @staticmethod
    def _collect_all_leaves(node: dict, prefix: str, target: set):
        """Collect all leaf filepaths from a subtree."""
        for key, val in node.items():
            if key == "_hash":
                continue
            path = os.path.join(prefix, key) if prefix else key
            if isinstance(val, str):
                target.add(path)
            elif isinstance(val, dict):
                MerkleManifest._collect_all_leaves(val, path, target)

    # ── Incremental update ──────────────────────────────────

    def update_leaf(self, filepath: str, new_hash: str) -> str:
        """Update a single leaf and recompute hashes up to root.

        O(depth) operation — typically 2-4 hash recomputations.
        Returns new root hash.
        """
        parts = filepath.split(os.sep)
        self._set_leaf(self._tree, parts, new_hash)
        self._tree = self._hash_tree(self._strip_hashes(self._tree))
        self._root_hash = self._tree.get("_hash", "")
        return self._root_hash

    def remove_leaf(self, filepath: str) -> str:
        """Remove a leaf and recompute hashes up to root.

        Returns new root hash.
        """
        parts = filepath.split(os.sep)
        self._remove_at(self._tree, parts)
        self._tree = self._hash_tree(self._strip_hashes(self._tree))
        self._root_hash = self._tree.get("_hash", "")
        self._note_count = max(0, self._note_count - 1)
        return self._root_hash

    def _set_leaf(self, node: dict, parts: list, value: str):
        """Navigate to the leaf position and set its value."""
        if len(parts) == 1:
            node[parts[0]] = value
            return
        child = node.setdefault(parts[0], {})
        if isinstance(child, str):
            # Was a leaf, now becoming a directory — shouldn't happen in practice
            node[parts[0]] = {}
            child = node[parts[0]]
        self._set_leaf(child, parts[1:], value)

    def _remove_at(self, node: dict, parts: list):
        """Navigate to the leaf and remove it, cleaning empty dirs."""
        if len(parts) == 1:
            node.pop(parts[0], None)
            return
        child = node.get(parts[0])
        if not isinstance(child, dict):
            return
        self._remove_at(child, parts[1:])
        # Clean up empty directories (only _hash key remaining)
        remaining = {k for k in child if k != "_hash"}
        if not remaining:
            del node[parts[0]]

    @staticmethod
    def _strip_hashes(node: dict) -> dict:
        """Return a copy of the tree with all _hash keys removed (for re-hashing)."""
        result = {}
        for k, v in node.items():
            if k == "_hash":
                continue
            if isinstance(v, dict):
                result[k] = MerkleManifest._strip_hashes(v)
            else:
                result[k] = v
        return result

    # ── Persistence ─────────────────────────────────────────

    def save(self):
        """Write manifest to disk."""
        if not self._filepath:
            return
        data = {
            "version": self.VERSION,
            "root_hash": self._root_hash,
            "generated_at": datetime.now().strftime("%Y%m%d%H%M%S"),
            "note_count": self._note_count,
            "tree": self._tree,
            "vectordb_root_hash": self._vectordb_root_hash,
        }
        with open(self._filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, persist_dir: str) -> Optional["MerkleManifest"]:
        """Load manifest from disk. Returns None if file doesn't exist."""
        filepath = os.path.join(persist_dir, "merkle_manifest.json")
        if not os.path.exists(filepath):
            return None
        manifest = cls(persist_dir)
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") != cls.VERSION:
            return None  # incompatible version, force rebuild
        manifest._tree = data.get("tree", {})
        manifest._root_hash = data.get("root_hash", "")
        manifest._note_count = data.get("note_count", 0)
        manifest._vectordb_root_hash = data.get("vectordb_root_hash", "")
        return manifest

    # ── Vectordb hash ───────────────────────────────────────

    def compute_vectordb_hash(self, stored_hashes: Dict[str, str]) -> str:
        """Compute aggregate hash of vectordb state for integrity check."""
        parts = [f"{k}:{v}" for k, v in sorted(stored_hashes.items())]
        raw = "\n".join(parts).encode("utf-8")
        self._vectordb_root_hash = hashlib.sha256(raw).hexdigest()[:16]
        return self._vectordb_root_hash

---

## Proposed changes

### Epic 1: Merkle package — protocols, tree, tracker, store

**Files:** `dashboard/agentic_memory/merkle/` (NEW package, 7 files, ~540 lines total)

Implement the full Merkle package following the class decomposition from the Architecture section:

| File | Class(es) | Lines | Pattern |
|------|-----------|-------|---------|
| `protocols.py` | `HashStrategy`, `ManifestRepository`, `IntegrityProvider` | ~60 | Protocol (DIP) |
| `tree.py` | `MerkleTree`, `MerkleDiff` | ~200 | Pure data structure + Value Object |
| `hashers.py` | `Sha256Hasher` | ~30 | Strategy |
| `dirty.py` | `DirtyTracker` | ~50 | Dataclass with behavior |
| `store.py` | `JsonManifestStore` | ~80 | Repository + Atomic writes |
| `tracker.py` | `IntegrityTracker` | ~120 | Facade / Mediator |
| `__init__.py` | Re-exports | ~10 | Package API |

**Key behaviors (on `MerkleTree`):**

| Method | Complexity | Description |
|--------|-----------|-------------|
| `build(leaves)` | O(N) | Full rebuild from `{filepath: hash}` — used on boot or corruption |
| `diff(other)` | O(changed) amortized | Tree walk that prunes unchanged subtrees |
| `update_leaf(filepath, hash)` | O(depth) | Incremental update — typically 2-4 re-hashes |
| `remove_leaf(filepath)` | O(depth) | Incremental remove with empty-dir cleanup |

**Key behaviors (on `IntegrityTracker`):**

| Method | Complexity | Description |
|--------|-----------|-------------|
| `notify_save(id, filepath, hash)` | O(depth) | Update tree + mark dirty |
| `notify_delete(id, filepath)` | O(depth) | Update tree + mark dirty |
| `get_dirty_ids()` | O(1) | Return set of changed note IDs |
| `flush()` | O(tree_size) | Clear dirty + persist manifest |
| `load_or_rebuild(notes)` | O(1) or O(N) | Load from disk or full rebuild |

**Critical design constraint:** `MerkleTree.build()` accepts `Dict[str, str]` (filepath -> content_hash), **not** `Dict[str, MemoryNote]`. The tree package never imports `MemoryNote` — it only works with strings. This enforces DIP.

**Test files:**
- `dashboard/tests/test_merkle_tree.py` — tree operations, diff, deterministic hashing (~150 lines)
- `dashboard/tests/test_integrity_tracker.py` — facade behavior, load/rebuild, dirty tracking (~100 lines)
- `dashboard/tests/test_merkle_store.py` — JSON persistence, atomic writes, corruption recovery (~60 lines)

Test cases:
- Build from empty notes → root hash is empty string
- Build from 1 note → root hash = hash of single leaf
- Build from 100 notes → deterministic root hash
- `diff()` of identical trees → no changes
- `diff()` after `update_leaf()` → exactly 1 changed leaf
- `diff()` after `remove_leaf()` → exactly 1 removed leaf
- `diff()` prunes unchanged subtrees correctly
- Round-trip: `save()` then `load()` → identical tree and root hash
- Second preimage protection: `L:` and `D:` prefix differentiation
- Empty directory cleanup in `remove_leaf()`
- Version mismatch in `load()` → returns None (forces rebuild)

---

### Epic 2: Integrate manifest into `sync_to_disk()`

**Files:** `dashboard/agentic_memory/memory_system.py`

Replace the all-or-nothing write loop with Merkle-guided selective writes.

#### [MODIFY] `__init__()` — initialize manifest

```python
# After line 153 (self._dirty = False):
from .merkle_manifest import MerkleManifest

self._merkle = MerkleManifest(self.persist_dir)
self._per_note_dirty: Set[str] = set()  # note IDs that changed since last sync
```

#### [MODIFY] `_load_notes()` — load or rebuild manifest on boot

```python
# After line 505 (self._rebuild_backlinks()):
loaded = MerkleManifest.load(self.persist_dir) if self.persist_dir else None
if loaded and loaded.note_count == len(self.memories):
    self._merkle = loaded
else:
    # Manifest missing, corrupted, or note count mismatch → full rebuild
    self._merkle.build_from_notes(self.memories)
    self._merkle.save()
```

#### [MODIFY] `_save_note()` — update manifest incrementally

```python
# After writing the file (end of _save_note):
self._merkle.update_leaf(note.filepath, note.content_hash)
```

#### [MODIFY] `_delete_note_file()` — update manifest on delete

```python
# After removing the file:
self._merkle.remove_leaf(note.filepath)
```

#### [MODIFY] mutation methods — track per-note dirty

```python
# In add_note(), after self.memories[note.id] = note:
self._per_note_dirty.add(note.id)

# In update(), after modification:
self._per_note_dirty.add(memory_id)

# In process_memory(), when neighbors are updated:
self._per_note_dirty.add(neighbor_id)
```

#### [MODIFY] `sync_to_disk()` — selective writes

```python
def sync_to_disk(self) -> Dict:
    if not self._notes_dir:
        return {"error": "No persist_dir configured"}

    # Step 1: Merge (only if dirty)
    is_dirty = getattr(self, "_dirty", True)
    if is_dirty:
        merge_result = self.merge_from_disk()
    else:
        merge_result = {"skipped": True, "reason": "no local changes"}

    # Step 2: Write only dirty notes (not all notes)
    written = 0
    if self._per_note_dirty:
        for note_id in self._per_note_dirty:
            note = self.memories.get(note_id)
            if note:
                self._save_note(note, touch_modified=False)
                written += 1
    else:
        # Fallback: if per-note tracking was bypassed, write all
        for note in self.memories.values():
            self._save_note(note, touch_modified=False)
            written += 1

    # Step 3: Save manifest
    self._merkle.save()
    self._dirty = False
    self._per_note_dirty.clear()
    return {"merge": merge_result, "written": written}
```

**Impact:** At 500 notes with 3 changes since last sync: **3 file writes instead of 500**.

---

### Epic 3: Integrate manifest into `merge_from_disk()`

**Files:** `dashboard/agentic_memory/memory_system.py`

Replace the full disk walk with Merkle-guided selective reads.

#### [MODIFY] `merge_from_disk()` — Merkle-accelerated merge

```python
def merge_from_disk(self) -> Dict:
    # Step 1: Build a manifest from current disk state
    #   Option A (fast): walk disk but only read filenames + stat (no parse)
    #   Option B (fallback): full _load_disk_notes() if no manifest exists
    disk_manifest = self._build_disk_manifest()

    # Step 2: Diff against in-memory manifest
    diff = self._merkle.diff(disk_manifest)

    if not diff.has_changes:
        return {"unchanged": True, "skipped_subtrees": len(diff.unchanged_subtrees)}

    # Step 3: Only read/parse the changed files
    added_from_disk = 0
    updated_from_disk = 0

    for filepath in diff.added_leaves | diff.changed_leaves:
        full_path = os.path.join(self._notes_dir, filepath)
        if not os.path.exists(full_path):
            continue
        with open(full_path, "r", encoding="utf-8") as f:
            note = MemoryNote.from_markdown(f.read())

        if note.id in self.memories:
            # Changed leaf → conflict resolution
            mem_note = self.memories[note.id]
            if note.content_hash != mem_note.content_hash:
                winner = self._resolve_conflict(note, mem_note)
                if winner.id != mem_note.id or winner is not mem_note:
                    self.memories[note.id] = note
                    self.retriever.delete_document(note.id)
                    metadata = self._build_note_metadata(note)
                    self.retriever.add_document(note.content, metadata, note.id)
                    updated_from_disk += 1
        else:
            # Added leaf → adopt from disk
            self.memories[note.id] = note
            metadata = self._build_note_metadata(note)
            self.retriever.add_document(note.content, metadata, note.id)
            added_from_disk += 1

    for filepath in diff.removed_leaves:
        # Note was on disk in the old manifest but no longer exists
        # Find the note ID by filepath and remove if appropriate
        pass  # Usually means disk was manually edited — handle conservatively

    self._rebuild_backlinks()

    # Step 4: Update in-memory manifest to reflect merged state
    self._merkle.build_from_notes(self.memories)

    return {
        "added_from_disk": added_from_disk,
        "updated_from_disk": updated_from_disk,
        "skipped_subtrees": len(diff.unchanged_subtrees),
        "changed_files_read": len(diff.all_changed),
    }
```

#### [NEW] `_build_disk_manifest()` — fast disk scan

```python
def _build_disk_manifest(self) -> MerkleManifest:
    """Build a MerkleManifest from disk by reading only frontmatter hashes.

    This is faster than _load_disk_notes() because it extracts just the
    content_hash from each file's frontmatter without fully parsing the note.
    """
    manifest = MerkleManifest()
    raw_tree: dict = {}

    for dirpath, _dirnames, filenames in os.walk(self._notes_dir):
        for filename in filenames:
            if not filename.endswith(".md"):
                continue
            filepath = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(filepath, self._notes_dir)

            # Fast hash extraction: read first ~500 bytes for frontmatter
            content_hash = self._extract_hash_from_frontmatter(filepath)
            if not content_hash:
                continue

            # Build tree path
            parts = rel_path.split(os.sep)
            node = raw_tree
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = content_hash

    manifest._tree = manifest._hash_tree(raw_tree)
    manifest._root_hash = manifest._tree.get("_hash", "")
    return manifest

@staticmethod
def _extract_hash_from_frontmatter(filepath: str) -> Optional[str]:
    """Read just enough of a file to extract the content_hash.

    Reads at most 1KB — the frontmatter is always at the top.
    Falls back to None if the hash can't be extracted.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            header = f.read(1024)
        for line in header.split("\n"):
            if line.startswith("content_hash:"):
                _, value = line.split(":", 1)
                return json.loads(value.strip())
    except Exception:
        pass
    return None
```

**Impact:** At 500 notes with 3 disk changes: reads 1KB from each of 500 files (fast stat-level I/O) + full parse of only 3 changed files. Versus: full parse of all 500 files.

**Further optimization (future):** Store disk-side manifest at `<notes_dir>/../merkle_manifest.json`. If the disk manifest's `generated_at` timestamp matches the file mtime, skip the walk entirely → O(1) merge check.

---

### Epic 4: Vectordb consistency via Merkle hash

**Files:** `dashboard/agentic_memory/memory_system.py`, `dashboard/agentic_memory/merkle_manifest.py`

Replace the per-note vectordb hash check with an aggregate hash comparison.

#### Current approach (O(N)):
```python
# merge_from_disk() lines 1214-1237:
all_mem_ids = list(self.memories.keys())
stored_hashes = self.retriever.get_stored_hashes(all_mem_ids)  # fetches ALL
for nid in all_mem_ids:
    if stored_hash != note.content_hash:
        # repair
```

#### New approach (O(1) check, O(changed) repair):

```python
def _check_vectordb_consistency(self) -> int:
    """Check vectordb integrity using aggregate Merkle hash.

    Returns number of vectors repaired.
    """
    # Step 1: Compute expected vectordb hash from in-memory notes
    expected_hashes = {nid: note.content_hash for nid, note in self.memories.items()}
    expected_root = self._merkle.compute_vectordb_hash(expected_hashes)

    # Step 2: Compare against stored vectordb hash
    if expected_root == self._merkle.vectordb_root_hash:
        return 0  # O(1) — vectordb is consistent

    # Step 3: Full check only on mismatch (rare)
    stored_hashes = self.retriever.get_stored_hashes(list(self.memories.keys()))
    repaired = 0
    for nid, note in self.memories.items():
        stored = stored_hashes.get(nid)
        if stored == note.content_hash:
            continue
        if stored is not None:
            self.retriever.delete_document(nid)
        metadata = self._build_note_metadata(note)
        self.retriever.add_document(note.content, metadata, nid)
        repaired += 1

    # Step 4: Update stored vectordb hash
    self._merkle._vectordb_root_hash = expected_root
    return repaired
```

**Impact:** When vectordb is consistent (99% of syncs): O(1) hash comparison instead of O(N) fetch.

---

### Epic 5: Dashboard endpoint caching via root hash

**Files:** `dashboard/routes/amem.py`

Use the Merkle root hash as a cache key for the graph and stats endpoints.

#### [MODIFY] Module-level cache

```python
# At module level in amem.py:
from functools import lru_cache
from threading import Lock

_graph_cache: Dict[str, Tuple[str, dict]] = {}  # plan_id -> (root_hash, graph_data)
_stats_cache: Dict[str, Tuple[str, dict]] = {}  # plan_id -> (root_hash, stats_data)
_cache_lock = Lock()
```

#### [MODIFY] Graph endpoint

```python
@router.get("/api/amem/{plan_id}/graph")
async def get_memory_graph(plan_id: str, ...):
    mem_dir = _require_memory_dir(plan_id)
    notes_dir = mem_dir / "notes"

    # Check manifest root hash
    manifest_path = mem_dir / "merkle_manifest.json"
    current_hash = ""
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text())
            current_hash = data.get("root_hash", "")
        except Exception:
            pass

    # Cache hit?
    with _cache_lock:
        cached = _graph_cache.get(plan_id)
        if cached and cached[0] == current_hash and current_hash:
            return cached[1]

    # Cache miss → full computation
    notes = await asyncio.to_thread(_load_notes, notes_dir)
    result = await asyncio.to_thread(_build_graph, notes)

    # Store in cache
    if current_hash:
        with _cache_lock:
            _graph_cache[plan_id] = (current_hash, result)

    return result
```

**Impact:** Dashboard graph/stats endpoints go from O(N) per request to O(1) on cache hit. Cache is automatically invalidated when the Merkle root hash changes (i.e., when any note is added/modified/deleted).

---

### Epic 6: Cross-plan deduplication via root hash comparison (stretch)

**Files:** `dashboard/agentic_memory/memory_pool.py`, `dashboard/routes/amem.py`

Enable comparing Merkle roots across plans to identify shared knowledge.

#### [NEW] Pool-level comparison endpoint

```python
@router.get("/api/amem/compare/{plan_a}/{plan_b}")
async def compare_plans(plan_a: str, plan_b: str, ...):
    """Compare two plan memory namespaces via Merkle tree diff.

    Returns the set of notes that differ between plans, without
    reading any note content — only manifest comparison.
    """
    manifest_a = MerkleManifest.load(_require_memory_dir(plan_a))
    manifest_b = MerkleManifest.load(_require_memory_dir(plan_b))

    if manifest_a is None or manifest_b is None:
        raise HTTPException(400, "One or both plans lack a Merkle manifest")

    if manifest_a.root_hash == manifest_b.root_hash:
        return {"identical": True, "root_hash": manifest_a.root_hash}

    diff = manifest_a.diff(manifest_b)
    return {
        "identical": False,
        "plan_a_root": manifest_a.root_hash,
        "plan_b_root": manifest_b.root_hash,
        "added_in_a": sorted(diff.added_leaves),
        "removed_from_a": sorted(diff.removed_leaves),
        "changed": sorted(diff.changed_leaves),
        "shared_subtrees": sorted(diff.unchanged_subtrees),
    }
```

**Use cases:**
- Detect if two plans share the same architecture knowledge
- "Shallow clone" — copy only the notes that differ
- Dashboard UI: visualize knowledge overlap between plans

---

## Execution order

### Phase 1: Foundation (Epic 1) — zero integration risk

1. Create `dashboard/agentic_memory/merkle/` package
2. Implement protocols: `HashStrategy`, `ManifestRepository`, `IntegrityProvider`
3. Implement `MerkleTree` + `MerkleDiff` (pure data structure, no I/O)
4. Implement `Sha256Hasher`, `DirtyTracker`, `JsonManifestStore`
5. Implement `IntegrityTracker` facade
6. Write tests for each class independently (~30 test cases)
7. Verify deterministic hashing across platforms

### Phase 2: Core integration (Epics 2, 3) — 4 call sites in memory_system.py

8. Add `integrity: IntegrityProvider = None` constructor param to `AgenticMemorySystem`
9. Wire `notify_save()` into `_save_note()` and `notify_delete()` into `_delete_note_file()`
10. Modify `sync_to_disk()` to use `get_dirty_ids()` for selective writes
11. Modify `merge_from_disk()` to use `diff_against_disk()` for selective reads
12. Add `_extract_hash_from_frontmatter()` for fast disk scanning
13. Run full test suite + benchmarks

### Phase 3: Consistency & caching (Epics 4, 5)

14. Add vectordb aggregate hash comparison via `compute_vectordb_hash()`
15. Add dashboard endpoint caching with `root_hash` as cache key
16. Run integration tests

### Phase 4: Cross-plan (Epic 6) — stretch

17. Add plan comparison endpoint using `MerkleTree.diff()`
18. Add dashboard UI for knowledge overlap (optional)

---

## Files to modify

| File | Epic(s) | Changes |
|------|---------|---------|
| `dashboard/agentic_memory/merkle/__init__.py` | 1 | **NEW** — Re-exports `IntegrityTracker`, `IntegrityProvider`, `MerkleDiff` |
| `dashboard/agentic_memory/merkle/protocols.py` | 1 | **NEW** — `HashStrategy`, `ManifestRepository`, `IntegrityProvider` protocols (~60 lines) |
| `dashboard/agentic_memory/merkle/tree.py` | 1 | **NEW** — `MerkleTree`, `MerkleDiff` pure data structures (~200 lines) |
| `dashboard/agentic_memory/merkle/hashers.py` | 1 | **NEW** — `Sha256Hasher` strategy implementation (~30 lines) |
| `dashboard/agentic_memory/merkle/dirty.py` | 1 | **NEW** — `DirtyTracker` dataclass (~50 lines) |
| `dashboard/agentic_memory/merkle/store.py` | 1 | **NEW** — `JsonManifestStore` repository with atomic writes (~80 lines) |
| `dashboard/agentic_memory/merkle/tracker.py` | 1 | **NEW** — `IntegrityTracker` facade (~120 lines) |
| `dashboard/agentic_memory/memory_system.py` | 2, 3, 4 | Add `integrity: IntegrityProvider` constructor param. Add 4 call sites: `notify_save()`, `notify_delete()`, `get_dirty_ids()` in sync, `load_or_rebuild()` in `_load_notes()`. Add `_extract_hash_from_frontmatter()`. Modify `sync_to_disk()` and `merge_from_disk()`. |
| `dashboard/routes/amem.py` | 5, 6 | Add graph/stats cache with root hash key. Add `/api/amem/compare/{a}/{b}` endpoint. |
| `dashboard/agentic_memory/memory_pool.py` | — | No changes — pool delegates to `AgenticMemorySystem` which handles `IntegrityTracker` internally. |
| `dashboard/tests/test_merkle_tree.py` | 1 | **NEW** — tree operations, diff, deterministic hashing (~150 lines) |
| `dashboard/tests/test_integrity_tracker.py` | 1 | **NEW** — facade behavior, load/rebuild, dirty tracking (~100 lines) |
| `dashboard/tests/test_merkle_store.py` | 1 | **NEW** — JSON persistence, atomic writes, corruption recovery (~60 lines) |
| `dashboard/tests/test_memory_system.py` | 2, 3, 4 | Add tests for selective sync, Merkle-guided merge, vectordb hash check |
| `dashboard/tests/test_amem_api.py` | 5, 6 | Add tests for cached graph endpoint, plan comparison endpoint |

---

## Risk assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Manifest gets out of sync with actual notes | High | Rebuild from scratch if note_count mismatches, or if root hash verification fails after merge. `build_from_notes()` is the fallback. |
| Hash collision in 16-hex-char truncation (64 bits) | Very Low | At 10,000 notes, birthday attack probability is ~3×10⁻¹⁴. Adequate for integrity (not security). |
| `_extract_hash_from_frontmatter()` fails on malformed files | Low | Falls back to `None`, which triggers full parse via existing `_load_disk_notes()` path |
| Dashboard cache serves stale data | Low | Cache is keyed on root hash — any note change produces a new hash, invalidating the cache automatically |
| Per-note dirty tracking misses a mutation | Medium | `sync_to_disk()` falls back to writing all notes if `get_dirty_ids()` returns empty but `_dirty` is True. `IntegrityTracker` is the single source of truth for dirty state. |
| Manifest file corruption (disk error, partial write) | Low | `load()` returns None on parse error → triggers full rebuild from `build_from_notes()` |
| Cross-plan comparison leaks data between plans | Low | Comparison only returns filepaths and hashes, never note content. Authentication still required. |

---

## Success criteria

1. `sync_to_disk()` with 500 notes and 0 changes completes in **< 5ms** (currently ~50-200ms for 500 file writes)
2. `sync_to_disk()` with 500 notes and 5 changes writes **exactly 5 files** + manifest (currently 500 files)
3. `merge_from_disk()` with 500 notes and 0 disk changes completes in **< 50ms** (currently ~500ms-2s for 500 file reads + parses)
4. Dashboard graph endpoint returns in **< 10ms** on cache hit (currently 200ms-1s for disk walk)
5. All existing tests pass without modification
6. Merkle root hash is **deterministic** — same notes always produce same root hash regardless of insertion order
7. Manifest survives process crashes — worst case is a full rebuild on next boot (~200ms for 500 notes)

---

## Verification

```bash
# 1. Unit tests for Merkle package
PYTHONPATH=. pytest dashboard/tests/test_merkle_tree.py dashboard/tests/test_integrity_tracker.py dashboard/tests/test_merkle_store.py -v

# 2. Verify deterministic hashing (MerkleTree only works with strings, not MemoryNote)
python -c "
from dashboard.agentic_memory.merkle import IntegrityTracker

# Create leaves in different orders
leaves_a = {f'dir-{i%5}/note-{i}.md': f'hash{i:04d}' for i in range(100)}
leaves_b = dict(reversed(list(leaves_a.items())))

from dashboard.agentic_memory.merkle.tree import MerkleTree
t1 = MerkleTree()
t1.build(leaves_a)

t2 = MerkleTree()
t2.build(leaves_b)

assert t1.root_hash == t2.root_hash, 'Root hash must be order-independent!'
print(f'Deterministic: {t1.root_hash}')
"

# 3. Verify selective sync
python -c "
from dashboard.agentic_memory.memory_system import AgenticMemorySystem
import tempfile
sys = AgenticMemorySystem(persist_dir=tempfile.mkdtemp(), vector_backend='zvec')
# Add 50 notes
for i in range(50):
    sys.add_note(f'Test note {i} with enough content for meaningful analysis')
result = sys.sync_to_disk()
print(f'First sync: {result[\"written\"]} files written')

# Second sync with no changes
result = sys.sync_to_disk()
print(f'Second sync: {result[\"written\"]} files written')  # should be 0
"

# 4. Verify Merkle diff (pure tree, no MemoryNote dependency)
python -c "
from dashboard.agentic_memory.merkle.tree import MerkleTree

t1 = MerkleTree()
t1.build({
    'dir-a/note-1.md': 'aaa',
    'dir-a/note-2.md': 'bbb',
    'dir-b/note-3.md': 'ccc',
})

t2 = MerkleTree()
t2.build({
    'dir-a/note-1.md': 'aaa',
    'dir-a/note-2.md': 'CHANGED',
    'dir-b/note-3.md': 'ccc',
})

diff = t2.diff(t1)
print(f'Changed: {diff.changed_leaves}')       # {'dir-a/note-2.md'}
print(f'Unchanged subtrees: {diff.unchanged_subtrees}')  # {'dir-b'}
assert 'dir-a/note-2.md' in diff.changed_leaves
assert 'dir-b' in diff.unchanged_subtrees
print('Merkle diff works correctly!')
"

# 5. Full test suite regression
PYTHONPATH=. pytest dashboard/tests/ -q --tb=short

# 6. Benchmark (with Plan 018 suite)
pytest dashboard/tests/memory/benchmark/t2_integrated/bench_sync.py \
  --benchmark-only --benchmark-compare=baselines/baseline.json
```

---

## Appendix: Comparison with prior art

| System | Merkle usage | Our adaptation |
|--------|-------------|----------------|
| **Git** | Content-addressable blobs + tree objects + commit objects. Trees reference blobs by SHA-1. | We only need the tree-of-hashes layer — notes are already content-hashed. No commit objects needed. |
| **ZFS** | Block-level Merkle tree for end-to-end data integrity across disk blocks. | We operate at file level (one note = one leaf), not block level. Similar anti-entropy pattern. |
| **Cassandra** | Anti-entropy: replicas exchange Merkle trees to find out-of-sync key ranges. | Our `merge_from_disk()` is the same pattern — compare local vs disk Merkle trees, sync only differing ranges. |
| **Bitcoin** | Transaction Merkle tree in each block header. SPV nodes verify transactions via Merkle proofs. | We don't need individual proofs (no SPV equivalent). We need the diff operation. |
| **IPFS** | Content-addressed DAG (Merkle DAG). Each file chunk is a node. | Our notes are atomic — no chunking needed. We use directory hierarchy, not content-addressed DAG. |
