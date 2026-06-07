import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import '@testing-library/jest-dom';
import { ProviderCard } from '../components/settings/ProviderCard';
import type { ProviderSettings, ModelInfo } from '../types/settings';
import * as apiClient from '../lib/api-client';

vi.mock('../lib/api-client', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}));

const mockModelRegistry: ModelInfo[] = [
  { id: 'claude-opus-4', label: 'Claude Opus 4', context_window: '200k', tier: 'flagship' },
  { id: 'claude-sonnet-4', label: 'Claude Sonnet 4', context_window: '200k', tier: 'standard' },
];

describe('ProviderCard', () => {
  const mockOnToggle = vi.fn();
  const mockOnModelChange = vi.fn();
  const mockOnSettingsChange = vi.fn();
  const mockOnVaultClick = vi.fn();
  const mockOnServiceAccountUpload = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    (apiClient.apiGet as ReturnType<typeof vi.fn>).mockResolvedValue({ authenticated: false });
    (apiClient.apiPost as ReturnType<typeof vi.fn>).mockResolvedValue({ authorization_url: 'https://example.com/oauth', state: 'test-state' });
  });

  describe('Compact variant (anthropic, openai)', () => {
    const defaultProvider: ProviderSettings = {
      enabled: true,
      default_model: 'claude-opus-4',
    };

    it('renders provider name', () => {
      render(
        <ProviderCard
          name="anthropic"
          provider={defaultProvider}
          variant="compact"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={['claude-opus-4', 'claude-sonnet-4']}
        />
      );

      expect(screen.getByText('anthropic')).toBeInTheDocument();
    });

    it('shows "Click to configure" when vaultSet is false', () => {
      render(
        <ProviderCard
          name="anthropic"
          provider={defaultProvider}
          variant="compact"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={false}
          models={[]}
        />
      );

      expect(screen.getByText('Click to configure')).toBeInTheDocument();
    });

    it('shows masked key when vaultSet is true', () => {
      render(
        <ProviderCard
          name="anthropic"
          provider={defaultProvider}
          variant="compact"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={[]}
        />
      );

      expect(screen.getByText('\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022')).toBeInTheDocument();
    });

    it('calls onVaultClick when API key button is clicked', () => {
      render(
        <ProviderCard
          name="anthropic"
          provider={defaultProvider}
          variant="compact"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={false}
          models={[]}
        />
      );

      fireEvent.click(screen.getByText('Click to configure'));
      expect(mockOnVaultClick).toHaveBeenCalledTimes(1);
    });

    it('does not render test button (feature removed)', () => {
      render(
        <ProviderCard
          name="anthropic"
          provider={defaultProvider}
          variant="compact"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={[]}
        />
      );

      expect(screen.queryByText('Test Connection')).not.toBeInTheDocument();
      expect(screen.queryByText('Testing...')).not.toBeInTheDocument();
    });

    it('does not render latency display (feature removed)', () => {
      render(
        <ProviderCard
          name="anthropic"
          provider={defaultProvider}
          variant="compact"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={[]}
        />
      );

      expect(screen.queryByText(/Latency:/)).not.toBeInTheDocument();
    });
  });

  describe('Primary variant - Generic (non-Google)', () => {
    const defaultProvider: ProviderSettings = {
      enabled: true,
      default_model: 'gpt-4',
    };

    it('renders provider name with "Provisioning" suffix', () => {
      render(
        <ProviderCard
          name="openai"
          provider={defaultProvider}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={['gpt-4', 'gpt-3.5-turbo']}
        />
      );

      expect(screen.getByText('openai Provisioning')).toBeInTheDocument();
    });

    it('shows ACTIVE status when enabled', () => {
      render(
        <ProviderCard
          name="openai"
          provider={defaultProvider}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={[]}
        />
      );

      expect(screen.getByText('ACTIVE')).toBeInTheDocument();
    });

    it('shows READY in footer when enabled', () => {
      render(
        <ProviderCard
          name="openai"
          provider={defaultProvider}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={[]}
        />
      );

      expect(screen.getByText('READY')).toBeInTheDocument();
    });

    it('shows INACTIVE in footer when disabled', () => {
      render(
        <ProviderCard
          name="openai"
          provider={{ enabled: false }}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={false}
          models={[]}
        />
      );

      const inactiveElements = screen.getAllByText('INACTIVE');
      expect(inactiveElements.length).toBeGreaterThan(0);
    });

    it('does not render test button (feature removed)', () => {
      render(
        <ProviderCard
          name="openai"
          provider={defaultProvider}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={[]}
        />
      );

      expect(screen.queryByText('[RUN TEST]')).not.toBeInTheDocument();
      expect(screen.queryByText('TESTING...')).not.toBeInTheDocument();
    });
  });

  describe('Primary variant - Google', () => {
    const defaultProvider: ProviderSettings = {
      enabled: true,
      deployment_mode: 'gemini',
      default_model: 'gemini-3-flash',
    };

    it('renders "Google Cloud Provisioning" header', () => {
      render(
        <ProviderCard
          name="google"
          provider={defaultProvider}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onSettingsChange={mockOnSettingsChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={[]}
          modelRegistry={mockModelRegistry}
        />
      );

      expect(screen.getByText('Google Cloud Provisioning')).toBeInTheDocument();
    });

    it('shows ACTIVE status when enabled', () => {
      render(
        <ProviderCard
          name="google"
          provider={defaultProvider}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onSettingsChange={mockOnSettingsChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={[]}
        />
      );

      expect(screen.getByText('ACTIVE')).toBeInTheDocument();
    });

    it('shows INACTIVE status when disabled', () => {
      render(
        <ProviderCard
          name="google"
          provider={{ enabled: false }}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onSettingsChange={mockOnSettingsChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={false}
          models={[]}
        />
      );

      const inactiveElements = screen.getAllByText('INACTIVE');
      expect(inactiveElements.length).toBeGreaterThan(0);
    });

    it('renders GOOGLE and VERTEX AI mode buttons', () => {
      render(
        <ProviderCard
          name="google"
          provider={defaultProvider}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onSettingsChange={mockOnSettingsChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={[]}
        />
      );

      expect(screen.getByText('GOOGLE')).toBeInTheDocument();
      expect(screen.getByText('VERTEX AI')).toBeInTheDocument();
    });

    it('highlights selected deployment mode', () => {
      render(
        <ProviderCard
          name="google"
          provider={defaultProvider}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onSettingsChange={mockOnSettingsChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={[]}
        />
      );

      const geminiButton = screen.getByText('GOOGLE').closest('button');
      expect(geminiButton).toHaveClass('border-blue-600');
    });

    it('calls onSettingsChange when switching to Vertex mode', () => {
      render(
        <ProviderCard
          name="google"
          provider={defaultProvider}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onSettingsChange={mockOnSettingsChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={[]}
        />
      );

      fireEvent.click(screen.getByText('VERTEX AI'));
      expect(mockOnSettingsChange).toHaveBeenCalledWith({ deployment_mode: 'vertex', default_model: undefined });
    });

    it('calls onSettingsChange when switching to Gemini mode', () => {
      render(
        <ProviderCard
          name="google"
          provider={{ enabled: true, deployment_mode: 'vertex' }}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onSettingsChange={mockOnSettingsChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={[]}
        />
      );

      fireEvent.click(screen.getByText('GOOGLE'));
      expect(mockOnSettingsChange).toHaveBeenCalledWith({ deployment_mode: 'gemini', default_model: undefined });
    });

    it('shows API key input in Gemini mode', () => {
      render(
        <ProviderCard
          name="google"
          provider={defaultProvider}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onSettingsChange={mockOnSettingsChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={false}
          models={[]}
        />
      );

      expect(screen.getByText('GOOGLE_API_KEY')).toBeInTheDocument();
    });

    it('shows Vertex AI configuration fields in Vertex mode', () => {
      render(
        <ProviderCard
          name="google"
          provider={{ enabled: true, deployment_mode: 'vertex', project_id: 'test-project' }}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onSettingsChange={mockOnSettingsChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={[]}
        />
      );

      expect(screen.getByPlaceholderText('my-gcp-project-id')).toBeInTheDocument();
      expect(screen.getByPlaceholderText('global')).toBeInTheDocument();
    });

    it('shows READY in footer when enabled', () => {
      render(
        <ProviderCard
          name="google"
          provider={defaultProvider}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onSettingsChange={mockOnSettingsChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={[]}
        />
      );

      expect(screen.getByText('READY')).toBeInTheDocument();
    });

    it('shows MODE indicator in footer', () => {
      render(
        <ProviderCard
          name="google"
          provider={defaultProvider}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onSettingsChange={mockOnSettingsChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={[]}
        />
      );

      expect(screen.getByText((_content, node) => node?.textContent === 'MODE: GOOGLE')).toBeInTheDocument();
    });

    it('does not render test button (feature removed)', () => {
      render(
        <ProviderCard
          name="google"
          provider={defaultProvider}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onSettingsChange={mockOnSettingsChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={[]}
        />
      );

      expect(screen.queryByText('[RUN TEST]')).not.toBeInTheDocument();
      expect(screen.queryByText('TESTING...')).not.toBeInTheDocument();
      expect(screen.queryByText(/LATENCY/)).not.toBeInTheDocument();
    });

    it('renders authentication method selector in Vertex mode', () => {
      render(
        <ProviderCard
          name="google"
          provider={{ enabled: true, deployment_mode: 'vertex', vertex_auth_mode: 'service_account' }}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onSettingsChange={mockOnSettingsChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={[]}
        />
      );

      expect(screen.getByText('Service Account')).toBeInTheDocument();
      expect(screen.getByText('Browser Login')).toBeInTheDocument();
    });

    it('calls onSettingsChange when switching auth mode', () => {
      render(
        <ProviderCard
          name="google"
          provider={{ enabled: true, deployment_mode: 'vertex', vertex_auth_mode: 'service_account' }}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onSettingsChange={mockOnSettingsChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={[]}
        />
      );

      fireEvent.click(screen.getByText('Browser Login'));
      expect(mockOnSettingsChange).toHaveBeenCalledWith({ vertex_auth_mode: 'oauth' });
    });

    it('shows service account upload UI when service_account auth mode selected', () => {
      render(
        <ProviderCard
          name="google"
          provider={{ enabled: true, deployment_mode: 'vertex', vertex_auth_mode: 'service_account' }}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onSettingsChange={mockOnSettingsChange}
          onVaultClick={mockOnVaultClick}
          onServiceAccountUpload={mockOnServiceAccountUpload}
          vaultSet={true}
          serviceAccountVaultSet={false}
          models={[]}
        />
      );

      expect(screen.getByText('Attach service-account.json')).toBeInTheDocument();
    });

    it('shows OAuth login button when oauth auth mode selected', () => {
      render(
        <ProviderCard
          name="google"
          provider={{ enabled: true, deployment_mode: 'vertex', vertex_auth_mode: 'oauth' }}
          variant="primary"
          onToggle={mockOnToggle}
          onModelChange={mockOnModelChange}
          onSettingsChange={mockOnSettingsChange}
          onVaultClick={mockOnVaultClick}
          vaultSet={true}
          models={[]}
        />
      );

      expect(screen.getByText('Sign in with Google')).toBeInTheDocument();
    });
  });
});
