'use client';

import React, { useState, useCallback, useRef, useEffect } from 'react';
import { NamespaceMetaResponse } from '@/hooks/use-knowledge-namespaces';
import { QueryResultResponse } from '@/hooks/use-knowledge-query';
import { GraphCountsResponse, JobStatusResponse } from '@/hooks/use-knowledge-import';
import BacklinkBadge from './BacklinkBadge';
import AnswerMarkdown from './AnswerMarkdown';
import { getNodeColor } from './constants';

/* ── Helpers ───────────────────────────────────────────────────────── */

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch { return iso; }
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
  } catch { return iso; }
}

const LANGUAGE_META: Record<string, { flag: string; native: string }> = {
  English:    { flag: '🇬🇧', native: 'English' },
  Vietnamese: { flag: '🇻🇳', native: 'Tiếng Việt' },
  Chinese:    { flag: '🇨🇳', native: '中文' },
  Spanish:    { flag: '🇪🇸', native: 'Español' },
};

function getLanguageDisplay(lang: string): { flag: string; label: string } {
  const meta = LANGUAGE_META[lang];
  if (meta) return { flag: meta.flag, label: meta.native };
  return { flag: '🌐', label: lang };
}

/* ── Props ─────────────────────────────────────────────────────────── */

interface NamespaceOverviewProps {
  namespace: NamespaceMetaResponse;
  graphCounts?: GraphCountsResponse;
  activeJob?: JobStatusResponse;
  onNavigateImport: () => void;
  onNavigateResearch: () => void;
  onNavigateQuery: () => void;
  onDelete: () => void;
  onRefresh: () => void;
  queryResult?: QueryResultResponse | null;
  queryLoading?: boolean;
  queryError?: Error | null;
  onExecuteQuery?: (query: string, mode: 'raw' | 'graph' | 'summarized', topK: number) => Promise<void>;
  onClearResult?: () => void;
  onNoteClick?: (noteId: string) => void;
}

/* ── Session history entry ─────────────────────────────────────────── */

interface HistoryEntry {
  query: string;
  timestamp: number;
}

/* ── Stat Pill ─────────────────────────────────────────────────────── */

function StatPill({ icon, label, value, color }: {
  icon: string; label: string; value: string | number; color: string;
}) {
  return (
    <div
      className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium"
      style={{ background: `${color}10`, color }}
    >
      <span className="material-symbols-outlined" style={{ fontSize: 13 }}>{icon}</span>
      <span>{typeof value === 'number' ? value.toLocaleString() : value}</span>
      <span style={{ opacity: 0.7 }}>{label}</span>
    </div>
  );
}

/* ── Suggestion Chip ──────────────────────────────────────────────── */

function SuggestionChip({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="px-3 py-1.5 rounded-full text-[11px] font-medium border transition-all duration-200 hover:shadow-sm"
      style={{
        borderColor: 'var(--color-border)',
        color: 'var(--color-text-muted)',
        background: 'var(--color-surface)',
      }}
    >
      {label}
    </button>
  );
}

/* ── Result Chunk Card ─────────────────────────────────────────────── */

function ChunkCard({ chunk, namespace, onNoteClick }: {
  chunk: QueryResultResponse['chunks'][number];
  namespace: string;
  onNoteClick?: (noteId: string) => void;
}) {
  return (
    <div
      className="rounded-xl border p-3.5 transition-all duration-150 hover:shadow-sm"
      style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined" style={{ fontSize: 14, color: 'var(--color-text-faint)' }}>
            description
          </span>
          <span className="text-[11px] font-medium" style={{ color: 'var(--color-text-muted)' }}>
            {chunk.filename}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {chunk.memory_links && chunk.memory_links.length > 0 && (
            <BacklinkBadge memoryLinks={chunk.memory_links} namespace={namespace} onNoteClick={onNoteClick} />
          )}
          <span
            className="px-1.5 py-0.5 rounded-md text-[10px] font-bold"
            style={{ background: 'var(--color-primary-muted)', color: 'var(--color-primary)' }}
          >
            {chunk.score.toFixed(2)}
          </span>
        </div>
      </div>
      <p className="text-xs leading-relaxed" style={{ color: 'var(--color-text-main)' }}>
        {chunk.text.slice(0, 300)}{chunk.text.length > 300 ? '…' : ''}
      </p>
    </div>
  );
}

/* ── Session History Item ──────────────────────────────────────────── */

