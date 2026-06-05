'use client';

import React, { useState, useRef, useEffect } from 'react';
import { NamespaceMetaResponse } from '@/hooks/use-knowledge-namespaces';

/* ── Helpers ───────────────────────────────────────────────────────── */

const AVATAR_COLORS = [
  '#3B82F6', '#8B5CF6', '#EC4899', '#F97316',
  '#14B8A6', '#EAB308', '#22C55E', '#0EA5E9',
];

function getAvatarColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

function formatRelativeTime(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60_000);
    if (mins < 1) return 'now';
    if (mins < 60) return `${mins}m`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h`;
    const days = Math.floor(hrs / 24);
    return `${days}d`;
  } catch {
    return '';
  }
}

/* ── Props ─────────────────────────────────────────────────────────── */

interface NamespaceSidebarProps {
  namespaces: NamespaceMetaResponse[];
  selectedNamespace: string | null;
  onSelect: (namespace: string) => void;
  onCreateClick: () => void;
  isLoading: boolean;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
}

/* ── Sidebar Item ──────────────────────────────────────────────────── */

function SidebarItem({
  ns,
  isSelected,
  onSelect,
  collapsed = false,
}: {
  ns: NamespaceMetaResponse;
  isSelected: boolean;
  onSelect: () => void;
  collapsed?: boolean;
}) {
  const color = getAvatarColor(ns.name);
  const initial = ns.name.charAt(0).toUpperCase();
  const totalItems = ns.stats.files_indexed + ns.stats.chunks;

  if (collapsed) {
    return (
      <button
        onClick={onSelect}
        className={`
          relative mx-auto flex h-10 w-10 items-center justify-center rounded-lg
          transition-all duration-150
          ${isSelected
            ? 'bg-primary/10 ring-1 ring-primary/30'
            : 'hover:bg-surface-hover'
          }
        `}
        title={ns.name}
        aria-label={`Select namespace ${ns.name}`}
        aria-pressed={isSelected}
      >
        <div
          className="flex h-7 w-7 items-center justify-center rounded-lg text-[11px] font-bold text-white"
          style={{ backgroundColor: color }}
          aria-hidden="true"
        >
          {initial}
        </div>
        {isSelected && (
          <span
            className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full"
            style={{ background: 'var(--color-primary)' }}
            aria-hidden="true"
          />
        )}
      </button>
    );
  }

  return (
    <button
      onClick={onSelect}
      className={`
        w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left
        transition-all duration-150 group
        ${isSelected
          ? 'bg-primary/10 ring-1 ring-primary/30'
          : 'hover:bg-surface-hover'
        }
      `}
      aria-label={`Select namespace ${ns.name}`}
      aria-pressed={isSelected}
    >
      {/* Avatar */}
      <div
        className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 text-white font-bold text-[11px]"
        style={{ backgroundColor: color }}
      >
        {initial}
      </div>

      {/* Name + meta */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span
            className={`text-xs font-medium truncate ${
              isSelected ? 'text-primary' : ''
            }`}
            style={isSelected ? {} : { color: 'var(--color-text-main)' }}
          >
            {ns.name}
          </span>
          <span
            className="text-[10px] shrink-0"
            style={{ color: 'var(--color-text-faint)' }}
          >
            {formatRelativeTime(ns.updated_at)}
          </span>
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          {totalItems > 0 ? (
            <>
              {ns.stats.files_indexed > 0 && (
                <span className="text-[10px] flex items-center gap-0.5" style={{ color: 'var(--color-text-faint)' }}>
                  <span className="material-symbols-outlined" style={{ fontSize: 10 }}>description</span>
                  {ns.stats.files_indexed}
                </span>
              )}
              {ns.stats.entities > 0 && (
                <span className="text-[10px] flex items-center gap-0.5" style={{ color: 'var(--color-text-faint)' }}>
                  <span className="material-symbols-outlined" style={{ fontSize: 10 }}>hub</span>
                  {ns.stats.entities}
                </span>
              )}
            </>
          ) : (
            <span className="text-[10px] italic" style={{ color: 'var(--color-text-faint)' }}>
              empty
            </span>
          )}
        </div>
      </div>

      {/* Selected check */}
      {isSelected && (
        <span
          className="material-symbols-outlined shrink-0"
          style={{ fontSize: 14, color: 'var(--color-primary)' }}
        >
          check_circle
        </span>
      )}
    </button>
  );
}

/* ── Main Component ────────────────────────────────────────────────── */

export default function NamespaceSidebar({
  namespaces,
  selectedNamespace,
  onSelect,
  onCreateClick,
  isLoading,
  collapsed = false,
  onToggleCollapsed,
}: NamespaceSidebarProps) {
  const [searchTerm, setSearchTerm] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);

  // Keyboard shortcut: "/" to focus search
  useEffect(() => {
    if (collapsed) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === '/' && document.activeElement?.tagName !== 'INPUT') {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [collapsed]);

  // Filter + sort
  const isSearching = searchTerm.trim().length > 0 && !collapsed;
  const filtered = isSearching
    ? namespaces.filter(ns =>
        ns.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        ns.description?.toLowerCase().includes(searchTerm.toLowerCase())
      )
    : namespaces;

  const sorted = [...filtered].sort((a, b) => {
    if (a.name === selectedNamespace) return -1;
    if (b.name === selectedNamespace) return 1;
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
  });

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className={`${collapsed ? 'px-2 py-2' : 'px-3 pt-3 pb-2'} shrink-0`}>
        {collapsed ? (
          <div className="flex flex-col items-center gap-2">
            {onToggleCollapsed && (
              <button
                onClick={onToggleCollapsed}
                className="flex h-9 w-9 items-center justify-center rounded-lg transition-colors hover:bg-surface-hover"
                style={{ color: 'var(--color-text-muted)' }}
                aria-label="Expand namespace navigation"
                title="Expand namespace navigation"
              >
                <span className="material-symbols-outlined" style={{ fontSize: 18 }} aria-hidden="true">
                  chevron_right
                </span>
              </button>
            )}
            <button
              onClick={onCreateClick}
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-white transition-colors hover:bg-primary/90"
              aria-label="Create new namespace"
              title="Create namespace"
            >
              <span className="material-symbols-outlined" style={{ fontSize: 17 }} aria-hidden="true">add</span>
            </button>
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <h2
                className="text-sm font-semibold"
                style={{ color: 'var(--color-text-main)' }}
              >
                Namespaces
              </h2>
              <p className="text-[10px] mt-0.5" style={{ color: 'var(--color-text-faint)' }}>
                {namespaces.length} total
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <button
                onClick={onCreateClick}
                className="w-7 h-7 rounded-lg flex items-center justify-center bg-primary text-white hover:bg-primary/90 transition-colors"
                aria-label="Create new namespace"
                title="Create namespace"
              >
                <span className="material-symbols-outlined" style={{ fontSize: 16 }}>add</span>
              </button>
              {onToggleCollapsed && (
                <button
                  onClick={onToggleCollapsed}
                  className="flex h-7 w-7 items-center justify-center rounded-lg transition-colors hover:bg-surface-hover"
                  style={{ color: 'var(--color-text-muted)' }}
                  aria-label="Collapse namespace navigation"
                  title="Collapse namespace navigation"
                >
                  <span className="material-symbols-outlined" style={{ fontSize: 17 }} aria-hidden="true">
                    chevron_left
                  </span>
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Search */}
      {!collapsed && (
        <div className="px-3 pb-2 shrink-0">
          <div
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border"
            style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)' }}
          >
            <span
              className="material-symbols-outlined shrink-0"
              style={{ fontSize: 14, color: 'var(--color-text-faint)' }}
            >
              search
            </span>
            <input
              ref={searchRef}
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search…  /"
              className="flex-1 text-[11px] bg-transparent outline-none"
              style={{ color: 'var(--color-text-main)' }}
            />
            {searchTerm && (
              <button
                onClick={() => setSearchTerm('')}
                className="shrink-0"
                aria-label="Clear search"
              >
                <span
                  className="material-symbols-outlined"
                  style={{ fontSize: 12, color: 'var(--color-text-faint)' }}
                >
                  close
                </span>
              </button>
            )}
          </div>
        </div>
      )}

      {/* Namespace list */}
      <div
        className={`flex-1 overflow-y-auto pb-2 ${collapsed ? 'px-1.5 space-y-1' : 'px-2 space-y-0.5'}`}
        style={{ scrollbarWidth: 'thin' }}
      >
        {isLoading && sorted.length === 0 ? (
          <div className="flex items-center justify-center py-8">
            <div
              className="w-5 h-5 border-2 border-t-transparent rounded-full animate-spin"
              style={{ borderColor: 'var(--color-border)', borderTopColor: 'transparent' }}
            />
          </div>
        ) : sorted.length === 0 ? (
          <div className="text-center py-6">
            <span
              className="material-symbols-outlined text-[24px] mb-1"
              style={{ color: 'var(--color-text-muted)' }}
            >
              {isSearching ? 'search_off' : 'folder_off'}
            </span>
            <p className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>
              {isSearching ? `No results for "${searchTerm}"` : 'No namespaces yet'}
            </p>
          </div>
        ) : (
          sorted.map((ns) => (
            <SidebarItem
              key={ns.name}
              ns={ns}
              isSelected={selectedNamespace === ns.name}
              onSelect={() => onSelect(ns.name)}
              collapsed={collapsed}
            />
          ))
        )}
      </div>
    </div>
  );
}
