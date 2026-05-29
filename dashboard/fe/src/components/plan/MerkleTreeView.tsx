'use client';

import React, { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import useSWR from 'swr';
import { fetcher } from '@/lib/api-client';
import * as d3Hierarchy from 'd3-hierarchy';

// ── Types ────────────────────────────────────────────────────────────

interface MerkleNode {
  name: string;
  hash: string;
  type: 'dir' | 'leaf';
  children: MerkleNode[];
}

interface MerkleData {
  root_hash: string;
  generated_at: string;
  note_count: number;
  vectordb_root_hash: string;
  tree: MerkleNode;
}

type HNode = d3Hierarchy.HierarchyPointNode<MerkleNode>;

// ── Constants ────────────────────────────────────────────────────────

const GROUP_COLORS = [
  '#8b5cf6', '#3b82f6', '#10b981', '#f59e0b',
  '#ef4444', '#ec4899', '#06b6d4', '#84cc16',
];

const MARGIN = { top: 30, right: 180, bottom: 30, left: 90 };
const NODE_HEIGHT = 28;  // vertical spacing between nodes

// ── Helpers ──────────────────────────────────────────────────────────

function formatRelativeTime(ts: string): string {
  if (!ts || ts.length < 14) return ts || '—';
  try {
    const y = ts.slice(0, 4), mo = ts.slice(4, 6), d = ts.slice(6, 8);
    const h = ts.slice(8, 10), mi = ts.slice(10, 12), s = ts.slice(12, 14);
    const date = new Date(`${y}-${mo}-${d}T${h}:${mi}:${s}`);
    const diff = Date.now() - date.getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  } catch {
    return ts;
  }
}

function getDepthColor(depth: number): string {
  return GROUP_COLORS[depth % GROUP_COLORS.length];
}

function countChildren(node: MerkleNode): { leaves: number; dirs: number } {
  let leaves = 0, dirs = 0;
  for (const c of node.children) {
    if (c.type === 'leaf') leaves++;
    else dirs++;
  }
  return { leaves, dirs };
}

function getAncestorPath(node: HNode): HNode[] {
  const path: HNode[] = [];
  let current: HNode | null = node;
  while (current) {
    path.unshift(current);
    current = current.parent;
  }
  return path;
}

// ── MerkleIntegrityBar ───────────────────────────────────────────────

function MerkleIntegrityBar({ data }: { data: MerkleData }) {
  const [copied, setCopied] = useState(false);

  const copyHash = useCallback(() => {
    navigator.clipboard.writeText(data.root_hash).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [data.root_hash]);

  return (
    <div
      className="flex items-center gap-3 px-3 py-2 rounded-lg border flex-shrink-0"
      style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface-hover)' }}
    >
      {/* Root hash */}
      <button
        onClick={copyHash}
        className="flex items-center gap-1.5 px-2 py-0.5 rounded-md hover:bg-[var(--color-background)] transition-colors"
        title={copied ? 'Copied!' : `Root: ${data.root_hash} (click to copy)`}
      >
        <span className="material-symbols-outlined text-[14px]" style={{ color: 'var(--color-primary)' }}>
          fingerprint
        </span>
        <span className="font-mono text-[11px] font-medium" style={{ color: 'var(--color-text-main)' }}>
          {data.root_hash.slice(0, 8)}
        </span>
        <span className="material-symbols-outlined text-[12px]" style={{ color: 'var(--color-text-muted)' }}>
          {copied ? 'check' : 'content_copy'}
        </span>
      </button>

      <span className="w-px h-4" style={{ background: 'var(--color-border)' }} />

      {/* Note count */}
      <div className="flex items-center gap-1">
        <span className="material-symbols-outlined text-[14px]" style={{ color: 'var(--color-text-muted)' }}>
          description
        </span>
        <span className="text-[11px] font-medium" style={{ color: 'var(--color-text-main)' }}>
          {data.note_count} notes
        </span>
      </div>

      <span className="w-px h-4" style={{ background: 'var(--color-border)' }} />

      {/* Vectordb hash */}
      <div className="flex items-center gap-1" title={`VecDB: ${data.vectordb_root_hash}`}>
        <span className="material-symbols-outlined text-[14px]" style={{ color: 'var(--color-text-muted)' }}>
          database
        </span>
        <span className="font-mono text-[11px]" style={{ color: 'var(--color-text-muted)' }}>
          {data.vectordb_root_hash ? data.vectordb_root_hash.slice(0, 8) : '—'}
        </span>
      </div>

      <span className="w-px h-4" style={{ background: 'var(--color-border)' }} />

      {/* Generated timestamp */}
      <div className="flex items-center gap-1">
        <span className="material-symbols-outlined text-[14px]" style={{ color: 'var(--color-text-muted)' }}>
          schedule
        </span>
        <span className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>
          {formatRelativeTime(data.generated_at)}
        </span>
      </div>
    </div>
  );
}

// ── MerkleNodeDetail ─────────────────────────────────────────────────

function MerkleNodeDetail({
  node,
  onGoToNote,
}: {
  node: HNode | null;
  onGoToNote?: (leafName: string) => void;
}) {
  if (!node) {
    return (
      <div className="h-full flex items-center justify-center p-4">
        <p className="text-xs text-center" style={{ color: 'var(--color-text-muted)' }}>
          Select a node to see details
        </p>
      </div>
    );
  }

  const d = node.data;
  const ancestors = getAncestorPath(node);
  const { leaves, dirs } = d.type === 'dir' ? countChildren(d) : { leaves: 0, dirs: 0 };
  const [copied, setCopied] = useState(false);

  const copyHash = useCallback(() => {
    navigator.clipboard.writeText(d.hash).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [d.hash]);

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4" style={{ scrollbarWidth: 'thin' }}>
      {/* Header */}
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <span
            className="material-symbols-outlined text-[18px]"
            style={{ color: d.type === 'dir' ? 'var(--color-primary)' : getDepthColor(node.depth) }}
          >
            {d.type === 'dir' ? 'folder' : 'description'}
          </span>
          <h3 className="text-sm font-semibold truncate" style={{ color: 'var(--color-text-main)' }}>
            {d.name}
          </h3>
        </div>
        <span
          className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium"
          style={{
            background: d.type === 'dir' ? 'var(--color-primary-muted)' : 'var(--color-surface-hover)',
            color: d.type === 'dir' ? 'var(--color-primary)' : 'var(--color-text-muted)',
          }}
        >
          {d.type === 'dir' ? 'Directory' : 'Leaf (Note)'}
        </span>
      </div>

      {/* Hash */}
      <div className="space-y-1">
        <label className="text-[10px] font-medium uppercase tracking-wider" style={{ color: 'var(--color-text-muted)' }}>
          Hash
        </label>
        <button
          onClick={copyHash}
          className="flex items-center gap-1.5 w-full px-2 py-1.5 rounded-md border text-left hover:bg-[var(--color-surface-hover)] transition-colors"
          style={{ borderColor: 'var(--color-border)' }}
          title={copied ? 'Copied!' : 'Click to copy'}
        >
          <span className="font-mono text-[11px] flex-1 break-all" style={{ color: 'var(--color-text-main)' }}>
            {d.hash}
          </span>
          <span className="material-symbols-outlined text-[14px] flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>
            {copied ? 'check' : 'content_copy'}
          </span>
        </button>
      </div>

      {/* Children (directories only) */}
      {d.type === 'dir' && d.children.length > 0 && (
        <div className="space-y-1">
          <label className="text-[10px] font-medium uppercase tracking-wider" style={{ color: 'var(--color-text-muted)' }}>
            Children ({leaves} leaves, {dirs} dirs)
          </label>
          <div className="space-y-0.5 max-h-48 overflow-y-auto" style={{ scrollbarWidth: 'thin' }}>
            {d.children.map((child) => (
              <div
                key={child.name}
                className="flex items-center gap-2 px-2 py-1 rounded-md"
                style={{ background: 'var(--color-background)' }}
              >
                <span
                  className="material-symbols-outlined text-[12px]"
                  style={{ color: child.type === 'dir' ? 'var(--color-primary)' : 'var(--color-text-muted)' }}
                >
                  {child.type === 'dir' ? 'folder' : 'description'}
                </span>
                <span className="text-[11px] flex-1 truncate" style={{ color: 'var(--color-text-main)' }}>
                  {child.name}
                </span>
                <span className="font-mono text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                  {child.hash.slice(0, 8)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Path from root */}
      <div className="space-y-1">
        <label className="text-[10px] font-medium uppercase tracking-wider" style={{ color: 'var(--color-text-muted)' }}>
          Path from root
        </label>
        <div className="space-y-0.5">
          {ancestors.map((a, i) => (
            <div key={i} className="flex items-center gap-1.5" style={{ paddingLeft: i * 12 }}>
              {i > 0 && (
                <span className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>{'└─'}</span>
              )}
              <span className="text-[11px] font-medium" style={{ color: 'var(--color-text-main)' }}>
                {a.data.name}
              </span>
              <span className="font-mono text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                {a.data.hash.slice(0, 8)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Go to note (leaves only) */}
      {d.type === 'leaf' && onGoToNote && (
        <button
          onClick={() => onGoToNote(d.name)}
          className="w-full px-3 py-2 rounded-lg text-xs font-medium transition-colors flex items-center justify-center gap-1.5"
          style={{
            background: 'var(--color-primary)',
            color: 'white',
          }}
        >
          <span className="material-symbols-outlined text-[14px]">open_in_new</span>
          Go to Note
        </button>
      )}
    </div>
  );
}

// ── MerkleTreeDiagram ────────────────────────────────────────────────

function MerkleTreeDiagram({
  tree,
  selectedNode,
  searchQuery,
  onSelectNode,
}: {
  tree: MerkleNode;
  selectedNode: HNode | null;
  searchQuery: string;
  onSelectNode: (node: HNode) => void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [collapsedPaths, setCollapsedPaths] = useState<Set<string>>(new Set());
  const dragging = useRef(false);
  const lastPointer = useRef({ x: 0, y: 0 });

  // Measure container
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const obs = new ResizeObserver(([entry]) => {
      setDimensions({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  // Build the path string for a hierarchy node (for collapse tracking)
  const getNodePath = useCallback((node: d3Hierarchy.HierarchyNode<MerkleNode>): string => {
    const parts: string[] = [];
    let cur: d3Hierarchy.HierarchyNode<MerkleNode> | null = node;
    while (cur) {
      parts.unshift(cur.data.name);
      cur = cur.parent;
    }
    return parts.join('/');
  }, []);

  // Build the d3 hierarchy with collapse support
  const { root, nodes, links } = useMemo(() => {
    // Deep clone tree data and apply collapse
    function applyCollapse(node: MerkleNode, path: string): MerkleNode {
      if (collapsedPaths.has(path) && node.type === 'dir') {
        return { ...node, children: [] }; // collapsed: hide children
      }
      return {
        ...node,
        children: node.children.map((c) =>
          applyCollapse(c, `${path}/${c.name}`)
        ),
      };
    }
    const processedTree = applyCollapse(tree, tree.name);

    const root = d3Hierarchy.hierarchy(processedTree);
    const visibleLeaves = root.leaves().length || 1;
    const treeHeight = Math.max(400, visibleLeaves * NODE_HEIGHT);

    const layout = d3Hierarchy.tree<MerkleNode>()
      .size([treeHeight, dimensions.width - MARGIN.left - MARGIN.right])
      .separation((a, b) => (a.parent === b.parent ? 1 : 1.2));

    layout(root);

    const nodes = root.descendants() as HNode[];
    const links = root.links();

    return { root: root as HNode, nodes, links };
  }, [tree, dimensions.width, collapsedPaths]);

  // Auto-collapse deep subtrees on first render
  useEffect(() => {
    const toCollapse = new Set<string>();
    function walk(node: d3Hierarchy.HierarchyNode<MerkleNode>, path: string, depth: number) {
      if (depth >= 3 && node.data.type === 'dir' && node.data.children.length > 0) {
        toCollapse.add(path);
      }
      for (const c of node.children || []) {
        walk(c, `${path}/${c.data.name}`, depth + 1);
      }
    }
    const tempRoot = d3Hierarchy.hierarchy(tree);
    walk(tempRoot, tree.name, 0);
    if (toCollapse.size > 0) setCollapsedPaths(toCollapse);
  }, [tree]);

  // Toggle collapse on a directory node
  const toggleCollapse = useCallback((node: HNode) => {
    if (node.data.type !== 'dir') return;
    const path = getNodePath(node);
    setCollapsedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, [getNodePath]);

  // Check if a node's original data had children (for showing expand icon)
  const isCollapsedDir = useCallback((node: HNode): boolean => {
    if (node.data.type !== 'dir') return false;
    const path = getNodePath(node);
    return collapsedPaths.has(path);
  }, [collapsedPaths, getNodePath]);

  // Search matching
  const matchesSearchFn = useCallback((node: HNode): boolean => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      node.data.name.toLowerCase().includes(q) ||
      node.data.hash.toLowerCase().includes(q)
    );
  }, [searchQuery]);

  // Pan handlers
  const onPointerDown = useCallback((e: React.PointerEvent) => {
    if (e.button !== 0) return;
    dragging.current = true;
    lastPointer.current = { x: e.clientX, y: e.clientY };
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragging.current) return;
    const dx = e.clientX - lastPointer.current.x;
    const dy = e.clientY - lastPointer.current.y;
    lastPointer.current = { x: e.clientX, y: e.clientY };
    setPan((p) => ({ x: p.x + dx, y: p.y + dy }));
  }, []);

  const onPointerUp = useCallback(() => {
    dragging.current = false;
  }, []);

  // Zoom handler
  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 0.95 : 1.05;
    setZoom((z) => Math.min(2.5, Math.max(0.3, z * factor)));
  }, []);

  // Compute SVG internal height
  const treeHeight = nodes.length > 0
    ? Math.max(...nodes.map(n => n.x)) - Math.min(...nodes.map(n => n.x)) + MARGIN.top + MARGIN.bottom + 40
    : 400;

  // Link path generator (horizontal tree: swap x/y)
  const linkPath = useCallback((d: d3Hierarchy.HierarchyPointLink<MerkleNode>) => {
    const sx = d.source.y;
    const sy = d.source.x;
    const tx = d.target.y;
    const ty = d.target.x;
    const mx = (sx + tx) / 2;
    return `M${sx},${sy} C${mx},${sy} ${mx},${ty} ${tx},${ty}`;
  }, []);

  return (
    <div
      ref={containerRef}
      className="w-full h-full overflow-hidden cursor-grab active:cursor-grabbing"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerUp}
      onWheel={onWheel}
    >
      <svg
        ref={svgRef}
        width={dimensions.width}
        height={dimensions.height}
        style={{ display: 'block' }}
      >
        <g transform={`translate(${pan.x + MARGIN.left}, ${pan.y + MARGIN.top}) scale(${zoom})`}>
          {/* Links */}
          {links.map((link, i) => (
            <path
              key={i}
              d={linkPath(link as d3Hierarchy.HierarchyPointLink<MerkleNode>)}
              fill="none"
              stroke="var(--color-border)"
              strokeWidth={1.5}
              strokeOpacity={0.6}
            />
          ))}

          {/* Nodes */}
          {nodes.map((node) => {
            const isSelected = selectedNode && getNodePath(selectedNode) === getNodePath(node);
            const matchSearch = matchesSearchFn(node);
            const isDir = node.data.type === 'dir';
            const collapsed = isCollapsedDir(node);

            return (
              <g
                key={getNodePath(node)}
                transform={`translate(${node.y}, ${node.x})`}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectNode(node);
                  if (isDir) toggleCollapse(node);
                }}
                className="cursor-pointer"
                opacity={matchSearch ? 1 : 0.25}
              >
                {/* Node shape */}
                {isDir ? (
                  <rect
                    x={-9}
                    y={-9}
                    width={18}
                    height={18}
                    rx={4}
                    fill={isSelected ? 'var(--color-primary)' : getDepthColor(node.depth)}
                    stroke={isSelected ? 'var(--color-primary)' : 'none'}
                    strokeWidth={isSelected ? 2 : 0}
                    fillOpacity={isSelected ? 1 : 0.8}
                  />
                ) : (
                  <circle
                    r={6}
                    fill={isSelected ? 'var(--color-primary)' : getDepthColor(node.depth)}
                    stroke={isSelected ? 'var(--color-primary)' : 'none'}
                    strokeWidth={isSelected ? 2 : 0}
                    fillOpacity={isSelected ? 1 : 0.8}
                  />
                )}

                {/* Collapse indicator for directories */}
                {isDir && (
                  <text
                    x={0}
                    y={1}
                    textAnchor="middle"
                    dominantBaseline="central"
                    fontSize={10}
                    fill="white"
                    fontWeight="bold"
                    style={{ pointerEvents: 'none' }}
                  >
                    {collapsed ? '+' : node.data.children.length > 0 ? '−' : '○'}
                  </text>
                )}

                {/* Label: name */}
                <text
                  x={isDir ? 14 : 12}
                  dy={-2}
                  fontSize={11}
                  fontWeight={isDir ? 600 : 400}
                  fill="var(--color-text-main)"
                  style={{ pointerEvents: 'none' }}
                >
                  {node.data.name}
                </text>

                {/* Label: hash (truncated) */}
                <text
                  x={isDir ? 14 : 12}
                  dy={11}
                  fontSize={9}
                  fontFamily="monospace"
                  fill="var(--color-text-muted)"
                  style={{ pointerEvents: 'none' }}
                >
                  {node.data.hash.slice(0, 8)}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}

// ── Main MerkleTreeView ──────────────────────────────────────────────

export default function MerkleTreeView({
  planId,
  searchQuery,
  onGoToNote,
}: {
  planId: string;
  searchQuery: string;
  onGoToNote?: (leafName: string) => void;
}) {
  const { data, error, isLoading } = useSWR<MerkleData>(
    planId ? `/amem/${planId}/merkle` : null,
    fetcher,
  );
  const [selectedNode, setSelectedNode] = useState<HNode | null>(null);

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center space-y-3">
          <div
            className="w-10 h-10 border-2 border-t-transparent rounded-full animate-spin mx-auto"
            style={{ borderColor: 'var(--color-border)', borderTopColor: 'transparent' }}
          />
          <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
            Loading Merkle tree...
          </p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center space-y-3 max-w-md">
          <span className="material-symbols-outlined text-[48px]" style={{ color: 'var(--color-text-muted)' }}>
            account_tree
          </span>
          <p className="text-sm font-medium" style={{ color: 'var(--color-text-main)' }}>
            No Merkle tree available
          </p>
          <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            {error?.message || 'Run a memory sync to generate the Merkle integrity manifest.'}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col gap-3">
      {/* Integrity bar */}
      <MerkleIntegrityBar data={data} />

      {/* Tree + detail */}
      <div className="flex-1 flex gap-3 min-h-0 overflow-hidden">
        {/* Tree diagram */}
        <div
          className="flex-1 min-w-0 rounded-2xl border overflow-hidden"
          style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}
        >
          <MerkleTreeDiagram
            tree={data.tree}
            selectedNode={selectedNode}
            searchQuery={searchQuery}
            onSelectNode={setSelectedNode}
          />
        </div>

        {/* Detail panel */}
        <div
          className="flex-shrink-0 rounded-2xl border overflow-hidden"
          style={{
            borderColor: 'var(--color-border)',
            background: 'var(--color-surface-hover)',
            width: 280,
          }}
        >
          <MerkleNodeDetail node={selectedNode} onGoToNote={onGoToNote} />
        </div>
      </div>
    </div>
  );
}
