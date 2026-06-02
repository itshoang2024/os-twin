import React from 'react';
import type { OntologyProfile, OntologyRelationshipType } from '@/hooks/use-ontology';
import { csv, Field, keysOf, labelFor, parseCsv, SectionCard, Select, TextInput, updateProfileRecord } from './ontology-ui';

export default function RelationshipStudio({ profile, onChange }: { profile: OntologyProfile; onChange: (profile: OntologyProfile) => void }) {
  const ids = keysOf(profile.relationship_types);
  const [selected, setSelected] = React.useState(ids[0] ?? '');
  React.useEffect(() => { if (!selected && ids[0]) setSelected(ids[0]); }, [ids, selected]);
  const relation = selected ? profile.relationship_types[selected] : null;
  const conceptIds = keysOf(profile.concept_types);
  const familyOptions = Array.from(new Set(ids.map((id) => profile.relationship_types[id]?.family).filter(Boolean))) as string[];
  const styleOptions = Array.from(new Set(['solid', ...ids.map((id) => profile.relationship_types[id]?.style ?? profile.relationship_types[id]?.display_style).filter(Boolean)])) as string[];
  const patch = (patch: Partial<OntologyRelationshipType>) => relation && onChange(updateProfileRecord<OntologyRelationshipType>(profile, 'relationship_types', relation.id, patch));
  return (
    <SectionCard title="Relationship Studio" subtitle="Edit canonical relation labels, families, inverses, constraints, weights, and display style.">
      <div className="grid gap-4 lg:grid-cols-[260px,1fr]">
        <div className="space-y-2">{ids.map((id) => <button key={id} onClick={() => setSelected(id)} className="w-full rounded-xl border px-3 py-2 text-left text-sm transition hover:bg-surface-hover" style={{ borderColor: selected === id ? 'var(--color-primary)' : 'var(--color-border)', background: selected === id ? 'var(--color-primary-muted)' : 'var(--color-background)', color: selected === id ? 'var(--color-primary)' : 'var(--color-text-main)' }}>{labelFor(id, profile.relationship_types[id]?.label)}<div className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>{profile.relationship_types[id]?.family || 'No family'}</div></button>)}</div>
        {relation && <div className="grid gap-3 md:grid-cols-2">
          <Field label="Canonical label"><TextInput aria-label="Canonical type label" value={relation.label} onChange={(e) => patch({ label: e.target.value })} /></Field>
          <Field label="Family"><Select aria-label="Relationship family" value={relation.family ?? ''} onChange={(e) => patch({ family: e.target.value })}><option value="">None</option>{familyOptions.map((f) => <option key={f} value={f}>{f}</option>)}</Select></Field>
          <Field label="Inverse"><Select aria-label="Inverse relationship" value={relation.inverse ?? ''} onChange={(e) => patch({ inverse: e.target.value || undefined })}><option value="">None</option>{ids.filter((id) => id !== relation.id).map((id) => <option key={id} value={id}>{labelFor(id, profile.relationship_types[id]?.label)}</option>)}</Select></Field>
          <Field label="Weight"><TextInput aria-label="Relationship weight" type="number" min="0" max="1" step="0.05" value={relation.weight ?? 0} onChange={(e) => patch({ weight: Number(e.target.value) })} /></Field>
          <Field label="Allowed source types"><TextInput aria-label="Allowed source types" value={csv(relation.allowed_source_types)} onChange={(e) => patch({ allowed_source_types: parseCsv(e.target.value).filter((id) => conceptIds.includes(id)) })} placeholder={conceptIds.join(', ')} /></Field>
          <Field label="Allowed target types"><TextInput aria-label="Allowed target types" value={csv(relation.allowed_target_types)} onChange={(e) => patch({ allowed_target_types: parseCsv(e.target.value).filter((id) => conceptIds.includes(id)) })} placeholder={conceptIds.join(', ')} /></Field>
          <Field label="Display style"><Select aria-label="Display style" value={relation.style ?? relation.display_style ?? 'solid'} onChange={(e) => patch({ style: e.target.value })}>{styleOptions.map((s) => <option key={s} value={s}>{s}</option>)}</Select></Field>
        </div>}
      </div>
    </SectionCard>
  );
}
