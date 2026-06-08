'use client';

import React, { useState, useCallback, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useKnowledgeNamespaces } from '@/hooks/use-knowledge-namespaces';
import { useKnowledgeImportMonitor } from '@/hooks/use-knowledge-import';
import { useKnowledgeQuery } from '@/hooks/use-knowledge-query';
import { useNotificationStore } from '@/lib/stores/notificationStore';
import NamespaceSidebar from '@/components/knowledge/NamespaceSidebar';
import NamespaceOverview from '@/components/knowledge/NamespaceOverview';
import NamespaceList from '@/components/knowledge/NamespaceList';
import ImportPanel from '@/components/knowledge/ImportPanel';
import ResearchPanel from '@/components/knowledge/ResearchPanel';
import NexusExplorer from '@/components/knowledge/NexusExplorer';
import MetricsStrip from '@/components/knowledge/MetricsStrip';
import OntologyPanel from '@/components/knowledge/ontology/OntologyPanel';

type DetailView = 'overview' | 'import' | 'research' | 'nexus' | 'ontology';

/**
 * Props interface for the KnowledgeTabCore component.
 * This component is decoupled from PlanContext and can be used in both
 * plan and global contexts.
 */
export interface KnowledgeTabCoreProps {
  /** Optional callback when a note is clicked (e.g., to navigate to Memory tab) */
  onNoteClick?: (noteId: string) => void;
  /** Optional default namespace to select on mount */
  defaultNamespace?: string;
  /** Optional header variant - 'full' shows title with icon, 'minimal' hides header */
  headerVariant?: 'full' | 'minimal';
  /** Optional CSS class name for the container */
  className?: string;
  /** Whether this is being used in a plan context (changes header text) */
  isPlanContext?: boolean;
  /** Callback for "View All Knowledge" navigation (plan context only) */
  onViewAllKnowledge?: () => void;
  /** Whether to show the MetricsStrip panel (default: true) */
  showMetrics?: boolean;
  /** If set, filter namespaces to only show this specific namespace */
  filterNamespace?: string;
  /** Default tab to open in the detail view (used by deep-link routes) */
  defaultTab?: 'import' | 'research' | 'nexus' | 'ontology';
}

/**
 * Core KnowledgeTab component that is decoupled from PlanContext.
 * All plan-specific behaviors are passed via optional props.
 * 
 * Usage:
 * - In plan context: Use PlanKnowledgeTab wrapper which bridges PlanContext
 * - In global context: Use directly with no plan-specific props
 */
