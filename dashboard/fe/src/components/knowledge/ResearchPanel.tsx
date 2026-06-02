'use client';

import React, { useState, useCallback, useRef, useEffect } from 'react';
import {
  useResearchSearch,
  useResearchIngest,
  SearchResultItem,
  ResearchIngestItem,
  ResearchJobResult,
} from '@/hooks/use-knowledge-research';
import { useKnowledgeJob, JobStatusResponse } from '@/hooks/use-knowledge-import';

/* ── Constants ─────────────────────────────────────────────────────── */

const AVAILABLE_ENGINES = [
  { id: 'google', label: 'Google', icon: 'search' },
  { id: 'youtube', label: 'YouTube', icon: 'play_circle' },
  { id: 'github', label: 'GitHub', icon: 'code' },
  { id: 'bing', label: 'Bing', icon: 'language' },
  { id: 'duckduckgo', label: 'DuckDuckGo', icon: 'shield' },
  { id: 'wikipedia', label: 'Wikipedia', icon: 'menu_book' },
];

const AVAILABLE_CATEGORIES = [
  { id: 'general', label: 'General' },
  { id: 'it', label: 'IT' },
  { id: 'videos', label: 'Videos' },
  { id: 'science', label: 'Science' },
  { id: 'news', label: 'News' },
  { id: 'files', label: 'Files' },
];

const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'vi', label: 'Tiếng Việt' },
  { code: 'zh', label: '中文' },
  { code: 'ja', label: '日本語' },
  { code: 'de', label: 'Deutsch' },
  { code: 'es', label: 'Español' },
  { code: 'fr', label: 'Français' },
  { code: 'ko', label: '한국어' },
];

type PanelState = 'idle' | 'searching' | 'previewing' | 'ingesting' | 'complete';

/* ── Props ─────────────────────────────────────────────────────────── */

interface ResearchPanelProps {
  selectedNamespace: string | null;
  onJobStart?: () => void;
}

/* ── Main Component ────────────────────────────────────────────────── */

