import React from 'react';
import type { OntologyProfile, OntologyValidationIssue } from '@/hooks/use-ontology';

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
