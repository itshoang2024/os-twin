'use client';

import React from 'react';
import { useNexusContext } from './NexusContext';
import ContextualCard from './ContextualCard';
import { Icon } from './Icon';
import FactReviewPanel from './FactReviewPanel';

export default function RightDock({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const ctx = useNexusContext();
  const { graph, actions, path, namespace } = ctx;

  if (collapsed || !graph.selectedNode) {
    return (
      <div
        className="flex flex-col items-center py-2 border-l"
        style={{ width: collapsed ? 32 : 0, borderColor: 'var(--color-border)', background: 'var(--surface-overlay-bg)', overflow: 'hidden' }}
      >
        {collapsed && (
          <>
            <button
              onClick={onToggle}
              className="p-1 rounded hover:bg-white/10 transition-colors"
              title="Expand right dock"
            >
              <Icon name="chevron_left" size={14} style={{ color: 'var(--color-text-muted)' }} />
            </button>
          </>
        )}
      </div>
    );
  }

  return (
    <div
      className="overflow-hidden flex flex-col border-l"
      style={{ width: 360, borderColor: 'var(--color-border)', background: 'var(--surface-overlay-bg)' }}
    >
      <div className="flex items-center justify-end px-2 py-1 border-b shrink-0" style={{ borderColor: 'var(--color-border)' }}>
        <button
          onClick={onToggle}
          className="p-1 rounded hover:bg-white/10 transition-colors"
          title="Collapse right dock"
        >
          <Icon name="chevron_right" size={14} style={{ color: 'var(--color-text-muted)' }} />
        </button>
      </div>
      <div className="flex-1 overflow-auto">
        <ContextualCard
          node={graph.selectedNode}
          edges={graph.edges}
          isLoading={graph.isLoading}
          onExpand={actions.expand}
          onTracePath={path.tracePathFromCard}
          onClose={() => path.handleNodeClick(null)}
          docked
        />
        <FactReviewPanel namespace={namespace.selectedNamespace} subjectId={graph.selectedNode.id} />
      </div>
    </div>
  );
}
