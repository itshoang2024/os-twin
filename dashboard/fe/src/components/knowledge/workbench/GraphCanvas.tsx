import React from 'react';
import { layout } from './layout/engine';
import type { ColorBy, LayoutMode, RenderMode, WorkbenchModel, WorkbenchNode } from './model/workbenchModel';

const palette = ['#2563eb', '#0f766e', '#b7791f', '#7c3aed', '#be123c', '#475569', '#0e7490', '#9333ea'];

function stableColor(value: string) {
  const hash = value.split('').reduce((sum, char) => ((sum << 5) - sum + char.charCodeAt(0)) | 0, 0);
  return palette[Math.abs(hash) % palette.length];
}

function colorFor(node: WorkbenchNode, colorBy: ColorBy, propertyName?: string, fixedColor = '#2563eb') {
  if (colorBy === 'fixed') return fixedColor;
  if (colorBy === 'property') {
    const value = String(node.properties?.[propertyName ?? ''] ?? 'fallback');
    if (value === 'true') return '#16a34a';
    if (value === 'false') return '#dc2626';
    return stableColor(value);
  }
  return node.color ?? stableColor(node.type);
}

function edgeDash(style?: string) {
  if (style === 'dashed') return '6 4';
  if (style === 'dotted') return '2 4';
  return undefined;
}

function edgeWidth(style?: string, weight?: number) {
  const base = Math.max(1.2, Math.min(4, 1.1 + Number(weight ?? 1)));
  return style === 'bold' ? Math.max(base, 3) : base;
}

export function GraphCanvasControls({ page, totalPages, visibleCount, totalCount, density, truncated, onPageChange, onDensityChange, onRestoreFocus }: { page: number; totalPages: number; visibleCount: number; totalCount: number; density: RenderMode; truncated?: boolean; onPageChange?: (page: number) => void; onDensityChange?: (density: RenderMode) => void; onRestoreFocus?: () => void }) {
  return <div data-testid="graph-canvas-controls" className="wb-graph-controls" aria-label="Graph canvas controls"><span>{visibleCount} of {totalCount} visible{truncated ? ' · truncated by server limit' : ''}</span><button type="button" disabled={page <= 0} onClick={() => onPageChange?.(page - 1)}>Previous page</button><span>Page {page + 1} of {totalPages}</span><button type="button" disabled={page >= totalPages - 1} onClick={() => onPageChange?.(page + 1)}>Next page</button><label>Density <select aria-label="Graph density" value={density} onChange={(event) => onDensityChange?.(event.target.value as RenderMode)}><option value="compact">Compact</option><option value="extended">Extended</option></select></label><button type="button" onClick={onRestoreFocus}>Restore focus</button></div>;
}

