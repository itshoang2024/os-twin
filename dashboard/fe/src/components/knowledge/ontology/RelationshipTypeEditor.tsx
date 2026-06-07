import React from 'react';
import type { OntologyProfile } from '@/hooks/use-ontology';
import { Field, labelFor, SectionCard, Select, TextArea, TextInput } from './ontology-ui';
import type { RelationshipTypeDraftInput } from './ontology-draft-commands';

const cardinalities = ['', 'one_to_one', 'one_to_many', 'many_to_one', 'many_to_many'];
const families = ['dependency', 'composition', 'flow', 'semantic', 'ownership', 'classification', 'causality', 'temporal', 'validation', 'traceability', 'assurance'];
const styles = ['solid', 'dashed', 'dotted', 'bold'];

export default function RelationshipTypeEditor({ profile, seed, onCreate, onCancel }: { profile: OntologyProfile; seed?: Partial<RelationshipTypeDraftInput>; onCreate: (input: RelationshipTypeDraftInput) => void; onCancel: () => void }) {
  const conceptIds = Object.keys(profile.concept_types ?? {});
  const [label, setLabel] = React.useState(seed?.label ?? 'Depends on');
  const [description, setDescription] = React.useState(seed?.description ?? '');
  const [sourceTypes, setSourceTypes] = React.useState<string[]>(seed?.sourceTypes?.length ? seed.sourceTypes : conceptIds.slice(0, 1));
  const [targetTypes, setTargetTypes] = React.useState<string[]>(seed?.targetTypes?.length ? seed.targetTypes : conceptIds.slice(0, 1));
  const [family, setFamily] = React.useState(seed?.family ?? 'dependency');
  const [cardinality, setCardinality] = React.useState(seed?.cardinality ?? 'many_to_many');
  const [mapDirection, setMapDirection] = React.useState(seed?.mapDirection ?? 'forward');
  const [style, setStyle] = React.useState(seed?.style ?? 'solid');
  const [weight, setWeight] = React.useState(seed?.weight ?? 0.5);

  const toggle = (items: string[], id: string, setter: (items: string[]) => void) => setter(items.includes(id) ? items.filter((item) => item !== id) : [...items, id]);
  const canCreate = label.trim() && sourceTypes.length > 0 && targetTypes.length > 0;

  return (
    <SectionCard title="Create Relationship Type" subtitle="Govern an edge contract between Object Types with chips/selectors instead of CSV endpoint arrays." action={<button type="button" onClick={onCancel} className="rounded-lg border px-3 py-1.5 text-xs font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Cancel</button>}>
      <div className="grid gap-3">
        <Field label="Relationship label"><TextInput aria-label="New relationship label" value={label} onChange={(event) => setLabel(event.target.value)} /></Field>
        <Field label="Description"><TextArea aria-label="New relationship description" value={description} onChange={(event) => setDescription(event.target.value)} /></Field>
        <div className="grid gap-3 md:grid-cols-2">
          <fieldset className="rounded-xl border p-3" style={{ borderColor: 'var(--color-border)' }}><legend className="px-1 text-xs font-semibold">Source Object Types</legend>{conceptIds.map((id) => <label key={id} className="mt-2 flex items-center gap-2 text-xs"><input aria-label={`Source ${id}`} type="checkbox" checked={sourceTypes.includes(id)} onChange={() => toggle(sourceTypes, id, setSourceTypes)} />{labelFor(id, profile.concept_types[id]?.label)}</label>)}</fieldset>
          <fieldset className="rounded-xl border p-3" style={{ borderColor: 'var(--color-border)' }}><legend className="px-1 text-xs font-semibold">Target Object Types</legend>{conceptIds.map((id) => <label key={id} className="mt-2 flex items-center gap-2 text-xs"><input aria-label={`Target ${id}`} type="checkbox" checked={targetTypes.includes(id)} onChange={() => toggle(targetTypes, id, setTargetTypes)} />{labelFor(id, profile.concept_types[id]?.label)}</label>)}</fieldset>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Family"><Select aria-label="New relationship family" value={family} onChange={(event) => setFamily(event.target.value)}>{families.map((item) => <option key={item} value={item}>{labelFor(item)}</option>)}</Select></Field>
          <Field label="Cardinality"><Select aria-label="New relationship cardinality" value={cardinality ?? ''} onChange={(event) => setCardinality(event.target.value)}>{cardinalities.map((item) => <option key={item || 'none'} value={item}>{item || 'not specified'}</option>)}</Select></Field>
          <Field label="Direction"><Select aria-label="New relationship direction" value={mapDirection} onChange={(event) => setMapDirection(event.target.value)}><option value="forward">forward</option><option value="reversed">reversed</option><option value="bidirectional">bidirectional</option><option value="none">none</option></Select></Field>
          <Field label="Style"><Select aria-label="New relationship style" value={style} onChange={(event) => setStyle(event.target.value)}>{styles.map((item) => <option key={item} value={item}>{item}</option>)}</Select></Field>
          <Field label="Weight"><TextInput aria-label="New relationship weight" type="number" min="0" max="1" step="0.05" value={weight} onChange={(event) => setWeight(Number(event.target.value))} /></Field>
        </div>
        <div className="flex flex-wrap gap-2"><button type="button" disabled={!canCreate} onClick={() => onCreate({ label, description, sourceTypes, targetTypes, family, cardinality, mapDirection, style, weight })} className="rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">Create Relationship</button><span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>{sourceTypes.length} source chips · {targetTypes.length} target chips</span></div>
      </div>
    </SectionCard>
  );
}
