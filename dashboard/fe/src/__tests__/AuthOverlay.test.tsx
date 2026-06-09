import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  navState: { pathname: '/' },
}));

vi.mock('next/navigation', () => ({
  usePathname: () => mocks.navState.pathname,
}));

vi.mock('@/components/auth/AuthProvider', () => ({
  useAuth: () => ({
    isAuthenticated: false,
    isLoading: false,
    error: null,
    login: mocks.login,
  }),
}));

import AuthOverlay, { isOntologyFixturePath, isOntologyGraphBuilderFixturePath } from '@/components/auth/AuthOverlay';

describe('AuthOverlay', () => {
  beforeEach(() => {
    mocks.login.mockReset();
    mocks.navState.pathname = '/';
    window.history.pushState({}, '', '/');
  });

  it('detects only the ontology fixture route as local setup bypassable', () => {
    expect(isOntologyFixturePath('/knowledge/ontology-fixture')).toBe(true);
    expect(isOntologyFixturePath('/knowledge/ontology-fixture/')).toBe(true);
    expect(isOntologyFixturePath('/knowledge/ontology-fixture?tab=ontology')).toBe(true);
    expect(isOntologyFixturePath('/knowledge/ontology-fixture-extra')).toBe(false);
    expect(isOntologyFixturePath('/knowledge/retention-test?tab=ontology')).toBe(false);
  });

  it('detects only fixture-backed ontology graph builder routes as local setup bypassable', () => {
    expect(isOntologyGraphBuilderFixturePath('/knowledge/demo/ontology-graph-builder', '?fixture=basic')).toBe(true);
    expect(isOntologyGraphBuilderFixturePath('/knowledge/demo/ontology-graph-builder/', 'fixture=empty')).toBe(true);
    expect(isOntologyGraphBuilderFixturePath('/knowledge/demo/ontology-graph-builder', '?fixture=redacted')).toBe(true);
    expect(isOntologyGraphBuilderFixturePath('/knowledge/demo/ontology-graph-builder', '?fixture=large')).toBe(true);
    expect(isOntologyGraphBuilderFixturePath('/knowledge/demo/ontology-graph-builder', '?fixture=error')).toBe(true);
    expect(isOntologyGraphBuilderFixturePath('/knowledge/demo/ontology-graph-builder', '')).toBe(false);
    expect(isOntologyGraphBuilderFixturePath('/knowledge/demo/ontology-graph-builder', '?fixture=live')).toBe(false);
    expect(isOntologyGraphBuilderFixturePath('/knowledge/demo/ontology')).toBe(false);
  });

  it('does not render setup overlay on the ontology fixture route', () => {
    mocks.navState.pathname = '/knowledge/ontology-fixture';
    window.history.pushState({}, '', '/knowledge/ontology-fixture');

    render(<AuthOverlay />);

    expect(screen.queryByText(/finish local setup to continue/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /save and enter dashboard/i })).not.toBeInTheDocument();
  });

  it('does not render setup overlay on fixture-backed ontology graph builder routes', () => {
    mocks.navState.pathname = '/knowledge/demo/ontology-graph-builder';
    window.history.pushState({}, '', '/knowledge/demo/ontology-graph-builder?fixture=basic');

    render(<AuthOverlay />);

    expect(screen.queryByText(/finish local setup to continue/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /save and enter dashboard/i })).not.toBeInTheDocument();
  });

  it('keeps setup overlay on non-fixture ontology graph builder routes', () => {
    mocks.navState.pathname = '/knowledge/demo/ontology-graph-builder';
    window.history.pushState({}, '', '/knowledge/demo/ontology-graph-builder');

    render(<AuthOverlay />);

    expect(screen.getByText(/finish local setup to continue/i)).toBeInTheDocument();
  });

  it('falls back to the browser URL when hydration exposes a placeholder path', () => {
    mocks.navState.pathname = '/knowledge/_';
    window.history.pushState({}, '', '/knowledge/ontology-fixture');

    render(<AuthOverlay />);

    expect(screen.queryByText(/finish local setup to continue/i)).not.toBeInTheDocument();
  });

  it('requires and submits username with the OSTWIN API key', async () => {
    mocks.login.mockResolvedValue(true);
    mocks.navState.pathname = '/knowledge';
    window.history.pushState({}, '', '/knowledge');

    render(<AuthOverlay />);

    const submit = screen.getByRole('button', { name: /save and enter dashboard/i });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/your name/i), { target: { value: 'Ada Lovelace' } });
    fireEvent.change(screen.getByLabelText(/ostwin api key/i), { target: { value: 'ostwin_key' } });
    expect(submit).toBeEnabled();

    fireEvent.click(submit);

    await waitFor(() => {
      expect(mocks.login).toHaveBeenCalledWith('ostwin_key', 'Ada Lovelace');
    });
  });
});