export default function GraphCanvas({ model, renderMode = 'extended', layoutMode = 'auto', colorBy = 'object_type', propertyName = '', fixedColor = '#2563eb', onSelectNode, onSelectEdge }: { model: WorkbenchModel; renderMode?: RenderMode; layoutMode?: LayoutMode; colorBy?: ColorBy; propertyName?: string; fixedColor?: string; onSelectNode?: (nodeId: string) => void; onSelectEdge?: (edgeId: string) => void }) {
  const positions = React.useMemo(() => layout(model.nodes, model.edges, layoutMode, { width: 920, height: 560 }), [model.nodes, model.edges, layoutMode]);
  const nodeIds = React.useMemo(() => new Set(model.nodes.map((node) => node.id)), [model.nodes]);
  const propertyLegend = React.useMemo(() => colorBy === 'property' ? Array.from(new Set(model.nodes.map((node) => String(node.properties?.[propertyName] ?? 'fallback')))).slice(0, 8) : [], [colorBy, model.nodes, propertyName]);
  return (
    <figure className="wb-graph-frame" data-color-by={colorBy}>
      {colorBy === 'property' ? <figcaption data-testid="graph-color-legend" className="wb-color-legend">{propertyLegend.map((value) => <span key={value}><i style={{ background: stableColor(value) }} />{value}</span>)}</figcaption> : null}
      <svg className="wb-graph" data-testid="graph-canvas" data-render-mode={renderMode} data-layout-mode={layoutMode} role="img" aria-label={model.title} width="920" height="560" viewBox="0 0 920 560">
        {model.edges.map((edge) => {
          const from = positions[edge.source];
          const to = positions[edge.target];
          if (!from || !to) return null;
          const isDimmed = !nodeIds.has(edge.source) || !nodeIds.has(edge.target);
          const midX = (from.x + to.x) / 2 + 72;
          const midY = (from.y + to.y) / 2 + 20;
          const label = edge.displayLabel ?? edge.label;
          return <g key={edge.id} data-testid={`graph-edge-${edge.id}`} role="button" tabIndex={0} aria-label={`Select relationship ${label ?? edge.id}`} opacity={isDimmed ? 0.22 : 1} onClick={() => onSelectEdge?.(edge.id)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') onSelectEdge?.(edge.id); }}><line x1={from.x + 72} y1={from.y + 28} x2={to.x + 72} y2={to.y + 28} stroke={edge.color ?? '#64748b'} strokeDasharray={edgeDash(edge.style)} strokeWidth={edgeWidth(edge.style, edge.weight)} />{label ? <g><rect x={midX - Math.max(28, label.length * 3.5)} y={midY - 14} width={Math.max(56, label.length * 7)} height="18" rx="9" fill="#ffffff" stroke="#cbd5e1" /><text x={midX} y={midY - 1} textAnchor="middle" fontSize="10" fill="#334155">{label}</text></g> : null}</g>;
        })}
        {model.nodes.map((node) => {
          const pos = positions[node.id] ?? { x: 0, y: 0 };
          const w = renderMode === 'compact' ? 132 : 184;
          const h = renderMode === 'compact' ? 42 : 88;
          const nodeColor = colorFor(node, colorBy, propertyName, fixedColor);
          const validationCount = Number(node.validationIssueCount ?? 0);
          const eventCount = Number(node.eventCount ?? 0);
          const badges = [node.lifecycleState, node.reviewState, node.candidateState, node.qualityState, ...(node.badges ?? [])].filter(Boolean).map(String).filter((value, index, all) => all.indexOf(value) === index).slice(0, 4);
          return <g key={node.id} data-testid={`graph-node-${node.id}`} role="button" tabIndex={0} aria-label={`Select ${node.label}`} onClick={() => onSelectNode?.(node.id)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') onSelectNode?.(node.id); }}><rect x={pos.x} y={pos.y} width={w} height={h} rx="10" fill={`${nodeColor}21`} stroke={nodeColor} strokeWidth={node.candidateState || node.lifecycleState === 'candidate' ? 2.2 : 1.6} strokeDasharray={validationCount ? '5 4' : undefined} /><text x={pos.x + 10} y={pos.y + 22} fontWeight="700" fill="#172033">{node.label}</text>{renderMode === 'extended' ? <text x={pos.x + 10} y={pos.y + 42} fontSize="11" fill="#526071">{node.subtitle ?? node.type}</text> : null}{renderMode === 'extended' ? badges.slice(0, 3).map((badge, index) => <text key={`${badge}-${index}`} x={pos.x + 10 + index * 56} y={pos.y + h - 12} fontSize="10" fill="#475569">{badge}</text>) : null}{validationCount > 0 ? <circle data-testid={`graph-node-${node.id}-validation`} cx={pos.x + w - 14} cy={pos.y + 14} r="5" fill="#dc2626" /> : null}{eventCount > 0 ? <g data-testid={`graph-node-${node.id}-event-count`}><circle cx={pos.x + w - 17} cy={pos.y + h - 18} r="11" fill="#1d4ed8" /><text x={pos.x + w - 17} y={pos.y + h - 14} textAnchor="middle" fontSize="10" fill="#fff">{eventCount}</text></g> : null}</g>;
        })}
        {!model.nodes.length ? <text x="460" y="280" textAnchor="middle">No graph nodes available.</text> : null}
      </svg>
    </figure>
  );
}
