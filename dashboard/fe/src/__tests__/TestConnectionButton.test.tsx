import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import '@testing-library/jest-dom';
import TestConnectionButton from '../components/roles/TestConnectionButton';
import { apiPost } from '../lib/api-client';

vi.mock('../lib/api-client', () => ({
  apiPost: vi.fn(),
}));

describe('TestConnectionButton', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the test button', () => {
    render(<TestConnectionButton version="claude-opus-4" />);
    expect(screen.getByText('Test Connection')).toBeInTheDocument();
  });

  it('does nothing when version is empty', () => {
    render(<TestConnectionButton version="" />);
    fireEvent.click(screen.getByText('Test Connection'));
    expect(apiPost).not.toHaveBeenCalled();
  });

  it('calls apiPost with correct path on click', async () => {
    (apiPost as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: 'ok',
      latency_ms: 120,
    });

    render(<TestConnectionButton version="claude-opus-4" />);
    fireEvent.click(screen.getByText('Test Connection'));

    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith(
        expect.stringContaining('/models/'),
        expect.anything()
      );
    });
  });

  it('uses apiPost instead of raw fetch for correct base URL handling', async () => {
    (apiPost as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: 'ok',
      latency_ms: 50,
    });

    render(<TestConnectionButton version="google-vertex/gemini-3-flash" />);
    fireEvent.click(screen.getByText('Test Connection'));

    await waitFor(() => {
      // Must use apiPost (which respects NEXT_PUBLIC_API_BASE_URL), not raw fetch
      expect(apiPost).toHaveBeenCalled();
    });
  });

  it('shows success result with latency', async () => {
    (apiPost as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: 'ok',
      latency_ms: 150,
    });

    render(<TestConnectionButton version="claude-opus-4" />);
    fireEvent.click(screen.getByText('Test Connection'));

    await waitFor(() => {
      expect(screen.getByText(/OK/)).toBeInTheDocument();
      expect(screen.getByText(/150ms/)).toBeInTheDocument();
    });
  });

  it('shows error message from API response when test fails', async () => {
    (apiPost as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: 'fail',
      error: 'API key not configured for Gemini',
    });

    render(<TestConnectionButton version="google-vertex/gemini-3-flash" />);
    fireEvent.click(screen.getByText('Test Connection'));

    await waitFor(() => {
      // Should show the actual error message from the backend, not just "Connection Failed"
      expect(screen.getByText(/API key not configured/i)).toBeInTheDocument();
    });
  });

  it('shows generic error for network failures', async () => {
    (apiPost as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('Network error')
    );

    render(<TestConnectionButton version="claude-opus-4" />);
    fireEvent.click(screen.getByText('Test Connection'));

    await waitFor(() => {
      expect(screen.getByText(/Network error/i)).toBeInTheDocument();
    });
  });

  it('shows loading state while testing', async () => {
    let resolvePromise: (value: unknown) => void;
    const promise = new Promise((resolve) => { resolvePromise = resolve; });
    (apiPost as unknown as ReturnType<typeof vi.fn>).mockReturnValue(promise);

    render(<TestConnectionButton version="claude-opus-4" />);
    fireEvent.click(screen.getByText('Test Connection'));

    expect(screen.getByText('Testing…')).toBeInTheDocument();

    resolvePromise!({ status: 'ok', latency_ms: 100 });
    await waitFor(() => {
      expect(screen.queryByText('Testing…')).not.toBeInTheDocument();
    });
  });
});
