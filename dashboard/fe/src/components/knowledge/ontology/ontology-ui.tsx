import React from 'react';
import type { EvidenceArtifact, EvidenceAnchor, OntologyCandidate, OntologyProfile, OntologyValidationIssue, ProvenanceLinkDetail } from '@/hooks/use-ontology';

export function keysOf<T>(record: Record<string, T> | undefined): string[] {
  return Object.keys(record ?? {}).sort();
}

export function labelFor(id: string, label?: string) {
  return label || id.replaceAll('_', ' ').replace(/\b\w/g, (m) => m.toUpperCase());
}

export function parseCsv(value: string): string[] {
  return value.split(',').map((v) => v.trim()).filter(Boolean);
}

export function csv(value: string[] | undefined): string {
  return (value ?? []).join(', ');
}

export function validationErrorCount(issues: OntologyValidationIssue[]) {
  return issues.filter((issue) => issue.severity === 'error').length;
}

export function cloneProfile(profile: OntologyProfile): OntologyProfile {
  return JSON.parse(JSON.stringify(profile)) as OntologyProfile;
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-[11px] font-semibold uppercase tracking-[0.14em]" style={{ color: 'var(--color-text-muted)' }}>{label}</span>
      {children}
    </label>
  );
}

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`w-full rounded-lg border px-3 py-2 text-sm outline-none transition focus:ring-2 focus:ring-primary/20 ${props.className ?? ''}`} style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)', ...props.style }} />;
}

export function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`w-full rounded-lg border px-3 py-2 text-sm outline-none transition focus:ring-2 focus:ring-primary/20 ${props.className ?? ''}`} style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)', ...props.style }} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`w-full rounded-lg border px-3 py-2 text-sm outline-none transition focus:ring-2 focus:ring-primary/20 ${props.className ?? ''}`} style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)', ...props.style }} />;
}

export function SectionCard({ title, subtitle, children, action }: { title: string; subtitle?: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="rounded-2xl border p-4 shadow-sm" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>{title}</h3>
          {subtitle && <p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function IssueList({ issues }: { issues: OntologyValidationIssue[] }) {
  if (issues.length === 0) return null;
  return (
    <div className="space-y-2">
      {issues.map((issue, idx) => (
        <div key={`${issue.code}-${idx}`} className="rounded-xl border px-3 py-2 text-xs" style={{ borderColor: issue.severity === 'error' ? 'var(--color-danger)' : 'var(--color-border)', background: issue.severity === 'error' ? 'rgba(239,68,68,0.08)' : 'var(--color-background)' }}>
          <div className="flex items-center gap-2 font-semibold" style={{ color: issue.severity === 'error' ? 'var(--color-danger)' : 'var(--color-text-main)' }}>
            <span className="material-symbols-outlined text-[15px]">{issue.severity === 'error' ? 'error' : 'info'}</span>
            {issue.message}
          </div>
          <p className="mt-1" style={{ color: 'var(--color-text-muted)' }}>{issue.path} · {issue.code}{issue.suggested_fix ? ` · ${issue.suggested_fix}` : ''}</p>
        </div>
      ))}
    </div>
  );
}

export function updateProfileRecord<T extends { id: string }>(profile: OntologyProfile, key: 'relationship_types' | 'concept_types' | 'layers' | 'abstraction_levels' | 'metadata_fields', id: string, patch: Partial<T>): OntologyProfile {
  const next = cloneProfile(profile);
  const record = (next[key] ?? {}) as unknown as Record<string, T>;
  record[id] = { ...(record[id] ?? { id }), ...patch } as T;
  (next[key] as unknown as Record<string, T>) = record;
  return next;
}


const limitationLabels: Record<string, string> = {
  ocr_needed: 'OCR needed',
  conversion_needed: 'Conversion needed',
  failed: 'Failed',
  partial: 'Partial read',
  sampled: 'Sampled',
  unsupported: 'Unsupported',
  empty: 'No readable content',
};

export function formatEvidenceLocator(locator: EvidenceAnchor['locator'] | undefined): string {
  if (!locator) return 'No locator recorded';
  const parts: string[] = [];
  if (locator.page) parts.push(`page ${locator.page}`);
  if (locator.section) parts.push(`section ${locator.section}`);
  if (locator.heading) parts.push(`heading ${locator.heading}`);
  if (locator.row) parts.push(`row ${locator.row}`);
  if (locator.column) parts.push(`column ${locator.column}`);
  if (locator.line_start || locator.line_end) parts.push(`lines ${locator.line_start ?? '?'}-${locator.line_end ?? locator.line_start ?? '?'}`);
  if (locator.chunk_id !== undefined && locator.chunk_id !== null) parts.push(`chunk ${locator.chunk_id}`);
  if (locator.timestamp) parts.push(`time ${locator.timestamp}`);
  return parts.length ? parts.join(' · ') : 'Source-level locator';
}

export function evidenceStateLabel(artifact?: EvidenceArtifact | null): string {
  if (!artifact) return 'No source evidence';
  if (artifact.limitations?.length) return artifact.limitations.map((item) => limitationLabels[item] ?? labelFor(item)).join(', ');
  return labelFor(artifact.source_state || artifact.read_coverage || 'source');
}

export function EvidenceBadge({ artifact }: { artifact?: EvidenceArtifact | null }) {
  const limitation = Boolean(artifact?.limitations?.length);
  return (
    <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold" style={{ borderColor: limitation ? 'var(--color-warning)' : 'var(--color-border)', color: limitation ? 'var(--color-warning)' : 'var(--color-text-muted)', background: limitation ? 'rgba(245,158,11,0.08)' : 'var(--color-background)' }}>
      <span className="material-symbols-outlined text-[14px]">{artifact ? (limitation ? 'warning' : 'verified') : 'link_off'}</span>
      {evidenceStateLabel(artifact)}
    </span>
  );
}

export function EvidenceSourcePanel({ evidence, fallbackExcerpt }: { evidence?: ProvenanceLinkDetail | null; fallbackExcerpt?: string }) {
  const artifact = evidence?.artifact ?? null;
  const anchor = evidence?.anchor ?? null;
  if (!artifact && !anchor && !fallbackExcerpt) {
    return (
      <div className="rounded-xl border p-3 text-xs" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)', background: 'var(--color-background)' }}>
        No source evidence has been attached yet.
      </div>
    );
  }
  return (
    <div className="space-y-2 rounded-xl border p-3 text-xs" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}>
      <div className="flex flex-wrap items-center gap-2">
        <EvidenceBadge artifact={artifact} />
        {artifact?.source_type && <span style={{ color: 'var(--color-text-muted)' }}>{labelFor(artifact.source_type)}</span>}
        {artifact?.title && <span className="font-semibold" style={{ color: 'var(--color-text-main)' }}>{artifact.title}</span>}
      </div>
      {(anchor?.excerpt || fallbackExcerpt) && <p style={{ color: 'var(--color-text-main)' }}>“{anchor?.excerpt || fallbackExcerpt}”</p>}
      <p style={{ color: 'var(--color-text-muted)' }}>{formatEvidenceLocator(anchor?.locator)}</p>
      {artifact?.source_uri && <p className="truncate" title={artifact.source_uri} style={{ color: 'var(--color-text-muted)' }}>{artifact.source_uri}</p>}
    </div>
  );
}

export function CandidateEvidenceSummary({ candidate }: { candidate: OntologyCandidate }) {
  return <EvidenceSourcePanel evidence={candidate.source_evidence} fallbackExcerpt={candidate.sample_text} />;
}
