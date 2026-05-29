# Plan 022: Merkle Tree Dashboard Visualization

**Status:** Draft
**Date:** 2026-05-18
**Depends on:** Plan 021 (Merkle tree data structure + `merkle_manifest.json` persistence)

---

## Problem

Plan 021 added a Merkle tree integrity layer to the memory system, but the tree is invisible to users.  The `merkle_manifest.json` file sits on disk with root hashes, per-directory hashes, and leaf hashes -- but there is no way to:

1. **See** the current hash tree structure for a plan's memory namespace
2. **Verify** integrity at a glance (root hash, note count, last generated)
3. **Explore** which subtrees changed between syncs
4. **Understand** how the directory hierarchy maps to hash aggregation

The dashboard already has a Memory tab (`MemoryTab.tsx`, 1171 lines) with a force-directed graph of notes and links.  This plan adds a Merkle tree visualization alongside it.

---

## Goal

Add a Merkle tree panel to the Memory tab that:

1. Visualizes the full hash tree as an interactive, collapsible tree diagram
2. Shows root hash, note count, and generation timestamp as integrity badges
3. Color-codes nodes by hash match/mismatch when comparing against a previous snapshot
4. Allows clicking a directory node to see its aggregate hash and child count
5. Allows clicking a leaf node to navigate to that note in the existing note list

---

## Non-goals

- Replacing the existing force-directed graph (the Merkle view is a **new sub-tab**, not a replacement)
- Real-time diff between two plans (Plan 021 Epic 6 stretch -- out of scope here)
- Editing notes from the Merkle view
- 3D visualization (the Three.js stack is installed but overkill for a tree diagram)

---

## Architectural audit: current dashboard patterns

| Concern | Current pattern | Source |
|---------|----------------|--------|
| **Data fetching** | `apiGet()` with `useState`/`useEffect` in MemoryTab; `useSWR` everywhere else | `MemoryTab.tsx:893`, `use-plans.ts:9` |
| **Graph rendering** | Custom SVG with hand-written force simulation (no library) | `MemoryTab.tsx:84-465` |
| **Tree rendering** | Custom SVG in DAGViewer (wave-based layout, `foreignObject` nodes) | `DAGViewer.tsx` |
| **Hierarchy libs** | `d3-force` installed but unused by MemoryTab. **No `d3-hierarchy`** | `package.json` |
| **Styling** | Tailwind v4 + CSS variables (`var(--color-*)`) | Throughout |
| **Icons** | Google Material Symbols (`material-symbols-outlined`) | Throughout |
| **Tabs** | Lazy-loaded via `WorkspaceTabs.tsx` switch statement | `WorkspaceTabs.tsx:22-45` |
| **API prefix** | All amem endpoints at `/api/amem/{plan_id}/...`, no mount prefix | `amem.py`, `api.py:456` |
| **Thread offload** | `asyncio.to_thread()` for CPU-bound work | `amem.py:318` |
| **Caching** | None on amem endpoints (every request re-reads disk) | `amem.py` |
| **Panel layout** | Resizable three-pane with custom `Splitter` component | `MemoryTab.tsx:780-835` |

### Design decisions for this plan

1. **Use `d3-hierarchy`** for tree layout -- it provides `d3.tree()` (tidy tree) and `d3.hierarchy()` (data structuring) out of the box, and D3 is already a project dependency via `d3-force`. Install `d3-hierarchy` as a new dependency.
2. **SVG rendering** (consistent with MemoryTab and DAGViewer), not canvas -- the Merkle tree has at most a few hundred nodes, well within SVG performance limits.
3. **Sub-tab within Memory tab** -- add a toggle between "Graph" and "Merkle Tree" views rather than a new top-level tab. This keeps the Memory tab as the single entry point for memory visualization.
4. **SWR for data fetching** -- follow the majority pattern, not MemoryTab's outlier `apiGet` pattern. SWR gives free caching, revalidation, and stale-while-revalidate behavior.
5. **Merkle root hash caching on the backend** -- read `merkle_manifest.json` directly instead of re-walking all notes. This is O(1) file read instead of O(N).

---

## Design

### Backend: new API endpoint

#### `GET /api/amem/{plan_id}/merkle`

Returns the Merkle manifest data for visualization.

**Response shape:**

