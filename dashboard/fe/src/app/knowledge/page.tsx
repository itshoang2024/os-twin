'use client';

import Link from 'next/link';
import { useCallback, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { type NamespaceMetaResponse, useKnowledgeNamespaces } from '@/hooks/use-knowledge-namespaces';
import { useNotificationStore } from '@/lib/stores/notificationStore';
import NamespaceList from '@/components/knowledge/NamespaceList';
import MetricsStrip from '@/components/knowledge/MetricsStrip';

type ReadinessFilter = 'all' | 'profiled' | 'graph-ready' | 'needs-profile' | 'empty';
type MetricTone = 'blue' | 'green' | 'amber' | 'rose';

interface KnowledgeMetric {
  id: string;
  label: string;
  value: string;
  delta: string;
  description: string;
  tone: MetricTone;
}

const readinessLabels: Record<ReadinessFilter, string> = {
  all: 'All states',
  profiled: 'Profiled',
  'graph-ready': 'Graph ready',
  'needs-profile': 'Needs profile',
  empty: 'Empty',
};

const readinessStyles: Record<Exclude<ReadinessFilter, 'all'>, string> = {
  profiled: 'bg-emerald-500/10 text-emerald-700 border-emerald-200',
  'graph-ready': 'bg-blue-500/10 text-blue-700 border-blue-200',
  'needs-profile': 'bg-amber-500/10 text-amber-700 border-amber-200',
  empty: 'bg-slate-500/10 text-slate-600 border-slate-200',
};

const metricTones: Record<MetricTone, { background: string; color: string }> = {
  blue: {
    background: 'oklch(0.94 0.035 250)',
    color: 'oklch(0.38 0.16 252)',
  },
  green: {
    background: 'oklch(0.94 0.045 158)',
    color: 'oklch(0.42 0.13 158)',
  },
  amber: {
    background: 'oklch(0.95 0.052 82)',
    color: 'oklch(0.47 0.12 70)',
  },
  rose: {
    background: 'oklch(0.94 0.035 18)',
    color: 'oklch(0.44 0.14 18)',
  },
};

function formatCount(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toLocaleString();
}

function formatBytes(bytes: number): string {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** unitIndex).toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function relativeDate(value: string): string {
  const days = Math.round((new Date(value).getTime() - Date.now()) / 86_400_000);
  if (Math.abs(days) < 1) return 'today';
  return new Intl.RelativeTimeFormat('en', { numeric: 'auto' }).format(days, 'day');
}

function getReadiness(namespace: NamespaceMetaResponse): Exclude<ReadinessFilter, 'all'> {
  if (namespace.ontology_profile_version) return 'profiled';
  if (namespace.stats.entities > 0 || namespace.stats.relations > 0) return 'graph-ready';
  if (namespace.stats.files_indexed > 0 || namespace.stats.chunks > 0) return 'needs-profile';
  return 'empty';
}

function MetricCard({ metric, index }: { metric: KnowledgeMetric; index: number }) {
  const tone = metricTones[metric.tone];
  return (
    <article
      className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-[0_12px_36px_rgba(15,23,42,0.07)] transition duration-300 hover:-translate-y-1 hover:shadow-[0_18px_48px_rgba(15,23,42,0.1)]"
      style={{ animationDelay: `${index * 80}ms` }}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase text-[var(--color-text-muted)]">{metric.label}</p>
          <p className="mt-3 text-3xl font-black text-[var(--color-text-main)]">{metric.value}</p>
        </div>
        <span className="rounded-full px-3 py-1 text-xs font-bold" style={{ background: tone.background, color: tone.color }}>
          {metric.delta}
        </span>
      </div>
      <p className="mt-5 max-w-[30ch] text-sm leading-6 text-[var(--color-text-muted)]">{metric.description}</p>
    </article>
  );
}

function LoadingMetrics() {
  return (
    <div className="grid gap-5 lg:grid-cols-4">
      {Array.from({ length: 4 }).map((_, index) => (
        <div key={index} className="h-44 animate-pulse rounded-lg bg-[color-mix(in_oklch,var(--color-border),transparent_55%)]" />
      ))}
    </div>
  );
}

function ReadinessBadge({ state }: { state: Exclude<ReadinessFilter, 'all'> }) {
  return (
    <span className={`rounded-full border px-2.5 py-1 text-[11px] font-bold uppercase ${readinessStyles[state]}`}>
      {readinessLabels[state]}
    </span>
  );
}

/**
 * Global Knowledge homepage — card grid discovery view.
 *
 * Displays all namespaces in a searchable card grid.
 * Clicking any card navigates to `/knowledge/{name}` which opens
 * the master-detail layout with sidebar + Overview/Import/Query tabs.
 */
export default function KnowledgePage() {
  const router = useRouter();
  const addToast = useNotificationStore((state) => state.addToast);
  const [query, setQuery] = useState('');
  const [readiness, setReadiness] = useState<ReadinessFilter>('all');
  const [language, setLanguage] = useState('all');

  const {
    namespaces,
    isLoading,
    isError,
    createNamespace,
    refresh,
  } = useKnowledgeNamespaces();

  const allNamespaces = useMemo(() => namespaces ?? [], [namespaces]);

  const totals = useMemo(() => {
    return allNamespaces.reduce(
      (acc, namespace) => {
        acc.files += namespace.stats.files_indexed;
        acc.chunks += namespace.stats.chunks;
        acc.entities += namespace.stats.entities;
        acc.relations += namespace.stats.relations;
        acc.vectors += namespace.stats.vectors;
        acc.bytes += namespace.stats.bytes_on_disk;
        acc.runningImports += namespace.imports.filter((record) => record.status === 'running').length;
        if (namespace.ontology_profile_version) acc.profiled += 1;
        return acc;
      },
      { files: 0, chunks: 0, entities: 0, relations: 0, vectors: 0, bytes: 0, runningImports: 0, profiled: 0 },
    );
  }, [allNamespaces]);

  const languages = useMemo(() => {
    return ['all', ...Array.from(new Set(allNamespaces.map((namespace) => namespace.language).filter(Boolean))).sort()];
  }, [allNamespaces]);

  const filteredNamespaces = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return allNamespaces.filter((namespace) => {
      const state = getReadiness(namespace);
      const matchesQuery = !normalized || [
        namespace.name,
        namespace.description ?? '',
        namespace.embedding_model,
        namespace.ontology_profile_version ?? '',
      ].join(' ').toLowerCase().includes(normalized);

      return matchesQuery
        && (readiness === 'all' || state === readiness)
        && (language === 'all' || namespace.language === language);
    });
  }, [allNamespaces, language, query, readiness]);

  const recentNamespaces = useMemo(() => {
    return [...allNamespaces]
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
      .slice(0, 4);
  }, [allNamespaces]);

  const firstNamespace = filteredNamespaces[0] ?? allNamespaces[0];
  const ontologyHref = firstNamespace
    ? `/knowledge/${encodeURIComponent(firstNamespace.name)}?tab=ontology`
    : '#namespace-manager';

  const metrics: KnowledgeMetric[] = [
    {
      id: 'namespaces',
      label: 'Namespaces',
      value: formatCount(allNamespaces.length),
      delta: `${totals.runningImports} importing`,
      tone: 'blue',
      description: 'Active knowledge containers available for import, query, graph exploration, and ontology work.',
    },
    {
      id: 'documents',
      label: 'Indexed files',
      value: formatCount(totals.files),
      delta: `${formatCount(totals.chunks)} chunks`,
      tone: 'green',
      description: 'Documents and chunks already prepared for retrieval and graph extraction.',
    },
    {
      id: 'graph',
      label: 'Graph objects',
      value: formatCount(totals.entities + totals.relations),
      delta: `${formatCount(totals.vectors)} vectors`,
      tone: 'amber',
      description: 'Entities, relations, and embeddings that make the namespace queryable beyond raw files.',
    },
    {
      id: 'ontology',
      label: 'Profiled namespaces',
      value: `${totals.profiled} of ${allNamespaces.length}`,
      delta: formatBytes(totals.bytes),
      tone: 'rose',
      description: 'Namespaces with an active ontology profile version written into the namespace manifest.',
    },
  ];

  const handleSelectNamespace = useCallback((name: string) => {
    router.push(`/knowledge/${encodeURIComponent(name)}`);
  }, [router]);

  const handleCreateNamespace = useCallback(async (name: string, description?: string, language?: string) => {
    try {
      await createNamespace({ name, description, language });
      addToast({
        type: 'success',
        title: 'Namespace Created',
        message: `Namespace "${name}" has been created successfully.`,
        autoDismiss: true,
      });
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
      refresh();
      addToast({
        type: 'success',
        title: 'Namespace Deleted',
        message: `Namespace "${name}" has been deleted successfully.`,
        autoDismiss: true,
      });
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to delete namespace';
      addToast({
        type: 'error',
        title: 'Deletion Failed',
        message: errorMessage,
        autoDismiss: false,
      });
    }
  }, [refresh, addToast]);

  return (
    <div className="min-h-[calc(100dvh-56px)] overflow-auto bg-[var(--color-background)] px-5 py-6 md:px-8 lg:px-10">
      <section className="mx-auto flex w-full max-w-7xl flex-col gap-8">
        <header className="grid gap-6 border-b border-[var(--color-border)] pb-6 md:pb-8 lg:grid-cols-[1.1fr_0.9fr]">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-[var(--color-surface)] px-3 py-1.5 text-xs font-bold uppercase text-[var(--color-text-muted)]">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              Knowledge control room
            </div>
            <h1 className="mt-5 max-w-4xl text-3xl font-black leading-tight text-[var(--color-text-main)] md:text-4xl">
              Knowledge Base
            </h1>
            <p className="mt-5 max-w-2xl text-base leading-7 text-[var(--color-text-muted)] md:text-lg">
              Manage namespaces, import documents, and shape each graph with an ontology profile before agents rely on it.
            </p>
          </div>

          <div className="flex flex-col justify-between gap-5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
            <div>
              <p className="text-xs font-bold uppercase text-[var(--color-text-faint)]">Ontology profile path</p>
              <p className="mt-3 text-2xl font-black text-[var(--color-text-main)]">
                Start from the namespace, then tune the profile as the graph proves itself.
              </p>
            </div>
            <div className="grid gap-2 text-sm text-[var(--color-text-muted)]">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[18px] text-[var(--color-primary)]">dataset</span>
                Import source material into one namespace.
              </div>
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[18px] text-[var(--color-primary)]">schema</span>
                Seed or install the ontology profile.
              </div>
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[18px] text-[var(--color-primary)]">rule_settings</span>
                Review candidates and promote canonical terms.
              </div>
            </div>
            <div className="flex flex-wrap gap-3">
              <Link href={ontologyHref} className="rounded-full bg-[var(--color-text-main)] px-5 py-3 text-sm font-bold text-[var(--color-surface)] transition hover:-translate-y-0.5">
                Open ontology
              </Link>
              <Link href="#namespace-manager" className="rounded-full border border-[var(--color-border)] px-5 py-3 text-sm font-bold text-[var(--color-text-main)] transition hover:-translate-y-0.5">
                Manage namespaces
              </Link>
            </div>
          </div>
        </header>

        {isLoading && !namespaces ? <LoadingMetrics /> : (
          <div className="grid gap-5 lg:grid-cols-4">
            {metrics.map((metric, index) => <MetricCard key={metric.id} metric={metric} index={index} />)}
          </div>
        )}

        <section className="grid gap-5 lg:grid-cols-[0.95fr_1.05fr]">
          <article className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-[0_12px_36px_rgba(15,23,42,0.07)] md:p-6">
            <p className="text-xs font-bold uppercase text-[var(--color-text-muted)]">Ontology readiness</p>
            <h2 className="mt-2 text-xl font-black text-[var(--color-text-main)]">Profile coverage by namespace state</h2>
            <div className="mt-6 grid gap-3">
              {(['profiled', 'graph-ready', 'needs-profile', 'empty'] as const).map((state) => {
                const count = allNamespaces.filter((namespace) => getReadiness(namespace) === state).length;
                const percentage = allNamespaces.length ? Math.round((count / allNamespaces.length) * 100) : 0;
                return (
                  <div key={state}>
                    <div className="mb-1.5 flex items-center justify-between gap-3 text-xs font-bold text-[var(--color-text-muted)]">
                      <span>{readinessLabels[state]}</span>
                      <span>{count} namespace{count === 1 ? '' : 's'}</span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-[color-mix(in_oklch,var(--color-border),transparent_35%)]">
                      <div className="h-full rounded-full bg-[var(--color-primary)] transition-all duration-700" style={{ width: `${percentage}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </article>

          <article className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-[0_12px_36px_rgba(15,23,42,0.07)] md:p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-bold uppercase text-[var(--color-text-muted)]">Recent namespaces</p>
                <h2 className="mt-2 text-xl font-black text-[var(--color-text-main)]">Latest graph activity</h2>
              </div>
              <span className="material-symbols-outlined text-[var(--color-text-faint)]">hub</span>
            </div>
            <div className="mt-5 divide-y divide-[var(--color-border-light)]">
              {recentNamespaces.length > 0 ? recentNamespaces.map((namespace) => {
                const state = getReadiness(namespace);
                return (
                  <Link
                    key={namespace.name}
                    href={`/knowledge/${encodeURIComponent(namespace.name)}`}
                    className="flex items-center justify-between gap-4 py-3 transition hover:translate-x-1"
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate text-sm font-black text-[var(--color-text-main)]">{namespace.name}</p>
                        <ReadinessBadge state={state} />
                      </div>
                      <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                        {formatCount(namespace.stats.entities)} entities / {formatCount(namespace.stats.relations)} relations / updated {relativeDate(namespace.updated_at)}
                      </p>
                    </div>
                    <span className="material-symbols-outlined text-[18px] text-[var(--color-text-faint)]">arrow_forward</span>
                  </Link>
                );
              }) : (
                <div className="py-8 text-sm text-[var(--color-text-muted)]">Create a namespace to start building the knowledge layer.</div>
              )}
            </div>
          </article>
        </section>

        <section
          id="namespace-manager"
          data-testid="namespace-manager"
          className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[0_12px_36px_rgba(15,23,42,0.07)]"
        >
          <div className="grid gap-4 border-b border-[var(--color-border)] p-5 md:p-6">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-xs font-bold uppercase text-[var(--color-text-muted)]">Namespace portfolio</p>
                <h2 className="mt-2 text-xl font-black text-[var(--color-text-main)]">Filterable knowledge home</h2>
              </div>
              <label className="w-full max-w-md">
                <span className="sr-only">Search namespaces</span>
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search namespaces, descriptions, models..."
                  className="w-full rounded-full border border-[var(--color-border)] bg-[var(--color-background)] px-5 py-3 text-sm font-semibold text-[var(--color-text-main)] outline-none transition focus:border-[var(--color-primary)] focus:ring-4 focus:ring-blue-500/10"
                />
              </label>
            </div>

            <div className="flex flex-wrap gap-2" aria-label="Ontology readiness filters">
              {(Object.keys(readinessLabels) as ReadinessFilter[]).map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setReadiness(value)}
                  className={`rounded-full border px-3 py-2 text-sm font-bold transition hover:-translate-y-0.5 ${
                    readiness === value
                      ? 'border-[var(--color-text-main)] bg-[var(--color-text-main)] text-[var(--color-surface)]'
                      : 'border-[var(--color-border)] bg-[var(--color-background)] text-[var(--color-text-muted)]'
                  }`}
                >
                  {readinessLabels[value]}
                </button>
              ))}
            </div>

            <div className="flex flex-wrap gap-2" aria-label="Language filters">
              {languages.map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setLanguage(value)}
                  className={`rounded-full border px-3 py-2 text-sm font-bold transition hover:-translate-y-0.5 ${
                    language === value
                      ? 'border-[var(--color-primary)] bg-[var(--color-primary)] text-white'
                      : 'border-[var(--color-border)] bg-[var(--color-background)] text-[var(--color-text-muted)]'
                  }`}
                >
                  {value === 'all' ? 'All languages' : value}
                </button>
              ))}
            </div>

            {isError && (
              <div className="rounded-lg border border-red-200 bg-red-500/10 p-4 text-sm font-semibold text-red-700">
                Knowledge namespaces could not be loaded.
              </div>
            )}
          </div>

          <MetricsStrip className="m-5 md:m-6" />

          <NamespaceList
            namespaces={allNamespaces}
            visibleNamespaces={filteredNamespaces}
            selectedNamespace={null}
            onSelect={handleSelectNamespace}
            onCreate={handleCreateNamespace}
            onDelete={handleDeleteNamespace}
            isLoading={isLoading}
            onNamespaceUpdated={refresh}
          />
        </section>
      </section>
    </div>
  );
}
