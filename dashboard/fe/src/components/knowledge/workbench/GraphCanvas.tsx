import React from 'react';
import { layout } from './layout/engine';
import type { LayoutMode, RenderMode, WorkbenchModel } from './model/workbenchModel';

export default function GraphCanvas({ model, renderMode = 'extended', layoutMode = 'auto', onSelectNode, onSelectEdge }: { model: WorkbenchModel; renderMode?: RenderMode; layoutMode?: LayoutMode; onSelectNode?: (nodeId: string) => void; onSelectEdge?: (edgeId: string) => void }) {
  const positions = React.useMemo(() => layout(model.nodes, model.edges, layoutMode, { width: 920, height: 560 }), [model.nodes, model.edges, layoutMode]);
  return (
    <svg className="wb-graph" data-testid="graph-canvas" data-render-mode={renderMode} role="img" aria-label={model.title} width="920" height="560" viewBox="0 0 920 560">
      {model.edges.map((edge) => {
        const from = positions[edge.source];
        const to = positions[edge.target];
        if (!from || !to) return null;
        return <g key={edge.id} data-testid={`graph-edge-${edge.id}`} role="button" tabIndex={0} onClick={() => onSelectEdge?.(edge.id)}><line x1={from.x + 72} y1={from.y + 28} x2={to.x + 72} y2={to.y + 28} stroke="#64748b" strokeDasharray={edge.style === 'dashed' ? '6 4' : edge.style === 'dotted' ? '2 4' : undefined} strokeWidth={edge.style === 'bold' ? 2.5 : 1.5} /><text x={(from.x + to.x) / 2 + 72} y={(from.y + to.y) / 2 + 20}>{edge.label}</text></g>;
      })}
      {model.nodes.map((node) => {
        const pos = positions[node.id] ?? { x: 0, y: 0 };
        const w = renderMode === 'compact' ? 132 : 172;
        const h = renderMode === 'compact' ? 38 : 76;
        return <g key={node.id} data-testid={`graph-node-${node.id}`} role="button" tabIndex={0} onClick={() => onSelectNode?.(node.id)}><rect x={pos.x} y={pos.y} width={w} height={h} rx="10" fill={`${node.color ?? '#2563eb'}22`} stroke={node.color ?? '#2563eb'} /><text x={pos.x + 10} y={pos.y + 22}>{node.label}</text>{renderMode === 'extended' ? <text x={pos.x + 10} y={pos.y + 46}>{node.subtitle ?? node.type}</text> : null}{renderMode === 'extended' ? node.badges?.slice(0, 2).map((badge, index) => <text key={badge} x={pos.x + 10 + index * 54} y={pos.y + h - 10}>{badge}</text>) : null}</g>;
      })}
      {!model.nodes.length ? <text x="460" y="280" textAnchor="middle">No graph nodes available.</text> : null}
    </svg>
  );
}