```json
{
  "root_hash": "a3f8c1d2e4b7f9a0",
  "generated_at": "20260518153022",
  "note_count": 42,
  "vectordb_root_hash": "x1y2z3w4v5u6t7s8",
  "tree": {
    "name": "(root)",
    "hash": "a3f8c1d2e4b7f9a0",
    "type": "dir",
    "children": [
      {
        "name": "devops",
        "hash": "b7d2e4f1c9a3e8d0",
        "type": "dir",
        "children": [
          {
            "name": "kubernetes",
            "hash": "c9f1a3b7d2e4f8c1",
            "type": "dir",
            "children": [
              {
                "name": "pod-basics.md",
                "hash": "aaa111bbb222ccc3",
                "type": "leaf",
                "children": []
              },
              {
                "name": "networking.md",
                "hash": "ddd444eee555fff6",
                "type": "leaf",
                "children": []
              }
            ]
          }
        ]
      },
      {
        "name": "architecture",
        "hash": "e1f2g3h4i5j6k7l8",
        "type": "dir",
        "children": [
          {
            "name": "database",
            "hash": "f9a0b1c2d3e4f5a6",
            "type": "dir",
            "children": [
              {
                "name": "postgres.md",
                "hash": "789abc012def345c",
                "type": "leaf",
                "children": []
              }
            ]
          }
        ]
      }
    ]
  }
}
```

This shape is designed to be directly consumable by `d3.hierarchy()` which expects `{ children: [...] }` at every node.

**Key design choice:** The raw `merkle_manifest.json` uses `_hash` keys and mixed string/dict values. The API endpoint **transforms** this into a uniform `{ name, hash, type, children }` shape because:
- `d3.hierarchy()` needs a consistent `children` accessor
- The frontend shouldn't parse the `_hash` convention
- The `type: "leaf" | "dir"` field enables different rendering for files vs directories

#### Implementation (in `routes/amem.py`):

```python
@router.get("/api/amem/{plan_id}/merkle", responses={404: {"description": "Not found"}})
async def get_merkle_tree(
    plan_id: str,
    user: Annotated[dict, Depends(get_current_user)] = None,
):
    """Return the Merkle integrity tree for a plan's memory namespace."""
    mem_dir = _require_memory_dir(plan_id)
    manifest_path = mem_dir / "merkle_manifest.json"

    if not manifest_path.exists():
        raise HTTPException(
            status_code=404,
            detail="No Merkle manifest found. Run a sync to generate one.",
        )

    data = await asyncio.to_thread(_load_merkle_manifest, manifest_path)
    return data


def _load_merkle_manifest(manifest_path: Path) -> dict:
    """Load and transform merkle_manifest.json into a d3-hierarchy-friendly shape."""
    import json

    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    tree_data = raw.get("tree", {})

    def transform(node: dict, name: str = "(root)") -> dict:
        """Convert the raw nested dict into {name, hash, type, children}."""
        children = []
        for key, value in sorted(node.items()):
            if key == "_hash":
                continue
            if isinstance(value, str):
                # Leaf node
                children.append({
                    "name": key,
                    "hash": value,
                    "type": "leaf",
                    "children": [],
                })
            elif isinstance(value, dict):
                # Directory node — recurse
                children.append(transform(value, key))
        return {
            "name": name,
            "hash": node.get("_hash", ""),
            "type": "dir",
            "children": children,
        }

    return {
        "root_hash": raw.get("root_hash", ""),
        "generated_at": raw.get("generated_at", ""),
        "note_count": raw.get("note_count", 0),
        "vectordb_root_hash": raw.get("vectordb_root_hash", ""),
        "tree": transform(tree_data),
    }
```

**Complexity:** O(1) file read + O(tree_size) transformation. No note parsing.

---

### Frontend: component architecture

```
MemoryTab.tsx (existing, modified)
  ├── [View toggle: "Graph" | "Merkle Tree"]
  │
  ├── when "Graph":
  │   └── MemoryGraph (existing, unchanged)
  │
  └── when "Merkle Tree":
      └── MerkleTreeView.tsx (NEW, ~400 lines)
          ├── MerkleIntegrityBar (header: root hash, count, timestamp)
          ├── MerkleTreeDiagram (SVG tree via d3-hierarchy)
          └── MerkleNodeDetail (side panel for selected node)
```

#### 1. View toggle in MemoryTab

Add a small toggle button group in the existing stats bar (line ~935 of `MemoryTab.tsx`) that switches between `"graph"` and `"merkle"` views:

