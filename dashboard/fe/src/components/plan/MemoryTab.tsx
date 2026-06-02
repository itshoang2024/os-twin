'use client';

import React, { useEffect, useState, useCallback, useRef, useMemo, lazy, Suspense } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { usePlanContext } from './PlanWorkspace';
import { apiGet } from '@/lib/api-client';

const MerkleTreeView = lazy(() => import('./MerkleTreeView'));

// ── Types ────────────────────────────────────────────────────────────

interface GraphGroup {
  id: string;
  label: string;
  color: string;
  description: string;
}

interface GraphNode {
  id: string;
  title: string;
  path: string;
  pathLabel: string;
  excerpt: string;
  /** Markdown body with frontmatter stripped (parsed server-side). */
  body: string;
  /** Raw markdown including frontmatter — kept for clients that want it. */
  content: string;
  /** Optional summary from frontmatter. */
  summary?: string | null;
  /** Optional context blurb from frontmatter. */
  context?: string | null;
  category?: string | null;
  /** Timestamp string YYYYMMDDHHMM. */
  timestamp?: string | null;
  last_accessed?: string | null;
  retrieval_count?: number;
  tags: string[];
  keywords: string[];
  groupId: string;
  color: string;
  weight: number;
  connections: number;
  // computed by layout
  x?: number;
  y?: number;
}

interface GraphLink {
  source: string;
  target: string;
  strength: number;
}

interface GraphData {
  groups: GraphGroup[];
  nodes: GraphNode[];
  links: GraphLink[];
  stats: { total_memories: number; total_links: number; total_groups: number };
}

interface MemoryStats {
  total_notes: number;
  total_tags: number;
  total_keywords: number;
  total_paths: number;
  memory_dir: string;
  tags: string[];
  paths: string[];
}

function matchesSearch(node: GraphNode, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return node.title.toLowerCase().includes(q) ||
    node.pathLabel.toLowerCase().includes(q) ||
    node.tags.some(t => t.toLowerCase().includes(q)) ||
    node.excerpt.toLowerCase().includes(q);
}

// ── Simple force layout ──────────────────────────────────────────────

type PositionedNode = GraphNode & { x: number; y: number };

function layoutNodes(nodes: GraphNode[], links: GraphLink[], width: number, height: number): PositionedNode[] {
  const positioned: PositionedNode[] = nodes.map((n, i) => ({
    ...n,
    x: width / 2 + (Math.cos(i * 2.399) * Math.min(width, height) * 0.35),
    y: height / 2 + (Math.sin(i * 2.399) * Math.min(width, height) * 0.35),
  }));

  // Simple force iterations
  const nodeMap = new Map(positioned.map(n => [n.id, n]));
  for (let iter = 0; iter < 50; iter++) {
    // Repel
    for (let i = 0; i < positioned.length; i++) {
      for (let j = i + 1; j < positioned.length; j++) {
        const a = positioned[i], b = positioned[j];
        const dx = b.x - a.x, dy = b.y - a.y;
        const dist = Math.max(Math.hypot(dx, dy), 1);
        const force = 800 / (dist * dist);
        a.x -= (dx / dist) * force;
        a.y -= (dy / dist) * force;
        b.x += (dx / dist) * force;
        b.y += (dy / dist) * force;
      }
    }
    // Attract linked
    for (const link of links) {
      const a = nodeMap.get(link.source), b = nodeMap.get(link.target);
      if (!a || !b) continue;
      const dx = b.x - a.x, dy = b.y - a.y;
      const dist = Math.max(Math.hypot(dx, dy), 1);
      const force = (dist - 120) * 0.02;
      a.x += (dx / dist) * force;
      a.y += (dy / dist) * force;
      b.x -= (dx / dist) * force;
      b.y -= (dy / dist) * force;
    }
    // Center
    for (const n of positioned) {
      n.x += (width / 2 - n.x) * 0.01;
      n.y += (height / 2 - n.y) * 0.01;
    }
  }
  return positioned;
}

// ── Interactive Graph ───────────────────────────────────────────────

const MIN_ZOOM = 0.6;
const MAX_ZOOM = 2.25;
const DRAG_THRESHOLD = 4;

type DragState = {
  pointerId: number | null;
  originClientX: number;
  originClientY: number;
  anchorX: number;
  anchorY: number;
  moved: boolean;
};

