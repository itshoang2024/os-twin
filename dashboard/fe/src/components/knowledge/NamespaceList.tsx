'use client';

import React, { useState, useCallback } from 'react';
import { NamespaceMetaResponse } from '@/hooks/use-knowledge-namespaces';
import NamespaceActions from './NamespaceActions';

const SUPPORTED_LANGUAGES = [
  { value: 'English', label: 'English', flag: '🇬🇧' },
  { value: 'Vietnamese', label: 'Tiếng Việt', flag: '🇻🇳' },
  { value: 'Chinese', label: '中文', flag: '🇨🇳' },
  { value: 'Spanish', label: 'Español', flag: '🇪🇸' },
] as const;

interface NamespaceListProps {
  namespaces: NamespaceMetaResponse[];
  visibleNamespaces?: NamespaceMetaResponse[];
  selectedNamespace: string | null;
  onSelect: (namespace: string) => void;
  onCreate: (name: string, description?: string, language?: string) => Promise<void>;
  onDelete: (namespace: string) => Promise<void>;
  isLoading: boolean;
  onNamespaceUpdated?: () => void;
}

/* ── Helpers ───────────────────────────────────────────────────────── */

const CARD_COLORS = [
  '#3B82F6',
  '#8B5CF6',
  '#EC4899',
  '#F97316',
  '#14B8A6',
  '#EAB308',
  '#22C55E',
  '#0EA5E9',
];

function getCardColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  return CARD_COLORS[Math.abs(hash) % CARD_COLORS.length];
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function formatRelativeTime(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60_000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    if (days < 30) return `${days}d ago`;
    return new Date(iso).toLocaleDateString();
  } catch {
    return iso;
  }
}

const LANGUAGE_FLAGS: Record<string, string> = {
  English: '🇬🇧',
  Vietnamese: '🇻🇳',
  Chinese: '🇨🇳',
  Spanish: '🇪🇸',
};

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

/* ── Stat Pill ─────────────────────────────────────────────────────── */

function StatPill({ icon, value, label }: { icon: string; value: string; label: string }) {
  return (
    <div 
      className="flex items-center gap-1 px-2 py-1 rounded-md"
      style={{ background: 'var(--color-surface-hover)' }}
      title={label}
    >
      <span 
        className="material-symbols-outlined" 
        style={{ fontSize: 12, color: 'var(--color-text-faint)' }}
      >
        {icon}
      </span>
      <span className="text-[10px] font-semibold" style={{ color: 'var(--color-text-muted)' }}>
        {value}
      </span>
    </div>
  );
}

/* ── Namespace Card ────────────────────────────────────────────────── */

