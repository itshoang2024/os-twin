import React from 'react';
import type { OntologyProfile, OntologySummaryResponse } from '@/hooks/use-ontology';
import { keysOf, SectionCard } from './ontology-ui';

export default function ProfileSummary({ profile, summary, profileExists, defaultSuggested }: { profile: OntologyProfile; summary: OntologySummaryResponse | null; profileExists: boolean; defaultSuggested: boolean }) {
  const metrics = [
    ['Concept types', summary?.concept_type_count ?? keysOf(profile.concept_types).length],
    ['Relation types', summary?.relation_type_count ?? keysOf(profile.relationship_types).length],
    ['Aliases', summary?.alias_count ?? keysOf(profile.aliases).length],
    ['Candidates', summary?.candidate_count ?? 0],
  ];
  const status = profile.status ?? (profileExists ? 'active' : 'draft');
  const statusColor = status === 'deprecated' ? '#b45309' : status === 'draft' ? '#2563eb' : 'var(--color-primary)';
  const statusBg = status === 'deprecated' ? 'rgba(245,158,11,0.14)' : 'var(--color-primary-muted)';
  return (
    <SectionCard title="Profile Summary" subtitle={`${profile.profile_id} · v${profile.version}`} action={<div className="flex flex-wrap gap-2"><span className="rounded-full px-2 py-1 text-[11px] font-semibold" style={{ background: statusBg, color: statusColor }}>Status: {status}</span><span className="rounded-full px-2 py-1 text-[11px] font-semibold" style={{ background: defaultSuggested ? 'rgba(245,158,11,0.14)' : 'var(--color-primary-muted)', color: defaultSuggested ? '#b45309' : 'var(--color-primary)' }}>{profileExists ? 'Active profile' : 'Bootstrap suggested'}</span></div>}>
      <div className="grid gap-3 sm:grid-cols-4">
        {metrics.map(([label, value]) => <div key={label} className="rounded-xl border p-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}><div className="text-2xl font-semibold" style={{ color: 'var(--color-text-main)' }}>{value}</div><div className="text-[11px] uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-muted)' }}>{label}</div></div>)}
      </div>
    </SectionCard>
  );
}
