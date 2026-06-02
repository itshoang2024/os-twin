import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
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
    expect(screen.getByRole('button', { name: /login with codex/i })).toBeInTheDocument();
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
});
