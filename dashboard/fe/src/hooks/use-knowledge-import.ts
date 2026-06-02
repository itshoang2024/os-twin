/**
 * SWR hooks for Knowledge import/jobs API.
 * 
 * Endpoints:
 * - POST /api/knowledge/namespaces/{namespace}/import -> ImportFolderResponse
 * - POST /api/knowledge/namespaces/{namespace}/import-text -> ImportTextResponse
 * - GET /api/knowledge/namespaces/{namespace}/jobs -> NamespaceJobsResponse
 * - GET /api/knowledge/namespaces/{namespace}/jobs/{job_id} -> JobStatusResponse
 */

import { useState, useCallback } from 'react';
import useSWR from 'swr';
import { apiPost } from '@/lib/api-client';

export interface ImportFolderRequest {
  folder_path: string;
  options?: {
    chunk_size?: number;
    overlap?: number;
    llm_model?: string;
    vision_ocr?: boolean;
    vision_ocr_model?: string;
    [key: string]: unknown;
  };
}

export interface ImportFolderResponse {
  job_id: string;
  namespace: string;
}

export interface ImportTextRequest {
  text: string;
  source_label?: string;
  options?: {
    chunk_size?: number;
    chunk_overlap?: number;
    llm_model?: string;
    [key: string]: unknown;
  };
  category?: string;
}

export interface ImportTextResponse {
  namespace: string;
  chunks_added: number;
  entities_added: number;
  relations_added: number;
  elapsed_seconds: number;
}

export interface JobStatusResponse {
  job_id: string;
  namespace: string;
  operation: string;
  state: 'pending' | 'running' | 'completed' | 'failed' | 'interrupted' | 'cancelled';
  submitted_at: string;
  started_at: string | null;
  finished_at: string | null;
  progress_current: number;
  progress_total: number;
  message: string;
  errors: string[];
  result: Record<string, unknown> | null;
}

export interface GraphCountsResponse {
  entities: number;
  chunks: number;
  relations: number;
}

export interface NamespaceJobsResponse {
  jobs: JobStatusResponse[];
  graph_counts: GraphCountsResponse;
}

const KNOWLEDGE_BASE = '/knowledge';

/**
 * Hook to fetch all jobs for a namespace (with live graph counts).
 */
export function useKnowledgeJobs(namespace: string | null) {
  const { data, error, mutate, isLoading } = useSWR<NamespaceJobsResponse>(
    namespace ? `${KNOWLEDGE_BASE}/namespaces/${namespace}/jobs` : null,
    {
      revalidateOnFocus: false,
      dedupingInterval: 2000,
      refreshInterval: (latestData) => {
        // Poll every 3s while any job is still running
        const hasActive = latestData?.jobs?.some(j =>
          ['pending', 'running'].includes(j.state)
        );
        return hasActive ? 3000 : 0;
      },
    }
  );

  return {
    jobs: data?.jobs,
    graphCounts: data?.graph_counts ?? { entities: 0, chunks: 0, relations: 0 },
    isLoading,
    isError: error,
    refresh: mutate,
  };
}

/**
 * Hook to fetch a single job status.
 * Automatically polls while job is running (every 2s).
 */
export function useKnowledgeJob(namespace: string | null, jobId: string | null) {
  const isTerminalState = (state: string) => 
    ['completed', 'failed', 'interrupted', 'cancelled'].includes(state);

  const { data, error, mutate, isLoading } = useSWR<JobStatusResponse>(
    namespace && jobId ? `${KNOWLEDGE_BASE}/namespaces/${namespace}/jobs/${jobId}` : null,
    {
      revalidateOnFocus: false,
      // Poll every 2 seconds while job is running
      refreshInterval: (data) => {
        if (data && !isTerminalState(data.state)) {
          return 2000;
        }
        return 0;
      },
      dedupingInterval: 1000,
    }
  );

  return {
    job: data,
    isLoading,
    isError: error,
    isTerminal: data ? isTerminalState(data.state) : false,
    refresh: mutate,
  };
}

/**
 * Hook to trigger an import operation.
 */
export function useKnowledgeImport() {
  const startImport = async (
    namespace: string,
    request: ImportFolderRequest
  ): Promise<ImportFolderResponse> => {
    return apiPost<ImportFolderResponse>(
      `${KNOWLEDGE_BASE}/namespaces/${namespace}/import`,
      request
    );
  };

  return {
    startImport,
  };
}

/**
 * Combined hook for import panel - handles import trigger and job monitoring.
 */
export function useKnowledgeImportMonitor(namespace: string | null) {
  const { jobs, graphCounts, isLoading: jobsLoading, refresh: refreshJobs } = useKnowledgeJobs(namespace);
  const { startImport } = useKnowledgeImport();

  // Get the most recent running/pending job
  const activeJob = jobs?.find(j => 
    ['pending', 'running'].includes(j.state)
  );

  // Get the most recent job (any state)
  const latestJob = jobs?.[0];

  return {
    jobs,
    graphCounts,
    activeJob,
    latestJob,
    isLoading: jobsLoading,
    startImport,
    refreshJobs,
  };
}

/**
 * Hook to trigger a plain-text import operation (synchronous).
 * Unlike folder import (which returns a job_id), text import returns
 * the result directly with chunk/entity/relation counts.
 */
export function useKnowledgeTextImport() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [result, setResult] = useState<ImportTextResponse | null>(null);

  const startImportText = useCallback(
    async (namespace: string, request: ImportTextRequest): Promise<ImportTextResponse> => {
      setIsLoading(true);
      setError(null);
      setResult(null);
      try {
        const res = await apiPost<ImportTextResponse>(
          `${KNOWLEDGE_BASE}/namespaces/${namespace}/import-text`,
          request
        );
        setResult(res);
        return res;
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        setError(error);
        throw error;
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  return {
    startImportText,
    isLoading,
    error,
    result,
  };
}
