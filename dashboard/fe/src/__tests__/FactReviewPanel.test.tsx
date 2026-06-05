import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import FactReviewFixturePanel from '@/components/knowledge/nexus/FactReviewFixturePanel';

describe('FactReviewFixturePanel', () => {
  it('renders deterministic reviewed claims without backend namespace data', () => {
    render(<FactReviewFixturePanel />);

    expect(screen.getByTestId('fact-review-fixture-panel')).toBeInTheDocument();
    expect(screen.getByText('Facts review staging plane')).toBeInTheDocument();
    expect(screen.getByText('Acme Platform depends on Kafka for event streaming.')).toBeInTheDocument();
    expect(screen.getByText('Approved for promotion')).toBeInTheDocument();
    expect(screen.getAllByText(/source-backed/i).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Promote to edge' })).toHaveAttribute('href', '/knowledge/facts-fixture?promoted=1');
    expect(screen.getByRole('button', { name: 'Raise type candidate' })).toHaveAttribute('href', '/knowledge/facts-fixture?candidate=1');
  });

  it('renders browser-visible action states from URL-backed fixture flags', () => {
    render(<FactReviewFixturePanel promoted candidate approved />);

    expect(screen.getByText('edge edge:fact-approved-dependency')).toBeInTheDocument();
    expect(screen.getByText('candidate relationship-candidate:summarizes responsibility for')).toBeInTheDocument();
    expect(screen.getAllByText('Approved for promotion')).toHaveLength(2);
  });
});
