import { renderHook, waitFor } from '@testing-library/react';
import { SWRConfig } from 'swr';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { fetcher } from '@/lib/api-client';
import { useKnowledgeNamespace, useKnowledgeNamespaces } from '@/hooks/use-knowledge-namespaces';

vi.mock('@/lib/api-client', () => ({
  fetcher: vi.fn(),
  apiPost: vi.fn(),
  apiDelete: vi.fn(),
}));

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
    {children}
  </SWRConfig>
);

const namespace = {
  schema_version: 3,
  name: 'qa-epic015',
  created_at: '2026-06-04T00:00:00Z',
  updated_at: '2026-06-04T00:00:00Z',
  language: 'English',
  description: 'QA namespace',
  embedding_model: 'test-embedding',
  embedding_dimension: 1024,
  stats: {
    files_indexed: 0,
    chunks: 0,
    entities: 0,
    relations: 0,
    vectors: 0,
    bytes_on_disk: 0,
  },
  imports: [],
  ontology_profile_version: '1.0.0',
};

describe('useKnowledgeNamespaces', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('uses the shared API fetcher and resolves namespace data', async () => {
    vi.mocked(fetcher).mockResolvedValueOnce([namespace]);

    const { result } = renderHook(() => useKnowledgeNamespaces(), { wrapper });

    await waitFor(() => expect(result.current.namespaces).toEqual([namespace]));
    expect(fetcher).toHaveBeenCalledWith('/knowledge/namespaces');
    expect(result.current.isLoading).toBe(false);
    expect(result.current.isError).toBeUndefined();
  });

  it('uses the shared API fetcher for a single namespace lookup', async () => {
    vi.mocked(fetcher).mockResolvedValueOnce(namespace);

    const { result } = renderHook(() => useKnowledgeNamespace('qa-epic015'), { wrapper });

    await waitFor(() => expect(result.current.namespace).toEqual(namespace));
    expect(fetcher).toHaveBeenCalledWith('/knowledge/namespaces/qa-epic015');
  });
});