export default function KnowledgeTabCore({
  onNoteClick,
  defaultNamespace,
  headerVariant = 'full',
  className = '',
  isPlanContext = false,
  onViewAllKnowledge,
  showMetrics = true,
  filterNamespace,
  defaultTab,
}: KnowledgeTabCoreProps) {
  // Determine initial detail view based on context
  const [activeDetailView, setActiveDetailView] = useState<DetailView>(
    defaultTab ?? (isPlanContext && filterNamespace ? 'nexus' : 'overview')
  );
  const [selectedNamespace, setSelectedNamespace] = useState<string | null>(
    defaultNamespace ?? filterNamespace ?? null
  );

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null);
  const [showMetricsPanel, setShowMetricsPanel] = useState(false);
  const router = useRouter();
  const addToast = useNotificationStore((state) => state.addToast);

  // Hooks
  const {
    namespaces,
    isLoading: namespacesLoading,
    createNamespace,
    refresh: refreshNamespaces,
  } = useKnowledgeNamespaces();

  // Sync selectedNamespace when defaultNamespace prop changes (handles static export hydration)
  useEffect(() => {
    if (defaultNamespace && defaultNamespace !== '_') {
      // Update if current selection is stale (null, '_', or differs from the intended default)
      if (!selectedNamespace || selectedNamespace === '_' || selectedNamespace !== defaultNamespace) {
        setSelectedNamespace(defaultNamespace);
        if (defaultTab) {
          setActiveDetailView(defaultTab);
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaultNamespace, namespacesLoading]);

  const {
    jobs,
    graphCounts,
    activeJob,
    isLoading: jobsLoading,
    startImport,
    refreshJobs,
  } = useKnowledgeImportMonitor(selectedNamespace);

  // Track previous active job to detect completion transitions
  const prevActiveJobRef = useRef<string | null>(null);

  useEffect(() => {
    const prevJobId = prevActiveJobRef.current;
    const currentActiveId = activeJob?.job_id ?? null;

    // Detect transition: was active → now no active job (i.e. job finished)
    if (prevJobId && !currentActiveId) {
      // Find the completed job in the jobs list
      const finishedJob = jobs?.find(j => j.job_id === prevJobId);
      if (finishedJob) {
        if (finishedJob.state === 'completed') {
          addToast({
            type: 'success',
            title: 'Ingestion Complete',
            message: finishedJob.message || `Job finished successfully.`,
            autoDismiss: true,
          });
        } else if (finishedJob.state === 'failed') {
          addToast({
            type: 'error',
            title: 'Ingestion Failed',
            message: finishedJob.errors?.[0] || finishedJob.message || 'Job failed.',
            autoDismiss: false,
          });
        }
      }
      // Refresh namespace metadata + graph counts to update stats
      refreshNamespaces();
      refreshJobs();
    }

    prevActiveJobRef.current = currentActiveId;
  }, [activeJob, jobs, addToast, refreshNamespaces, refreshJobs]);

  const {
    result: queryResult,
    isLoading: queryLoading,
    error: queryError,
    executeQuery,
    clearResult,
  } = useKnowledgeQuery(selectedNamespace);

  // Handlers
  const handleSelectNamespace = useCallback((ns: string) => {
    const isSameNamespace = ns === selectedNamespace;
    setSelectedNamespace(ns);
    // Only reset to overview when switching to a different namespace
    if (!isSameNamespace) {
      setActiveDetailView('overview');
      clearResult();
    }
    // Sync URL if in global context (not plan context)
    if (!isPlanContext) {
      router.replace(`/knowledge/${encodeURIComponent(ns)}`, { scroll: false });
    }
  }, [isPlanContext, router, clearResult, selectedNamespace]);

  const handleCreateNamespace = useCallback(async (name: string, description?: string, language?: string) => {
    try {
      await createNamespace({ name, description, language });
      addToast({
        type: 'success',
        title: 'Namespace Created',
        message: `Namespace "${name}" has been created successfully.`,
        autoDismiss: true,
      });
      setShowCreateModal(false);
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to create namespace';
      addToast({
        type: 'error',
        title: 'Creation Failed',
        message: errorMessage,
        autoDismiss: false,
      });
    }
  }, [createNamespace, addToast]);

  const handleDeleteNamespace = useCallback(async (name: string) => {
    try {
      const { apiDelete } = await import('@/lib/api-client');
      await apiDelete(`/knowledge/namespaces/${name}`);
      refreshNamespaces();
      if (selectedNamespace === name) {
        setSelectedNamespace(null);
        setActiveDetailView('overview');
      }
      addToast({
        type: 'success',
        title: 'Namespace Deleted',
        message: `Namespace "${name}" has been deleted successfully.`,
        autoDismiss: true,
      });
      setShowDeleteConfirm(null);
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to delete namespace';
      addToast({
        type: 'error',
        title: 'Deletion Failed',
        message: errorMessage,
        autoDismiss: false,
      });
    }
  }, [refreshNamespaces, addToast, selectedNamespace]);

  const handleStartImport = useCallback(async (folderPath: string, options?: Record<string, unknown>) => {
    if (!selectedNamespace) {
      addToast({
        type: 'error',
        title: 'No Namespace Selected',
        message: 'Please select a namespace before importing.',
        autoDismiss: false,
      });
      return;
    }

    try {
      await startImport(selectedNamespace, { folder_path: folderPath, options });
      refreshJobs();
      addToast({
        type: 'success',
        title: 'Import Started',
        message: `Import job has been started for "${folderPath}".`,
        autoDismiss: true,
      });
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to start import';
      addToast({
        type: 'error',
        title: 'Import Failed',
        message: errorMessage,
        autoDismiss: false,
      });
    }
  }, [selectedNamespace, startImport, refreshJobs, addToast]);

  const handleExecuteQuery = useCallback(async (query: string, mode: 'raw' | 'graph' | 'summarized', topK: number) => {
    try {
      await executeQuery({ query, mode, top_k: topK });
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Query failed';
      addToast({
        type: 'error',
        title: 'Query Failed',
        message: errorMessage,
        autoDismiss: false,
      });
    }
  }, [executeQuery, addToast]);

  const handleNoteClick = useCallback((noteId: string) => {
    if (onNoteClick) {
      onNoteClick(noteId);
    }
  }, [onNoteClick]);

  // Filter namespaces when filterNamespace is set (plan context)
  const displayNamespaces = filterNamespace
    ? (namespaces ?? []).filter(ns => ns.name === filterNamespace)
    : namespaces;

  // Get the full metadata for the selected namespace
  const selectedNsMeta = (namespaces ?? []).find(ns => ns.name === selectedNamespace);

  // Detail-view tabs for the selected namespace
  const detailTabs: { id: DetailView; label: string; icon: string }[] = [
    { id: 'overview', label: 'Overview', icon: 'dashboard' },
    { id: 'import', label: 'Import', icon: 'upload' },
    { id: 'research', label: 'Research', icon: 'travel_explore' },
    { id: 'nexus', label: 'Nexus', icon: 'hub' },
    { id: 'ontology', label: 'Ontology', icon: 'schema' },
  ];

  // In plan context with filter, hide overview tab
  const visibleDetailTabs = isPlanContext && filterNamespace
    ? detailTabs.filter(t => t.id !== 'overview')
    : detailTabs;

  // Loading state
  if (namespacesLoading && !namespaces) {
    return (
      <div className={`h-full flex items-center justify-center ${className}`}>
        <div className="text-center space-y-3">
          <div 
            className="w-10 h-10 border-2 border-t-transparent rounded-full animate-spin mx-auto"
            style={{ borderColor: 'var(--color-border)', borderTopColor: 'transparent' }} 
          />
          <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
            {isPlanContext ? 'Loading plan knowledge...' : 'Loading knowledge namespaces...'}
          </p>
        </div>
      </div>
    );
  }

  // Empty state — no namespaces at all
  if (!namespaces || namespaces.length === 0 || (filterNamespace && displayNamespaces?.length === 0)) {
    return (
      <div className={`h-full flex items-center justify-center ${className}`}>
        <div className="text-center space-y-4 max-w-md">
          <span 
            className="material-symbols-outlined text-[48px]" 
            style={{ color: 'var(--color-text-muted)' }}
          >
            auto_stories
          </span>
          <h3 className="text-lg font-semibold" style={{ color: 'var(--color-text-main)' }}>
            {filterNamespace ? 'Plan Namespace Not Ready' : 'No Knowledge Namespaces'}
          </h3>
          <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
            {filterNamespace
              ? `The namespace "${filterNamespace}" is being set up for this plan.`
              : 'Create a namespace to start importing and querying your knowledge base.'}
          </p>
          {!filterNamespace && (
            <NamespaceList
              namespaces={[]}
              selectedNamespace={selectedNamespace}
              onSelect={handleSelectNamespace}
              onCreate={handleCreateNamespace}
              onDelete={handleDeleteNamespace}
              isLoading={namespacesLoading}
            />
          )}
        </div>
      </div>
    );
  }

  /* ── Plan context: simplified layout (no sidebar) ────────────────── */
  if (isPlanContext && filterNamespace) {
    return (
      <div className={`h-full flex flex-col overflow-hidden ${className}`}>
        {/* Header with tabs */}
        {headerVariant === 'full' && (
          <div className="flex items-center justify-between px-4 py-3 border-b shrink-0" style={{ borderColor: 'var(--color-border)' }}>
            <div className="flex items-center gap-3">
              <span className="material-symbols-outlined text-[20px]" style={{ color: 'var(--color-primary)' }}>
                auto_stories
              </span>
              <h2 className="text-base font-semibold" style={{ color: 'var(--color-text-main)' }}>
                Plan Knowledge
              </h2>
              {selectedNamespace && activeDetailView !== 'nexus' && (
                <span className="px-2 py-0.5 rounded-lg text-[11px] font-medium"
                  style={{ background: 'var(--color-primary-muted)', color: 'var(--color-primary)' }}>
                  {selectedNamespace}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <nav className="flex items-center gap-1">
                {visibleDetailTabs.map((tab) => {
                  const isActive = activeDetailView === tab.id;
                  return (
                    <button
                      key={tab.id}
                      onClick={() => setActiveDetailView(tab.id)}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                        isActive 
                          ? 'bg-primary/10 text-primary' 
                          : 'text-text-muted hover:bg-surface-hover hover:text-text-main'
                      }`}
                      aria-label={tab.label}
                    >
                      <span className="material-symbols-outlined text-[16px]">{tab.icon}</span>
                      {tab.label}
                    </button>
                  );
                })}
              </nav>
              {onViewAllKnowledge && (
                <button
                  onClick={onViewAllKnowledge}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium text-primary hover:bg-primary/10 transition-all"
                  aria-label="View all knowledge in global page"
                >
                  <span className="material-symbols-outlined text-[16px]">open_in_new</span>
                  View All Knowledge
                </button>
              )}
            </div>
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-hidden flex flex-col">
          <div className="flex-1 overflow-auto">
            {activeDetailView === 'import' && (
              <ImportPanel
                selectedNamespace={selectedNamespace}
                jobs={jobs ?? []}
                activeJob={activeJob}
                isLoading={jobsLoading}
                onStartImport={handleStartImport}
                onRefresh={refreshJobs}
              />
            )}
            {activeDetailView === 'research' && (
              <ResearchPanel selectedNamespace={selectedNamespace} onJobStart={refreshJobs} />
            )}
            {activeDetailView === 'nexus' && (
              <NexusExplorer
                namespaces={displayNamespaces ?? []}
                selectedNamespace={selectedNamespace}
                onSelectNamespace={handleSelectNamespace}
                onNoteClick={handleNoteClick}
              />
            )}
            {activeDetailView === 'ontology' && (
              <OntologyPanel selectedNamespace={selectedNamespace} />
            )}
          </div>
        </div>
      </div>
    );
  }

  /* ── Global context: master-detail layout ────────────────────────── */
  return (
    <div className={`h-full flex overflow-hidden ${className}`}>
      {/* Left sidebar — namespace list */}
      <div
        className="w-[260px] shrink-0 border-r flex flex-col"
        style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)' }}
      >
        <NamespaceSidebar
          namespaces={displayNamespaces ?? []}
          selectedNamespace={selectedNamespace}
          onSelect={handleSelectNamespace}
          onCreateClick={() => setShowCreateModal(true)}
          isLoading={namespacesLoading}
        />

        {/* Metrics toggle at bottom of sidebar */}
        {showMetrics && (
          <div className="shrink-0 border-t" style={{ borderColor: 'var(--color-border)' }}>
            <button
              onClick={() => setShowMetricsPanel(!showMetricsPanel)}
              className="w-full flex items-center gap-2 px-3 py-2 text-[11px] font-medium hover:bg-surface-hover transition-colors"
              style={{ color: 'var(--color-text-muted)' }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
                {showMetricsPanel ? 'expand_more' : 'expand_less'}
              </span>
              System Metrics
              <span className="material-symbols-outlined ml-auto" style={{ fontSize: 14 }}>
                monitoring
              </span>
            </button>
            {showMetricsPanel && (
              <div className="px-2 pb-2">
                <MetricsStrip className="" />
              </div>
            )}
          </div>
        )}
      </div>

      {/* Right detail area — query-first unified view */}
      <div className="flex-1 flex flex-col overflow-hidden" style={{ background: 'var(--color-background)' }}>
        <div className="flex-1 overflow-hidden">
          {!selectedNamespace ? (
            /* No namespace selected */
            <div className="h-full flex items-center justify-center">
              <div className="text-center space-y-3 max-w-sm">
                <span
                  className="material-symbols-outlined text-[48px]"
                  style={{ color: 'var(--color-text-muted)' }}
                >
                  arrow_back
                </span>
                <p className="text-sm font-medium" style={{ color: 'var(--color-text-main)' }}>
                  Select a Namespace
                </p>
                <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                  Choose a namespace from the sidebar to view details, import documents, or query your knowledge base.
                </p>
              </div>
            </div>
          ) : activeDetailView === 'import' ? (
            <div className="h-full flex flex-col">
              <div className="flex items-center gap-2 px-5 py-2.5 border-b shrink-0" style={{ borderColor: 'var(--color-border)' }}>
                <button
                  onClick={() => setActiveDetailView('overview')}
                  className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium text-text-muted hover:bg-surface-hover transition-all"
                >
                  <span className="material-symbols-outlined text-[16px]">arrow_back</span>
                  Back
                </button>
                <span className="text-xs font-semibold" style={{ color: 'var(--color-text-main)' }}>Import Documents</span>
              </div>
              <div className="flex-1 overflow-auto">
                <ImportPanel
                  selectedNamespace={selectedNamespace}
                  jobs={jobs ?? []}
                  activeJob={activeJob}
                  isLoading={jobsLoading}
                  onStartImport={handleStartImport}
                  onRefresh={refreshJobs}
                />
              </div>
            </div>
          ) : activeDetailView === 'nexus' ? (
            <NexusExplorer
              namespaces={displayNamespaces ?? []}
              selectedNamespace={selectedNamespace}
              onSelectNamespace={handleSelectNamespace}
              onNoteClick={handleNoteClick}
            />
          ) : activeDetailView === 'ontology' ? (
            <OntologyPanel selectedNamespace={selectedNamespace} />
          ) : activeDetailView === 'research' ? (
            <div className="h-full flex flex-col">
              <div className="flex items-center gap-2 px-5 py-2.5 border-b shrink-0" style={{ borderColor: 'var(--color-border)' }}>
                <button
                  onClick={() => setActiveDetailView('overview')}
                  className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium text-text-muted hover:bg-surface-hover transition-all"
                >
                  <span className="material-symbols-outlined text-[16px]">arrow_back</span>
                  Back
                </button>
                <span className="text-xs font-semibold" style={{ color: 'var(--color-text-main)' }}>Web Research</span>
              </div>
              <div className="flex-1 overflow-auto">
                <ResearchPanel selectedNamespace={selectedNamespace} onJobStart={refreshJobs} />
              </div>
            </div>
          ) : selectedNsMeta ? (
            <NamespaceOverview
              namespace={selectedNsMeta}
              graphCounts={graphCounts}
              activeJob={activeJob}
              onNavigateImport={() => setActiveDetailView('import')}
              onNavigateResearch={() => setActiveDetailView('research')}
              onNavigateQuery={() => setActiveDetailView('nexus')}
              onDelete={() => setShowDeleteConfirm(selectedNamespace)}
              onRefresh={refreshNamespaces}
              queryResult={queryResult}
              queryLoading={queryLoading}
              queryError={queryError}
              onExecuteQuery={handleExecuteQuery}
              onClearResult={clearResult}
              onNoteClick={handleNoteClick}
            />
          ) : null}
        </div>
      </div>

      {/* Create Namespace Modal */}
      {showCreateModal && (
        <CreateNamespaceModal
          namespaces={namespaces ?? []}
          onSubmit={handleCreateNamespace}
          onClose={() => setShowCreateModal(false)}
        />
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteConfirm && (
        <DeleteConfirmModal
          namespace={showDeleteConfirm}
          onConfirm={() => handleDeleteNamespace(showDeleteConfirm)}
          onClose={() => setShowDeleteConfirm(null)}
        />
      )}
    </div>
  );
}

/* ── Create Namespace Modal ────────────────────────────────────────── */

const SUPPORTED_LANGUAGES = [
  { value: 'English', label: 'English', flag: '🇬🇧' },
  { value: 'Vietnamese', label: 'Tiếng Việt', flag: '🇻🇳' },
  { value: 'Chinese', label: '中文', flag: '🇨🇳' },
  { value: 'Spanish', label: 'Español', flag: '🇪🇸' },
] as const;

function CreateNamespaceModal({
  namespaces,
  onSubmit,
  onClose,
}: {
  namespaces: { name: string }[];
  onSubmit: (name: string, description?: string, language?: string) => Promise<void>;
  onClose: () => void;
}) {
  const [newName, setNewName] = React.useState('');
  const [newDescription, setNewDescription] = React.useState('');
  const [newLanguage, setNewLanguage] = React.useState('English');
  const [isCreating, setIsCreating] = React.useState(false);
  const [validationError, setValidationError] = React.useState<string | null>(null);

  const validateName = React.useCallback((name: string): string | null => {
    if (!name.trim()) return 'Name is required';
    if (name.length > 64) return 'Name must be 64 characters or less';
    if (!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(name)) {
      return 'Must start with lowercase letter/number. Only lowercase, numbers, _, -';
    }
    if (namespaces.some(ns => ns.name === name)) {
      return 'A namespace with this name already exists';
    }
    return null;
  }, [namespaces]);

  const handleCreate = React.useCallback(async () => {
    const error = validateName(newName);
    if (error) {
      setValidationError(error);
      return;
    }
    setIsCreating(true);
    try {
      await onSubmit(newName, newDescription || undefined, newLanguage);
    } finally {
      setIsCreating(false);
    }
  }, [newName, newDescription, newLanguage, validateName, onSubmit]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 animate-in fade-in duration-200">
      <div
        className="rounded-xl border p-6 w-full max-w-md mx-4 shadow-xl animate-in zoom-in-95 duration-200"
        style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold" style={{ color: 'var(--color-text-main)' }}>
            Create Namespace
          </h3>
          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-surface-hover transition-colors"
            aria-label="Close modal"
          >
            <span className="material-symbols-outlined text-[20px]" style={{ color: 'var(--color-text-muted)' }}>
              close
            </span>
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--color-text-muted)' }}>
              Name *
            </label>
            <input
              type="text"
              value={newName}
              onChange={(e) => { setNewName(e.target.value); setValidationError(null); }}
              placeholder="my-namespace"
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{
                background: 'var(--color-background)',
                borderColor: validationError ? 'var(--color-danger)' : 'var(--color-border)',
                color: 'var(--color-text-main)'
              }}
              autoFocus
            />
            {validationError && (
              <p className="text-[11px] mt-1" style={{ color: 'var(--color-danger)' }}>
                {validationError}
              </p>
            )}
            <p className="text-[10px] mt-1" style={{ color: 'var(--color-text-faint)' }}>
              Lowercase letters, numbers, underscores, and hyphens only.
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--color-text-muted)' }}>
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
            <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--color-text-muted)' }}>
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
            onClick={onClose}
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
  );
}

/* ── Delete Confirm Modal ──────────────────────────────────────────── */

function DeleteConfirmModal({
  namespace,
  onConfirm,
  onClose,
}: {
  namespace: string;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}) {
  const [isDeleting, setIsDeleting] = React.useState(false);

  const handleDelete = React.useCallback(async () => {
    setIsDeleting(true);
    try {
      await onConfirm();
    } finally {
      setIsDeleting(false);
    }
  }, [onConfirm]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 animate-in fade-in duration-200">
      <div
        className="rounded-xl border p-6 w-full max-w-sm mx-4 shadow-xl animate-in zoom-in-95 duration-200"
        style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
      >
        <div className="flex items-center gap-3 mb-4">
          <span className="material-symbols-outlined text-[24px]" style={{ color: 'var(--color-danger)' }}>
            warning
          </span>
          <h3 className="text-base font-semibold" style={{ color: 'var(--color-text-main)' }}>
            Delete Namespace?
          </h3>
        </div>
        <p className="text-sm mb-6" style={{ color: 'var(--color-text-muted)' }}>
          Are you sure you want to delete <strong>&quot;{namespace}&quot;</strong>? This will remove all indexed files, chunks, and entities. This action cannot be undone.
        </p>
        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-xs font-medium transition-colors"
            style={{ color: 'var(--color-text-muted)' }}
          >
            Cancel
          </button>
          <button
            onClick={handleDelete}
            disabled={isDeleting}
            className="px-4 py-2 rounded-lg text-xs font-semibold bg-danger text-white hover:bg-danger/90 transition-colors disabled:opacity-50"
          >
            {isDeleting ? 'Deleting...' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  );
}
