import React from 'react';
import type { OntologyConceptType, OntologyProfile, OntologySourceMapping } from '@/hooks/use-ontology';
import { Field, labelFor, SectionCard, Select, TextArea, TextInput } from './ontology-ui';
import { addMetadataFieldToObjectType, attachSourceMapping, patchObjectType } from './ontology-draft-commands';

export default function ObjectTypeEditor({ profile, conceptId, onChange }: { profile: OntologyProfile; conceptId: string; onChange: (profile: OntologyProfile) => void }) {
  const concept = profile.concept_types[conceptId];
  const [newProperty, setNewProperty] = React.useState('');
  const [sourceId, setSourceId] = React.useState('');
  const [fieldPath, setFieldPath] = React.useState('');
  if (!concept) return null;
  const graphDefaults = profile.graph_instruction?.concept_type_defaults?.[conceptId] ?? { concept_type: conceptId };
  const layerIds = Object.keys(profile.layers ?? {});
  const levelIds = Object.keys(profile.abstraction_levels ?? {});
  const patch = (payload: Partial<OntologyConceptType>) => onChange(patchObjectType(profile, conceptId, payload));
  const patchGraph = (payload: Record<string, unknown>) => onChange({ ...profile, graph_instruction: { ...(profile.graph_instruction ?? {}), concept_type_defaults: { ...(profile.graph_instruction?.concept_type_defaults ?? {}), [conceptId]: { ...graphDefaults, ...payload, concept_type: conceptId } } } });
  const mappings = concept.source_mappings ?? [];

  return (
    <SectionCard title="Object Type Editor" subtitle="Single inspector path for identity, properties, sources, lifecycle, and View-plane defaults.">
      <div className="grid gap-4">
        <section className="grid gap-3 md:grid-cols-2" data-testid="object-type-editor">
          <Field label="Label"><TextInput aria-label="Object editor label" value={concept.label ?? ''} onChange={(event) => patch({ label: event.target.value })} /></Field>
          <Field label="Lifecycle"><Select aria-label="Object editor lifecycle" value={String(concept.lifecycle_state ?? 'active')} onChange={(event) => patch({ lifecycle_state: event.target.value })}><option value="draft">draft</option><option value="active">active</option><option value="deprecated">deprecated</option><option value="retired">retired</option></Select></Field>
          <Field label="Layer"><Select aria-label="Object editor layer" value={String(concept.default_layer ?? concept.layer ?? '')} onChange={(event) => patch({ default_layer: event.target.value, layer: event.target.value })}>{layerIds.map((id) => <option key={id} value={id}>{labelFor(id, profile.layers[id]?.label)}</option>)}</Select></Field>
          <Field label="Abstraction"><Select aria-label="Object editor abstraction" value={String(concept.abstraction_level ?? '')} onChange={(event) => patch({ abstraction_level: event.target.value })}>{levelIds.map((id) => <option key={id} value={id}>{labelFor(id, profile.abstraction_levels[id]?.label)}</option>)}</Select></Field>
          <div className="md:col-span-2"><Field label="Description"><TextArea aria-label="Object editor description" value={concept.description ?? ''} onChange={(event) => patch({ description: event.target.value })} /></Field></div>
        </section>
        <section className="rounded-xl border p-3" style={{ borderColor: 'var(--color-border)' }}>
          <h4 className="text-xs font-bold uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-muted)' }}>Properties</h4>
          <div className="mt-2 flex flex-wrap gap-2">{(concept.metadata_fields ?? []).map((id) => <span key={id} className="rounded-full border px-2 py-1 text-xs" style={{ borderColor: 'var(--color-border)' }}>{labelFor(id, profile.metadata_fields[id]?.label)} · {profile.metadata_fields[id]?.field_type ?? 'string'}</span>)}</div>
          <div className="mt-3 flex gap-2"><TextInput aria-label="New object property label" value={newProperty} onChange={(event) => setNewProperty(event.target.value)} placeholder="Property label" /><button type="button" disabled={!newProperty.trim()} onClick={() => { const result = addMetadataFieldToObjectType(profile, conceptId, { label: newProperty }); onChange(result.profile); setNewProperty(''); }} className="rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">Add Property</button></div>
        </section>
        <section className="rounded-xl border p-3" style={{ borderColor: 'var(--color-border)' }}>
          <h4 className="text-xs font-bold uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-muted)' }}>Source mappings</h4>
          <div className="mt-2 space-y-1">{mappings.length ? mappings.map((mapping: OntologySourceMapping, index) => <p key={`${mapping.source_id}-${index}`} className="text-xs" style={{ color: 'var(--color-text-muted)' }}>{mapping.source_id || 'source'} · {mapping.field_path || 'field path pending'}</p>) : <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>No source mapping attached yet.</p>}</div>
          <div className="mt-3 grid gap-2 md:grid-cols-[1fr,1fr,auto]"><TextInput aria-label="Object editor source id" value={sourceId} onChange={(event) => setSourceId(event.target.value)} placeholder="source id" /><TextInput aria-label="Object editor source field path" value={fieldPath} onChange={(event) => setFieldPath(event.target.value)} placeholder="field path" /><button type="button" disabled={!sourceId.trim() && !fieldPath.trim()} onClick={() => { onChange(attachSourceMapping(profile, conceptId, { source_id: sourceId, field_path: fieldPath, source_label: sourceId })); setSourceId(''); setFieldPath(''); }} className="rounded-lg border px-3 py-2 text-xs font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Attach</button></div>
        </section>
        <section className="grid gap-3 rounded-xl border p-3 md:grid-cols-3" style={{ borderColor: 'var(--color-border)' }}>
          <Field label="View color"><TextInput aria-label="Object editor view color" type="color" value={String(graphDefaults.color ?? '#64748b')} onChange={(event) => patchGraph({ color: event.target.value })} /></Field>
          <Field label="View shape"><TextInput aria-label="Object editor view shape" value={String(graphDefaults.shape ?? 'rounded_rectangle')} onChange={(event) => patchGraph({ shape: event.target.value })} /></Field>
          <Field label="Label template"><TextInput aria-label="Object editor label template" value={String(graphDefaults.label_template ?? '{label}')} onChange={(event) => patchGraph({ label_template: event.target.value })} /></Field>
        </section>
      </div>
    </SectionCard>
  );
}