function NamespaceCard({
  ns,
  isSelected,
  onSelect,
  onDelete,
  onNamespaceUpdated,
}: {
  ns: NamespaceMetaResponse;
  isSelected: boolean;
  onSelect: () => void;
  onDelete: () => void;
  onNamespaceUpdated?: () => void;
}) {
  const avatarColor = getCardColor(ns.name);
  const initial = ns.name.charAt(0).toUpperCase();
  const { stats } = ns;
  const hasContent = stats.files_indexed > 0 || stats.chunks > 0;

  return (
    <div
      className={`
        group relative rounded-2xl border p-4 cursor-pointer
        transition-all duration-200 ease-out
        hover:translate-y-[-2px] hover:shadow-lg
        ${isSelected 
          ? 'ring-2 ring-primary shadow-md' 
          : 'hover:border-primary/30'
        }
      `}
      style={{ 
        background: 'var(--color-surface)', 
        borderColor: isSelected ? 'var(--color-primary)' : 'var(--color-border)',
      }}
      onClick={onSelect}
      onKeyDown={(e) => e.key === 'Enter' && onSelect()}
      tabIndex={0}
      role="button"
      aria-label={`Select namespace ${ns.name}`}
      aria-pressed={isSelected}
    >
      {/* Top row: avatar + actions */}
      <div className="flex items-start justify-between mb-3">
        {/* Avatar + name */}
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <div 
            className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0 text-white font-bold text-sm"
            style={{ backgroundColor: avatarColor }}
          >
            {initial}
          </div>
          <div className="min-w-0 flex-1">
            <h4 className="text-sm font-semibold truncate" style={{ color: 'var(--color-text-main)' }}>
              {ns.name}
            </h4>
            <p className="text-[10px] mt-0.5" style={{ color: 'var(--color-text-faint)' }}>
              {LANGUAGE_FLAGS[ns.language] || '🌐'} {ns.language} · {formatRelativeTime(ns.updated_at)}
            </p>
          </div>
        </div>

        {/* Actions */}
        <div 
          className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
          onClick={(e) => e.stopPropagation()}
        >
          <NamespaceActions 
            namespace={ns.name} 
            onRefresh={onNamespaceUpdated}
          />
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            className="p-1 rounded-md hover:bg-danger/10 transition-colors"
            style={{ color: 'var(--color-danger)' }}
            aria-label={`Delete namespace ${ns.name}`}
          >
            <span className="material-symbols-outlined" style={{ fontSize: 16 }}>delete</span>
          </button>
        </div>
      </div>

      {/* Description */}
      {ns.description && (
        <p 
          className="text-xs mb-3 line-clamp-2 leading-relaxed"
          style={{ color: 'var(--color-text-muted)' }}
        >
          {ns.description}
        </p>
      )}

      {/* Stats grid */}
      {hasContent ? (
        <div className="flex flex-wrap gap-1.5">
          {stats.files_indexed > 0 && (
            <StatPill icon="description" value={formatCount(stats.files_indexed)} label={`${stats.files_indexed} files indexed`} />
          )}
          {stats.chunks > 0 && (
            <StatPill icon="dataset" value={formatCount(stats.chunks)} label={`${stats.chunks} chunks`} />
          )}
          {stats.entities > 0 && (
            <StatPill icon="hub" value={formatCount(stats.entities)} label={`${stats.entities} entities`} />
          )}
          {stats.vectors > 0 && (
            <StatPill icon="conversion_path" value={formatCount(stats.vectors)} label={`${stats.vectors} vectors`} />
          )}
          {stats.bytes_on_disk > 0 && (
            <StatPill icon="hard_drive" value={formatBytes(stats.bytes_on_disk)} label={`${formatBytes(stats.bytes_on_disk)} storage`} />
          )}
        </div>
      ) : (
        <div 
          className="flex items-center gap-1.5 text-[10px] py-1"
          style={{ color: 'var(--color-text-faint)' }}
        >
          <span className="material-symbols-outlined" style={{ fontSize: 14 }}>info</span>
          Empty — import documents to get started
        </div>
      )}

      {/* Selection indicator */}
      {isSelected && (
        <div 
          className="absolute top-2 right-2 w-5 h-5 rounded-full flex items-center justify-center group-hover:opacity-0 transition-opacity"
          style={{ background: 'var(--color-primary)' }}
        >
          <span className="material-symbols-outlined text-white" style={{ fontSize: 14 }}>check</span>
        </div>
      )}
    </div>
  );
}

/* ── Main Component ────────────────────────────────────────────────── */

