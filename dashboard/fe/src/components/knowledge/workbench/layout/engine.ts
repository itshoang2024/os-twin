import type { LayoutMode, WorkbenchEdge, WorkbenchNode } from '../model/workbenchModel';

export interface WorkbenchPosition { x: number; y: number }
export type WorkbenchPositions = Record<string, WorkbenchPosition>;
export interface LayoutOptions { width?: number; height?: number }

const DEFAULT_WIDTH = 960;
const DEFAULT_HEIGHT = 560;
const NODE_GAP_X = 168;
const NODE_GAP_Y = 112;

function ordered(nodes: WorkbenchNode[]) {
  return [...nodes].sort((a, b) => a.id.localeCompare(b.id));
}

function grid(nodes: WorkbenchNode[], width = DEFAULT_WIDTH): WorkbenchPositions {
  const cols = Math.max(1, Math.floor(width / NODE_GAP_X));
  return Object.fromEntries(ordered(nodes).map((node, index) => [node.id, { x: 48 + (index % cols) * NODE_GAP_X, y: 48 + Math.floor(index / cols) * NODE_GAP_Y }]));
}

function row(nodes: WorkbenchNode[]): WorkbenchPositions {
  return Object.fromEntries(ordered(nodes).map((node, index) => [node.id, { x: 48 + index * NODE_GAP_X, y: 96 }]));
}

function column(nodes: WorkbenchNode[]): WorkbenchPositions {
  return Object.fromEntries(ordered(nodes).map((node, index) => [node.id, { x: 96, y: 48 + index * NODE_GAP_Y }]));
}

function circular(nodes: WorkbenchNode[], width = DEFAULT_WIDTH, height = DEFAULT_HEIGHT, radius = 220): WorkbenchPositions {
  const sorted = ordered(nodes);
  const cx = width / 2;
  const cy = height / 2;
  return Object.fromEntries(sorted.map((node, index) => {
    const angle = sorted.length ? (Math.PI * 2 * index) / sorted.length : 0;
    return [node.id, { x: Math.round(cx + Math.cos(angle) * radius), y: Math.round(cy + Math.sin(angle) * radius) }];
  }));
}

function layered(nodes: WorkbenchNode[]): WorkbenchPositions {
  const groups = new Map<string, WorkbenchNode[]>();
  ordered(nodes).forEach((node) => {
    const key = node.layerId ?? node.type ?? 'default';
    groups.set(key, [...(groups.get(key) ?? []), node]);
  });
  const positions: WorkbenchPositions = {};
  Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b)).forEach(([, group], rowIndex) => {
    group.forEach((node, index) => { positions[node.id] = { x: 48 + index * NODE_GAP_X, y: 48 + rowIndex * NODE_GAP_Y }; });
  });
  return positions;
}

function hierarchy(nodes: WorkbenchNode[], edges: WorkbenchEdge[]): WorkbenchPositions {
  const incoming = new Map(nodes.map((node) => [node.id, 0]));
  edges.forEach((edge) => incoming.set(edge.target, (incoming.get(edge.target) ?? 0) + 1));
  const levels = new Map<string, number>();
  ordered(nodes).forEach((node) => levels.set(node.id, incoming.get(node.id) ? 1 : 0));
  edges.forEach((edge) => levels.set(edge.target, Math.max(levels.get(edge.target) ?? 0, (levels.get(edge.source) ?? 0) + 1)));
  const byLevel = new Map<number, WorkbenchNode[]>();
  ordered(nodes).forEach((node) => { const level = levels.get(node.id) ?? 0; byLevel.set(level, [...(byLevel.get(level) ?? []), node]); });
  const positions: WorkbenchPositions = {};
  Array.from(byLevel.entries()).sort(([a], [b]) => a - b).forEach(([level, group]) => {
    group.forEach((node, index) => { positions[node.id] = { x: 60 + level * NODE_GAP_X, y: 60 + index * NODE_GAP_Y }; });
  });
  return positions;
}

export function layout(nodes: WorkbenchNode[], edges: WorkbenchEdge[] = [], mode: LayoutMode = 'auto', options: LayoutOptions = {}): WorkbenchPositions {
  switch (mode) {
    case 'row': return row(nodes);
    case 'column': return column(nodes);
    case 'circular': return circular(nodes, options.width, options.height, 220);
    case 'radial': return circular(nodes, options.width, options.height, 260);
    case 'cluster': return layered(nodes);
    case 'hierarchy': return hierarchy(nodes, edges);
    case 'layered': return layered(nodes);
    case 'cartesian': return grid(nodes, Math.min(options.width ?? 720, 720));
    case 'grid': return grid(nodes, options.width ?? DEFAULT_WIDTH);
    case 'auto':
    default: return edges.length ? hierarchy(nodes, edges) : grid(nodes, options.width ?? DEFAULT_WIDTH);
  }
}
