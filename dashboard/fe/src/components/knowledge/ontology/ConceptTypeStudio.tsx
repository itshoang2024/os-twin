import React from 'react';
import type { OntologyAbstractionLevel, OntologyConceptType, OntologyLayer, OntologyMetadataField, OntologyProfile } from '@/hooks/use-ontology';
import { csv, Field, keysOf, labelFor, parseCsv, SectionCard, Select, TextInput, updateProfileRecord } from './ontology-ui';

export default function ConceptTypeStudio({ profile, onChange }: { profile: OntologyProfile; onChange: (profile: OntologyProfile) => void }) {
  const ids = keysOf(profile.concept_types);
  const [selected, setSelected] = React.useState(ids[0] ?? '');
  React.useEffect(() => { if (!selected && ids[0]) setSelected(ids[0]); }, [ids, selected]);
  const concept = selected ? profile.concept_types[selected] : null;
  const levelIds = keysOf(profile.abstraction_levels);
  const layerIds = keysOf(profile.layers);
  const metadataIds = keysOf(profile.metadata_fields);
  const shapes = Array.from(new Set(['rectangle', ...ids.map((id) => profile.concept_types[id]?.shape).filter(Boolean)])) as string[];
  const getMetadataIds = (c: OntologyConceptType) => c.metadata_fields ?? Object.keys(c.metadata_schema ?? {});
  const patch = (patch: Partial<OntologyConceptType>) => concept && onChange(updateProfileRecord<OntologyConceptType>(profile, 'concept_types', concept.id, patch));
  const patchMetadataField = (id: string, patch: Partial<OntologyMetadataField>) => onChange(updateProfileRecord<OntologyMetadataField>(profile, 'metadata_fields', id, { id, ...patch }));
  const patchLayer = (id: string, patch: Partial<OntologyLayer>) => onChange(updateProfileRecord<OntologyLayer>(profile, 'layers', id, { id, ...patch }));
  const patchLevel = (id: string, patch: Partial<OntologyAbstractionLevel>) => onChange(updateProfileRecord<OntologyAbstractionLevel>(profile, 'abstraction_levels', id, { id, ...patch }));

  return (
    <SectionCard title="Concept Type Studio" subtitle="Edit abstraction levels, layer defaults, metadata fields, colors, and shapes.">
      <div className="grid gap-4 lg:grid-cols-[260px,1fr]">
        <div className="space-y-2">{ids.map((id) => <button key={id} onClick={() => setSelected(id)} className="w-full rounded-xl border px-3 py-2 text-left text-sm transition hover:bg-surface-hover" style={{ borderColor: selected === id ? 'var(--color-primary)' : 'var(--color-border)', background: selected === id ? 'var(--color-primary-muted)' : 'var(--color-background)', color: selected === id ? 'var(--color-primary)' : 'var(--color-text-main)' }}><span className="mr-2 inline-block h-2.5 w-2.5 rounded-full" style={{ background: profile.concept_types[id]?.color ?? 'var(--color-primary)' }} />{labelFor(id, profile.concept_types[id]?.label)}<div className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>{profile.concept_types[id]?.abstraction_level || 'No level'}</div></button>)}</div>
        {concept && <div className="grid gap-3 md:grid-cols-2">
          <Field label="Label"><TextInput aria-label="Concept label" value={concept.label} onChange={(e) => patch({ label: e.target.value })} /></Field>
          <Field label="Abstraction level"><Select aria-label="Abstraction level" value={concept.abstraction_level ?? ''} onChange={(e) => patch({ abstraction_level: e.target.value })}>{levelIds.map((id) => <option key={id} value={id}>{labelFor(id, profile.abstraction_levels[id]?.label)}</option>)}</Select></Field>
          <Field label="Layer default"><Select aria-label="Layer default" value={concept.default_layer ?? concept.layer ?? ''} onChange={(e) => patch({ default_layer: e.target.value, layer: e.target.value })}><option value="">None</option>{layerIds.map((id) => <option key={id} value={id}>{labelFor(id, profile.layers[id]?.label)}</option>)}</Select></Field>
          <Field label="Metadata fields"><TextInput aria-label="Metadata fields" value={csv(getMetadataIds(concept))} onChange={(e) => patch({ metadata_fields: parseCsv(e.target.value).filter((id) => metadataIds.includes(id)) })} placeholder={metadataIds.join(', ')} /></Field>
          <Field label="Color"><TextInput aria-label="Concept color" type="color" value={concept.color ?? '#64748b'} onChange={(e) => patch({ color: e.target.value })} /></Field>
          <Field label="Shape"><Select aria-label="Concept shape" value={concept.shape ?? ''} onChange={(e) => patch({ shape: e.target.value })}>{shapes.map((shape) => <option key={shape} value={shape}>{shape}</option>)}</Select></Field>
          <div className="md:col-span-2 rounded-xl border p-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}>
            <p className="mb-2 text-xs font-semibold" style={{ color: 'var(--color-text-main)' }}>Layer catalog</p>
            <div className="grid gap-2 md:grid-cols-2">{layerIds.map((id) => <Field key={id} label={id}><TextInput aria-label={`Layer ${id}`} value={profile.layers[id]?.label ?? id} onChange={(e) => patchLayer(id, { label: e.target.value })} /></Field>)}</div>
          </div>
          <div className="md:col-span-2 rounded-xl border p-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}>
            <p className="mb-2 text-xs font-semibold" style={{ color: 'var(--color-text-main)' }}>Abstraction level catalog</p>
            <div className="grid gap-2 md:grid-cols-2">{levelIds.map((id) => <Field key={id} label={id}><TextInput aria-label={`Abstraction level ${id}`} value={profile.abstraction_levels[id]?.label ?? id} onChange={(e) => patchLevel(id, { label: e.target.value })} /></Field>)}</div>
          </div>
          <div className="md:col-span-2 rounded-xl border p-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}>
            <p className="mb-2 text-xs font-semibold" style={{ color: 'var(--color-text-main)' }}>Metadata catalog</p>
            <div className="grid gap-2 md:grid-cols-2">{metadataIds.map((id) => <div key={id} className="grid gap-2 md:grid-cols-2"><Field label={`${id} label`}><TextInput aria-label={`Metadata ${id}`} value={profile.metadata_fields[id]?.label ?? id} onChange={(e) => patchMetadataField(id, { label: e.target.value })} /></Field><Field label="Type"><Select aria-label={`Metadata ${id} type`} value={profile.metadata_fields[id]?.field_type ?? 'string'} onChange={(e) => patchMetadataField(id, { field_type: e.target.value })}><option value="string">string</option><option value="number">number</option><option value="boolean">boolean</option><option value="enum">enum</option><option value="date">date</option></Select></Field></div>)}</div>
          </div>
        </div>}
      </div>
    </SectionCard>
  );
}
