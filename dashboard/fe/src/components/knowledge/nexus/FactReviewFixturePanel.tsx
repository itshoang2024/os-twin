import type { ReactNode } from 'react';
import type { OntologyFact } from '@/hooks/use-ontology';

const now = '2026-06-04T00:00:00.000Z';
const FIXTURE_PATH = '/knowledge/facts-fixture';

export interface FactReviewFixturePanelProps {
  promoted?: boolean;
  candidate?: boolean;
  approved?: boolean;
  rejected?: boolean;
}

function stateLabel(state: string) {
  switch (state) {
    case 'draft': return 'Draft claim';
    case 'assistive': return 'Assistive claim';
    case 'reviewed': return 'Reviewed claim';
    case 'approved': return 'Approved for promotion';
    case 'rejected': return 'Rejected claim';
    default: return state;
  }
}

function buildHref(next: Partial<FactReviewFixturePanelProps>) {
  const params = new URLSearchParams();
  if (next.promoted) params.set('promoted', '1');
  if (next.candidate) params.set('candidate', '1');
  if (next.approved) params.set('approved', '1');
  if (next.rejected) params.set('rejected', '1');
  const query = params.toString();
  return query ? `${FIXTURE_PATH}?${query}` : FIXTURE_PATH;
}

function getFixtureFacts(state: FactReviewFixturePanelProps): OntologyFact[] {
  return [
    {
      id: 'fact-approved-dependency',
      namespace: 'qa-facts-fixture',
      statement: 'Acme Platform depends on Kafka for event streaming.',
      subjects: [
        { kind: 'node', id: 'acme-platform', label: 'Acme Platform', concept_type: 'system' },
        { kind: 'node', id: 'kafka', label: 'Kafka', concept_type: 'technology' },
      ],
      subject_ids: ['acme-platform', 'kafka'],
      confidence: 0.91,
      review_state: 'approved',
      source: 'extraction',
      evidence_refs: ['qa-fixture:architecture-note#L12-L18'],
      provenance_refs: ['qa-fixture:epic006-browser'],
      suggested_mapping: { relationship_type: 'depends_on', source_id: 'acme-platform', target_id: 'kafka', source_kind: 'node', target_kind: 'node', confidence: 0.89 },
      source_hash: 'qa-epic006-fixture-approved',
      promoted_edge_id: state.promoted ? 'edge:fact-approved-dependency' : null,
      created_at: now,
      reviewed_at: now,
      reviewed_by: 'po-fixture',
      metadata: { relation: 'depends on', qa_fixture: true },
    },
    {
      id: 'fact-assistive-summary',
      namespace: 'qa-facts-fixture',
      statement: 'Assistant analysis suggests the onboarding guide summarizes support escalation responsibilities.',
      subjects: [
        { kind: 'candidate', id: 'onboarding-guide', label: 'Onboarding guide', concept_type: 'document' },
        { kind: 'label', id: 'support-escalation', label: 'Support escalation', concept_type: 'process' },
      ],
      subject_ids: ['onboarding-guide', 'support-escalation'],
      confidence: 0.67,
      review_state: state.rejected ? 'rejected' : state.approved ? 'approved' : 'assistive',
      source: 'assistant',
      evidence_refs: [],
      provenance_refs: ['qa-fixture:assistant-context'],
      suggested_mapping: null,
      source_hash: 'qa-epic006-fixture-assistive',
      promoted_edge_id: null,
      created_at: now,
      reviewed_at: state.approved || state.rejected ? now : null,
      reviewed_by: state.approved || state.rejected ? 'qa-fixture' : null,
      metadata: {
        relation: 'summarizes responsibility for',
        qa_fixture: true,
        ...(state.candidate ? { relationship_candidate_id: 'relationship-candidate:summarizes responsibility for' } : {}),
      },
    },
  ];
}

function ActionLink({ href, tone, children }: { href: string; tone: 'emerald' | 'rose' | 'blue' | 'amber'; children: ReactNode }) {
  const toneClass = {
    emerald: 'bg-emerald-500/20 text-emerald-100',
    rose: 'bg-rose-500/20 text-rose-100',
    blue: 'bg-blue-500/20 text-blue-100',
    amber: 'bg-amber-500/20 text-amber-100',
  }[tone];
  return <a role="button" className={`rounded px-2 py-1 text-xs ${toneClass}`} href={href}>{children}</a>;
}