export default function ResearchPanel({ selectedNamespace, onJobStart }: ResearchPanelProps) {
  // State
  const [panelState, setPanelState] = useState<PanelState>('idle');
  const [query, setQuery] = useState('');
  const [selectedEngines, setSelectedEngines] = useState<string[]>([]);
  const [selectedCategories, setSelectedCategories] = useState<string[]>([]);
  const [maxResults, setMaxResults] = useState(10);
  const [language, setLanguage] = useState('en');
  const [summarize, setSummarize] = useState(true);
  const [selectedUrls, setSelectedUrls] = useState<Set<string>>(new Set());
  const [searchHistory, setSearchHistory] = useState<string[]>([]);

  // Hooks
  const { results, searchMeta, isSearching, searchError, search, clearResults } =
    useResearchSearch(selectedNamespace);
  const { jobId, isSubmitting, submitError, ingest, reset: resetIngest } =
    useResearchIngest(selectedNamespace);
  const { job: jobStatus, isError: jobPollError } = useKnowledgeJob(selectedNamespace, jobId);

  // Elapsed timer for searching
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const isJobComplete = Boolean(jobStatus && ['completed', 'failed'].includes(jobStatus.state));
  const activePanelState: PanelState = isJobComplete ? 'complete' : panelState;
  const completedResult = jobStatus?.state === 'completed' && jobStatus.result
    ? jobStatus.result as unknown as ResearchJobResult
    : null;

  // Track elapsed search time while the hook is actively searching.
  useEffect(() => {
    if (isSearching) {
      timerRef.current = setInterval(() => setElapsed(e => e + 0.1), 100);
    } else if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [isSearching]);

  // Handlers
  const handleSearch = useCallback(async () => {
    if (!query.trim()) return;
    setPanelState('searching');
    setElapsed(0);
    setSelectedUrls(new Set());
    try {
      const response = await search({
        query: query.trim(),
        engines: selectedEngines.length > 0 ? selectedEngines : undefined,
        categories: selectedCategories.length > 0 ? selectedCategories : undefined,
        max_results: maxResults,
        language,
      });
      setPanelState('previewing');
      setSelectedUrls(new Set(response.results.map(r => r.url)));
      // Add to history
      setSearchHistory(prev => {
        const updated = [query.trim(), ...prev.filter(q => q !== query.trim())];
        return updated.slice(0, 5);
      });
    } catch {
      // Error is captured in hook state
    }
  }, [query, selectedEngines, selectedCategories, maxResults, language, search]);

  const handleIngest = useCallback(async () => {
    const items: ResearchIngestItem[] = results
      .filter(r => selectedUrls.has(r.url))
      .map(r => ({
        url: r.url,
        title: r.title,
        engine: r.engine,
        snippet: r.snippet,
      }));

    if (items.length === 0) return;

    setPanelState('ingesting');
    try {
      await ingest(items, query, { summarize, language });
      onJobStart?.();
    } catch {
      // Error captured in hook state
    }
  }, [results, selectedUrls, query, summarize, language, ingest, onJobStart]);

  const handleNewSearch = useCallback(() => {
    setPanelState('idle');
    clearResults();
    resetIngest();
    setSelectedUrls(new Set());
    setQuery('');
  }, [clearResults, resetIngest]);

  const handleToggleUrl = useCallback((url: string) => {
    setSelectedUrls(prev => {
      const next = new Set(prev);
      if (next.has(url)) next.delete(url);
      else next.add(url);
      return next;
    });
  }, []);

  const handleSelectAll = useCallback(() => {
    setSelectedUrls(new Set(results.map(r => r.url)));
  }, [results]);

  const handleDeselectAll = useCallback(() => {
    setSelectedUrls(new Set());
  }, []);

  const toggleEngine = useCallback((id: string) => {
    setSelectedEngines(prev =>
      prev.includes(id) ? prev.filter(e => e !== id) : [...prev, id]
    );
  }, []);

  const toggleCategory = useCallback((id: string) => {
    setSelectedCategories(prev =>
      prev.includes(id) ? prev.filter(c => c !== id) : [...prev, id]
    );
  }, []);

  // No namespace selected
  if (!selectedNamespace) {
    return (
      <div className="h-full flex items-center justify-center p-8">
        <div className="text-center space-y-3">
          <span className="material-symbols-outlined text-[48px]" style={{ color: 'var(--color-text-muted)' }}>
            travel_explore
          </span>
          <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
            Select a namespace to start web research.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="shrink-0 px-5 py-4 border-b" style={{ borderColor: 'var(--color-border)' }}>
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-[20px]" style={{ color: 'var(--color-primary)' }}>
            travel_explore
          </span>
          <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>
            Web Research
          </h3>
          <span className="px-2 py-0.5 rounded-lg text-[10px] font-medium"
            style={{ background: 'var(--color-primary-muted)', color: 'var(--color-primary)' }}>
            {selectedNamespace}
          </span>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto px-5 py-4 space-y-4">
        {/* ─── Search Form ─────────────────────────────────────────── */}
        {(activePanelState === 'idle' || activePanelState === 'searching') && (
          <SearchForm
            query={query}
            onQueryChange={setQuery}
            selectedEngines={selectedEngines}
            onToggleEngine={toggleEngine}
            selectedCategories={selectedCategories}
            onToggleCategory={toggleCategory}
            maxResults={maxResults}
            onMaxResultsChange={setMaxResults}
            language={language}
            onLanguageChange={setLanguage}
            onSubmit={handleSearch}
            isSearching={isSearching}
            elapsed={elapsed}
            error={searchError}
            searchHistory={searchHistory}
            onHistoryClick={(q) => { setQuery(q); }}
          />
        )}

        {/* ─── Results Preview ─────────────────────────────────────── */}
        {activePanelState === 'previewing' && (
          <ResultsPreview
            results={results}
            searchMeta={searchMeta}
            selectedUrls={selectedUrls}
            onToggleUrl={handleToggleUrl}
            onSelectAll={handleSelectAll}
            onDeselectAll={handleDeselectAll}
            summarize={summarize}
            onSummarizeChange={setSummarize}
            onIngest={handleIngest}
            onNewSearch={handleNewSearch}
            isSubmitting={isSubmitting}
            submitError={submitError}
          />
        )}

        {/* ─── Ingest Progress ─────────────────────────────────────── */}
        {activePanelState === 'ingesting' && (
          jobPollError ? (
            <div className="space-y-4">
              <div className="flex items-center gap-2 p-3 rounded-lg border" style={{ borderColor: 'var(--color-danger)' }}>
                <span className="material-symbols-outlined text-[18px]" style={{ color: 'var(--color-danger)' }}>error</span>
                <div>
                  <p className="text-xs font-medium" style={{ color: 'var(--color-danger)' }}>Failed to check job status</p>
                  <p className="text-[11px] mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
                    The ingestion may still be running in the background.
                  </p>
                </div>
              </div>
              <button
                onClick={handleNewSearch}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors hover:bg-surface-hover"
                style={{ color: 'var(--color-primary)' }}
              >
                <span className="material-symbols-outlined text-[14px]">refresh</span>
                Start Over
              </button>
            </div>
          ) : jobStatus ? (
            <IngestProgress jobStatus={jobStatus} />
          ) : (
            <div className="flex items-center gap-3 p-4">
              <span className="w-5 h-5 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
              <span className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Submitting ingestion job...</span>
            </div>
          )
        )}

        {/* ─── Completed Results ───────────────────────────────────── */}
        {activePanelState === 'complete' && (
          <CompletedView
            jobStatus={jobStatus}
            result={completedResult}
            onNewSearch={handleNewSearch}
          />
        )}
      </div>
    </div>
  );
}

/* ── Search Form Sub-component ─────────────────────────────────────── */

function SearchForm({
  query,
  onQueryChange,
  selectedEngines,
  onToggleEngine,
  selectedCategories,
  onToggleCategory,
  maxResults,
  onMaxResultsChange,
  language,
  onLanguageChange,
  onSubmit,
  isSearching,
  elapsed,
  error,
  searchHistory,
  onHistoryClick,
}: {
  query: string;
  onQueryChange: (v: string) => void;
  selectedEngines: string[];
  onToggleEngine: (id: string) => void;
  selectedCategories: string[];
  onToggleCategory: (id: string) => void;
  maxResults: number;
  onMaxResultsChange: (v: number) => void;
  language: string;
  onLanguageChange: (v: string) => void;
  onSubmit: () => void;
  isSearching: boolean;
  elapsed: number;
  error: Error | null;
  searchHistory: string[];
  onHistoryClick: (q: string) => void;
}) {
  return (
    <div className="space-y-4">
      {/* Query Input */}
      <div>
        <div className="flex gap-2">
          <input
            type="text"
            value={query}
            onChange={e => onQueryChange(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !isSearching) onSubmit(); }}
            placeholder="What do you want to research?"
            disabled={isSearching}
            className="flex-1 px-3 py-2 rounded-lg border text-sm outline-none transition-colors focus:ring-2 focus:ring-primary/30"
            style={{
              background: 'var(--color-surface)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-main)',
            }}
          />
          <button
            onClick={onSubmit}
            disabled={!query.trim() || isSearching}
            className="px-4 py-2 rounded-lg text-sm font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              background: 'var(--color-primary)',
              color: 'white',
            }}
          >
            {isSearching ? (
              <span className="flex items-center gap-1.5">
                <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                {elapsed.toFixed(1)}s
              </span>
            ) : (
              <span className="flex items-center gap-1.5">
                <span className="material-symbols-outlined text-[16px]">search</span>
                Search
              </span>
            )}
          </button>
        </div>
      </div>

      {/* History chips */}
      {searchHistory.length > 0 && !isSearching && (
        <div className="flex flex-wrap gap-1.5">
          <span className="text-[10px] font-medium self-center mr-1" style={{ color: 'var(--color-text-muted)' }}>
            Recent:
          </span>
          {searchHistory.map(q => (
            <button
              key={q}
              onClick={() => onHistoryClick(q)}
              className="px-2 py-0.5 rounded-full text-[11px] font-medium transition-colors hover:opacity-80"
              style={{ background: 'var(--color-surface-hover)', color: 'var(--color-text-main)' }}
            >
              {q.length > 30 ? q.slice(0, 30) + '…' : q}
            </button>
          ))}
        </div>
      )}

      {/* Engines */}
      <div>
        <label className="text-[11px] font-medium mb-1.5 block" style={{ color: 'var(--color-text-muted)' }}>
          Engines (optional)
        </label>
        <div className="flex flex-wrap gap-1.5">
          {AVAILABLE_ENGINES.map(eng => {
            const active = selectedEngines.includes(eng.id);
            return (
              <button
                key={eng.id}
                onClick={() => onToggleEngine(eng.id)}
                disabled={isSearching}
                className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium transition-all border ${
                  active ? 'ring-1 ring-primary/40' : ''
                }`}
                style={{
                  background: active ? 'var(--color-primary-muted)' : 'var(--color-surface)',
                  borderColor: active ? 'var(--color-primary)' : 'var(--color-border)',
                  color: active ? 'var(--color-primary)' : 'var(--color-text-main)',
                }}
              >
                <span className="material-symbols-outlined text-[12px]">{eng.icon}</span>
                {eng.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Categories */}
      <div>
        <label className="text-[11px] font-medium mb-1.5 block" style={{ color: 'var(--color-text-muted)' }}>
          Categories (optional)
        </label>
        <div className="flex flex-wrap gap-1.5">
          {AVAILABLE_CATEGORIES.map(cat => {
            const active = selectedCategories.includes(cat.id);
            return (
              <button
                key={cat.id}
                onClick={() => onToggleCategory(cat.id)}
                disabled={isSearching}
                className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-all border ${
                  active ? 'ring-1 ring-primary/40' : ''
                }`}
                style={{
                  background: active ? 'var(--color-primary-muted)' : 'var(--color-surface)',
                  borderColor: active ? 'var(--color-primary)' : 'var(--color-border)',
                  color: active ? 'var(--color-primary)' : 'var(--color-text-main)',
                }}
              >
                {cat.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Max Results + Language row */}
      <div className="flex items-end gap-4">
        <div className="flex-1">
          <label className="text-[11px] font-medium mb-1.5 block" style={{ color: 'var(--color-text-muted)' }}>
            Max results: {maxResults}
          </label>
          <input
            type="range"
            min={1}
            max={50}
            value={maxResults}
            onChange={e => onMaxResultsChange(Number(e.target.value))}
            disabled={isSearching}
            className="w-full accent-primary"
          />
        </div>
        <div>
          <label className="text-[11px] font-medium mb-1.5 block" style={{ color: 'var(--color-text-muted)' }}>
            Language
          </label>
          <select
            value={language}
            onChange={e => onLanguageChange(e.target.value)}
            disabled={isSearching}
            className="px-2 py-1.5 rounded-lg border text-[11px] outline-none"
            style={{
              background: 'var(--color-surface)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-main)',
            }}
          >
            {LANGUAGES.map(l => (
              <option key={l.code} value={l.code}>{l.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-2 p-3 rounded-lg border" style={{ borderColor: 'var(--color-danger)', background: 'var(--color-danger)/10' }}>
          <span className="material-symbols-outlined text-[16px]" style={{ color: 'var(--color-danger)' }}>error</span>
          <div>
            <p className="text-xs font-medium" style={{ color: 'var(--color-danger)' }}>Search failed</p>
            <p className="text-[11px] mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
              {error.message.includes('fetch') || error.message.includes('ECONNREFUSED')
                ? 'SearXNG service is not available. Make sure it\'s running: docker compose -f docker-compose.searxng.yml up -d'
                : error.message}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Results Preview Sub-component ─────────────────────────────────── */

function ResultsPreview({
  results,
  searchMeta,
  selectedUrls,
  onToggleUrl,
  onSelectAll,
  onDeselectAll,
  summarize,
  onSummarizeChange,
  onIngest,
  onNewSearch,
  isSubmitting,
  submitError,
}: {
  results: SearchResultItem[];
  searchMeta: { query: string; elapsed_seconds: number; warnings: string[] } | null;
  selectedUrls: Set<string>;
  onToggleUrl: (url: string) => void;
  onSelectAll: () => void;
  onDeselectAll: () => void;
  summarize: boolean;
  onSummarizeChange: (v: boolean) => void;
  onIngest: () => void;
  onNewSearch: () => void;
  isSubmitting: boolean;
  submitError: Error | null;
}) {
  const selectedCount = selectedUrls.size;
  const allSelected = selectedCount === results.length;

  return (
    <div className="space-y-3">
      {/* Meta bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button
            onClick={onNewSearch}
            className="flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium transition-colors hover:bg-surface-hover"
            style={{ color: 'var(--color-text-muted)' }}
          >
            <span className="material-symbols-outlined text-[14px]">arrow_back</span>
            New Search
          </button>
          {searchMeta && (
            <span className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>
              {results.length} results in {searchMeta.elapsed_seconds.toFixed(1)}s
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={allSelected ? onDeselectAll : onSelectAll}
            className="text-[11px] font-medium px-2 py-1 rounded-lg transition-colors hover:bg-surface-hover"
            style={{ color: 'var(--color-primary)' }}
          >
            {allSelected ? 'Deselect All' : 'Select All'}
          </button>
        </div>
      </div>

      {/* Warnings */}
      {searchMeta?.warnings && searchMeta.warnings.length > 0 && (
        <div className="p-2 rounded-lg text-[11px]" style={{ background: 'var(--color-warning)/10', color: 'var(--color-warning)' }}>
          {searchMeta.warnings.join(', ')}
        </div>
      )}

      {/* Results list */}
      <div className="space-y-2 max-h-[400px] overflow-auto">
        {results.map(result => (
          <ResultCard
            key={result.url}
            result={result}
            selected={selectedUrls.has(result.url)}
            onToggle={() => onToggleUrl(result.url)}
          />
        ))}
      </div>

      {/* Empty results */}
      {results.length === 0 && (
        <div className="text-center py-8">
          <span className="material-symbols-outlined text-[32px]" style={{ color: 'var(--color-text-muted)' }}>
            search_off
          </span>
          <p className="text-xs mt-2" style={{ color: 'var(--color-text-muted)' }}>
            No results found. Try different keywords or engines.
          </p>
        </div>
      )}

      {/* Action bar */}
      {results.length > 0 && (
        <div className="flex items-center justify-between pt-3 border-t" style={{ borderColor: 'var(--color-border)' }}>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={summarize}
                onChange={e => onSummarizeChange(e.target.checked)}
                className="accent-primary w-3.5 h-3.5"
              />
              <span className="text-[11px] font-medium" style={{ color: 'var(--color-text-main)' }}>
                Generate summary
              </span>
            </label>
          </div>
          <button
            onClick={onIngest}
            disabled={selectedCount === 0 || isSubmitting}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ background: 'var(--color-primary)', color: 'white' }}
          >
            {isSubmitting ? (
              <>
                <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Submitting...
              </>
            ) : (
              <>
                <span className="material-symbols-outlined text-[14px]">download</span>
                Ingest Selected ({selectedCount})
              </>
            )}
          </button>
        </div>
      )}

      {/* Submit error */}
      {submitError && (
        <div className="flex items-start gap-2 p-3 rounded-lg border" style={{ borderColor: 'var(--color-danger)' }}>
          <span className="material-symbols-outlined text-[16px]" style={{ color: 'var(--color-danger)' }}>error</span>
          <p className="text-[11px]" style={{ color: 'var(--color-danger)' }}>{submitError.message}</p>
        </div>
      )}
    </div>
  );
}

/* ── Result Card ───────────────────────────────────────────────────── */

function ResultCard({
  result,
  selected,
  onToggle,
}: {
  result: SearchResultItem;
  selected: boolean;
  onToggle: () => void;
}) {
  const domain = (() => {
    try { return new URL(result.url).hostname.replace('www.', ''); }
    catch { return result.url; }
  })();

  return (
    <div
      className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-all ${
        selected ? 'ring-1 ring-primary/30' : ''
      }`}
      style={{
        background: selected ? 'var(--color-primary-muted)' : 'var(--color-surface)',
        borderColor: selected ? 'var(--color-primary)' : 'var(--color-border)',
      }}
      onClick={onToggle}
    >
      {/* Checkbox */}
      <input
        type="checkbox"
        checked={selected}
        onChange={onToggle}
        onClick={e => e.stopPropagation()}
        className="accent-primary w-4 h-4 mt-0.5 shrink-0"
      />

      {/* Thumbnail */}
      {result.thumbnail_url && (
        <img
          src={result.thumbnail_url}
          alt=""
          className="w-12 h-12 rounded-lg object-cover shrink-0"
          onError={e => { (e.target as HTMLImageElement).style.display = 'none'; }}
        />
      )}

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <h4 className="text-xs font-semibold truncate" style={{ color: 'var(--color-text-main)' }}>
            {result.title || domain}
          </h4>
          {result.engine && (
            <span className="shrink-0 px-1.5 py-0.5 rounded text-[9px] font-medium"
              style={{ background: 'var(--color-surface-hover)', color: 'var(--color-text-muted)' }}>
              {result.engine}
            </span>
          )}
        </div>
        <a
          href={result.url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={e => e.stopPropagation()}
          className="text-[10px] truncate block mt-0.5 hover:underline"
          style={{ color: 'var(--color-primary)' }}
        >
          {domain}
        </a>
        {result.snippet && (
          <p className="text-[11px] mt-1 line-clamp-2" style={{ color: 'var(--color-text-muted)' }}>
            {result.snippet}
          </p>
        )}
      </div>

      {/* Score indicator */}
      {result.score > 0 && (
        <div className="shrink-0 text-[9px] font-medium px-1.5 py-0.5 rounded"
          style={{ background: 'var(--color-surface-hover)', color: 'var(--color-text-muted)' }}>
          {result.score.toFixed(1)}
        </div>
      )}
    </div>
  );
}

/* ── Ingest Progress Sub-component ─────────────────────────────────── */

function IngestProgress({ jobStatus }: { jobStatus: JobStatusResponse }) {
  const progress = jobStatus.progress_total > 0
    ? Math.round((jobStatus.progress_current / jobStatus.progress_total) * 100)
    : 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-full flex items-center justify-center" style={{ background: 'var(--color-primary-muted)' }}>
          <span className="material-symbols-outlined text-[18px] animate-pulse" style={{ color: 'var(--color-primary)' }}>
            cloud_download
          </span>
        </div>
        <div>
          <p className="text-sm font-medium" style={{ color: 'var(--color-text-main)' }}>
            Fetching & Ingesting Sources
          </p>
          <p className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>
            {jobStatus.message || 'Processing...'}
          </p>
        </div>
      </div>

      {/* Progress bar */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-[10px] font-medium" style={{ color: 'var(--color-text-muted)' }}>
            {jobStatus.progress_current} / {jobStatus.progress_total} sources
          </span>
          <span className="text-[10px] font-medium" style={{ color: 'var(--color-primary)' }}>
            {progress}%
          </span>
        </div>
        <div className="h-2 rounded-full overflow-hidden" style={{ background: 'var(--color-surface-hover)' }}>
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{ width: `${progress}%`, background: 'var(--color-primary)' }}
          />
        </div>
      </div>

      <p className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
        You can navigate away — this job will continue in the background.
      </p>
    </div>
  );
}

/* ── Completed View Sub-component ──────────────────────────────────── */

function CompletedView({
  jobStatus,
  result,
  onNewSearch,
}: {
  jobStatus: JobStatusResponse | undefined;
  result: ResearchJobResult | null;
  onNewSearch: () => void;
}) {
  const isFailed = jobStatus?.state === 'failed';

  if (isFailed) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2 p-3 rounded-lg border" style={{ borderColor: 'var(--color-danger)' }}>
          <span className="material-symbols-outlined text-[18px]" style={{ color: 'var(--color-danger)' }}>error</span>
          <div>
            <p className="text-xs font-medium" style={{ color: 'var(--color-danger)' }}>Ingestion Failed</p>
            <p className="text-[11px] mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
              {jobStatus?.message || 'An unexpected error occurred during ingestion.'}
            </p>
          </div>
        </div>
        <button
          onClick={onNewSearch}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors hover:bg-surface-hover"
          style={{ color: 'var(--color-primary)' }}
        >
          <span className="material-symbols-outlined text-[14px]">refresh</span>
          Try Again
        </button>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="text-center py-8">
        <span className="material-symbols-outlined text-[32px] animate-spin" style={{ color: 'var(--color-primary)' }}>
          hourglass_top
        </span>
      </div>
    );
  }

  const ingested = result.sources.filter(s => s.status === 'ingested');
  const failed = result.sources.filter(s => s.status === 'error');
  const skipped = result.sources.filter(s => s.status === 'skipped');

  return (
    <div className="space-y-4">
      {/* Success header */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-full flex items-center justify-center" style={{ background: 'hsla(142, 71%, 45%, 0.15)' }}>
          <span className="material-symbols-outlined text-[18px]" style={{ color: 'var(--color-success)' }}>check_circle</span>
        </div>
        <div>
          <p className="text-sm font-medium" style={{ color: 'var(--color-text-main)' }}>Research Complete</p>
          <p className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>
            {ingested.length} sources ingested · {result.total_chunks_added} chunks · {result.total_entities_added} entities
          </p>
        </div>
      </div>

      {/* Stats pills */}
      <div className="flex flex-wrap gap-2">
        <StatPill icon="check_circle" label="Ingested" value={ingested.length} color="var(--color-success)" />
        {failed.length > 0 && <StatPill icon="error" label="Failed" value={failed.length} color="var(--color-danger)" />}
        {skipped.length > 0 && <StatPill icon="skip_next" label="Skipped" value={skipped.length} color="var(--color-text-muted)" />}
        <StatPill icon="data_array" label="Chunks" value={result.total_chunks_added} color="var(--color-primary)" />
        <StatPill icon="hub" label="Entities" value={result.total_entities_added} color="var(--color-primary)" />
      </div>

      {/* Summary */}
      {result.summary && (
        <div className="p-3 rounded-xl border" style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)' }}>
          <div className="flex items-center gap-1.5 mb-2">
            <span className="material-symbols-outlined text-[14px]" style={{ color: 'var(--color-primary)' }}>auto_awesome</span>
            <span className="text-[11px] font-semibold" style={{ color: 'var(--color-text-main)' }}>Summary</span>
          </div>
          <p className="text-xs leading-relaxed whitespace-pre-wrap" style={{ color: 'var(--color-text-main)' }}>
            {result.summary}
          </p>
        </div>
      )}

      {/* Source list */}
      <div>
        <h4 className="text-[11px] font-semibold mb-2" style={{ color: 'var(--color-text-muted)' }}>
          Sources ({result.sources.length})
        </h4>
        <div className="space-y-1.5 max-h-[250px] overflow-auto">
          {result.sources.map(src => (
            <SourceResultRow key={src.url} source={src} />
          ))}
        </div>
      </div>

      {/* Action */}
      <div className="pt-3 border-t" style={{ borderColor: 'var(--color-border)' }}>
        <button
          onClick={onNewSearch}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-medium transition-all"
          style={{ background: 'var(--color-primary)', color: 'white' }}
        >
          <span className="material-symbols-outlined text-[14px]">search</span>
          New Research
        </button>
      </div>
    </div>
  );
}

/* ── Shared small components ───────────────────────────────────────── */

function StatPill({ icon, label, value, color }: { icon: string; label: string; value: number; color: string }) {
  return (
    <div className="flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-medium"
      style={{ background: 'var(--color-surface-hover)', color }}>
      <span className="material-symbols-outlined text-[12px]">{icon}</span>
      {label}: {value}
    </div>
  );
}

function SourceResultRow({ source }: { source: ResearchJobResult['sources'][number] }) {
  const statusConfig: Record<string, { icon: string; color: string }> = {
    ingested: { icon: 'check_circle', color: 'var(--color-success)' },
    error: { icon: 'error', color: 'var(--color-danger)' },
    skipped: { icon: 'skip_next', color: 'var(--color-text-muted)' },
    fetched: { icon: 'download_done', color: 'var(--color-primary)' },
  };
  const cfg = statusConfig[source.status] || statusConfig.skipped;

  const domain = (() => {
    try { return new URL(source.url).hostname.replace('www.', ''); }
    catch { return source.url; }
  })();

  return (
    <div className="flex items-center gap-2 p-2 rounded-lg" style={{ background: 'var(--color-surface)' }}>
      <span className="material-symbols-outlined text-[14px]" style={{ color: cfg.color }}>{cfg.icon}</span>
      <div className="flex-1 min-w-0">
        <p className="text-[11px] font-medium truncate" style={{ color: 'var(--color-text-main)' }}>
          {source.title || domain}
        </p>
        {source.error && (
          <p className="text-[10px] truncate" style={{ color: 'var(--color-danger)' }}>{source.error}</p>
        )}
      </div>
      {source.chunks_added > 0 && (
        <span className="text-[9px] font-medium px-1.5 py-0.5 rounded" style={{ background: 'var(--color-surface-hover)', color: 'var(--color-text-muted)' }}>
          {source.chunks_added} chunks
        </span>
      )}
    </div>
  );
}
