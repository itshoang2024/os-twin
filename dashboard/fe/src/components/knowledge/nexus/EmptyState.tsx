'use client';

import React from 'react';
import type { NamespaceMetaResponse } from '@/hooks/use-knowledge-namespaces';
import { FONT } from './typography';
import { Icon } from './Icon';

interface EmptyStateProps {
  namespaces: NamespaceMetaResponse[];
  onSelectNamespace: (ns: string) => void;
}

export default function EmptyState({ namespaces, onSelectNamespace }: EmptyStateProps) {
  return (
    <div className="h-full w-full flex items-center justify-center">
      <div
        className="absolute inset-0"
        style={{
          background: 'radial-gradient(ellipse at center, rgba(37, 99, 235, 0.04) 0%, transparent 70%)',
        }}
      />
      <div className="text-center space-y-4 max-w-md relative z-10">
        <div
          className="w-16 h-16 rounded-2xl mx-auto flex items-center justify-center border"
          style={{
            background: 'var(--color-primary-muted)',
            borderColor: 'var(--color-border)',
          }}
        >
          <Icon name="hub" size={32} style={{ color: 'var(--color-primary)' }} />
        </div>
        <h3 className="text-lg font-bold" style={{ color: 'var(--color-text-main)' }}>
          Graph View
        </h3>
        <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
          Select a namespace to begin exploring your knowledge graph.
          Send a sonar ping to discover connections.
        </p>
        {namespaces.length > 0 ? (
          <div className="grid grid-cols-2 gap-2 mt-4">
            {namespaces.slice(0, 8).map(ns => (
              <button
                key={ns.name}
                onClick={() => onSelectNamespace(ns.name)}
                className="flex flex-col items-start gap-1 px-3 py-2.5 rounded-lg border text-left transition-all hover:border-primary/50 hover:bg-primary/5"
                style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}
              >
                <span className="text-xs font-semibold truncate w-full" style={{ color: 'var(--color-text-main)' }}>
                  {ns.name}
                </span>
                {ns.stats?.chunks !== undefined && (
                  <span className={FONT.caption} style={{ color: 'var(--color-text-muted)' }}>
                    {ns.stats.chunks} chunks · {ns.stats.entities} entities
                  </span>
                )}
              </button>
            ))}
          </div>
        ) : (
          <p className="text-xs" style={{ color: 'var(--color-text-faint)' }}>
            No namespaces available. Create one first.
          </p>
        )}
      </div>
    </div>
  );
}