```tsx
const [memoryView, setMemoryView] = useState<'graph' | 'merkle'>('graph');

// In the header bar:
<div className="flex gap-1 rounded-md border border-[var(--color-border)] p-0.5">
  <button
    className={`px-2 py-0.5 text-xs rounded ${memoryView === 'graph' ? 'bg-[var(--color-primary)] text-white' : ''}`}
    onClick={() => setMemoryView('graph')}
  >
    <span className="material-symbols-outlined text-sm">hub</span> Graph
  </button>
  <button
    className={`px-2 py-0.5 text-xs rounded ${memoryView === 'merkle' ? 'bg-[var(--color-primary)] text-white' : ''}`}
    onClick={() => setMemoryView('merkle')}
  >
    <span className="material-symbols-outlined text-sm">account_tree</span> Merkle
  </button>
</div>

// Conditional rendering:
{memoryView === 'graph' ? (
  <MemoryGraph ... />
) : (
  <MerkleTreeView planId={planId} />
)}
```

#### 2. `MerkleTreeView.tsx` — new component (~400 lines)

Three sections stacked vertically:

##### A. `MerkleIntegrityBar` — header badges

```
┌──────────────────────────────────────────────────────────────┐
│  Root: a3f8c1d2  │  Notes: 42  │  VecDB: x1y2z3w4  │  Gen: 2h ago  │
└──────────────────────────────────────────────────────────────┘
```

- Root hash displayed as a monospace badge with copy-to-clipboard
- Note count badge
- Vectordb hash badge (green if matches root hash expectation, amber if unknown)
- Relative timestamp (`generated_at` → "2 hours ago")

##### B. `MerkleTreeDiagram` — the tree visualization (SVG, ~250 lines)

**Layout:** d3 tidy tree (`d3.tree()`) rendered horizontally (root left, leaves right). This matches how file systems are typically visualized and gives ample horizontal space for deep paths.

```
(root) ─── devops ─── kubernetes ─── pod-basics.md
   a3f8c1       b7d2e4     c9f1a3       aaa111
                       └── networking.md
                              ddd444
           └── cicd ─── pipeline.md
                d1e2f3     ccc333

       └── architecture ─── database ─── postgres.md
              e1f2g3          f9a0b1       789abc
```

**Node rendering:**

| Property | Directory node | Leaf node |
|----------|---------------|-----------|
| Shape | Rounded rectangle (16x16 square with 4px radius) | Circle (radius 6) |
| Color | `var(--color-primary)` fill | Group color (same 8-color palette as MemoryGraph) |
| Label | Name + hash (truncated to 8 chars) | Filename + hash (truncated to 8 chars) |
| Icon | `folder` material icon | `description` material icon |
| Hover | Tooltip with full hash + child count | Tooltip with full hash |
| Click | Expand/collapse children + show in detail panel | Show in detail panel + highlight in note list |

**Interaction:**
- **Pan + zoom** — same pointer-event pattern as `MemoryGraph` (lines 252-322)
- **Collapse/expand** — click a directory node to toggle its subtree (d3 supports this natively via `node.children = null`)
- **Search highlight** — reuse the existing `searchQuery` state from MemoryTab; matching nodes get full opacity, non-matches dim to 0.3
- **Animated transitions** — use `framer-motion` (already installed) for smooth expand/collapse

**SVG structure:**

```tsx
<svg ref={svgRef} width="100%" height="100%">
  <g transform={`translate(${pan.x + margin.left}, ${pan.y + margin.top}) scale(${zoom})`}>
    {/* Links: curved paths from parent to child */}
    {links.map(link => (
      <path
        key={`${link.source.data.name}-${link.target.data.name}`}
        d={d3.linkHorizontal()
          .x(d => d.y)    // horizontal tree: swap x/y
          .y(d => d.x)
          ({source: link.source, target: link.target})}
        fill="none"
        stroke="var(--color-border)"
        strokeWidth={1.5}
      />
    ))}

    {/* Nodes */}
    {nodes.map(node => (
      <g
        key={node.data.name + node.depth}
        transform={`translate(${node.y}, ${node.x})`}
        onClick={() => handleNodeClick(node)}
        className="cursor-pointer"
      >
        {node.data.type === 'dir' ? (
          <rect x={-8} y={-8} width={16} height={16} rx={4} fill="var(--color-primary)" />
        ) : (
          <circle r={6} fill={getGroupColor(node)} />
        )}
        <text x={14} dy={4} fontSize={11} fill="var(--color-text-main)">
          {node.data.name}
        </text>
        <text x={14} dy={16} fontSize={9} fill="var(--color-text-muted)" fontFamily="monospace">
          {node.data.hash.slice(0, 8)}
        </text>
      </g>
    ))}
  </g>
</svg>
```

