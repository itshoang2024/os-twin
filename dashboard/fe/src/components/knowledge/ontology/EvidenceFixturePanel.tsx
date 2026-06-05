import React from 'react';
import { CandidateEvidenceSummary, EvidenceBadge, EvidenceSourcePanel } from './ontology-ui';
import type { OntologyCandidate, ProvenanceLinkDetail } from '@/hooks/use-ontology';

const readableEvidence: ProvenanceLinkDetail = {
  artifact: {
    id: 'artifact:qa-readable-plan',
    source_type: 'document',
    source_uri: 'file:///qa-fixtures/company-plan.md',
    title: 'company-plan.md',
    checksum: 'sha256:readable-fixture',
    read_coverage: 'full',
    source_state: 'read',
    limitations: [],
    metadata: { extension: '.md', file_size: 1842 },
  },
  anchor: {
    id: 'anchor:qa-readable-plan:c0',
    artifact_id: 'artifact:qa-readable-plan',
    excerpt: 'The Support Portal initiative depends on the Customer Account model before rollout.',
    locator: { page: 1, section: 'Rollout dependencies', heading: 'Support Portal', line_start: 12, line_end: 14, chunk_id: '0' },
    extraction_method: 'parser',
    confidence: 1,
  },
  provenance_link: {
    id: 'prov:qa-candidate-support-portal',
    subject_type: 'candidate',
    subject_id: 'candidate:qa-support-portal',
    relation: 'derived_from',
  },
};

const reusedEvidence: ProvenanceLinkDetail = {
  ...readableEvidence,
  provenance_link: {
    id: 'prov:qa-fact-support-portal',
    subject_type: 'fact',
    subject_id: 'fact:qa-support-portal-dependency',
    relation: 'supports',
  },
};

const limitationEvidence: ProvenanceLinkDetail = {
  artifact: {
    id: 'artifact:qa-image-only',
    source_type: 'image',
    source_uri: 'file:///qa-fixtures/whiteboard-scan.png',
    title: 'whiteboard-scan.png',
    checksum: 'sha256:image-fixture',
    read_coverage: 'unread',
    source_state: 'ocr_needed',
    limitations: ['ocr_needed'],
    metadata: { extension: '.png', file_size: 4096 },
  },
  anchor: null,
  provenance_link: null,
};

const candidate: OntologyCandidate = {
  id: 'candidate:qa-support-portal',
  namespace: 'qa-evidence-fixture',
  candidate_type: 'relationship_type',
  source: 'fixture',
  original_label: 'depends_on',
  normalized_label: 'depends_on',
  suggested_canonical: 'depends_on',
  confidence: 0.86,
  sample_text: 'The Support Portal initiative depends on the Customer Account model before rollout.',
  status: 'pending',
  source_hash: 'readable-fixture',
  source_evidence_ref: 'prov:qa-candidate-support-portal',
  source_evidence: readableEvidence,
  created_at: '2026-06-03T00:00:00Z',
  metadata: { fixture: true },
};

export default function EvidenceFixturePanel() {
  return (
    <main className="h-full overflow-auto bg-[var(--color-background)] p-6" data-testid="evidence-fixture-panel">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="rounded-3xl border p-6 shadow-sm" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.2em]" style={{ color: 'var(--color-text-muted)' }}>EPIC-003 QA Fixture</p>
              <h1 className="mt-2 text-2xl font-black" style={{ color: 'var(--color-text-main)' }}>Evidence and provenance source inspection</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6" style={{ color: 'var(--color-text-muted)' }}>
                Deterministic browser-test fixture for source badges, locator details, excerpt rendering, limitation states, and provenance reuse. It does not call the backend, so QA can capture evidence even when local API authentication is unavailable.
              </p>
            </div>
            <EvidenceBadge artifact={readableEvidence.artifact} />
          </div>
        </header>

        <section className="grid gap-4 md:grid-cols-2">
          <article className="rounded-2xl border p-4" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
            <h2 className="text-sm font-bold" style={{ color: 'var(--color-text-main)' }}>Readable candidate evidence</h2>
            <p className="mb-3 mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>Shows a concrete source anchor, review excerpt, and locator beyond filename.</p>
            <CandidateEvidenceSummary candidate={candidate} />
          </article>

          <article className="rounded-2xl border p-4" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
            <h2 className="text-sm font-bold" style={{ color: 'var(--color-text-main)' }}>Unread image-only source</h2>
            <p className="mb-3 mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>Marks OCR-needed sources without fabricating a supporting evidence anchor.</p>
            <EvidenceSourcePanel evidence={limitationEvidence} />
          </article>
        </section>

        <section className="grid gap-4 md:grid-cols-2">
          <article className="rounded-2xl border p-4" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
            <h2 className="text-sm font-bold" style={{ color: 'var(--color-text-main)' }}>Reusable provenance anchor</h2>
            <p className="mb-3 mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>The same anchor can support a second subject through a separate provenance link.</p>
            <EvidenceSourcePanel evidence={reusedEvidence} />
            <p className="mt-3 rounded-xl px-3 py-2 text-xs" style={{ background: 'var(--color-background)', color: 'var(--color-text-muted)' }}>
              Provenance links: prov:qa-candidate-support-portal and prov:qa-fact-support-portal share anchor:qa-readable-plan:c0.
            </p>
          </article>

          <article className="rounded-2xl border p-4" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
            <h2 className="text-sm font-bold" style={{ color: 'var(--color-text-main)' }}>Empty source state</h2>
            <p className="mb-3 mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>Confirms candidates without source support do not imply evidence.</p>
            <EvidenceSourcePanel />
          </article>
        </section>
      </div>
    </main>
  );
}
