'use client';

import React from 'react';
import { useState } from 'react';
import { useOntologyFacts, type OntologyFact } from '@/hooks/use-ontology';

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

function FactRow({ fact, onApprove, onReject, onPromote, onRaiseCandidate }: {
  fact: OntologyFact;
  onApprove: (fact: OntologyFact) => void;
  onReject: (fact: OntologyFact) => void;
  onPromote: (fact: OntologyFact) => void;
  onRaiseCandidate: (fact: OntologyFact) => void;
}) {
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
        {fact.review_state !== 'approved' && fact.review_state !== 'rejected' && (
          <button className="rounded px-2 py-1 text-xs bg-emerald-500/20 text-emerald-100" onClick={() => onApprove(fact)}>Approve</button>
        )}
        {fact.review_state !== 'rejected' && (
          <button className="rounded px-2 py-1 text-xs bg-rose-500/20 text-rose-100" onClick={() => onReject(fact)}>Reject</button>
        )}
        {fact.review_state === 'approved' && mapping?.relationship_type && (
          <button className="rounded px-2 py-1 text-xs bg-blue-500/20 text-blue-100" onClick={() => onPromote(fact)}>Promote to edge</button>
        )}
        {!mapping?.relationship_type && (
          <button className="rounded px-2 py-1 text-xs bg-amber-500/20 text-amber-100" onClick={() => onRaiseCandidate(fact)}>Raise type candidate</button>
        )}
      </div>
    </article>
  );
}

interface FactReviewPanelProps {
  namespace: string | null;
  subjectId?: string | null;
  /**
   * Deterministic browser-QA mode: renders local facts and simulates review actions
   * without requiring an authenticated backend namespace. Production callers omit it.
   */
  fixtureFacts?: OntologyFact[];
}

export default function FactReviewPanel({ namespace, subjectId, fixtureFacts }: FactReviewPanelProps) {
  const isFixture = Boolean(fixtureFacts);
  const { facts: apiFacts, isLoading, error, reviewFact, promoteFactToEdge, raiseRelationshipCandidate } = useOntologyFacts(isFixture ? null : namespace);
  const [localFacts, setLocalFacts] = useState<OntologyFact[]>(fixtureFacts ?? []);


  const facts = isFixture ? localFacts : apiFacts;
  const visibleFacts = subjectId ? facts.filter(fact => fact.subject_ids.includes(subjectId) || fact.subjects.some(subject => subject.id === subjectId || subject.label === subjectId)) : facts;
  const topFacts = visibleFacts.slice(0, 6);

  const handleApprove = async (item: OntologyFact) => {
    if (isFixture) {
      setLocalFacts(current => current.map(fact => fact.id === item.id ? { ...fact, review_state: 'approved', reviewed_at: new Date().toISOString(), reviewed_by: 'qa-fixture' } : fact));
      return;
    }
    await reviewFact(item.id, 'approved');
  };

  const handleReject = async (item: OntologyFact) => {
    if (isFixture) {
      setLocalFacts(current => current.map(fact => fact.id === item.id ? { ...fact, review_state: 'rejected', reviewed_at: new Date().toISOString(), reviewed_by: 'qa-fixture' } : fact));
      return;
    }
    await reviewFact(item.id, 'rejected');
  };

  const handlePromote = async (item: OntologyFact) => {
    if (isFixture) {
      setLocalFacts(current => current.map(fact => fact.id === item.id ? { ...fact, promoted_edge_id: fact.promoted_edge_id ?? `edge:${fact.id}` } : fact));
      return;
    }
    await promoteFactToEdge(item.id, item.suggested_mapping || {});
  };

  const handleRaiseCandidate = async (item: OntologyFact) => {
    const relationshipLabel = String(item.metadata?.relation || 'related to');
    if (isFixture) {
      setLocalFacts(current => current.map(fact => fact.id === item.id ? { ...fact, metadata: { ...fact.metadata, relationship_candidate_id: `relationship-candidate:${relationshipLabel}` } } : fact));
      return;
    }
    await raiseRelationshipCandidate(item.id, relationshipLabel);
  };

  return (
    <section className="border-t p-3 space-y-3" style={{ borderColor: 'var(--color-border)' }} aria-label="Fact review panel">
      <div>
        <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Fact review</h3>
        <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Claims stay advisory until approved and promoted into typed graph edges.</p>
      </div>
      {isLoading && <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Loading facts…</p>}
      {error && <p className="text-xs text-rose-200">{error}</p>}
      {!isLoading && topFacts.length === 0 && (
        <div className="rounded-lg border border-dashed p-3 text-xs" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>
          No reviewed claims yet. Extraction and assistant output can stage source-backed facts here without changing graph truth.
        </div>
      )}
      <div className="space-y-2">
        {topFacts.map(fact => (
          <FactRow
            key={fact.id}
            fact={fact}
            onApprove={handleApprove}
            onReject={handleReject}
            onPromote={handlePromote}
            onRaiseCandidate={handleRaiseCandidate}
          />
        ))}
      </div>
    </section>
  );
}