##### C. `MerkleNodeDetail` — selected node panel (~100 lines)

When a node is selected, show a detail panel (reuses the right-panel layout pattern from MemoryTab):

```
┌─────────────────────────────┐
│  devops/kubernetes          │
│  Type: Directory            │
│  Hash: c9f1a3b7d2e4f8c1    │  [Copy]
│  Children: 2 leaves, 0 dirs │
│                             │
│  Child hashes:              │
│  ├── pod-basics.md   aaa111 │
│  └── networking.md   ddd444 │
│                             │
│  Path from root:            │
│  (root) → devops → k8s     │
│  a3f8c1   b7d2e4   c9f1a3  │
└─────────────────────────────┘
```

For leaf nodes, add a "Go to Note" button that switches to Graph view and selects that note (via the existing `selectedNodeId` state).

---

### Data fetching

Use `useSWR` for consistency with the rest of the dashboard:

```tsx
// In MerkleTreeView.tsx:
import useSWR from 'swr';
import { fetcher } from '@/lib/api-client';

interface MerkleData {
  root_hash: string;
  generated_at: string;
  note_count: number;
  vectordb_root_hash: string;
  tree: MerkleNode;
}

interface MerkleNode {
  name: string;
  hash: string;
  type: 'dir' | 'leaf';
  children: MerkleNode[];
}

function MerkleTreeView({ planId }: { planId: string }) {
  const { data, error, isLoading } = useSWR<MerkleData>(
    planId ? `/amem/${planId}/merkle` : null,
    fetcher,
  );

  // ... render
}
```

---

## Proposed changes

### Epic 1: Backend — Merkle manifest API endpoint

**File:** `dashboard/routes/amem.py`

| Change | Description |
|--------|-------------|
| Add `get_merkle_tree` endpoint | `GET /api/amem/{plan_id}/merkle` — reads `merkle_manifest.json`, transforms to d3-hierarchy shape |
| Add `_load_merkle_manifest()` helper | Transforms raw manifest into `{name, hash, type, children}` tree |

**Test file:** `dashboard/tests/test_amem_api.py` (add 5 test cases)
- Merkle endpoint returns 404 when no manifest exists
- Merkle endpoint returns correct shape with valid manifest
- Tree transformation produces `dir`/`leaf` types correctly
- Root hash matches manifest root
- Note count matches manifest count

---

### Epic 2: Frontend — install `d3-hierarchy` dependency

**File:** `dashboard/fe/package.json`

```bash
cd dashboard/fe && npm install d3-hierarchy @types/d3-hierarchy
```

`d3-hierarchy` is ~30KB gzipped and provides:
- `d3.hierarchy()` — converts `{children: [...]}` data into a traversable hierarchy
- `d3.tree()` — computes tidy tree layout positions (x, y per node)
- `d3.linkHorizontal()` — generates SVG path data for parent-child connections

---

### Epic 3: Frontend — `MerkleTreeView` component

**Files:**

| File | Lines | Description |
|------|-------|-------------|
| `dashboard/fe/src/components/plan/MerkleTreeView.tsx` | ~400 | Main component with integrity bar, tree diagram, and node detail |

