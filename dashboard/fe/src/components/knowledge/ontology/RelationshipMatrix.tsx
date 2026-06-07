import React from 'react';
import type { OntologyProfile } from '@/hooks/use-ontology';
import { labelFor } from './ontology-ui';
import { patchRelationshipEndpoints } from './ontology-draft-commands';

export default function RelationshipMatrix({ profile, onChange, onSelectRelationship }: { profile: OntologyProfile; onChange: (profile: OntologyProfile) => void; onSelectRelationship?: (id: string) => void }) {
  const concepts = Object.keys(profile.concept_types ?? {});
  const relationships = Object.entries(profile.relationship_types ?? {});
  if (!concepts.length || !relationships.length) {
    return <div data-testid="relationship-matrix" className="rounded-xl border p-3 text-xs" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>Create at least two Object Types and one Relationship Type to inspect endpoint coverage.</div>;
  }
  const toggle = (relationshipId: string, source: string, target: string) => {
    const rel = profile.relationship_types[relationshipId];
    const sourceTypes = rel.allowed_source_types?.includes(source) ? (rel.allowed_source_types ?? []).filter((id) => id !== source) : Array.from(new Set([...(rel.allowed_source_types ?? []), source]));
    const targetTypes = rel.allowed_target_types?.includes(target) ? (rel.allowed_target_types ?? []).filter((id) => id !== target) : Array.from(new Set([...(rel.allowed_target_types ?? []), target]));
    onChange(patchRelationshipEndpoints(profile, relationshipId, sourceTypes, targetTypes));
  };
  return (
    <section data-testid="relationship-matrix" className="overflow-auto rounded-xl border p-3" style={{ borderColor: 'var(--color-border)' }}>
      <h4 className="mb-2 text-xs font-bold uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-muted)' }}>Relationship Matrix</h4>
      <table className="min-w-full text-xs"><thead><tr><th className="p-2 text-left">Relationship</th>{concepts.map((id) => <th key={id} className="p-2 text-left">→ {labelFor(id, profile.concept_types[id]?.label)}</th>)}</tr></thead><tbody>{relationships.map(([relId, rel]) => <tr key={relId} className="border-t" style={{ borderColor: 'var(--color-border)' }}><th className="p-2 text-left"><button type="button" onClick={() => onSelectRelationship?.(relId)} className="font-semibold text-primary">{labelFor(relId, rel.label)}</button><div style={{ color: 'var(--color-text-muted)' }}>{rel.family ?? 'semantic'}</div></th>{concepts.map((target) => <td key={target} className="p-2">{concepts.map((source) => { const active = (rel.allowed_source_types ?? []).includes(source) && (rel.allowed_target_types ?? []).includes(target); return <button key={`${source}-${target}`} type="button" aria-label={`${relId} ${source} to ${target}`} aria-pressed={active} onClick={() => toggle(relId, source, target)} className={`mr-1 mt-1 rounded-full border px-2 py-1 ${active ? 'bg-primary text-white' : ''}`} style={{ borderColor: 'var(--color-border)', color: active ? undefined : 'var(--color-text-main)' }}>{labelFor(source)}→{labelFor(target)}</button>; })}</td>)}</tr>)}</tbody></table>
    </section>
  );
}
