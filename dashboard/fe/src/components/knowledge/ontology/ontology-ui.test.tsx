import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { CandidateEvidenceSummary, EvidenceBadge, formatEvidenceLocator } from './ontology-ui';
import EvidenceFixturePanel from './EvidenceFixturePanel';


describe('ontology evidence UI helpers', () => {
  it('formats fine grained locators', () => {
    expect(formatEvidenceLocator({ page: 2, section: 'Risk', line_start: 4, line_end: 9, chunk_id: 'c1' })).toBe('page 2 · section Risk · lines 4-9 · chunk c1');
  });

  it('renders limitation badges for unread sources', () => {
    render(<EvidenceBadge artifact={{ id: 'artifact:1', source_type: 'image', source_state: 'ocr_needed', limitations: ['ocr_needed'] }} />);
    expect(screen.getByText('OCR needed')).toBeInTheDocument();
  });

  it('renders candidate evidence excerpt and source locator', () => {
    render(
      <CandidateEvidenceSummary
        candidate={{
          id: 'cand1',
          namespace: 'demo',
          candidate_type: 'relationship_type',
          source: 'extractor',
          original_label: 'blocks',
          confidence: 0.8,
          sample_text: 'Feature A blocks Feature B',
          status: 'pending',
          created_at: '2026-06-01T00:00:00Z',
          source_evidence: {
            artifact: { id: 'artifact:1', source_type: 'document', title: 'plan.md', source_state: 'read', limitations: [] },
            anchor: { id: 'anchor:1', artifact_id: 'artifact:1', excerpt: 'Feature A blocks Feature B', locator: { chunk_id: '0' }, extraction_method: 'parser' },
            provenance_link: { id: 'prov:1' },
          },
        }}
      />,
    );
    expect(screen.getByText('plan.md')).toBeInTheDocument();
    expect(screen.getByText('“Feature A blocks Feature B”')).toBeInTheDocument();
    expect(screen.getByText('chunk 0')).toBeInTheDocument();
  });

  it('renders the QA fixture readable, limitation, reusable, and empty evidence states', () => {
    render(<EvidenceFixturePanel />);
    expect(screen.getByText('Evidence and provenance source inspection')).toBeInTheDocument();
    expect(screen.getAllByText('company-plan.md').length).toBeGreaterThan(0);
    expect(screen.getAllByText('OCR needed').length).toBeGreaterThan(0);
    expect(screen.getByText(/share anchor:qa-readable-plan:c0/)).toBeInTheDocument();
    expect(screen.getByText('No source evidence has been attached yet.')).toBeInTheDocument();
  });
});
