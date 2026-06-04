import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiPost } from '@/lib/api-client';
import { OpenAICodexPanel } from '../components/settings/OpenAICodexPanel';

vi.mock('@/lib/api-client', () => ({
  apiGet: vi.fn().mockResolvedValue({ connected: false }),
  apiPost: vi.fn(),
  ApiError: class ApiError extends Error {
    data?: unknown;
  },
}));

describe('OpenAICodexPanel', () => {
  const onVaultClick = vi.fn();
  const onSettingsChange = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders an OpenAI API key registration control alongside Codex login', () => {
    render(
      <OpenAICodexPanel
        provider={{ enabled: true, auth_mode: 'codex_oauth' }}
        onVaultClick={onVaultClick}
        vaultSet={false}
        onSettingsChange={onSettingsChange}
      />,
    );

    expect(screen.getByText('openai')).toBeInTheDocument();
    expect(screen.getByText('API Access Key')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /click to configure/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /browser/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /device code/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /login with codex/i })).toBeInTheDocument();
    expect(screen.getByText(/browser login uses local callback port 1455/i)).toBeInTheDocument();
    expect(screen.getByText(/if it is busy, use device code/i)).toBeInTheDocument();
  });

  it('shows the ChatGPT security setting note for device code login', () => {
    render(
      <OpenAICodexPanel
        provider={{ enabled: true }}
        onVaultClick={onVaultClick}
        vaultSet={false}
        onSettingsChange={onSettingsChange}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /device code/i }));

    expect(screen.getByText(/device code access/i)).toBeInTheDocument();
    expect(screen.getByText(/if device code is already enabled/i)).toBeInTheDocument();
    expect(screen.getByText(/if openai blocks login/i)).toBeInTheDocument();
    expect(screen.getByText(/enable codex device code authorization there/i)).toBeInTheDocument();
    expect(screen.getByText(/return here and click login with codex/i)).toBeInTheDocument();
  });

  it('opens the provider vault registration flow from the API key control', () => {
    render(
      <OpenAICodexPanel
        provider={{ enabled: true }}
        onVaultClick={onVaultClick}
        vaultSet={false}
        onSettingsChange={onSettingsChange}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /click to configure/i }));

    expect(onVaultClick).toHaveBeenCalledTimes(1);
  });

  it('starts device auth when device code method is selected', async () => {
    vi.spyOn(window, 'open').mockReturnValue(null);
    vi.mocked(apiPost).mockResolvedValue({
      status: 'connected',
      connected: true,
    });

    render(
      <OpenAICodexPanel
        provider={{ enabled: true }}
        onVaultClick={onVaultClick}
        vaultSet={false}
        onSettingsChange={onSettingsChange}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /device code/i }));
    fireEvent.click(screen.getByRole('button', { name: /login with codex/i }));

    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith('/settings/openai/codex/device/start');
    });
    await waitFor(() => {
      expect(onSettingsChange).toHaveBeenCalledWith(
        expect.objectContaining({
          auth_mode: 'codex_oauth',
        }),
      );
    });
  });
});
