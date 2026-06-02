/**
 * TanStack Query hooks for Knowledge namespaces API.
 * Uses SWR for consistency with the rest of the codebase.
 * 
 * Endpoints:
 * - GET /api/knowledge/namespaces -> NamespaceMetaResponse[]
 * - POST /api/knowledge/namespaces -> NamespaceMetaResponse
 * - GET /api/knowledge/namespaces/{namespace} -> NamespaceMetaResponse
 * - DELETE /api/knowledge/namespaces/{namespace} -> DeleteNamespaceResponse
 */

import useSWR from 'swr';
import { apiPost, apiDelete } from '@/lib/api-client';

// Types matching knowledge_models.py
export interface NamespaceStatsResponse {
  files_indexed: number;
  chunks: number;
  entities: number;
  relations: number;
  vectors: number;
  bytes_on_disk: number;
}

export interface ImportRecordResponse {
  folder_path: string;
  started_at: string;
  finished_at: string | null;
  status: 'running' | 'completed' | 'failed' | 'interrupted';
  file_count: number;
  error_count: number;
  job_id: string | null;
}

export interface RetentionPolicyResponse {
  policy: string;
  ttl_days: number | null;
  last_swept_at: string | null;
  auto_delete_when_empty: boolean;
}

export interface NamespaceMetaResponse {
  schema_version: number;
  name: string;
  created_at: string;
  updated_at: string;
  language: string;
  description: string | null;
  embedding_model: string;
  embedding_dimension: number;
  stats: NamespaceStatsResponse;
  imports: ImportRecordResponse[];
  retention?: RetentionPolicyResponse;
  ontology_profile_version?: string | null;
}

export interface CreateNamespaceRequest {
  name: string;
  language?: string;
  description?: string;
}

export interface DeleteNamespaceResponse {
  deleted: boolean;
  namespace: string;
}

export interface ErrorResponse {
  error: string;
  code: string;
  detail: Record<string, unknown> | null;
}

const KNOWLEDGE_BASE = '/knowledge';

/**
 * Hook to fetch all knowledge namespaces.
 */
export function useKnowledgeNamespaces() {
  const { data, error, mutate, isLoading } = useSWR<NamespaceMetaResponse[]>(
    `${KNOWLEDGE_BASE}/namespaces`,
    {
      revalidateOnFocus: false,
      dedupingInterval: 5000, // Cache for 5 seconds
    }
  );

  const createNamespace = async (request: CreateNamespaceRequest): Promise<NamespaceMetaResponse> => {
    // Optimistic update
    const tempNamespace: NamespaceMetaResponse = {
      schema_version: 2,
      name: request.name,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      language: request.language || 'English',
      description: request.description || null,
      embedding_model: 'text-embedding-3-small',
      embedding_dimension: 1536,
      stats: {
        files_indexed: 0,
        chunks: 0,
        entities: 0,
        relations: 0,
        vectors: 0,
        bytes_on_disk: 0,
      },
      imports: [],
      ontology_profile_version: null,
    };

    mutate((namespaces) => namespaces ? [...namespaces, tempNamespace] : [tempNamespace], false);

    try {
      const newNamespace = await apiPost<NamespaceMetaResponse>(`${KNOWLEDGE_BASE}/namespaces`, request);
      mutate((namespaces) => 
        namespaces?.map(n => n.name === request.name ? newNamespace : n), 
        false
      );
      return newNamespace;
    } catch (err) {
      mutate(); // Rollback on error
      throw err;
    }
  };

  return {
    namespaces: data,
    isLoading,
    isError: error,
    createNamespace,
    refresh: mutate,
  };
}

/**
 * Hook to fetch a single namespace by name.
 */
export function useKnowledgeNamespace(namespace: string | null) {
  const { data, error, mutate, isLoading } = useSWR<NamespaceMetaResponse>(
    namespace ? `${KNOWLEDGE_BASE}/namespaces/${namespace}` : null,
    {
      revalidateOnFocus: false,
      dedupingInterval: 5000,
    }
  );

  const deleteNamespace = async (): Promise<DeleteNamespaceResponse> => {
    const result = await apiDelete<DeleteNamespaceResponse>(`${KNOWLEDGE_BASE}/namespaces/${namespace}`);
    mutate(undefined, false);
    return result;
  };

  return {
    namespace: data,
    isLoading,
    isError: error,
    deleteNamespace,
    refresh: mutate,
  };
}