**Sub-components (all in the same file, following MemoryTab's pattern):**

| Component | Lines | Purpose |
|-----------|-------|---------|
| `MerkleIntegrityBar` | ~50 | Header with root hash, note count, vectordb hash, timestamp badges |
| `MerkleTreeDiagram` | ~250 | SVG tree via d3-hierarchy with pan/zoom/collapse/search |
| `MerkleNodeDetail` | ~100 | Selected node detail panel with hash, children, path-from-root |

---

### Epic 4: Frontend — integrate into MemoryTab

**File:** `dashboard/fe/src/components/plan/MemoryTab.tsx`

| Change | Description |
|--------|-------------|
| Add `memoryView` state | `useState<'graph' \| 'merkle'>('graph')` |
| Add view toggle buttons | In the stats bar, before the search input |
| Conditional rendering | Show `MemoryGraph` or `MerkleTreeView` based on toggle |
| Lazy import | `const MerkleTreeView = lazy(() => import('./MerkleTreeView'))` |

---

## Execution order

### Phase 1: Backend (Epic 1)

1. Add `get_merkle_tree` endpoint and `_load_merkle_manifest()` to `amem.py`
2. Write backend tests
3. Verify with `curl localhost:9000/api/amem/{plan_id}/merkle`

### Phase 2: Frontend foundation (Epics 2, 3)

4. Install `d3-hierarchy` dependency
5. Create `MerkleTreeView.tsx` with `MerkleIntegrityBar`
6. Implement `MerkleTreeDiagram` with d3 tree layout
7. Implement `MerkleNodeDetail` panel
8. Add pan/zoom/collapse interactions

### Phase 3: Integration (Epic 4)

9. Add view toggle to `MemoryTab.tsx`
10. Wire `MerkleTreeView` with lazy loading
11. Connect leaf node click → note selection in graph view

---

## Files to modify

| File | Epic | Change |
|------|------|--------|
| `dashboard/routes/amem.py` | 1 | Add `GET /api/amem/{plan_id}/merkle` endpoint + `_load_merkle_manifest()` |
| `dashboard/tests/test_amem_api.py` | 1 | Add 5 tests for merkle endpoint |
| `dashboard/fe/package.json` | 2 | Add `d3-hierarchy`, `@types/d3-hierarchy` |
| `dashboard/fe/src/components/plan/MerkleTreeView.tsx` | 3 | **NEW** — ~400 lines |
| `dashboard/fe/src/components/plan/MemoryTab.tsx` | 4 | Add view toggle state, buttons, conditional rendering, lazy import (~20 lines changed) |

---

## Risk assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| No `merkle_manifest.json` exists yet (plan never synced) | Medium | Endpoint returns 404 with clear message; UI shows "No Merkle data — trigger a sync" |
| Large tree (500+ nodes) causes SVG perf issues | Low | d3.tree() layout is O(N); SVG handles hundreds of nodes fine. Collapse deep subtrees by default (depth > 3). |
| `d3-hierarchy` bundle size | Very Low | ~30KB gzipped, tree-shakeable. Already have `d3-force` as a dependency. |
| Manifest is stale (generated hours ago) | Low | Show `generated_at` as relative time with amber/red badge if older than 1 hour. Add refresh button that calls `POST /api/amem/{plan_id}/sync` (future). |
| Cross-tab navigation from Merkle leaf to Graph note | Low | Reuse existing `selectedNodeId` state in MemoryTab. Switch `memoryView` to `'graph'` and set the ID. |

---

## Success criteria

1. `GET /api/amem/{plan_id}/merkle` returns valid d3-hierarchy-compatible JSON in < 10ms
2. Merkle tree renders correctly for 1, 10, 50, and 200 notes
3. Directory nodes are collapsible/expandable with smooth animation
4. Root hash badge matches the actual `merkle_manifest.json` content
5. Clicking a leaf node in Merkle view navigates to that note in Graph view
6. Search filter dims non-matching nodes in the tree
7. Pan and zoom work consistently (same UX as the existing memory graph)
8. View toggle persists in localStorage (like panel widths)

---

## Visual mockup (ASCII)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Memory  │ 42 notes │ 12 tags │ [Search...] │ [Graph] [Merkle] │ [⟳]  │
├─────────────────────────────────────────────────────────────────────────┤
│ Root: a3f8c1d2 │ Notes: 42 │ VecDB: x1y2z3w4 │ 2 min ago          │
├───────────────────────────────────────────────────┬─────────────────────┤
│                                                   │                     │
│   ■ (root)                                        │  devops/kubernetes  │
│   ├── ■ devops                                    │  Type: Directory    │
│   │   ├── ■ kubernetes                            │  Hash: c9f1a3b7...  │
│   │   │   ├── ● pod-basics.md                     │  Children: 2       │
│   │   │   │     aaa111bb                          │                     │
│   │   │   └── ● networking.md                     │  Path from root:    │
│   │   │         ddd444ee                          │  (root) → devops    │
│   │   └── ■ cicd                                  │    → kubernetes     │
│   │       └── ● pipeline.md                       │                     │
│   │             ccc333dd                          │  [Go to Note]       │
│   └── ■ architecture                              │                     │
│       └── ■ database                              │                     │
│           └── ● postgres.md                       │                     │
│                 789abc01                           │                     │
│                                                   │                     │
├───────────────────────────────────────────────────┴─────────────────────┤
│ ■ = directory node (collapsible)   ● = leaf node (note)                │
└─────────────────────────────────────────────────────────────────────────┘
```

Legend:
- **Blue squares (■)** = directory nodes with aggregate Merkle hash
- **Colored circles (●)** = leaf nodes (notes) with content hash
- Monospace hash fragments shown below each node name
- Right panel shows detail for the selected node
- Integrity bar at top shows root hash + metadata
