import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import OntologyFixturePanel from '@/components/knowledge/ontology/OntologyFixturePanel';

describe('OntologyFixturePanel', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders a sanctioned local-only launcher with pack and blank previews', () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);

    render(<OntologyFixturePanel />);

    expect(screen.getByTestId('ontology-fixture-panel')).toBeInTheDocument();
    expect(screen.getByTestId('ontology-unit-launcher')).toBeInTheDocument();
    expect(screen.getByText(/does not call protected APIs/i)).toBeInTheDocument();

    const gallery = screen.getByTestId('ontology-template-gallery');
    expect(within(gallery).getByText(/Blank profile/i)).toBeInTheDocument();
    expect(within(gallery).getByText(/QA Starting Strategy Pack/i)).toBeInTheDocument();
    expect(within(gallery).getAllByText(/Template preview — not installed yet/i).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByTestId('imported-knowledge-summary')).toHaveTextContent(/Blocks → anchor-blocks/i);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('opens blank and assistant paths as local preview or staged proposal only', () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);

    render(<OntologyFixturePanel />);
    fireEvent.click(within(screen.getByTestId('ontology-template-gallery')).getByText(/Blank profile/i));

    expect(screen.getByTestId('ontology-schema-canvas')).toHaveTextContent(/Add your first object type/i);
    expect(screen.getByTestId('ontology-fixture-network-log')).toHaveTextContent(/profile write skipped/i);
    expect(fetchSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /Back to launcher/i }));
    fireEvent.click(screen.getByText(/Ask AI to draft/i));

    expect(screen.getByTestId('ontology-assistant-proposals')).toHaveTextContent(/not published/i);
    expect(screen.getByTestId('ontology-assistant-proposals')).toHaveTextContent(/anchor-blocks/i);
    expect(screen.getByTestId('ontology-fixture-network-log')).toHaveTextContent(/staged proposal not published/i);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
