import React from 'react';
import type { OntologyCandidate, OntologyProfile } from '@/hooks/use-ontology';
import { keysOf, labelFor, SectionCard, Select } from './ontology-ui';

export default function CandidateReview({ profile, candidates, isLoading, onApprove, onMap, onReject, onBulkReject }: { profile: OntologyProfile; candidates: OntologyCandidate[]; isLoading: boolean; onApprove: (candidate: OntologyCandidate) => Promise<void>; onMap: (candidate: OntologyCandidate, canonicalId: string) => Promise<void>; onReject: (candidate: OntologyCandidate) => Promise<void>; onBulkReject: (candidates: OntologyCandidate[]) => Promise<void>; }) {
  const [selected, setSelected] = React.useState<Record<string, boolean>>({});
  const [mapping, setMapping] = React.useState<Record<string, string>>({});
  const canonicalOptions = React.useMemo(() => {
    const relationIds = keysOf(profile.relationship_types).map((id) => ({ id, label: labelFor(id, profile.relationship_types[id]?.label), group: 'Relationships' }));
    const conceptIds = keysOf(profile.concept_types).map((id) => ({ id, label: labelFor(id, profile.concept_types[id]?.label), group: 'Concepts' }));
    return [...relationIds, ...conceptIds];
  }, [profile]);
  const selectedCandidates = candidates.filter((candidate) => selected[candidate.id]);
  return (
    <SectionCard title="Candidate Review" subtitle="Review unknown extracted labels with source samples and suggested mappings." action={<button className="rounded-lg border px-3 py-1.5 text-xs font-semibold disabled:opacity-50" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} disabled={selectedCandidates.length === 0} onClick={() => onBulkReject(selectedCandidates)}>Reject selected</button>}>
      {isLoading ? <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading candidates…</p> : candidates.length === 0 ? <div className="rounded-xl border p-4 text-sm" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>No pending ontology candidates.</div> : <div className="space-y-3">{candidates.map((candidate) => {
        const target = mapping[candidate.id] ?? candidate.suggested_canonical ?? canonicalOptions[0]?.id ?? '';
        return <article key={candidate.id} className="rounded-xl border p-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}>
          <div className="flex flex-wrap items-start gap-3">
            <input aria-label={`Select ${candidate.original_label}`} type="checkbox" checked={Boolean(selected[candidate.id])} onChange={(e) => setSelected((prev) => ({ ...prev, [candidate.id]: e.target.checked }))} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2"><h4 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>{candidate.original_label}</h4><span className="rounded-full px-2 py-0.5 text-[11px]" style={{ background: 'var(--color-primary-muted)', color: 'var(--color-primary)' }}>{candidate.candidate_type}</span><span className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>{Math.round(candidate.confidence * 100)}% confidence</span></div>
              <p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>{candidate.sample_text}</p>
              <p className="mt-1 text-[11px]" style={{ color: 'var(--color-text-faint)' }}>Source: {candidate.source} · Suggested: {candidate.suggested_canonical ?? 'none'}</p>
            </div>
            <div className="flex min-w-[260px] flex-wrap gap-2">
              <Select aria-label={`Map ${candidate.original_label}`} value={target} onChange={(e) => setMapping((prev) => ({ ...prev, [candidate.id]: e.target.value }))}>{canonicalOptions.map((opt) => <option key={`${opt.group}-${opt.id}`} value={opt.id}>{opt.group}: {opt.label}</option>)}</Select>
              <button className="rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white" onClick={() => onMap(candidate, target)}>Map</button>
              <button className="rounded-lg border px-3 py-2 text-xs font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} onClick={() => onApprove(candidate)}>Approve</button>
              <button className="rounded-lg px-3 py-2 text-xs font-semibold text-danger hover:bg-danger/10" onClick={() => onReject(candidate)}>Reject</button>
            </div>
          </div>
        </article>;
      })}</div>}
    </SectionCard>
  );
}
