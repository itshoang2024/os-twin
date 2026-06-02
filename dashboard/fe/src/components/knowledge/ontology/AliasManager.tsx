import React from 'react';
import type { OntologyProfile } from '@/hooks/use-ontology';
import { Field, keysOf, labelFor, SectionCard, Select, TextInput, cloneProfile } from './ontology-ui';

type AliasKind = 'relationship' | 'concept';

function aliasTitle(kind: AliasKind) {
  return kind === 'relationship' ? 'Relationship aliases' : 'Concept aliases';
}

export default function AliasManager({ profile, onChange }: { profile: OntologyProfile; onChange: (profile: OntologyProfile) => void }) {
  const relationIds = keysOf(profile.relationship_types);
  const conceptIds = keysOf(profile.concept_types);
  const [newAlias, setNewAlias] = React.useState('');
  const [newKind, setNewKind] = React.useState<AliasKind>('relationship');
  const [newTarget, setNewTarget] = React.useState(relationIds[0] ?? '');

  const targetIds = newKind === 'relationship' ? relationIds : conceptIds;

  React.useEffect(() => {
    if (!targetIds.includes(newTarget)) setNewTarget(targetIds[0] ?? '');
  }, [newKind, newTarget, targetIds]);

  const setAlias = (kind: AliasKind, alias: string, target: string) => {
    const cleanAlias = alias.trim();
    if (!cleanAlias || !target) return;
    const next = cloneProfile(profile);
    if (kind === 'relationship') {
      next.aliases = { ...(next.aliases ?? {}), [cleanAlias]: target };
    } else {
      next.concept_aliases = { ...(next.concept_aliases ?? {}), [cleanAlias]: target };
    }
    onChange(next);
  };

  const removeAlias = (kind: AliasKind, alias: string) => {
    const next = cloneProfile(profile);
    if (kind === 'relationship') delete next.aliases[alias];
    else {
      next.concept_aliases = { ...(next.concept_aliases ?? {}) };
      delete next.concept_aliases[alias];
    }
    onChange(next);
  };

  const renameAlias = (kind: AliasKind, alias: string, value: string, target: string) => {
    const next = cloneProfile(profile);
    const clean = value.trim();
    if (kind === 'relationship') {
      delete next.aliases[alias];
      if (clean) next.aliases[clean] = target;
    } else {
      next.concept_aliases = { ...(next.concept_aliases ?? {}) };
      delete next.concept_aliases[alias];
      if (clean) next.concept_aliases[clean] = target;
    }
    onChange(next);
  };

  const renderAliasRows = (kind: AliasKind, entries: [string, string][], ids: string[]) => (
    <div className="space-y-2">
      <p className="text-xs font-semibold" style={{ color: 'var(--color-text-main)' }}>{aliasTitle(kind)}</p>
      {entries.length === 0 ? <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>No {kind} aliases yet.</p> : entries.map(([alias, target]) => (
        <div key={`${kind}-${alias}`} className="grid gap-2 md:grid-cols-[1fr,1fr,auto]">
          <TextInput aria-label={`${kind} alias ${alias}`} value={alias} onChange={(e) => renameAlias(kind, alias, e.target.value, target)} />
          <Select aria-label={`${kind} alias target ${alias}`} value={target} onChange={(e) => setAlias(kind, alias, e.target.value)}>
            {ids.map((id) => <option key={id} value={id}>{labelFor(id, kind === 'relationship' ? profile.relationship_types[id]?.label : profile.concept_types[id]?.label)}</option>)}
          </Select>
          <button className="rounded-lg px-3 py-2 text-xs font-semibold text-danger hover:bg-danger/10" onClick={() => removeAlias(kind, alias)}>Remove</button>
        </div>
      ))}
    </div>
  );

  return (
    <SectionCard title="Alias Manager" subtitle="Map extracted relationship and concept labels to canonical enum values loaded from the active profile.">
      <div className="grid gap-4 lg:grid-cols-2">
        {renderAliasRows('relationship', Object.entries(profile.aliases ?? {}).sort(([a], [b]) => a.localeCompare(b)), relationIds)}
        {renderAliasRows('concept', Object.entries(profile.concept_aliases ?? {}).sort(([a], [b]) => a.localeCompare(b)), conceptIds)}
      </div>
      <div className="mt-4 grid gap-2 rounded-xl border p-3 md:grid-cols-[1fr,160px,1fr,auto]" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}>
        <Field label="New alias"><TextInput aria-label="New alias" value={newAlias} onChange={(e) => setNewAlias(e.target.value)} placeholder={newKind === 'relationship' ? 'requires' : 'capability'} /></Field>
        <Field label="Alias type"><Select aria-label="Alias type" value={newKind} onChange={(e) => setNewKind(e.target.value as AliasKind)}><option value="relationship">Relationship</option><option value="concept">Concept</option></Select></Field>
        <Field label="Canonical target"><Select aria-label="New alias target" value={newTarget} onChange={(e) => setNewTarget(e.target.value)}>{targetIds.map((id) => <option key={id} value={id}>{labelFor(id, newKind === 'relationship' ? profile.relationship_types[id]?.label : profile.concept_types[id]?.label)}</option>)}</Select></Field>
        <button className="self-end rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white disabled:opacity-50" disabled={!newAlias.trim() || !newTarget} onClick={() => { setAlias(newKind, newAlias, newTarget); setNewAlias(''); }}>Add alias</button>
      </div>
    </SectionCard>
  );
}