function FactRow({ fact, fixtureState }: { fact: OntologyFact; fixtureState: FactReviewFixturePanelProps }) {
  const mapping = fact.suggested_mapping;
  return (
    <article className="rounded-lg border p-3 space-y-2" style={{ borderColor: 'var(--color-border)', background: 'rgba(255,255,255,0.04)' }}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>{fact.statement}</p>
        <span className="shrink-0 rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>
          {stateLabel(fact.review_state)}
        </span>
      </div>
      <div className="flex flex-wrap gap-1 text-[11px]" style={{ color: 'var(--color-text-muted)' }}>
        <span>confidence {(fact.confidence * 100).toFixed(0)}%</span>
        <span>•</span>
        <span>{fact.evidence_refs.length || fact.provenance_refs.length ? 'source-backed' : `${fact.source}-only`}</span>
        {fact.promoted_edge_id && <><span>•</span><span>edge {fact.promoted_edge_id}</span></>}
        {Boolean(fact.metadata?.relationship_candidate_id) && <><span>•</span><span>candidate {String(fact.metadata?.relationship_candidate_id)}</span></>}
      </div>
      {fact.subjects.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {fact.subjects.map(subject => (
            <span key={`${subject.kind}:${subject.id}`} className="rounded px-1.5 py-0.5 text-[11px]" style={{ background: 'rgba(99,102,241,0.14)', color: 'var(--color-text)' }}>
              {subject.label || subject.id}
            </span>
          ))}
        </div>
      )}
      <div className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>
        Suggested mapping: {mapping?.relationship_type || 'missing relationship type'} {mapping?.source_id && mapping?.target_id ? `(${mapping.source_id} → ${mapping.target_id})` : ''}
      </div>
      <div className="flex flex-wrap gap-2 pt-1">
        {fact.id === 'fact-approved-dependency' && (
          <>
            <ActionLink href={buildHref({ ...fixtureState, rejected: true })} tone="rose">Reject</ActionLink>
            <ActionLink href={buildHref({ ...fixtureState, promoted: true })} tone="blue">Promote to edge</ActionLink>
          </>
        )}
        {fact.id === 'fact-assistive-summary' && fact.review_state !== 'rejected' && (
          <>
            {fact.review_state !== 'approved' && <ActionLink href={buildHref({ ...fixtureState, approved: true, rejected: false })} tone="emerald">Approve</ActionLink>}
            <ActionLink href={buildHref({ ...fixtureState, rejected: true, approved: false })} tone="rose">Reject</ActionLink>
            <ActionLink href={buildHref({ ...fixtureState, candidate: true })} tone="amber">Raise type candidate</ActionLink>
          </>
        )}
      </div>
    </article>
  );
}

export default function FactReviewFixturePanel(props: FactReviewFixturePanelProps) {
  const fixtureFacts = getFixtureFacts(props);

  return (
    <main className="min-h-full overflow-auto bg-[var(--color-background)] p-6" data-testid="fact-review-fixture-panel">
      <div className="mx-auto max-w-3xl space-y-4">
        <header className="rounded-2xl border p-4" style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)' }}>
          <p className="text-xs font-semibold uppercase tracking-[0.2em]" style={{ color: 'var(--color-primary)' }}>EPIC-006 browser fixture</p>
          <h1 className="mt-2 text-2xl font-semibold" style={{ color: 'var(--color-text-main)' }}>Facts review staging plane</h1>
          <p className="mt-1 text-sm" style={{ color: 'var(--color-text-muted)' }}>Deterministic reviewed-claims surface for QA: facts remain advisory until approval and explicit promotion.</p>
        </header>
        <div className="rounded-2xl border" style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)' }}>
          <section className="border-t p-3 space-y-3" style={{ borderColor: 'var(--color-border)' }} aria-label="Fact review panel">
            <div>
              <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Fact review</h3>
              <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Claims stay advisory until approved and promoted into typed graph edges.</p>
            </div>
            <div className="space-y-2">
              {fixtureFacts.map(fact => <FactRow key={fact.id} fact={fact} fixtureState={props} />)}
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