function HistoryItem({ entry, isActive, onClick }: {
  entry: HistoryEntry; isActive: boolean; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="w-full text-left px-3 py-2.5 rounded-lg transition-all duration-150 group"
      style={{
        background: isActive ? 'var(--color-primary-muted)' : 'transparent',
        borderLeft: isActive ? '2px solid var(--color-primary)' : '2px solid transparent',
      }}
    >
      <p className="text-[12px] font-medium truncate" style={{
        color: isActive ? 'var(--color-primary)' : 'var(--color-text-main)',
      }}>
        {entry.query}
      </p>
      <p className="text-[10px] mt-0.5" style={{ color: 'var(--color-text-faint)' }}>
        {formatRelativeTime(new Date(entry.timestamp).toISOString())}
      </p>
    </button>
  );
}

/* ══════════════════════════════════════════════════════════════════════
   Main Component — Query-First Two-Column Layout
   ══════════════════════════════════════════════════════════════════════ */

export default function NamespaceOverview({
  namespace: ns,
  graphCounts,
  activeJob,
  onNavigateImport,
  onNavigateResearch,
  onNavigateQuery,
  onDelete,
  onRefresh,
  queryResult,
  queryLoading = false,
  queryError,
  onExecuteQuery,
  onClearResult,
  onNoteClick,
}: NamespaceOverviewProps) {
  const { stats } = ns;
  const hasContent = stats.files_indexed > 0 || stats.chunks > 0;

  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<'raw' | 'graph' | 'summarized'>('summarized');
  const [topK] = useState(10);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [activeHistoryIdx, setActiveHistoryIdx] = useState<number>(-1);
  const inputRef = useRef<HTMLInputElement>(null);

  // Live counts — use the higher of KuzuDB live counts vs manifest stats.
  // KuzuDB may report 0 when chunks exist only in the vector store (e.g.
  // embedding failures prevent graph persistence but chunks are still tracked
  // in the manifest).
  const entityCount = Math.max(graphCounts?.entities ?? 0, stats.entities);
  const chunkCount = Math.max(graphCounts?.chunks ?? 0, stats.chunks);
  const relationCount = Math.max(graphCounts?.relations ?? 0, stats.relations);

  // Reset local state when namespace changes
  const [prevNamespace, setPrevNamespace] = useState(ns.name);
  if (ns.name !== prevNamespace) {
    setPrevNamespace(ns.name);
    setQuery('');
    setHistory([]);
    setActiveHistoryIdx(-1);
  }

  useEffect(() => {
    if (hasContent) {
      const t = setTimeout(() => inputRef.current?.focus(), 300);
      return () => clearTimeout(t);
    }
  }, [hasContent]);

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim() || !onExecuteQuery) return;
    const q = query.trim();
    setHistory(prev => [{ query: q, timestamp: Date.now() }, ...prev]);
    setActiveHistoryIdx(0);
    await onExecuteQuery(q, mode, topK);
  }, [query, mode, topK, onExecuteQuery]);

  const handleSuggestion = useCallback((text: string) => {
    setQuery(text);
    if (onExecuteQuery) {
      setHistory(prev => [{ query: text, timestamp: Date.now() }, ...prev]);
      setActiveHistoryIdx(0);
      onExecuteQuery(text, mode, topK);
    }
  }, [mode, topK, onExecuteQuery]);

  const handleHistoryClick = useCallback((idx: number) => {
    const entry = history[idx];
    if (!entry || !onExecuteQuery) return;
    setQuery(entry.query);
    setActiveHistoryIdx(idx);
    onExecuteQuery(entry.query, mode, topK);
  }, [history, mode, topK, onExecuteQuery]);

  const suggestions = [
    `Summarize key themes in ${ns.name}`,
    'What are the main topics covered?',
    'Find the most important entities',
  ];

  const hasWarning = queryResult?.warnings?.includes('llm_unavailable');
  const showHistory = history.length > 0;

  return (
    <div className="h-full overflow-y-auto" style={{ scrollbarWidth: 'thin' }}>
      {/* ── Hero Section ─────────────────────────────────────────── */}
      <div
        className="px-6 pt-6 pb-5"
        style={{
          background: 'linear-gradient(180deg, var(--color-primary-muted) 0%, var(--color-background) 100%)',
        }}
      >
        {/* Header row */}
        <div className="flex items-start justify-between mb-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2.5 mb-1.5">
              <h2 className="text-xl font-bold truncate" style={{ color: 'var(--color-text-main)' }}>
                {ns.name}
              </h2>
              <span
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-semibold tracking-wide shrink-0"
                style={{ background: 'var(--color-primary-muted)', color: 'var(--color-primary)' }}
              >
                <span className="text-sm leading-none">{getLanguageDisplay(ns.language).flag}</span>
                {getLanguageDisplay(ns.language).label}
              </span>
            </div>
            {ns.description && (
              <p className="text-sm mb-2" style={{ color: 'var(--color-text-muted)' }}>{ns.description}</p>
            )}
            <div className="flex items-center gap-3 text-[11px]" style={{ color: 'var(--color-text-faint)' }}>
              <span>Created {formatDate(ns.created_at)}</span>
              <span>·</span>
              <span>Updated {formatRelativeTime(ns.updated_at)}</span>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={onNavigateImport}
              className="p-2 rounded-lg hover:bg-white/50 transition-colors shrink-0"
              aria-label="Import documents" title="Import Documents"
            >
              <span className="material-symbols-outlined" style={{ fontSize: 18, color: 'var(--color-text-muted)' }}>upload</span>
            </button>
            <button
              onClick={onNavigateResearch}
              className="p-2 rounded-lg hover:bg-white/50 transition-colors shrink-0"
              aria-label="Web research" title="Web Research"
            >
              <span className="material-symbols-outlined" style={{ fontSize: 18, color: 'var(--color-text-muted)' }}>travel_explore</span>
            </button>
            <button
              onClick={onRefresh}
              className="p-2 rounded-lg hover:bg-white/50 transition-colors shrink-0"
              aria-label="Refresh namespace" title="Refresh"
            >
              <span className="material-symbols-outlined" style={{ fontSize: 18, color: 'var(--color-text-muted)' }}>refresh</span>
            </button>
            <button
              onClick={onDelete}
              className="p-2 rounded-lg hover:bg-white/50 transition-colors shrink-0"
              aria-label="Delete namespace" title="Delete Namespace"
            >
              <span className="material-symbols-outlined" style={{ fontSize: 18, color: 'var(--color-danger, #ef4444)' }}>delete</span>
            </button>
          </div>
        </div>

        {/* Stat pills — live from KuzuDB */}
        <div className="flex flex-wrap gap-2 mb-5">
          <StatPill icon="description" label="Files" value={stats.files_indexed} color="#3B82F6" />
          <StatPill icon="dataset" label="Chunks" value={chunkCount} color="#8B5CF6" />
          <StatPill icon="hub" label="Entities" value={entityCount} color="#EC4899" />
          <StatPill icon="link" label="Relations" value={relationCount} color="#F59E0B" />
        </div>

        {/* Active job banner */}
        {activeJob && (
          <div className="flex items-center gap-3 px-4 py-3 mb-5 rounded-xl border" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
            <span className="material-symbols-outlined animate-spin" style={{ fontSize: 18, color: 'var(--color-primary)' }}>progress_activity</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between text-sm mb-1">
                <span style={{ color: 'var(--color-text)' }}>
                  {activeJob.operation === 'research_ingest' ? 'Web research' : 'Importing'} in progress…
                </span>
                {activeJob.progress_total > 0 && (
                  <span style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
                    {activeJob.progress_current}/{activeJob.progress_total}
                  </span>
                )}
              </div>
              <div className="w-full h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--color-border)' }}>
                <div
                  className="h-full rounded-full transition-all duration-300"
                  style={{
                    width: activeJob.progress_total > 0 ? `${Math.round((activeJob.progress_current / activeJob.progress_total) * 100)}%` : '30%',
                    background: 'var(--color-primary)',
                    ...(activeJob.progress_total === 0 ? { animation: 'pulse 1.5s ease-in-out infinite' } : {}),
                  }}
                />
              </div>
              {activeJob.message && (
                <p className="text-xs mt-1 truncate" style={{ color: 'var(--color-text-muted)' }}>{activeJob.message}</p>
              )}
            </div>
          </div>
        )}

        {/* ── Hero Search ──────────────────────────────────────── */}
        {hasContent && onExecuteQuery ? (
          <form onSubmit={handleSubmit}>
            <div
              className="flex items-center gap-3 px-4 py-3 rounded-2xl border shadow-sm transition-shadow focus-within:shadow-md focus-within:border-primary/40"
              style={{
                background: 'var(--color-surface)',
                borderColor: 'var(--color-border)',
              }}
            >
              <span className="material-symbols-outlined shrink-0" style={{ fontSize: 22, color: 'var(--color-primary)' }}>
                search
              </span>
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Ask anything about this knowledge base…"
                className="flex-1 text-sm bg-transparent outline-none"
                style={{ color: 'var(--color-text-main)' }}
              />
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value as 'raw' | 'graph' | 'summarized')}
                className="px-2 py-1 rounded-lg border text-[11px] font-medium shrink-0"
                style={{
                  background: 'var(--color-background)',
                  borderColor: 'var(--color-border)',
                  color: 'var(--color-text-muted)',
                }}
              >
                <option value="summarized">Summarized</option>
                <option value="graph">Graph</option>
                <option value="raw">Raw</option>
              </select>
              <button
                type="submit"
                disabled={queryLoading || !query.trim()}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold text-white transition-all duration-200 disabled:opacity-40 shrink-0"
                style={{ background: 'var(--color-primary)' }}
              >
                {queryLoading ? (
                  <span className="material-symbols-outlined animate-spin text-[16px]">progress_activity</span>
                ) : (
                  <span className="material-symbols-outlined text-[16px]">send</span>
                )}
                {queryLoading ? 'Searching…' : 'Ask'}
              </button>
            </div>

            {/* Suggestion chips — only when no result and no history */}
            {!queryResult && !showHistory && (
              <div className="flex flex-wrap gap-2 mt-3">
                {suggestions.map((s, i) => (
                  <SuggestionChip key={i} label={s} onClick={() => handleSuggestion(s)} />
                ))}
              </div>
            )}
          </form>
        ) : !hasContent ? (
          <div
            className="rounded-2xl border-2 border-dashed p-6 text-center"
            style={{ borderColor: 'var(--color-border)' }}
          >
            <span className="material-symbols-outlined text-[32px] mb-2" style={{ color: 'var(--color-text-muted)' }}>
              upload_file
            </span>
            <p className="text-sm font-medium mb-1" style={{ color: 'var(--color-text-main)' }}>
              This namespace is empty
            </p>
            <p className="text-xs mb-3" style={{ color: 'var(--color-text-muted)' }}>
              Import documents to start querying your knowledge base.
            </p>
            <button
              onClick={onNavigateImport}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold text-white transition-colors"
              style={{ background: 'var(--color-primary)' }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: 16 }}>upload</span>
              Import Documents
            </button>
          </div>
        ) : null}
      </div>

      {/* ── Two-Column Content Area ─────────────────────────────── */}
      <div className="px-6 pb-6">
        {/* Error */}
        {queryError && (
          <div className="p-4 rounded-xl text-sm mb-4" style={{ background: 'var(--color-danger-muted)', color: 'var(--color-danger)' }}>
            <p className="font-semibold mb-1">Query Error</p>
            <p>{queryError.message}</p>
          </div>
        )}

        <div className="flex gap-4" style={{ minHeight: showHistory || queryResult ? 400 : 'auto' }}>
          {/* ── Left: Session History ──────────────────────────── */}
          {showHistory && (
            <div
              className="w-[240px] shrink-0 rounded-xl border overflow-hidden self-start"
              style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)' }}
            >
              <div className="px-3 py-2.5 border-b flex items-center justify-between" style={{ borderColor: 'var(--color-border)' }}>
                <div className="flex items-center gap-1.5">
                  <span className="material-symbols-outlined" style={{ fontSize: 14, color: 'var(--color-text-muted)' }}>history</span>
                  <h4 className="text-xs font-semibold" style={{ color: 'var(--color-text-main)' }}>Session History</h4>
                </div>
                <span className="text-[10px] px-1.5 py-0.5 rounded-full" style={{ background: 'var(--color-background)', color: 'var(--color-text-faint)' }}>
                  {history.length}
                </span>
              </div>
              <div className="p-1.5 space-y-0.5 max-h-[500px] overflow-y-auto" style={{ scrollbarWidth: 'thin' }}>
                {history.map((entry, i) => (
                  <HistoryItem
                    key={entry.timestamp}
                    entry={entry}
                    isActive={i === activeHistoryIdx}
                    onClick={() => handleHistoryClick(i)}
                  />
                ))}
              </div>
            </div>
          )}

          {/* ── Right: Results Panel ──────────────────────────── */}
          <div className="flex-1 min-w-0 space-y-4">
            {/* Pre-query: show graph + suggestions */}
            {!queryResult && hasContent && !showHistory && (
              <div
                className="rounded-xl border p-6 flex flex-col items-center justify-center text-center transition-shadow hover:shadow-md cursor-pointer group"
                style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)' }}
                onClick={onNavigateQuery}
              >
                <div className="w-12 h-12 rounded-full flex items-center justify-center mb-3 group-hover:scale-110 transition-transform" style={{ background: 'var(--color-primary-muted)', color: 'var(--color-primary)' }}>
                  <span className="material-symbols-outlined text-[24px]">hub</span>
                </div>
                <h3 className="text-sm font-semibold mb-1" style={{ color: 'var(--color-text-main)' }}>Explore Knowledge Graph</h3>
                <p className="text-xs max-w-sm" style={{ color: 'var(--color-text-muted)' }}>
                  Dive into the interactive 3D Nexus Explorer to visualize relationships, discover communities, and trace paths between entities.
                </p>
                <button className="mt-4 px-4 py-2 rounded-lg text-xs font-semibold text-white transition-colors" style={{ background: 'var(--color-primary)' }}>
                  Open Nexus
                </button>
              </div>
            )}

            {/* Post-query results: Answer → Graph → Chunks → Entities */}
            {queryResult && (
              <>
                {/* Results header */}
                <div className="flex items-center justify-between pt-1">
                  <div className="flex items-center gap-3">
                    <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>Results</h3>
                    <span className="text-[10px]" style={{ color: 'var(--color-text-faint)' }}>
                      {queryResult.chunks.length} chunks · {queryResult.latency_ms}ms
                    </span>
                  </div>
                  <button
                    onClick={onClearResult}
                    className="text-[11px] font-medium px-2.5 py-1 rounded-lg hover:bg-surface-hover transition-colors"
                    style={{ color: 'var(--color-text-muted)' }}
                  >
                    Clear
                  </button>
                </div>

                {/* LLM warning */}
                {hasWarning && mode === 'summarized' && (
                  <div className="p-3 rounded-xl text-sm flex items-start gap-2"
                    style={{ background: 'var(--color-warning-muted)', color: 'var(--color-warning)' }}>
                    <span className="material-symbols-outlined text-[18px]">warning</span>
                    <div>
                      <p className="font-medium text-xs">LLM Not Configured</p>
                      <p className="text-[11px] mt-0.5">Summarized mode requires an LLM. Showing graph results instead.</p>
                    </div>
                  </div>
                )}

                {/* 1. Answer */}
                {queryResult.answer && (
                  <div className="rounded-xl border p-4" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
                    <div className="flex items-center gap-2 mb-2">
                      <span className="material-symbols-outlined" style={{ fontSize: 16, color: 'var(--color-primary)' }}>auto_awesome</span>
                      <h4 className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--color-primary)' }}>Answer</h4>
                    </div>
                    <AnswerMarkdown content={queryResult.answer} />
                  </div>
                )}

                {/* 2. Knowledge Graph (inline in results) */}
                {hasContent && (
                  <div
                    className="rounded-xl border p-4 flex items-center justify-between transition-colors hover:bg-surface-hover cursor-pointer"
                    style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)' }}
                    onClick={onNavigateQuery}
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-full flex items-center justify-center shrink-0" style={{ background: 'var(--color-primary-muted)', color: 'var(--color-primary)' }}>
                        <span className="material-symbols-outlined text-[20px]">hub</span>
                      </div>
                      <div>
                        <h4 className="text-xs font-semibold" style={{ color: 'var(--color-text-main)' }}>Explore these results visually</h4>
                        <p className="text-[11px] mt-0.5" style={{ color: 'var(--color-text-muted)' }}>Open Nexus to see how these entities connect</p>
                      </div>
                    </div>
                    <span className="material-symbols-outlined" style={{ color: 'var(--color-text-muted)', fontSize: 20 }}>arrow_forward</span>
                  </div>
                )}

                {/* 3. Relevant Chunks */}
                {queryResult.chunks.length > 0 && (
                  <div>
                    <h4 className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-muted)' }}>
                      Relevant Sources ({queryResult.chunks.length})
                    </h4>
                    <div className="space-y-2">
                      {queryResult.chunks.slice(0, 5).map((chunk, i) => (
                        <ChunkCard key={i} chunk={chunk} namespace={queryResult.namespace} onNoteClick={onNoteClick} />
                      ))}
                      {queryResult.chunks.length > 5 && (
                        <p className="text-xs text-center py-2" style={{ color: 'var(--color-text-muted)' }}>
                          +{queryResult.chunks.length - 5} more sources
                        </p>
                      )}
                    </div>
                  </div>
                )}

                {/* 4. Entity Tags */}
                {queryResult.entities.length > 0 && (
                  <div>
                    <h4 className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-muted)' }}>
                      Relevant Entity Tags ({queryResult.entities.length})
                    </h4>
                    <div className="flex flex-wrap gap-1.5">
                      {queryResult.entities.map((entity, i) => (
                        <span key={i} className="px-2 py-1 rounded-lg text-[11px] font-medium"
                          style={{
                            background: `${getNodeColor(entity.label)}15`,
                            color: getNodeColor(entity.label),
                            border: `1px solid ${getNodeColor(entity.label)}30`,
                          }}>
                          {entity.name}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