function MemoryGraph({
  data,
  selectedId,
  hoveredId,
  searchQuery,
  onSelect,
  onHover,
}: Readonly<{
  data: GraphData;
  selectedId: string | null;
  hoveredId: string | null;
  searchQuery: string;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
}>) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 500 });
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [isPanning, setIsPanning] = useState(false);
  const panRef = useRef(pan);
  const zoomRef = useRef(zoom);
  const dragStateRef = useRef<DragState>({
    pointerId: null,
    originClientX: 0,
    originClientY: 0,
    anchorX: 0,
    anchorY: 0,
    moved: false,
  });
  const suppressClickRef = useRef(false);

  useEffect(() => {
    panRef.current = pan;
  }, [pan]);

  useEffect(() => {
    zoomRef.current = zoom;
  }, [zoom]);

  useEffect(() => {
    const el = containerRef.current;
    if (el) {
      const obs = new ResizeObserver(entries => {
        const { width, height } = entries[0].contentRect;
        setDimensions({ width: Math.max(400, width), height: Math.max(300, height) });
      });
      obs.observe(el);
      return () => obs.disconnect();
    }
  }, []);

  const nodes = useMemo(
    () => layoutNodes(data.nodes, data.links, dimensions.width, dimensions.height),
    [data.nodes, data.links, dimensions.width, dimensions.height]
  );
  const nodeMap = useMemo(() => new Map(nodes.map(n => [n.id, n])), [nodes]);

  const activeId = hoveredId ?? selectedId;
  const neighborIds = useMemo(() => {
    const neighbors = new Set<string>();
    if (!activeId) return neighbors;
    for (const link of data.links) {
      if (link.source === activeId) neighbors.add(link.target);
      if (link.target === activeId) neighbors.add(link.source);
    }
    neighbors.add(activeId);
    return neighbors;
  }, [activeId, data.links]);

  const query = searchQuery.trim().toLowerCase();
  const searchMatches = useMemo(() => {
    if (!query) return new Set<string>();
    return new Set(nodes.filter(node => matchesSearch(node, query)).map(node => node.id));
  }, [nodes, query]);

  function clientToSvg(clientX: number, clientY: number) {
    const svg = svgRef.current;
    if (!svg) return { x: 0, y: 0 };
    const ctm = svg.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    const inv = ctm.inverse();
    return {
      x: inv.a * clientX + inv.c * clientY + inv.e,
      y: inv.b * clientX + inv.d * clientY + inv.f,
    };
  }

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const handleWheel = (event: WheelEvent) => {
      event.preventDefault();
      const oldZoom = zoomRef.current;
      const nextZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, oldZoom - event.deltaY * 0.0009));
      const cursor = clientToSvg(event.clientX, event.clientY);
      const currentPan = panRef.current;
      const graphX = (cursor.x - currentPan.x) / oldZoom;
      const graphY = (cursor.y - currentPan.y) / oldZoom;
      const newPanX = cursor.x - graphX * nextZoom;
      const newPanY = cursor.y - graphY * nextZoom;
      setZoom(nextZoom);
      setPan({ x: newPanX, y: newPanY });
    };
    el.addEventListener('wheel', handleWheel, { passive: false });
    return () => el.removeEventListener('wheel', handleWheel);
  }, []);

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!event.isPrimary || event.button !== 0) return;
    suppressClickRef.current = false;
    setIsPanning(true);

    const svgPt = clientToSvg(event.clientX, event.clientY);
    const currentPan = panRef.current;
    const currentZoom = zoomRef.current;
    dragStateRef.current = {
      pointerId: event.pointerId,
      originClientX: event.clientX,
      originClientY: event.clientY,
      anchorX: (svgPt.x - currentPan.x) / currentZoom,
      anchorY: (svgPt.y - currentPan.y) / currentZoom,
      moved: false,
    };
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const dragState = dragStateRef.current;
    if (!isPanning || dragState.pointerId !== event.pointerId) return;

    const rawDeltaX = event.clientX - dragState.originClientX;
    const rawDeltaY = event.clientY - dragState.originClientY;
    if (!dragState.moved && Math.hypot(rawDeltaX, rawDeltaY) >= DRAG_THRESHOLD) {
      dragState.moved = true;
      suppressClickRef.current = true;
      onHover(null);
    }

    const svgPt = clientToSvg(event.clientX, event.clientY);
    const currentZoom = zoomRef.current;
    setPan({
      x: svgPt.x - dragState.anchorX * currentZoom,
      y: svgPt.y - dragState.anchorY * currentZoom,
    });
  };

  const handlePointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    const dragState = dragStateRef.current;
    if (dragState.pointerId !== event.pointerId) return;
    suppressClickRef.current = dragState.moved;
    dragStateRef.current = {
      pointerId: null,
      originClientX: 0,
      originClientY: 0,
      anchorX: 0,
      anchorY: 0,
      moved: false,
    };
    setIsPanning(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const handlePointerCancel = (event: React.PointerEvent<HTMLDivElement>) => {
    const dragState = dragStateRef.current;
    if (dragState.pointerId !== event.pointerId) return;
    dragStateRef.current = {
      pointerId: null,
      originClientX: 0,
      originClientY: 0,
      anchorX: 0,
      anchorY: 0,
      moved: false,
    };
    setIsPanning(false);
  };

  const handleNodeClick = (event: React.MouseEvent<SVGGElement>, nodeId: string) => {
    event.stopPropagation();
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    onSelect(nodeId);
  };

  return (
    <div
      ref={containerRef}
      className={`relative w-full h-full overflow-hidden ${isPanning ? 'cursor-grabbing' : 'cursor-grab'}`}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerCancel}
      onPointerLeave={() => {
        if (!dragStateRef.current.pointerId) {
          onHover(null);
        }
      }}
    >
      <div className="pointer-events-none absolute top-3 right-3 rounded-full border px-3 py-1 text-[10px]"
        style={{
          borderColor: 'var(--color-border)',
          background: 'var(--color-background)',
          color: 'var(--color-text-muted)',
        }}>
        {(nodes?.length ?? 0)} nodes · {(data?.links?.length ?? 0)} links · {Math.round(zoom * 100)}%
      </div>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${dimensions.width} ${dimensions.height}`}
        className="w-full h-full"
        style={{ minHeight: 400 }}
      >
        <defs>
          <pattern id="memory-grid" width="48" height="48" patternUnits="userSpaceOnUse">
            <path d="M 48 0 L 0 0 0 48" fill="none" stroke="var(--color-border)" opacity="0.2" />
          </pattern>
        </defs>

        <rect x="0" y="0" width={dimensions.width} height={dimensions.height} fill="url(#memory-grid)" />

        <g transform={`translate(${pan.x} ${pan.y}) scale(${zoom})`}>
          {/* Links */}
          {data.links.map((link, i) => {
            const src = nodeMap.get(link.source);
            const tgt = nodeMap.get(link.target);
            if (!src || !tgt) return null;
            const linkKey = `${link.source}-${link.target}-${i}`;
            const isActive = activeId && (link.source === activeId || link.target === activeId);
            const isInNeighborhood = !activeId || (neighborIds.has(link.source) && neighborIds.has(link.target));
            const searchVisible = !query || (searchMatches.has(link.source) && searchMatches.has(link.target));
            const dx = tgt.x - src.x;
            const dy = tgt.y - src.y;
            const dist = Math.max(Math.hypot(dx, dy), 1);
            const normalX = -dy / dist;
            const normalY = dx / dist;
            const curve = Math.min(dist * 0.12, 40);
            const controlX = (src.x + tgt.x) / 2 + normalX * curve;
            const controlY = (src.y + tgt.y) / 2 + normalY * curve;
            const activeOpacity = isActive ? 0.9 : 0.5;
            const neighborhoodOpacity = isInNeighborhood ? activeOpacity : 0.18;
            const opacity = searchVisible ? neighborhoodOpacity : 0.06;
            const baseWidth = 1.6 + (link.strength ?? 0.4) * 1.4;
            const strokeWidth = isActive ? baseWidth + 1 : baseWidth;
            return (
              <path
                key={linkKey}
                d={`M ${src.x} ${src.y} Q ${controlX} ${controlY} ${tgt.x} ${tgt.y}`}
                fill="none"
                stroke="var(--color-text-muted)"
                strokeOpacity={opacity}
                strokeWidth={strokeWidth}
              />
            );
          })}

          {/* Nodes */}
          {nodes.map(node => {
            const isSelected = node.id === selectedId;
            const isActive = node.id === activeId;
            const inNeighborhood = !activeId || neighborIds.has(node.id);
            const isSearchMatch = !query || searchMatches.has(node.id);
            const r = 6 + (node.weight ?? 0) * 3;
            let opacity = 0.12;
            if (isSearchMatch) { opacity = inNeighborhood ? 1 : 0.35; }
            let labelOpacity = 0.1;
            if (isSearchMatch) { labelOpacity = inNeighborhood ? 0.9 : 0.35; }
            return (
              <g
                key={node.id}
                onClick={(event) => handleNodeClick(event, node.id)}
                onPointerEnter={(event) => {
                  event.stopPropagation();
                  if (dragStateRef.current.pointerId) return;
                  onHover(node.id);
                }}
                onPointerLeave={(event) => {
                  event.stopPropagation();
                  if (dragStateRef.current.pointerId) return;
                  onHover(null);
                }}
                style={{ cursor: 'pointer' }}
              >
                {isActive && (
                  <circle
                    cx={node.x} cy={node.y} r={r + 7}
                    fill="none"
                    stroke={node.color}
                    strokeWidth={2}
                    opacity={0.45}
                  />
                )}
                <circle
                  cx={node.x} cy={node.y} r={r}
                  fill={node.color}
                  opacity={opacity}
                  stroke={isSelected ? '#fff' : 'none'}
                  strokeWidth={isSelected ? 2 : 0}
                />
                <text
                  x={node.x} y={node.y + r + 14}
                  textAnchor="middle"
                  fontSize={11}
                  fill="var(--color-text-main)"
                  opacity={labelOpacity}
                  style={{ pointerEvents: 'none' }}
                >
                  {(node.title ?? '').length > 26 ? node.title.slice(0, 24) + '...' : node.title}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}

/** Format timestamp ("202604081932") to "Apr 8, 2026 - 19:32" */
function formatTimestamp(ts?: string | null): string | null {
  if (!ts || !/^\d{12}$/.test(ts)) return null;
  const y = ts.slice(0, 4);
  const monthIndex = Number.parseInt(ts.slice(4, 6), 10) - 1;
  const d = Number.parseInt(ts.slice(6, 8), 10);
  const hh = ts.slice(8, 10);
  const mm = ts.slice(10, 12);
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] as const;
  if (monthIndex < 0 || monthIndex > 11) return null;
  return `${months[monthIndex]} ${d}, ${y} · ${hh}:${mm}`;
}

// ── Markdown renderer config ─────────────────────────────────────────

/**
 * Style overrides for react-markdown. Memory notes are dense and the panel
 * is narrow, so we tighten line-heights and use the existing CSS variables
 * (var(--color-...)) instead of hard-coded colors so dark/light themes work.
 */
const markdownComponents = {
  h1: ({ children, ...p }: any) => (
    <h1 className="text-base font-semibold mt-5 mb-2 leading-snug" style={{ color: 'var(--color-text-main)' }} {...p}>{children}</h1>
  ),
  h2: ({ children, ...p }: any) => (
    <h2 className="text-sm font-semibold mt-4 mb-2 leading-snug" style={{ color: 'var(--color-text-main)' }} {...p}>{children}</h2>
  ),
  h3: ({ children, ...p }: any) => (
    <h3 className="text-[13px] font-semibold mt-3 mb-1.5" style={{ color: 'var(--color-text-main)' }} {...p}>{children}</h3>
  ),
  h4: ({ children, ...p }: any) => (
    <h4 className="text-[12px] font-semibold uppercase tracking-wide mt-3 mb-1" style={{ color: 'var(--color-text-muted)' }} {...p}>{children}</h4>
  ),
  p: ({ children, ...p }: any) => (
    <p className="text-[13px] leading-relaxed mb-2" style={{ color: 'var(--color-text-main)' }} {...p}>{children}</p>
  ),
  ul: ({ children, ...p }: any) => (
    <ul className="text-[13px] leading-relaxed mb-2 ml-4 list-disc space-y-0.5" style={{ color: 'var(--color-text-main)' }} {...p}>{children}</ul>
  ),
  ol: ({ children, ...p }: any) => (
    <ol className="text-[13px] leading-relaxed mb-2 ml-4 list-decimal space-y-0.5" style={{ color: 'var(--color-text-main)' }} {...p}>{children}</ol>
  ),
  li: ({ children, ...p }: any) => (
    <li className="leading-relaxed" {...p}>{children}</li>
  ),
  a: ({ children, href, ...p }: any) => (
    <a className="underline" style={{ color: 'var(--color-primary)' }} href={href} target="_blank" rel="noopener noreferrer" {...p}>{children}</a>
  ),
  strong: ({ children, ...p }: any) => (
    <strong className="font-semibold" style={{ color: 'var(--color-text-main)' }} {...p}>{children}</strong>
  ),
  em: ({ children, ...p }: any) => (
    <em className="italic" {...p}>{children}</em>
  ),
  blockquote: ({ children, ...p }: any) => (
    <blockquote
      className="border-l-2 pl-3 my-2 italic text-[12px]"
      style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
      {...p}
    >
      {children}
    </blockquote>
  ),
  code: ({ inline, className, children, ...p }: any) => {
    if (inline) {
      return (
        <code
          className="px-1 py-px rounded text-[12px] font-mono"
          style={{ background: 'var(--color-background)', color: 'var(--color-primary)' }}
          {...p}
        >
          {children}
        </code>
      );
    }
    // Block code is wrapped by <pre>; render inline content here.
    return <code className={`${className || ''} font-mono`} {...p}>{children}</code>;
  },
  pre: ({ children, ...p }: any) => (
    <pre
      className="rounded-lg p-3 my-2 overflow-x-auto text-[11px] leading-relaxed font-mono border"
      style={{
        background: 'var(--color-background)',
        borderColor: 'var(--color-border)',
        color: 'var(--color-text-main)',
        scrollbarWidth: 'thin',
      }}
      {...p}
    >
      {children}
    </pre>
  ),
  table: ({ children, ...p }: any) => (
    <div className="overflow-x-auto my-2">
      <table className="text-[12px] border-collapse" {...p}>{children}</table>
    </div>
  ),
  th: ({ children, ...p }: any) => (
    <th
      className="px-2 py-1 border text-left font-semibold"
      style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}
      {...p}
    >
      {children}
    </th>
  ),
  td: ({ children, ...p }: any) => (
    <td className="px-2 py-1 border" style={{ borderColor: 'var(--color-border)' }} {...p}>{children}</td>
  ),
  hr: () => <hr className="my-3" style={{ borderColor: 'var(--color-border)' }} />,
};

// ── Note detail panel ────────────────────────────────────────────────

function NoteDetail({ note }: Readonly<{ note: GraphNode | null }>) {
  if (!note) {
    return (
      <div className="p-8 text-center h-full flex flex-col items-center justify-center"
        style={{ color: 'var(--color-text-muted)' }}>
        <span className="material-symbols-outlined text-[48px] mb-3 opacity-30">psychology</span>
        <p className="text-sm font-medium mb-1" style={{ color: 'var(--color-text-muted)' }}>
          No memory selected
        </p>
        <p className="text-xs opacity-70">
          Click a node in the graph to view its details
        </p>
      </div>
    );
  }

  // All structured fields come straight from the backend (which uses the
  // shared MemoryNote.from_markdown parser from the memory system). No more
  // client-side frontmatter re-parsing.
  const tags = note.tags;
  const keywords = note.keywords;
  const created = formatTimestamp(note.timestamp);
  const accessed = formatTimestamp(note.last_accessed);
  // Split path into breadcrumb segments (drop trailing filename if same as title slug)
  const pathParts = note.pathLabel.split('/').filter(Boolean);

  return (
    <div className="h-full flex flex-col">
      {/* ── Header ─────────────────────────────────────── */}
      <div className="px-5 pt-5 pb-4 border-b"
        style={{ borderColor: 'var(--color-border)' }}>
        {/* Color dot + breadcrumb */}
        <div className="flex items-center gap-2 mb-2">
          <span
            className="w-2 h-2 rounded-full flex-shrink-0"
            style={{ background: note.color }}
          />
          <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider truncate"
            style={{ color: 'var(--color-text-muted)' }}>
            {pathParts.map((part, i) => (
              <React.Fragment key={`${part}-${i}`}>
                {i > 0 && <span className="opacity-50">/</span>}
                <span>{part}</span>
              </React.Fragment>
            ))}
          </div>
        </div>

        <h3 className="text-base font-semibold leading-snug"
          style={{ color: 'var(--color-text-main)' }}>
          {note.title}
        </h3>

        {/* Created / accessed timestamps */}
        {(created || accessed) && (
          <div className="flex items-center gap-3 mt-3 text-[10px]"
            style={{ color: 'var(--color-text-muted)' }}>
            {created && (
              <div className="flex items-center gap-1">
                <span className="material-symbols-outlined text-[12px]">schedule</span>
                <span>{created}</span>
              </div>
            )}
            {accessed && accessed !== created && (
              <div className="flex items-center gap-1">
                <span className="material-symbols-outlined text-[12px]">visibility</span>
                <span>{accessed}</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Scrollable body ────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5"
        style={{ scrollbarWidth: 'thin' }}>

        {/* Context callout */}
        {note.context && (
          <div className="rounded-lg border-l-2 px-3 py-2.5 text-xs leading-relaxed"
            style={{
              borderLeftColor: note.color,
              background: 'var(--color-background)',
              color: 'var(--color-text-muted)',
            }}>
            <p className="text-[9px] uppercase tracking-widest mb-1 font-medium opacity-70">
              Context
            </p>
            <p className="italic">{note.context}</p>
          </div>
        )}

        {/* Body — rendered as markdown */}
        {note.body && (
          <div>
            <p className="text-[9px] uppercase tracking-widest mb-2 font-medium"
              style={{ color: 'var(--color-text-muted)' }}>
              Memory
            </p>
            <div className="memory-markdown">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
              >
                {note.body}
              </ReactMarkdown>
            </div>
          </div>
        )}

        {/* Tags */}
        {tags.length > 0 && (
          <div>
            <p className="text-[9px] uppercase tracking-widest mb-2 font-medium"
              style={{ color: 'var(--color-text-muted)' }}>
              Tags
            </p>
            <div className="flex flex-wrap gap-1.5">
              {tags.map(tag => (
                <span
                  key={tag}
                  className="px-2 py-1 rounded-md text-[10px] font-medium"
                  style={{
                    background: 'var(--color-primary-muted)',
                    color: 'var(--color-primary)',
                  }}
                >
                  #{tag}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Keywords */}
        {keywords.length > 0 && (
          <div>
            <p className="text-[9px] uppercase tracking-widest mb-2 font-medium"
              style={{ color: 'var(--color-text-muted)' }}>
              Keywords
            </p>
            <div className="flex flex-wrap gap-1.5">
              {keywords.map(kw => (
                <span
                  key={kw}
                  className="px-2 py-1 rounded-md text-[10px] border"
                  style={{
                    borderColor: 'var(--color-border)',
                    color: 'var(--color-text-muted)',
                    background: 'var(--color-background)',
                  }}
                >
                  {kw}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Footer stats ───────────────────────────────── */}
      <div className="px-5 py-3 border-t flex items-center justify-between text-[10px]"
        style={{
          borderColor: 'var(--color-border)',
          color: 'var(--color-text-muted)',
        }}>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1">
            <span className="material-symbols-outlined text-[12px]">hub</span>
            <span>{note.connections} link{note.connections === 1 ? '' : 's'}</span>
          </div>
          {typeof note.retrieval_count === 'number' && (
            <div className="flex items-center gap-1">
              <span className="material-symbols-outlined text-[12px]">trending_up</span>
              <span>{note.retrieval_count} reads</span>
            </div>
          )}
        </div>
        {note.category && (
          <span className="px-1.5 py-0.5 rounded text-[9px] uppercase tracking-wider"
            style={{ background: 'var(--color-background)', color: 'var(--color-text-muted)' }}>
            {note.category}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Resizable splitter ───────────────────────────────────────────────

const LEFT_MIN = 160;
const LEFT_MAX = 480;
const RIGHT_MIN = 240;
const RIGHT_MAX = 640;
const LEFT_DEFAULT = 224;
const RIGHT_DEFAULT = 320;
const STORAGE_KEY = 'memoryTab.panels';

function Splitter({
  onDrag,
}: Readonly<{
  onDrag: (deltaX: number) => void;
}>) {
  const startX = useRef<number>(0);
  const dragging = useRef<boolean>(false);

  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    startX.current = e.clientX;
    dragging.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const handleMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      const delta = ev.clientX - startX.current;
      startX.current = ev.clientX;
      onDrag(delta);
    };
    const handleUp = () => {
      dragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      globalThis.removeEventListener('mousemove', handleMove);
      globalThis.removeEventListener('mouseup', handleUp);
    };
    globalThis.addEventListener('mousemove', handleMove);
    globalThis.addEventListener('mouseup', handleUp);
  };

  return (
    <button
      type="button"
      aria-label="Resize panels"
      onMouseDown={handleMouseDown}
      className="flex-shrink-0 group relative border-0 bg-transparent p-0"
      style={{
        width: 6,
        cursor: 'col-resize',
        margin: '0 -3px',
        zIndex: 10,
      }}
    >
      <span
        className="absolute top-0 bottom-0 left-1/2 -translate-x-1/2 transition-colors group-hover:bg-[var(--color-primary)]"
        style={{
          width: 2,
          background: 'transparent',
          display: 'block',
        }}
      />
    </button>
  );
}

// ── Main MemoryTab ───────────────────────────────────────────────────

export default function MemoryTab() {
  const { planId, highlightNoteId, setHighlightNoteId } = usePlanContext();
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [memoryView, setMemoryView] = useState<'graph' | 'merkle'>('graph');

  // Resizable side-panel widths (persisted to localStorage)
  const [leftWidth, setLeftWidth] = useState(LEFT_DEFAULT);
  const [rightWidth, setRightWidth] = useState(RIGHT_DEFAULT);

  // Load saved widths on mount
  useEffect(() => {
    if (globalThis.window === undefined) return;
    try {
      const saved = globalThis.window.localStorage.getItem(STORAGE_KEY);
      if (!saved) return;
      const parsed = JSON.parse(saved);
      if (typeof parsed.left === 'number') {
        setLeftWidth(Math.min(LEFT_MAX, Math.max(LEFT_MIN, parsed.left)));
      }
      if (typeof parsed.right === 'number') {
        setRightWidth(Math.min(RIGHT_MAX, Math.max(RIGHT_MIN, parsed.right)));
      }
    } catch {
      // ignore
    }
  }, []);

  // Persist widths whenever they change
  useEffect(() => {
    if (globalThis.window === undefined) return;
    try {
      globalThis.window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ left: leftWidth, right: rightWidth })
      );
    } catch {
      // ignore quota / privacy errors
    }
  }, [leftWidth, rightWidth]);

  const handleLeftDrag = useCallback((delta: number) => {
    setLeftWidth(w => Math.min(LEFT_MAX, Math.max(LEFT_MIN, w + delta)));
  }, []);

  const handleRightDrag = useCallback((delta: number) => {
    // Right panel grows when dragged left (negative delta), so invert
    setRightWidth(w => Math.min(RIGHT_MAX, Math.max(RIGHT_MIN, w - delta)));
  }, []);

  const fetchData = useCallback(async () => {
    if (!planId) return;
    setLoading(true);
    setError(null);
    try {
      const [graph, st] = await Promise.all([
        apiGet<GraphData>(`/amem/${planId}/graph`),
        apiGet<MemoryStats>(`/amem/${planId}/stats`),
      ]);
      setGraphData(graph);
      setStats(st);
      if (graph.nodes.length > 0 && !selectedNodeId) {
        setSelectedNodeId(graph.nodes[0].id);
      }
    } catch (e: any) {
      setError(e.message || 'Failed to load memory data');
    } finally {
      setLoading(false);
    }
  }, [planId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // EPIC-007: Handle highlightNoteId from cross-tab navigation (e.g., from KnowledgeTab BacklinkBadge)
  useEffect(() => {
    if (highlightNoteId && graphData?.nodes) {
      // Check if the note exists in the graph
      const noteExists = graphData.nodes.some(n => n.id === highlightNoteId);
      if (noteExists) {
        // Select the highlighted note
        setSelectedNodeId(highlightNoteId);
        // Clear the highlightNoteId so it doesn't persist
        setHighlightNoteId(null);
      }
    }
  }, [highlightNoteId, graphData?.nodes, setHighlightNoteId]);

  const selectedNode = graphData?.nodes.find(n => n.id === selectedNodeId) || null;

  // Filter nodes by search
  const filteredNodes = graphData?.nodes.filter(n => matchesSearch(n, searchQuery)) || [];

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center space-y-3">
          <div className="w-10 h-10 border-2 border-t-transparent rounded-full animate-spin mx-auto"
            style={{ borderColor: 'var(--color-border)', borderTopColor: 'transparent' }} />
          <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading memory graph...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center space-y-3 max-w-md">
          <span className="material-symbols-outlined text-[48px]" style={{ color: 'var(--color-text-muted)' }}>
            memory
          </span>
          <p className="text-sm font-medium" style={{ color: 'var(--color-text-main)' }}>
            No memories found
          </p>
          <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            {error}
          </p>
          <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            Run the plan to generate agent memories, or check that .memory/ exists in the project directory.
          </p>
        </div>
      </div>
    );
  }

  if (!graphData || graphData.nodes.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center space-y-3 max-w-md">
          <span className="material-symbols-outlined text-[48px]" style={{ color: 'var(--color-text-muted)' }}>
            psychology
          </span>
          <p className="text-sm font-medium" style={{ color: 'var(--color-text-main)' }}>
            No memories yet
          </p>
          <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            Agent memories will appear here after running the plan. Each save_memory() call creates a node.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col gap-4 p-4 overflow-hidden">
      {/* Stats bar */}
      <div className="flex items-center justify-between gap-4 flex-shrink-0">
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-[20px]" style={{ color: 'var(--color-primary)' }}>
            psychology
          </span>
          <h2 className="text-base font-semibold" style={{ color: 'var(--color-text-main)' }}>
            Agent Memory
          </h2>
          {stats && (
            <div className="flex gap-2">
              <span className="px-2 py-0.5 rounded-md text-[11px] font-medium"
                style={{ background: 'var(--color-primary-muted)', color: 'var(--color-primary)' }}>
                {stats.total_notes} notes
              </span>
              <span className="px-2 py-0.5 rounded-md text-[11px] font-medium"
                style={{ background: 'var(--color-surface-hover)', color: 'var(--color-text-muted)' }}>
                {stats.total_tags} tags
              </span>
              <span className="px-2 py-0.5 rounded-md text-[11px] font-medium"
                style={{ background: 'var(--color-surface-hover)', color: 'var(--color-text-muted)' }}>
                {graphData.links.length} links
              </span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* View toggle: Graph / Merkle */}
          <div className="flex rounded-lg border overflow-hidden" style={{ borderColor: 'var(--color-border)' }}>
            <button
              className="px-2.5 py-1.5 text-[11px] font-medium flex items-center gap-1 transition-colors"
              style={{
                background: memoryView === 'graph' ? 'var(--color-primary)' : 'transparent',
                color: memoryView === 'graph' ? 'white' : 'var(--color-text-muted)',
              }}
              onClick={() => setMemoryView('graph')}
            >
              <span className="material-symbols-outlined text-[14px]">hub</span>
              Graph
            </button>
            <button
              className="px-2.5 py-1.5 text-[11px] font-medium flex items-center gap-1 transition-colors"
              style={{
                background: memoryView === 'merkle' ? 'var(--color-primary)' : 'transparent',
                color: memoryView === 'merkle' ? 'white' : 'var(--color-text-muted)',
              }}
              onClick={() => setMemoryView('merkle')}
            >
              <span className="material-symbols-outlined text-[14px]">account_tree</span>
              Merkle
            </button>
          </div>

          <div className="relative">
            <span className="material-symbols-outlined text-[16px] absolute left-2.5 top-1/2 -translate-y-1/2"
              style={{ color: 'var(--color-text-muted)' }}>
              search
            </span>
            <input
              className="pl-8 pr-3 py-1.5 text-xs rounded-lg border"
              style={{
                background: 'var(--color-background)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-main)',
                width: 200,
              }}
              placeholder="Search memories..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
            />
          </div>
          <button
            onClick={fetchData}
            className="p-1.5 rounded-lg border transition-colors hover:bg-[var(--color-surface-hover)]"
            style={{ borderColor: 'var(--color-border)' }}
            title="Refresh"
          >
            <span className="material-symbols-outlined text-[16px]" style={{ color: 'var(--color-text-muted)' }}>
              refresh
            </span>
          </button>
          <button
            onClick={async () => {
              if (!window.confirm('Archive all memories? They will be saved to a timestamped backup and agents will start fresh.')) return;
              try {
                await fetch(`/api/amem/${planId}/archive`, { method: 'POST' });
                fetchData();
              } catch { /* ignore */ }
            }}
            className="px-2.5 py-1.5 rounded-lg border text-[11px] font-medium transition-colors hover:bg-[var(--color-surface-hover)]"
            style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
            title="Archive memories and start fresh"
          >
            <span className="material-symbols-outlined text-[14px] mr-1 align-middle">archive</span>
            Archive
          </button>
          <button
            onClick={async () => {
              if (!window.confirm('Delete ALL memories for this plan? This cannot be undone.')) return;
              try {
                await fetch(`/api/amem/${planId}`, { method: 'DELETE' });
                fetchData();
              } catch { /* ignore */ }
            }}
            className="px-2.5 py-1.5 rounded-lg border text-[11px] font-medium transition-colors hover:bg-red-50"
            style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
            title="Clear all memories"
          >
            <span className="material-symbols-outlined text-[14px] mr-1 align-middle">delete_sweep</span>
            Clear
          </button>
          <a
            href={`/api/amem/${planId}/export`}
            download
            className="px-2.5 py-1.5 rounded-lg border text-[11px] font-medium transition-colors hover:bg-[var(--color-surface-hover)] inline-flex items-center"
            style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
            title="Export as .tar.gz"
          >
            <span className="material-symbols-outlined text-[14px] mr-1">download</span>
            Export
          </a>
        </div>
      </div>

      {/* Main content: conditional on view toggle */}
      {memoryView === 'merkle' ? (
        <div className="flex-1 min-h-0 overflow-hidden">
          <Suspense fallback={
            <div className="h-full flex items-center justify-center">
              <div className="w-8 h-8 border-2 border-t-transparent rounded-full animate-spin"
                style={{ borderColor: 'var(--color-border)', borderTopColor: 'transparent' }} />
            </div>
          }>
            <MerkleTreeView
              planId={planId!}
              searchQuery={searchQuery}
              onGoToNote={(leafName) => {
                // Switch to graph view and try to find the note by filename
                setMemoryView('graph');
                const matchingNode = graphData?.nodes.find(
                  n => n.path?.endsWith(leafName) || n.title?.toLowerCase() === leafName.replace(/\.md$/, '').replace(/-/g, ' ')
                );
                if (matchingNode) setSelectedNodeId(matchingNode.id);
              }}
            />
          </Suspense>
        </div>
      ) : (
        <div className="flex-1 flex overflow-hidden min-h-0">
          {/* Left: note list */}
          <div className="flex-shrink-0 flex flex-col gap-2 overflow-y-auto pr-2"
            style={{ scrollbarWidth: 'thin', width: leftWidth }}>
            {/* Groups legend */}
            <div className="space-y-1 mb-2">
              {graphData.groups.map(g => (
                <div key={g.id} className="flex items-center gap-2 px-2 py-1">
                  <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: g.color }} />
                  <span className="text-[11px] truncate" style={{ color: 'var(--color-text-muted)' }}>
                    {g.label}
                  </span>
                </div>
              ))}
            </div>

            {/* Note list */}
            {filteredNodes.map(node => (
               <button
                key={node.id}
                className="group w-full text-left px-3 py-2.5 rounded-xl border transition-all"
                style={{
                  borderColor: selectedNodeId === node.id ? 'var(--color-primary)' : 'var(--color-border)',
                  background: selectedNodeId === node.id ? 'var(--color-primary-muted)' : 'transparent',
                }}
                onClick={() => setSelectedNodeId(node.id)}
              >
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: node.color }} />
                  <span className="text-xs font-medium truncate flex-1" style={{ color: 'var(--color-text-main)' }}>
                    {node.title}
                  </span>
                  <span
                    className="material-symbols-outlined text-[14px] opacity-0 group-hover:opacity-60 hover:!opacity-100 hover:text-red-500 transition-opacity cursor-pointer flex-shrink-0"
                    style={{ color: 'var(--color-text-muted)' }}
                    title="Delete this note"
                    onClick={async (e) => {
                      e.stopPropagation();
                      if (!window.confirm(`Delete "${node.title}"?`)) return;
                      try {
                        await fetch(`/api/amem/${planId}/notes/${node.id}`, { method: 'DELETE' });
                        fetchData();
                      } catch { /* ignore */ }
                    }}
                  >
                    delete
                  </span>
                </div>
                <p className="text-[10px] mt-0.5 truncate ml-4" style={{ color: 'var(--color-text-muted)' }}>
                  {node.pathLabel}
                </p>
              </button>
            ))}
          </div>

          {/* Splitter: left ↔ center */}
          <Splitter onDrag={handleLeftDrag} />

          {/* Center: graph */}
          <div className="flex-1 min-w-0 rounded-2xl border overflow-hidden mx-2"
            style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}>
            <MemoryGraph
              data={graphData}
              selectedId={selectedNodeId}
              hoveredId={hoveredNodeId}
              searchQuery={searchQuery}
              onSelect={setSelectedNodeId}
              onHover={setHoveredNodeId}
            />
          </div>

          {/* Splitter: center ↔ right */}
          <Splitter onDrag={handleRightDrag} />

          {/* Right: detail panel */}
          <div className="flex-shrink-0 rounded-2xl border overflow-hidden ml-2"
            style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface-hover)', width: rightWidth }}>
            <NoteDetail note={selectedNode} />
          </div>
        </div>
      )}
    </div>
  );
}
