import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { apiPost } from '@/lib/api-client';
import { GitHubCopilotPanel } from '../components/settings/GitHubCopilotPanel';

vi.mock('@/lib/api-client', () => ({
  apiGet: vi.fn().mockResolvedValue({ connected: false }),
  apiPost: vi.fn(),
  ApiError: class ApiError extends Error {
    data?: unknown;
  },
}));

describe('GitHubCopilotPanel', () => {
  const onSettingsChange = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders GitHub Copilot auth methods and connection status', () => {
    render(
      <GitHubCopilotPanel
        provider={{ enabled: false }}
        onSettingsChange={onSettingsChange}
      />,
    );

    expect(screen.getByText('github copilot')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /browser oauth/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /device code/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /login with github copilot/i })).toBeInTheDocument();
    expect(screen.getByText(/copilot not connected/i)).toBeInTheDocument();
  });

  it('starts browser oauth by default', async () => {
    const popup = {
      document: {
        write: vi.fn(),
        open: vi.fn(),
        close: vi.fn(),
      },
      focus: vi.fn(),
      location: { href: '' },
    } as unknown as Window;
    vi.spyOn(window, 'open').mockReturnValue(popup);
    vi.mocked(apiPost).mockResolvedValue({
      authorization_url: 'https://github.com/login/oauth/authorize?client_id=test',
    });

    render(
      <GitHubCopilotPanel
        provider={{ enabled: false }}
        onSettingsChange={onSettingsChange}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /login with github copilot/i }));

    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith('/settings/github/oauth/start');
    });
    expect(popup.location.href).toBe('https://github.com/login/oauth/authorize?client_id=test');
  });

  it('starts device auth and saves provider settings when already connected', async () => {
    vi.spyOn(window, 'open').mockReturnValue(null);
    vi.mocked(apiPost).mockResolvedValue({
      status: 'connected',
      connected: true,
    });

    render(
      <GitHubCopilotPanel
        provider={{ enabled: false }}
        onSettingsChange={onSettingsChange}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /device code/i }));
    fireEvent.click(screen.getByRole('button', { name: /login with github copilot/i }));

    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith('/settings/github/copilot/device/start');
    });
    await waitFor(() => {
      expect(onSettingsChange).toHaveBeenCalledWith({
        enabled: true,
        auth_mode: 'copilot_oauth',
        default_model: 'github-copilot/gpt-5.2',
      });
    });
  });
});