export default function NamespaceList({
  namespaces,
  visibleNamespaces,
  selectedNamespace,
  onSelect,
  onCreate,
  onDelete,
  onNamespaceUpdated,
}: NamespaceListProps) {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newLanguage, setNewLanguage] = useState('English');
  const [isCreating, setIsCreating] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');

  // Namespace name validation (matches backend regex)
  const validateName = useCallback((name: string): string | null => {
    if (!name.trim()) return 'Name is required';
    if (name.length > 64) return 'Name must be 64 characters or less';
    if (!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(name)) {
      return 'Name must start with lowercase letter or number, and contain only lowercase letters, numbers, underscores, and hyphens';
    }
    if (namespaces.some(ns => ns.name === name)) {
      return 'A namespace with this name already exists';
    }
    return null;
  }, [namespaces]);

  const handleCreate = useCallback(async () => {
    const error = validateName(newName);
    if (error) {
      setValidationError(error);
      return;
    }

    setIsCreating(true);
    try {
      await onCreate(newName, newDescription || undefined, newLanguage);
      setShowCreateModal(false);
      setNewName('');
      setNewDescription('');
      setNewLanguage('English');
      setValidationError(null);
    } finally {
      setIsCreating(false);
    }
  }, [newName, newDescription, newLanguage, validateName, onCreate]);

  const handleDelete = useCallback(async (namespace: string) => {
    setIsDeleting(true);
    try {
      await onDelete(namespace);
      setDeleteConfirm(null);
    } finally {
      setIsDeleting(false);
    }
  }, [onDelete]);

  const displayNamespaces = visibleNamespaces ?? namespaces;

  // Filter namespaces by search
  const filteredNamespaces = searchTerm
    ? displayNamespaces.filter(ns =>
        ns.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        ns.description?.toLowerCase().includes(searchTerm.toLowerCase())
      )
    : displayNamespaces;

  // Sort: selected first, then by updated_at desc
  const sortedNamespaces = [...filteredNamespaces].sort((a, b) => {
    if (a.name === selectedNamespace) return -1;
    if (b.name === selectedNamespace) return 1;
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
  });

  return (
    <div className="h-full overflow-y-auto p-5" style={{ scrollbarWidth: 'thin' }}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>
            Knowledge Namespaces
          </h3>
          <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
            {visibleNamespaces && visibleNamespaces.length !== namespaces.length
              ? `${visibleNamespaces.length} of ${namespaces.length}`
              : namespaces.length}{' '}
            namespace{namespaces.length !== 1 ? 's' : ''} available
          </p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-primary text-white hover:bg-primary/90 transition-colors"
          aria-label="Create new namespace"
        >
          <span className="material-symbols-outlined text-[16px]">add</span>
          New
        </button>
      </div>

      {/* Search */}
      {displayNamespaces.length > 6 && (
        <div className="mb-4">
          <div 
            className="flex items-center gap-2 px-3 py-2 rounded-lg border"
            style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)' }}
          >
            <span 
              className="material-symbols-outlined shrink-0" 
              style={{ fontSize: 16, color: 'var(--color-text-faint)' }}
            >
              search
            </span>
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search namespaces..."
              className="flex-1 text-xs bg-transparent outline-none"
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
                  style={{ fontSize: 14, color: 'var(--color-text-faint)' }}
                >
                  close
                </span>
              </button>
            )}
          </div>
        </div>
      )}

      {/* Card Grid */}
      <div 
        className="grid gap-3"
        style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}
      >
        {sortedNamespaces.map((ns) => (
          <NamespaceCard
            key={ns.name}
            ns={ns}
            isSelected={selectedNamespace === ns.name}
            onSelect={() => onSelect(ns.name)}
            onDelete={() => setDeleteConfirm(ns.name)}
            onNamespaceUpdated={onNamespaceUpdated}
          />
        ))}
      </div>

      {/* Empty search state */}
      {searchTerm && filteredNamespaces.length === 0 && (
        <div className="text-center py-8">
          <span 
            className="material-symbols-outlined text-[32px] mb-2"
            style={{ color: 'var(--color-text-muted)' }}
          >
            search_off
          </span>
          <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
            No namespaces matching &quot;{searchTerm}&quot;
          </p>
        </div>
      )}

      {!searchTerm && namespaces.length > 0 && sortedNamespaces.length === 0 && (
        <div className="text-center py-8">
          <span
            className="material-symbols-outlined text-[32px] mb-2"
            style={{ color: 'var(--color-text-muted)' }}
          >
            filter_alt_off
          </span>
          <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
            No namespaces match the active filters.
          </p>
        </div>
      )}

      {/* Empty state (no namespaces at all) */}
      {namespaces.length === 0 && (
        <div className="text-center py-12">
          <span 
            className="material-symbols-outlined text-[48px] mb-3"
            style={{ color: 'var(--color-text-muted)' }}
          >
            folder_off
          </span>
          <p className="text-sm font-medium mb-1" style={{ color: 'var(--color-text-main)' }}>
            No namespaces yet
          </p>
          <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            Create a namespace to start importing and querying your knowledge base.
          </p>
        </div>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div 
            className="rounded-2xl border p-6 w-full max-w-md mx-4"
            style={{ 
              background: 'var(--color-surface)', 
              borderColor: 'var(--color-border)' 
            }}
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-semibold" style={{ color: 'var(--color-text-main)' }}>
                Create Namespace
              </h3>
              <button
                onClick={() => {
                  setShowCreateModal(false);
                  setNewName('');
                  setNewDescription('');
                  setNewLanguage('English');
                  setValidationError(null);
                }}
                className="p-1 rounded hover:bg-surface-hover transition-colors"
                aria-label="Close modal"
              >
                <span className="material-symbols-outlined text-[20px]" style={{ color: 'var(--color-text-muted)' }}>
                  close
                </span>
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label 
                  className="block text-xs font-medium mb-1.5"
                  style={{ color: 'var(--color-text-muted)' }}
                >
                  Name *
                </label>
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => {
                    setNewName(e.target.value);
                    setValidationError(null);
                  }}
                  placeholder="my-namespace"
                  className="w-full px-3 py-2 rounded-lg border text-sm"
                  style={{ 
                    background: 'var(--color-background)', 
                    borderColor: validationError ? 'var(--color-danger)' : 'var(--color-border)',
                    color: 'var(--color-text-main)'
                  }}
                  aria-describedby={validationError ? 'name-error' : undefined}
                />
                {validationError && (
                  <p id="name-error" className="text-xs mt-1" style={{ color: 'var(--color-danger)' }}>
                    {validationError}
                  </p>
                )}
                <p className="text-[10px] mt-1" style={{ color: 'var(--color-text-faint)' }}>
                  Lowercase letters, numbers, underscores, and hyphens only. Max 64 chars.
                </p>
              </div>

              <div>
                <label 
                  className="block text-xs font-medium mb-1.5"
                  style={{ color: 'var(--color-text-muted)' }}
                >
                  Language
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {SUPPORTED_LANGUAGES.map((lang) => (
                    <button
                      key={lang.value}
                      type="button"
                      onClick={() => setNewLanguage(lang.value)}
                      className="flex items-center gap-2 px-3 py-2.5 rounded-lg border text-sm font-medium transition-all duration-150"
                      style={{
                        background: newLanguage === lang.value ? 'var(--color-primary-muted)' : 'var(--color-background)',
                        borderColor: newLanguage === lang.value ? 'var(--color-primary)' : 'var(--color-border)',
                        color: newLanguage === lang.value ? 'var(--color-primary)' : 'var(--color-text-main)',
                        boxShadow: newLanguage === lang.value ? '0 0 0 1px var(--color-primary)' : 'none',
                      }}
                    >
                      <span className="text-base">{lang.flag}</span>
                      <span>{lang.label}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label 
                  className="block text-xs font-medium mb-1.5"
                  style={{ color: 'var(--color-text-muted)' }}
                >
                  Description (optional)
                </label>
                <textarea
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  placeholder="Describe this knowledge namespace..."
                  rows={3}
                  className="w-full px-3 py-2 rounded-lg border text-sm resize-none"
                  style={{ 
                    background: 'var(--color-background)', 
                    borderColor: 'var(--color-border)',
                    color: 'var(--color-text-main)'
                  }}
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-6">
              <button
                onClick={() => {
                  setShowCreateModal(false);
                  setNewName('');
                  setNewDescription('');
                  setNewLanguage('English');
                  setValidationError(null);
                }}
                className="px-4 py-2 rounded-lg text-xs font-medium transition-colors"
                style={{ color: 'var(--color-text-muted)' }}
              >
                Cancel
              </button>
              <button
                onClick={handleCreate}
                disabled={isCreating || !newName.trim()}
                className="px-4 py-2 rounded-lg text-xs font-semibold bg-primary text-white hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {isCreating ? 'Creating...' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div 
            className="rounded-2xl border p-6 w-full max-w-sm mx-4"
            style={{ 
              background: 'var(--color-surface)', 
              borderColor: 'var(--color-border)' 
            }}
          >
            <div className="flex items-center gap-3 mb-4">
              <span 
                className="material-symbols-outlined text-[24px]"
                style={{ color: 'var(--color-danger)' }}
              >
                warning
              </span>
              <h3 className="text-base font-semibold" style={{ color: 'var(--color-text-main)' }}>
                Delete Namespace?
              </h3>
            </div>
            <p className="text-sm mb-6" style={{ color: 'var(--color-text-muted)' }}>
              Are you sure you want to delete <strong>&quot;{deleteConfirm}&quot;</strong>? This will remove all indexed files, chunks, and entities. This action cannot be undone.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="px-4 py-2 rounded-lg text-xs font-medium transition-colors"
                style={{ color: 'var(--color-text-muted)' }}
              >
                Cancel
              </button>
              <button
                onClick={() => handleDelete(deleteConfirm)}
                disabled={isDeleting}
                className="px-4 py-2 rounded-lg text-xs font-semibold bg-danger text-white hover:bg-danger/90 transition-colors disabled:opacity-50"
              >
                {isDeleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
