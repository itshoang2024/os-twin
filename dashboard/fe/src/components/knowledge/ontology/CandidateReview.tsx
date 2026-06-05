import React from 'react';
import type { OntologyCandidate, OntologyProfile } from '@/hooks/use-ontology';
import { keysOf, labelFor, SectionCard, Select } from './ontology-ui';

interface CandidateReviewProps {
  profile: OntologyProfile;
  candidates: OntologyCandidate[];
  isLoading: boolean;
  onApprove: (candidate: OntologyCandidate) => Promise<void>;
  onMap: (candidate: OntologyCandidate, canonicalId: string) => Promise<void>;
  onReject: (candidate: OntologyCandidate) => Promise<void>;
  onBulkReject: (candidates: OntologyCandidate[]) => Promise<void>;
}

const SPEC_CANDIDATES = new Set(['concept_type', 'relationship_type', 'metadata_field', 'alias', 'validation_rule']);
const GRAPH_CANDIDATES = new Set(['node', 'edge']);
const MAPPABLE_CANDIDATES = new Set(['concept_type', 'relationship_type', 'alias']);

function candidateImpact(candidate: OntologyCandidate) {
  if (candidate.candidate_type === 'node') return 'Impact: create a graph instance through approve-write, kept human-unverified until reviewed.';
  if (candidate.candidate_type === 'edge') return 'Impact: create a graph relationship through approve-write with provenance attached.';
  if (candidate.candidate_type === 'metadata_field') return 'Impact: add a metadata field definition to the active ontology profile.';
  if (candidate.candidate_type === 'validation_rule') return 'Impact: add a validation rule to future profile and instance checks.';
  if (candidate.candidate_type === 'alias') return 'Impact: map this phrase as an alias instead of creating duplicate vocabulary.';
  if (candidate.candidate_type === 'relationship_type') return 'Impact: create a relationship type, or map this phrase to an existing relation alias.';
  return 'Impact: create a concept type, or map this phrase to an existing concept alias.';
}

function routeLabel(candidate: OntologyCandidate) {
  if (GRAPH_CANDIDATES.has(candidate.candidate_type)) return 'Graph plane';
  if (SPEC_CANDIDATES.has(candidate.candidate_type)) return 'Spec plane';
  return 'Review required';
}

function CandidatePayloadPreview({ candidate }: { candidate: OntologyCandidate }) {
  const payload = candidate.proposed_payload ?? {};
  const payloadEntries = Object.entries(payload).slice(0, 4);
  return (
    <div className="mt-2 grid gap-1 text-[11px]" style={{ color: 'var(--color-text-faint)' }}>
      <div>Source: {candidate.source} · Evidence: {candidate.source_evidence_ref ?? 'sample text only'} · Route: {routeLabel(candidate)}</div>
      <div>{candidateImpact(candidate)}</div>
      {payloadEntries.length > 0 && (
        <div className="rounded-lg border px-2 py-1" style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface-muted)' }}>
          Payload: {payloadEntries.map(([key, value]) => `${key}=${typeof value === 'object' ? JSON.stringify(value) : String(value)}`).join(' · ')}
        </div>
      )}
    </div>
  );
}

export default function CandidateReview({ profile, candidates, isLoading, onApprove, onMap, onReject, onBulkReject }: CandidateReviewProps) {
  const [selected, setSelected] = React.useState<Record<string, boolean>>({});
  const [mapping, setMapping] = React.useState<Record<string, string>>({});
  const canonicalOptions = React.useMemo(() => {
    const relationIds = keysOf(profile.relationship_types).map((id) => ({ id, label: labelFor(id, profile.relationship_types[id]?.label), group: 'Relationships' }));
    const conceptIds = keysOf(profile.concept_types).map((id) => ({ id, label: labelFor(id, profile.concept_types[id]?.label), group: 'Concepts' }));
    return [...relationIds, ...conceptIds];
  }, [profile]);
  const selectedCandidates = candidates.filter((candidate) => selected[candidate.id]);
  const countsByType = React.useMemo(() => candidates.reduce<Record<string, number>>((acc, candidate) => {
    acc[candidate.candidate_type] = (acc[candidate.candidate_type] ?? 0) + 1;
    return acc;
  }, {}), [candidates]);

  return (
    <SectionCard
      title="Candidate Review"
      subtitle="Review unknown extracted labels with evidence, payload previews, and governed Spec/Graph routing."
      action={<button className="rounded-lg border px-3 py-1.5 text-xs font-semibold disabled:opacity-50" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} disabled={selectedCandidates.length === 0} onClick={() => onBulkReject(selectedCandidates)}>Reject selected</button>}
    >
      <div className="mb-3 flex flex-wrap gap-2">
        {Object.entries(countsByType).map(([type, count]) => (
          <span key={type} className="rounded-full px-2 py-1 text-[11px]" style={{ background: 'var(--color-primary-muted)', color: 'var(--color-primary)' }}>{type}: {count}</span>
        ))}
      </div>
      {isLoading ? (
        <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading candidates…</p>
      ) : candidates.length === 0 ? (
        <div className="rounded-xl border p-4 text-sm" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>No pending ontology candidates.</div>
      ) : (
        <div className="space-y-3">
          {candidates.map((candidate) => {
            const target = mapping[candidate.id] ?? candidate.suggested_canonical ?? canonicalOptions[0]?.id ?? '';
            const canMap = MAPPABLE_CANDIDATES.has(candidate.candidate_type) && canonicalOptions.length > 0;
            return (
              <article key={candidate.id} className="rounded-xl border p-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}>
                <div className="flex flex-wrap items-start gap-3">
                  <input aria-label={`Select ${candidate.original_label}`} type="checkbox" checked={Boolean(selected[candidate.id])} onChange={(e) => setSelected((prev) => ({ ...prev, [candidate.id]: e.target.checked }))} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h4 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>{candidate.original_label}</h4>
                      <span className="rounded-full px-2 py-0.5 text-[11px]" style={{ background: 'var(--color-primary-muted)', color: 'var(--color-primary)' }}>{candidate.candidate_type}</span>
                      <span className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>{Math.round(candidate.confidence * 100)}% confidence</span>
                    </div>
                    <p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>{candidate.sample_text}</p>
                    <p className="mt-1 text-[11px]" style={{ color: 'var(--color-text-faint)' }}>Suggested: {candidate.suggested_canonical ?? 'none'} · Source hash: {candidate.source_hash || 'none'}</p>
                    <CandidatePayloadPreview candidate={candidate} />
                  </div>
                  <div className="flex min-w-[260px] flex-wrap gap-2">
                    <Select aria-label={`Map ${candidate.original_label}`} value={target} disabled={!canMap} onChange={(e) => setMapping((prev) => ({ ...prev, [candidate.id]: e.target.value }))}>{canonicalOptions.map((opt) => <option key={`${opt.group}-${opt.id}`} value={opt.id}>{opt.group}: {opt.label}</option>)}</Select>
                    <button className="rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white disabled:opacity-50" disabled={!canMap} onClick={() => onMap(candidate, target)}>Map</button>
                    <button className="rounded-lg border px-3 py-2 text-xs font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} onClick={() => onApprove(candidate)}>Approve</button>
                    <button className="rounded-lg px-3 py-2 text-xs font-semibold text-danger hover:bg-danger/10" onClick={() => onReject(candidate)}>Reject</button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </SectionCard>
  );
}
