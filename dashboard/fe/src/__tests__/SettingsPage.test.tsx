import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import '@testing-library/jest-dom';
import * as React from 'react';
import { apiGet } from '@/lib/api-client';

const mockSettings = {
  providers: {},
  runtime: {},
  memory: {},
  knowledge: { llm_model: '', embedding_model: '', embedding_dimension: 384 },
};

const mockReloadModels = vi.hoisted(() => vi.fn());

vi.mock('@/hooks/use-settings', () => ({
  useSettings: () => ({
    settings: mockSettings,
    isLoading: false,
    isError: false,
    updateNamespace: vi.fn(),
    updateVault: vi.fn(),
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
    reload: mockReloadModels,
  }),
}));

vi.mock('@/lib/api-client', () => ({
  apiGet: vi.fn().mockResolvedValue({}),
  apiPost: vi.fn().mockResolvedValue({}),
  apiDelete: vi.fn().mockResolvedValue({}),
  apiPut: vi.fn().mockResolvedValue({}),
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

describe('Settings Page Integration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('T-002.1: Settings Page Loads with 4 Sub-Tabs', () => {
    it('renders the settings page with sidebar', async () => {
      render(
        <React.Suspense fallback={<div>Loading...</div>}>
          <SettingsPage />
        </React.Suspense>
      );

      await waitFor(() => {
        expect(screen.getAllByText('Provider Config').length).toBeGreaterThan(0);
        expect(screen.getAllByText('Runtime').length).toBeGreaterThan(0);
        expect(screen.getAllByText('Memory').length).toBeGreaterThan(0);
        expect(screen.getAllByText('Knowledge').length).toBeGreaterThan(0);
      });
    });

    it('shows Provider Config tab as default active', async () => {
      render(
        <React.Suspense fallback={<div>Loading...</div>}>
          <SettingsPage />
        </React.Suspense>
      );

      await waitFor(() => {
        expect(screen.getByText('Global Model Provisioning')).toBeInTheDocument();
      });
    });
  });

  describe('T-002.2: Knowledge Panel Renders', () => {
    it('renders Knowledge panel when Knowledge tab is clicked', async () => {
      render(
        <React.Suspense fallback={<div>Loading...</div>}>
          <SettingsPage />
        </React.Suspense>
      );

      await waitFor(() => {
        expect(screen.getAllByText('Provider Config').length).toBeGreaterThan(0);
      });

      const knowledgeButtons = screen.getAllByText('Knowledge');
      fireEvent.click(knowledgeButtons[0]);

      await waitFor(() => {
        expect(screen.getByText(/Knowledge Models/i)).toBeInTheDocument();
      });
    });

    it('renders LLM Model section in Knowledge panel', async () => {
      render(
        <React.Suspense fallback={<div>Loading...</div>}>
          <SettingsPage />
        </React.Suspense>
      );

      await waitFor(() => {
        expect(screen.getAllByText('Provider Config').length).toBeGreaterThan(0);
      });

      const knowledgeButtons = screen.getAllByText('Knowledge');
      fireEvent.click(knowledgeButtons[0]);

      await waitFor(() => {
        expect(screen.getAllByText(/Processing Model/i).length).toBeGreaterThan(0);
      });
    });

    it('renders Embedding Model section in Knowledge panel', async () => {
      render(
        <React.Suspense fallback={<div>Loading...</div>}>
          <SettingsPage />
        </React.Suspense>
      );

      await waitFor(() => {
        expect(screen.getAllByText('Provider Config').length).toBeGreaterThan(0);
      });

      const knowledgeButtons = screen.getAllByText('Knowledge');
      fireEvent.click(knowledgeButtons[0]);

      await waitFor(() => {
        expect(screen.getAllByText(/Embedding/i).length).toBeGreaterThan(0);
      });
    });

    it('renders ModelSelect with searchable input', async () => {
      render(
        <React.Suspense fallback={<div>Loading...</div>}>
          <SettingsPage />
        </React.Suspense>
      );

      await waitFor(() => {
        expect(screen.getAllByText('Provider Config').length).toBeGreaterThan(0);
      });

      const knowledgeButtons = screen.getAllByText('Knowledge');
      fireEvent.click(knowledgeButtons[0]);

      // Change backend to OpenAI-Compatible to show the ModelSelect
      await waitFor(() => {
        const backendBtns = screen.getAllByRole('button').filter(b => b.textContent?.includes('OpenAI-Compatible'));
        if (backendBtns.length > 0) {
           fireEvent.click(backendBtns[0]);
        }
      });

      await waitFor(() => {
        expect(screen.getAllByText(/— Select from providers —/i).length).toBeGreaterThan(0);
      });

      const triggers = screen.getAllByRole('button').filter((b) =>
        b.textContent?.includes('Select from providers')
      );
      if (triggers.length > 0) {
        fireEvent.click(triggers[0]);
      }

      await waitFor(() => {
        expect(screen.getByPlaceholderText(/search models/i)).toBeInTheDocument();
      });
    });
  });

  describe('T-002.4: Provider Cards Show Status Indicators', () => {
    it('renders Google Cloud provider card', async () => {
      render(
        <React.Suspense fallback={<div>Loading...</div>}>
          <SettingsPage />
        </React.Suspense>
      );

      await waitFor(() => {
        expect(screen.getByText('Google Cloud Provisioning')).toBeInTheDocument();
      });
    });

    it('renders Anthropic provider card', async () => {
      render(
        <React.Suspense fallback={<div>Loading...</div>}>
          <SettingsPage />
        </React.Suspense>
      );

      await waitFor(() => {
        expect(screen.getByText('anthropic')).toBeInTheDocument();
      });
    });

    it('renders OpenAI provider card', async () => {
      render(
        <React.Suspense fallback={<div>Loading...</div>}>
          <SettingsPage />
        </React.Suspense>
      );

      await waitFor(() => {
        expect(screen.getByText('openai')).toBeInTheDocument();
      });
    });

    it('shows status indicator (ACTIVE/INACTIVE) on provider cards', async () => {
      render(
        <React.Suspense fallback={<div>Loading...</div>}>
          <SettingsPage />
        </React.Suspense>
      );

      await waitFor(() => {
        const statusElements = screen.getAllByText(/ACTIVE|INACTIVE/);
        expect(statusElements.length).toBeGreaterThan(0);
      });
    });
  });

  describe('Model catalog refresh', () => {
    it('refreshes configured models after a model-update event', async () => {
      render(
        <React.Suspense fallback={<div>Loading...</div>}>
          <SettingsPage />
        </React.Suspense>
      );

      await waitFor(() => {
        expect(screen.getByText('Global Model Provisioning')).toBeInTheDocument();
      });

      window.dispatchEvent(new CustomEvent('ostwin:models-updated'));

      await waitFor(() => {
        expect(mockReloadModels).toHaveBeenCalled();
      });

      await waitFor(() => {
        const registryCalls = vi.mocked(apiGet).mock.calls.filter(([url]) => url === '/models/registry');
        expect(registryCalls.length).toBeGreaterThan(1);
      });
    });
  });

  describe('Navigation Between Tabs', () => {
    it('switches from Provider Config to Runtime', async () => {
      render(
        <React.Suspense fallback={<div>Loading...</div>}>
          <SettingsPage />
        </React.Suspense>
      );

      await waitFor(() => {
        expect(screen.getByText('Global Model Provisioning')).toBeInTheDocument();
      });

      const runtimeButtons = screen.getAllByText('Runtime');
      fireEvent.click(runtimeButtons[0]);

      await waitFor(() => {
        expect(screen.getAllByText('Runtime').length).toBeGreaterThan(0);
      });
    });

    it('switches from Provider Config to Memory', async () => {
      render(
        <React.Suspense fallback={<div>Loading...</div>}>
          <SettingsPage />
        </React.Suspense>
      );

      await waitFor(() => {
        expect(screen.getByText('Global Model Provisioning')).toBeInTheDocument();
      });

      const memoryButtons = screen.getAllByText('Memory');
      fireEvent.click(memoryButtons[0]);

      await waitFor(() => {
        expect(screen.getAllByText(/Memory/i).length).toBeGreaterThan(0);
      });
    });
  });
});
