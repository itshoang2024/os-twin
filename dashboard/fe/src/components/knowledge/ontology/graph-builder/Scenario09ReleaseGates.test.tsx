import React from 'react';
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import OntologyGraphBuilderPage from './OntologyGraphBuilderPage';
import { EnterpriseMapProjectionAdapter } from './EnterpriseMapProjectionAdapter';
import { canonicalErrorDetails } from './useOntologyGraphBuilderData';
import { canonicalErrorFixtures, getProjectionFixture } from './mock-fixtures';
import { CANONICAL_ERROR_CODES, REQUIRED_ONTOLOGY_GRAPH_FEATURE_FLAGS } from './types';

describe('Scenario 09 cross-cutting contracts and release gates', () => {
  it('keeps generated types, canonical error fixtures, and parser behavior aligned', () => {
    expect(Object.keys(canonicalErrorFixtures).sort()).toEqual([...CANONICAL_ERROR_CODES].sort());

    for (const code of CANONICAL_ERROR_CODES) {
      const fixture = canonicalErrorFixtures[code];
      expect(fixture.error.code).toBe(code);
      expect(fixture.error.message).toEqual(expect.any(String));
      expect(fixture.request_id).toMatch(/^mock-/);
      const details = canonicalErrorDetails(Object.assign(new Error(fixture.error.message), { data: fixture }));
      expect(details).toMatchObject({ code, message: fixture.error.message, requestId: fixture.request_id });
    }

    expect(canonicalErrorFixtures.VALIDATION_FAILED.error.validation_issues).toContain('filters.badges must be an array');
  });

  it('asserts projection minimum fields, meta requirements, feature flags, and permission summary', () => {
    for (const fixture of ['empty', 'basic', 'redacted', 'large'] as const) {
      const projection = getProjectionFixture(fixture, 'release-gate-namespace');
      expect(Array.isArray(projection.nodes)).toBe(true);
      expect(Array.isArray(projection.edges)).toBe(true);
      expect(projection.stats).toEqual(expect.objectContaining({ node_count: expect.any(Number), edge_count: expect.any(Number), truncated: expect.any(Boolean) }));
      expect(projection.meta).toEqual(expect.objectContaining({
        namespace: 'release-gate-namespace',
        generated_at: expect.any(String),
        truncated: expect.any(Boolean),
        event_limit: 3,
        warnings: expect.any(Array),
      }));
      for (const flag of REQUIRED_ONTOLOGY_GRAPH_FEATURE_FLAGS) {
        expect(projection.meta.feature_flags?.[flag]).toBe(true);
      }
      expect(projection.permissions).toEqual(expect.objectContaining({
        level: expect.stringMatching(/read|limited|blocked/),
        redacted_nodes: expect.any(Number),
        redacted_edges: expect.any(Number),
        notice: expect.any(String),
      }));
    }

    const large = getProjectionFixture('large', 'release-gate-namespace');
    expect(large.meta.node_limit).toBe(18);
    expect(large.meta.edge_limit).toBe(17);
    expect(large.meta.next_cursor).toBe('mock-next-cursor');
  });

  it('redacts sensitive values globally in fixtures and adapter output', () => {
    const projection = getProjectionFixture('redacted', 'release-gate-namespace');
    const serialized = JSON.stringify(projection);
    expect(serialized).not.toContain('123-45-6789');
    expect(serialized).not.toContain('secret-token');
    expect(projection.permissions?.redacted_nodes).toBeGreaterThan(0);

    const viewModel = EnterpriseMapProjectionAdapter.toCanvasViewModel(projection);
    const restricted = viewModel.nodes.find((node) => node.id === 'object.restricted-person');
    expect(restricted?.redacted).toBe(true);
    expect(restricted?.properties).toEqual({});
    expect(JSON.stringify(viewModel)).not.toContain('123-45-6789');
    expect(JSON.stringify(viewModel)).not.toContain('secret-token');
  });

  it('renders release-gate selectors for loading, empty, error, permission, redaction, and feature-disabled states', async () => {
    const emptyRender = render(<OntologyGraphBuilderPage namespace="qa-scenario09-empty" initialFixture="empty" />);
    expect(screen.getByTestId('loading-skeleton')).toHaveTextContent('Loading graph projection');
    expect(await screen.findByTestId('empty-state')).toHaveTextContent('Start with object search');
    emptyRender.unmount();

    const errorRender = render(<OntologyGraphBuilderPage namespace="qa-scenario09-error" initialFixture="error" />);
    expect(await screen.findByTestId('canonical-error-message')).toHaveTextContent('FEATURE_DISABLED');
    expect(screen.getByTestId('request-id')).toHaveTextContent('mock-feature-disabled');
    expect(screen.getByTestId('retry-button')).toHaveAccessibleName('Retry');
    errorRender.unmount();

    render(<OntologyGraphBuilderPage namespace="qa-scenario09-basic" initialFixture="basic" />);
    await screen.findByTestId('graph-canvas');
    expect(screen.getAllByTestId('permission-summary')[0]).toHaveTextContent('Permission summary');
    expect(screen.getAllByTestId('redaction-notice')[0]).toHaveTextContent('No permission redaction');
    expect(screen.getByTestId('feature-disabled-state')).toHaveTextContent('Unsupported backend-only functions remain disabled');
  });

  it('keeps modal controls keyboard reachable and closes dialogs with Escape', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-scenario09-a11y" initialFixture="basic" />);
    await screen.findByTestId('graph-canvas');

    fireEvent.click(screen.getByRole('button', { name: 'Search objects' }));
    const searchDialog = await screen.findByRole('dialog', { name: 'Object search' });
    expect(within(searchDialog).getByRole('button', { name: 'Search' })).toBeEnabled();
    expect(within(searchDialog).getByRole('button', { name: 'Close object search modal' })).toBeEnabled();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByTestId('search-modal')).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Share' }));
    const shareDialog = await screen.findByRole('dialog', { name: 'Share graph' });
    expect(within(shareDialog).getByRole('button', { name: 'Preview limited viewer' })).toBeEnabled();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByTestId('share-graph-modal')).not.toBeInTheDocument());
  });

  it('keeps redaction notices visible across inspector tabs without leaking sensitive values', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-scenario09-redacted" initialFixture="redacted" />);
    const redactedNode = await screen.findByTestId('redacted-node');
    fireEvent.click(redactedNode);

    fireEvent.click(screen.getByTestId('inspector-tab-properties'));
    expect(await screen.findByText('Properties redacted by permission policy.')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('123-45-6789');
    expect(document.body).not.toHaveTextContent('secret-token');

    fireEvent.click(screen.getByRole('button', { name: 'Permissions' }));
    expect(screen.getAllByTestId('permission-summary').at(-1)).toHaveTextContent('limited');
    expect(document.body).toHaveTextContent('Sensitive identity data is hidden in mock mode.');
    expect(document.body).not.toHaveTextContent('123-45-6789');
    expect(document.body).not.toHaveTextContent('secret-token');
  });

  it('autofocuses search input and exposes share redaction preview notice', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-scenario09-modal-focus" initialFixture="basic" />);
    await screen.findByTestId('graph-canvas');

    fireEvent.click(screen.getByRole('button', { name: 'Search objects' }));
    const searchDialog = await screen.findByRole('dialog', { name: 'Object search' });
    await waitFor(() => expect(document.activeElement).toBe(within(searchDialog).getByPlaceholderText('Search objects')));
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByTestId('search-modal')).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Share' }));
    const shareDialog = await screen.findByRole('dialog', { name: 'Share graph' });
    fireEvent.click(within(shareDialog).getByRole('button', { name: 'Preview limited viewer' }));
    expect(await within(shareDialog).findByTestId('redaction-notice')).toHaveTextContent('limited viewers see topology only');
  });

});
