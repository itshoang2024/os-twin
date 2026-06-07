import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { describe, expect, it, vi } from 'vitest';

import AuthOverlay from '@/components/auth/AuthOverlay';

const login = vi.fn();

vi.mock('@/components/auth/AuthProvider', () => ({
  useAuth: () => ({
    isAuthenticated: false,
    isLoading: false,
    error: null,
    login,
  }),
}));

describe('AuthOverlay', () => {
  it('requires and submits username with the OSTWIN API key', async () => {
    login.mockResolvedValue(true);
    render(<AuthOverlay />);

    const submit = screen.getByRole('button', { name: /save and enter dashboard/i });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/your name/i), { target: { value: 'Ada Lovelace' } });
    fireEvent.change(screen.getByLabelText(/ostwin api key/i), { target: { value: 'ostwin_key' } });
    expect(submit).toBeEnabled();

    fireEvent.click(submit);

    await waitFor(() => {
      expect(login).toHaveBeenCalledWith('ostwin_key', 'Ada Lovelace');
    });
  });
});
