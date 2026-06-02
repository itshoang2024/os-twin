import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as React from 'react';

const mocks = vi.hoisted(() => ({
  updateNamespace: vi.fn(),
  updateVault: vi.fn(),
  reloadModels: vi.fn(),
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiDelete: vi.fn(),
  apiPut: vi.fn(),
}));

vi.mock('@/hooks/use-settings', () => ({
  useSettings: () => ({
    settings: {
      providers: {
        openai: { enabled: true, auth_mode: 'codex_oauth' },
      },
      runtime: {},
      memory: {},
      knowledge: {},
    },
    isLoading: false,
    isError: false,
    updateNamespace: mocks.updateNamespace,
    updateVault: mocks.updateVault,
  }),
}));

vi.mock('@/hooks/use-configured-models', () => ({
  useConfiguredModels: () => ({
    configured: true,
    providers: {},
    allModels: [
      { id: 'anthropic/claude-opus-4', label: 'Claude Opus 4', provider_id: 'anthropic' },
      { id: 'openai/gpt-5', label: 'GPT-5', provider_id: 'openai' },
    ],
    reload: mocks.reloadModels,
  }),
}));

vi.mock('@/lib/api-client', () => ({
  apiGet: mocks.apiGet,
  apiPost: mocks.apiPost,
  apiDelete: mocks.apiDelete,
  apiPut: mocks.apiPut,
  ApiError: class ApiError extends Error {
    data?: unknown;
  },
}));

vi.mock('next/navigation', () => ({
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  })),
}));

import SettingsPage from '../app/settings/page';

describe('SettingsPage OpenAI credentials', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.updateVault.mockResolvedValue(undefined);
    mocks.updateNamespace.mockResolvedValue(undefined);
    mocks.apiPost.mockResolvedValue({});
    mocks.apiDelete.mockResolvedValue({});
    mocks.apiPut.mockResolvedValue({});
    mocks.apiGet.mockImplementation((url: string) => {
      if (url === '/models/registry') return Promise.resolve({});
      if (url === '/settings/openai/codex/session') return Promise.resolve({ connected: true });
      if (url === '/settings/vault/providers') {
        return Promise.resolve({
          keys: {
            google: { is_set: false },
            anthropic: { is_set: false },
            openai: { is_set: false },
            byteplus: { is_set: false },
          },
        });
      }
      return Promise.resolve({});
    });
  });

  it('stores an OpenAI API key through the vault and switches OpenAI to API-key auth', async () => {
    render(
      <React.Suspense fallback={<div>Loading...</div>}>
        <SettingsPage />
      </React.Suspense>,
    );

    await screen.findByText('openai');

    const openaiPanel = screen.getByRole('region', { name: /openai provider credentials/i });
    fireEvent.click(within(openaiPanel).getByRole('button', { name: /click to configure/i }));

    await screen.findByText('Vault Secret');
    fireEvent.change(screen.getByPlaceholderText('Enter secret value'), {
      target: { value: 'sk-test' },
    });
    fireEvent.click(screen.getByRole('button', { name: /save secret/i }));

    await waitFor(() => {
      expect(mocks.updateVault).toHaveBeenCalledWith('providers', 'openai', 'sk-test');
    });
    await waitFor(() => {
      expect(mocks.updateNamespace).toHaveBeenCalledWith(
        'providers',
        expect.objectContaining({
          openai: expect.objectContaining({
            enabled: true,
            auth_mode: 'api_key',
          }),
        }),
      );
    });
  });
});
