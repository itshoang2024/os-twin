/**
 * Hooks for Knowledge research API (two-step async flow).
 *
 * Endpoints:
 * - POST /api/knowledge/namespaces/{namespace}/research/search -> ResearchSearchResponse
 * - POST /api/knowledge/namespaces/{namespace}/research/ingest -> ResearchIngestJobResponse
 * - GET  /api/knowledge/namespaces/{namespace}/jobs/{job_id}   -> JobStatusResponse (polling)
 */

import { useState, useCallback } from 'react';
import { apiPost } from '@/lib/api-client';

// ── Types ─────────────────────────────────────────────────────────────────

export interface SearchResultItem {
  title: string;
  url: string;
  snippet: string;
  engine: string;
  score: number;
  thumbnail_url: string;
  metadata: Record<string, unknown>;
}

export interface ResearchSearchResponse {
  query: string;
  engines_used: string[];
  categories_used: string[];
  results: SearchResultItem[];
  elapsed_seconds: number;
  warnings: string[];
}

export interface ResearchIngestItem {
  url: string;
  title: string;
  engine: string;
  snippet: string;
}

export interface ResearchIngestJobResponse {
  job_id: string;
  namespace: string;
  status: string;
  message: string;
}

export interface ResearchSourceResult {
  url: string;
  title: string;
  engine: string;
  status: string;
  chunks_added: number;
  error: string | null;
}

export interface ResearchJobResult {
  query: string;
  namespace: string;
  engines_used: string[];
  categories_used: string[];
  sources: ResearchSourceResult[];
  total_chunks_added: number;
  total_entities_added: number;
  total_relations_added: number;
  summary: string | null;
  warnings: string[];
}

// ── Constants ─────────────────────────────────────────────────────────────

const KNOWLEDGE_BASE = '/knowledge';

// ── Search Hook ───────────────────────────────────────────────────────────

export interface UseResearchSearchParams {
  query: string;
  engines?: string[];
  categories?: string[];
  max_results?: number;
  language?: string;
}

/**
 * Hook for step 1: search SearXNG and get preview results.
 * Fast (~1-2s), no ingestion happens.
 */
export function useResearchSearch(namespace: string | null) {
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [searchMeta, setSearchMeta] = useState<{
    query: string;
    elapsed_seconds: number;
    warnings: string[];
  } | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState<Error | null>(null);

  const search = useCallback(async (params: UseResearchSearchParams) => {
    if (!namespace) {
      throw new Error('Namespace is required');
    }

    setIsSearching(true);
    setSearchError(null);

    try {
      const raw = await apiPost<ResearchSearchResponse | SearchResultItem[]>(
        `${KNOWLEDGE_BASE}/namespaces/${namespace}/research/search`,
        {
          query: params.query,
          engines: params.engines || null,
          categories: params.categories || null,
          max_results: params.max_results ?? 10,
          language: params.language ?? 'en',
        }
      );
      // api-client auto-unwraps responses with a "results" key into the bare array
      const response: ResearchSearchResponse = Array.isArray(raw)
        ? { results: raw, query: params.query, elapsed_seconds: 0, warnings: [], engines_used: params.engines || [], categories_used: params.categories || [] }
        : (raw as ResearchSearchResponse);
      setResults(response.results);
      setSearchMeta({
        query: response.query,
        elapsed_seconds: response.elapsed_seconds,
        warnings: response.warnings ?? [],
      });
      return response;
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      setSearchError(error);
      throw error;
    } finally {
      setIsSearching(false);
    }
  }, [namespace]);

  const clearResults = useCallback(() => {
    setResults([]);
    setSearchMeta(null);
    setSearchError(null);
  }, []);

  return {
    results,
    searchMeta,
    isSearching,
    searchError,
    search,
    clearResults,
  };
}

// ── Ingest Hook ───────────────────────────────────────────────────────────

/**
 * Hook for step 2: submit selected items for async fetch + ingest.
 * Returns a job_id immediately; use useKnowledgeJob() to poll progress.
 */
export function useResearchIngest(namespace: string | null) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<Error | null>(null);

  const ingest = useCallback(async (
    items: ResearchIngestItem[],
    query: string,
    options?: { summarize?: boolean; language?: string },
  ) => {
    if (!namespace) {
      throw new Error('Namespace is required');
    }

    setIsSubmitting(true);
    setSubmitError(null);

    try {
      const response = await apiPost<ResearchIngestJobResponse>(
        `${KNOWLEDGE_BASE}/namespaces/${namespace}/research/ingest`,
        {
          items,
          query,
          summarize: options?.summarize ?? true,
          language: options?.language ?? 'en',
        }
      );
      setJobId(response.job_id);
      return response;
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      setSubmitError(error);
      throw error;
    } finally {
      setIsSubmitting(false);
    }
  }, [namespace]);

  const reset = useCallback(() => {
    setJobId(null);
    setSubmitError(null);
  }, []);

  return {
    jobId,
    isSubmitting,
    submitError,
    ingest,
    reset,
  };
}
