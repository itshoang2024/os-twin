'use client';

import React, { useMemo, useRef, useState } from 'react';
import type { Cardinality, OntologyConceptType, OntologyProfile, OntologyRelationshipType, ValidationIssue, WorkbenchSelection } from './types';
import { addMetadataFieldToObjectType, attachSourceMapping, createObjectType, createRelationshipType, makeBlankOntologyProfile, patchObjectType, patchRelationshipType, toggleRelationshipEndpoint } from './ontology-draft-commands';
import { useOntologyDraftController } from './useOntologyDraftController';

type Props = {
  selectedNamespace: string | null;
  initialProfile?: OntologyProfile;
  saveProfile?: (profile: OntologyProfile, reason: string) => Promise<void> | void;
};

type EventLog = { id: string; message: string };

const pill = 'rounded-full border px-2 py-0.5 text-[11px] font-semibold';

export default function OntologyPanel({ selectedNamespace, initialProfile, saveProfile }: Props) {
  const sourceProfile = useMemo(() => initialProfile ?? makeBlankOntologyProfile(selectedNamespace ?? 'fixture'), [initialProfile, selectedNamespace]);
  const controller = useOntologyDraftController(sourceProfile);
  const { draft, commitDraft, runValidation, validationIssues, previewDiff, lastDiff, resetDraft, isDirty, undoStack, redoStack, handleUndoDraft, handleRedoDraft } = controller;
  const [selection, setSelection] = useState<WorkbenchSelection | undefined>();
  const [connectSource, setConnectSource] = useState<string | null>(null);
  const [impactPreview, setImpactPreview] = useState(false);
  const [publishReason, setPublishReason] = useState('Authoring workbench update');
  const [events, setEvents] = useState<EventLog[]>([]);
  const eventCounter = useRef(0);

  const objectTypes = Object.values(draft.conceptTypes);
  const relationships = Object.values(draft.relationshipTypes);

  function log(message: string) {
    eventCounter.current += 1;
    setEvents((items) => [...items.slice(-5), { id: `ontology-event-${Date.now()}-${eventCounter.current}`, message }]);
  }

  function handleAddObject(label = 'Feature') {
    const { profile, concept } = createObjectType(draft, label);
    commitDraft(profile, `Create Object Type ${concept.id}`);
    setSelection({ kind: 'concept', id: concept.id, focus: 'identity' });
    log(`Staged Object Type ${concept.label} locally`);
  }

  function handleCreateRelationship(sourceIds?: string[], targetIds?: string[]) {
    const source = sourceIds ?? objectTypes.slice(0, 1).map((c) => c.id);
    const target = targetIds ?? objectTypes.slice(-1).map((c) => c.id);
    const { profile, relationship } = createRelationshipType(draft, 'depends on', {
      allowedSourceTypes: source,
      allowedTargetTypes: target,
      cardinality: 'many_to_many',
      family: 'dependency',
      mapDirection: 'forward',
      style: 'solid',
      weight: 1,
    });
    commitDraft(profile, `Create Relationship Type ${relationship.id}`);
    setSelection({ kind: 'relationship', id: relationship.id, focus: 'endpoint' });
    log(`Staged Relationship Type ${relationship.label} locally`);
  }

  function handleCanvasConceptClick(id: string) {
    if (connectSource && connectSource !== id) {
      handleCreateRelationship([connectSource], [id]);
      setConnectSource(null);
      return;
    }
    if (connectSource === id) setConnectSource(null);
    setSelection({ kind: 'concept', id });
  }

  function handleIssue(issue: ValidationIssue) {
    const conceptMatch = issue.path.match(/conceptTypes\.([^.]+)/);
    const relMatch = issue.path.match(/relationshipTypes\.([^.]+)/);
    if (conceptMatch) setSelection({ kind: 'concept', id: conceptMatch[1], focus: issue.focus });
    if (relMatch) setSelection({ kind: 'relationship', id: relMatch[1], focus: issue.focus });
  }

  async function handlePublish() {
    const issues = runValidation();
    if (issues.some((issue) => issue.severity === 'error')) {
      log('Publish blocked by validation.');
      return;
    }
    previewDiff();
    const published = { ...draft, status: 'published' as const, updatedAt: new Date().toISOString() };
    if (saveProfile) await saveProfile(published, publishReason);
    else if (typeof window !== 'undefined') window.localStorage.setItem(`ontology-profile:${draft.namespace}`, JSON.stringify(published));
    log('Published profile after validate and diff preview.');
  }

  return (
    <section className="h-full min-h-[680px] flex flex-col overflow-hidden rounded-2xl border bg-white text-slate-900" style={{ borderColor: 'var(--color-border)' }} aria-label="Ontology Authoring Workbench">
      <TopRail
        namespace={selectedNamespace ?? draft.namespace}
        isDirty={isDirty}
        undoDisabled={!undoStack.length}
        redoDisabled={!redoStack.length}
        onUndo={handleUndoDraft}
        onRedo={handleRedoDraft}
        onValidate={() => { const issues = runValidation(); log(`Validation completed: ${issues.length} issue(s).`); }}
        onDiff={() => log(previewDiff())}
        onReset={resetDraft}
        onPublish={handlePublish}
        publishReason={publishReason}
        onPublishReasonChange={setPublishReason}
      />
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[260px_minmax(420px,1fr)_340px]">
        <Inventory objects={objectTypes} relationships={relationships} candidates={draft.candidates} onAddObject={() => handleAddObject()} onAddRelationship={() => handleCreateRelationship()} onSelect={setSelection} />
        <main className="min-w-0 border-x bg-slate-50/80" style={{ borderColor: 'var(--color-border)' }}>
          <GraphBuilder
            objects={objectTypes}
            relationships={relationships}
            selected={selection}
            connectSource={connectSource}
            onAddObject={() => handleAddObject()}
            onUseTemplate={() => { handleAddObject('Risk'); handleAddObject('Control'); }}
            onReviewCandidates={() => setSelection(draft.candidates[0] ? { kind: 'candidate', id: draft.candidates[0].id } : undefined)}
            onSelectConcept={handleCanvasConceptClick}
            onSelectRelationship={(id) => setSelection({ kind: 'relationship', id })}
            onStartConnect={(id) => setConnectSource(id)}
            onCancelConnect={() => setConnectSource(null)}
          />
          <BottomRail
            objectCount={objectTypes.length}
            relationshipCount={relationships.length}
            issueCount={validationIssues.length}
            lastDiff={lastDiff}
            impactPreview={impactPreview}
            onImpact={() => setImpactPreview((value) => !value)}
          />
        </main>
        <SelectionInspector
          profile={draft}
          selection={selection}
          focus={selection?.focus}
          onProfileChange={(next, label) => commitDraft(next, label)}
          onSelect={setSelection}
          onValidateIssue={handleIssue}
          issues={validationIssues}
          impactPreview={impactPreview}
          onStageCandidate={(candidateId) => {
            const candidate = draft.candidates.find((item) => item.id === candidateId);
            if (!candidate) return;
            if (candidate.kind === 'object') {
              const { profile, concept } = createObjectType(draft, candidate.label, { sourceMappings: [{ id: 'candidate_evidence', source: candidate.source, selector: candidate.label, evidenceRefs: candidate.evidenceRefs }] });
              commitDraft(profile, `Stage candidate ${candidate.id}`);
              setSelection({ kind: 'concept', id: concept.id, focus: 'source' });
            } else {
              handleCreateRelationship();
            }
            log(`Candidate ${candidate.label} staged locally; no profile write.`);
          }}
        />
      </div>
      <div className="flex flex-wrap gap-2 border-t px-3 py-2 text-[11px] text-slate-500" style={{ borderColor: 'var(--color-border)' }} aria-label="Authoring event log">
        {events.length ? events.map((event) => <span key={event.id} className="rounded bg-slate-100 px-2 py-1">{event.message}</span>) : <span>No local authoring events yet.</span>}
      </div>
    </section>
  );
}

function TopRail(props: {
  namespace: string; isDirty: boolean; undoDisabled: boolean; redoDisabled: boolean; publishReason: string;
  onUndo: () => void; onRedo: () => void; onValidate: () => void; onDiff: () => void; onReset: () => void; onPublish: () => void; onPublishReasonChange: (value: string) => void;
}) {
  return (
    <header className="flex flex-wrap items-center gap-3 border-b px-4 py-3" style={{ borderColor: 'var(--color-border)' }}>
      <div className="mr-auto">
        <div className="text-[10px] font-bold uppercase tracking-[0.22em] text-slate-500">Ontology Unit · {props.namespace}</div>
        <h2 className="text-lg font-semibold">Spec authoring graph builder</h2>
      </div>
      <span className={`${pill} ${props.isDirty ? 'border-amber-300 bg-amber-50 text-amber-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{props.isDirty ? 'Local draft' : 'Synced'}</span>
      <button className="rounded-lg border px-3 py-1 text-xs" onClick={props.onUndo} disabled={props.undoDisabled}>Undo</button>
      <button className="rounded-lg border px-3 py-1 text-xs" onClick={props.onRedo} disabled={props.redoDisabled}>Redo</button>
      <button className="rounded-lg border px-3 py-1 text-xs" onClick={props.onValidate}>Validate</button>
      <button className="rounded-lg border px-3 py-1 text-xs" onClick={props.onDiff}>Preview diff</button>
      <input aria-label="Publish reason" className="w-44 rounded-lg border px-2 py-1 text-xs" value={props.publishReason} onChange={(event) => props.onPublishReasonChange(event.target.value)} />
      <button className="rounded-lg bg-slate-900 px-4 py-1.5 text-xs font-bold text-white" onClick={props.onPublish}>Publish</button>
      <button className="rounded-lg border px-3 py-1 text-xs" onClick={props.onReset}>Reset</button>
    </header>
  );
}

function Inventory({ objects, relationships, candidates, onAddObject, onAddRelationship, onSelect }: {
  objects: OntologyConceptType[]; relationships: OntologyRelationshipType[]; candidates: OntologyProfile['candidates']; onAddObject: () => void; onAddRelationship: () => void; onSelect: (selection: WorkbenchSelection) => void;
}) {
  return (
    <aside className="min-h-0 overflow-auto p-3" aria-label="Model inventory">
      <InventorySection title="Objects" count={objects.length} actionLabel="Add Object Type" onAction={onAddObject}>
        {objects.map((object) => <button key={object.id} className="w-full rounded-lg border bg-white px-3 py-2 text-left text-xs hover:border-slate-400" onClick={() => onSelect({ kind: 'concept', id: object.id })}><strong>{object.label}</strong><br /><span className="text-slate-500">{object.layer} · {object.abstractionLevel}</span></button>)}
      </InventorySection>
      <InventorySection title="Relationships" count={relationships.length} actionLabel="Create Relationship" onAction={onAddRelationship}>
        {relationships.map((relationship) => <button key={relationship.id} className="w-full rounded-lg border bg-white px-3 py-2 text-left text-xs hover:border-slate-400" onClick={() => onSelect({ kind: 'relationship', id: relationship.id })}><strong>{relationship.label}</strong><br /><span className="text-slate-500">{relationship.family} · {relationship.cardinality}</span></button>)}
      </InventorySection>
      <InventorySection title="Properties" count={objects.reduce((sum, object) => sum + object.metadataFields.length, 0)} />
      <InventorySection title="Candidates" count={candidates.length}>
        {candidates.map((candidate) => <button key={candidate.id} className="w-full rounded-lg border bg-white px-3 py-2 text-left text-xs" onClick={() => onSelect({ kind: 'candidate', id: candidate.id })}>{candidate.label}<br /><span className="text-slate-500">{candidate.kind} · evidence {candidate.evidenceRefs.length}</span></button>)}
      </InventorySection>
      <InventorySection title="Sources" count={objects.flatMap((object) => object.sourceMappings).length} />
      <InventorySection title="Templates" count={4}><div className="text-[11px] text-slate-500">Build Software · Audit Airline · Audit Legal · Ecommerce Logistics</div></InventorySection>
    </aside>
  );
}

function InventorySection({ title, count, actionLabel, onAction, children }: { title: string; count: number; actionLabel?: string; onAction?: () => void; children?: React.ReactNode }) {
  return <section className="mb-4 space-y-2"><div className="flex items-center justify-between"><h3 className="text-[11px] font-bold uppercase tracking-wider text-slate-500">{title} <span className="text-slate-400">{count}</span></h3>{actionLabel && <button className="rounded bg-slate-900 px-2 py-1 text-[10px] font-bold text-white" onClick={onAction}>{actionLabel}</button>}</div>{children}</section>;
}

function GraphBuilder(props: {
  objects: OntologyConceptType[]; relationships: OntologyRelationshipType[]; selected?: WorkbenchSelection; connectSource: string | null;
  onAddObject: () => void; onUseTemplate: () => void; onReviewCandidates: () => void; onSelectConcept: (id: string) => void; onSelectRelationship: (id: string) => void; onStartConnect: (id: string) => void; onCancelConnect: () => void;
}) {
  if (!props.objects.length) {
    return <div className="flex min-h-[520px] items-center justify-center p-8"><div className="max-w-lg rounded-3xl border bg-white p-8 text-center shadow-sm"><div className="text-[10px] font-bold uppercase tracking-[0.3em] text-slate-400">First run</div><h3 className="mt-2 text-2xl font-semibold">Design Object Types before editing arrays</h3><p className="mt-3 text-sm text-slate-600">Start with nouns, then draw governed Relationship Types between them. Nothing is saved until Publish.</p><div className="mt-6 flex flex-wrap justify-center gap-2"><button className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-bold text-white" onClick={props.onAddObject}>Add Object Type</button><button className="rounded-xl border px-4 py-2 text-sm" onClick={props.onUseTemplate}>Use Template</button><button className="rounded-xl border px-4 py-2 text-sm" onClick={props.onReviewCandidates}>Review Candidates</button></div></div></div>;
  }
  const positions = props.objects.map((object, index) => ({ object, x: 120 + (index % 3) * 210, y: 110 + Math.floor(index / 3) * 160 }));
  const positionById = new Map(positions.map((item) => [item.object.id, item]));
  return <div className="relative min-h-[520px] overflow-auto p-6" aria-label="Ontology graph canvas"><div className="mb-3 flex items-center gap-2"><span className={`${pill} border-blue-200 bg-blue-50 text-blue-700`}>Layered graph builder</span>{props.connectSource && <><span className="text-xs text-slate-600">Connect mode: choose a target Object Type</span><button className="rounded border px-2 py-1 text-xs" onClick={props.onCancelConnect}>Cancel connect</button></>}</div><svg width="760" height="460" role="img" aria-label="Ontology object relationship canvas">{props.relationships.flatMap((rel) => rel.allowedSourceTypes.flatMap((source) => rel.allowedTargetTypes.map((target) => ({ rel, source: positionById.get(source), target: positionById.get(target) })))).filter((edge) => edge.source && edge.target).map((edge) => <g key={`${edge.rel.id}-${edge.source!.object.id}-${edge.target!.object.id}`} onClick={() => props.onSelectRelationship(edge.rel.id)} className="cursor-pointer"><line x1={edge.source!.x+70} y1={edge.source!.y+32} x2={edge.target!.x+70} y2={edge.target!.y+32} stroke="#64748b" strokeWidth={2} strokeDasharray={edge.rel.style === 'solid' ? undefined : edge.rel.style === 'dashed' ? '6 4' : '2 4'} /><text x={(edge.source!.x+edge.target!.x)/2+70} y={(edge.source!.y+edge.target!.y)/2+18} fontSize="12" fill="#334155">{edge.rel.label}</text></g>)}{positions.map(({ object, x, y }) => <g key={object.id} className="cursor-pointer"><rect x={x} y={y} width="140" height="64" rx="16" fill={props.selected?.kind === 'concept' && props.selected.id === object.id ? '#dbeafe' : '#fff'} stroke={props.connectSource === object.id ? '#f59e0b' : '#2563eb'} strokeWidth="2" onClick={() => props.onSelectConcept(object.id)} /><text x={x+16} y={y+28} fontSize="14" fontWeight="700" fill="#0f172a">{object.label}</text><text x={x+16} y={y+48} fontSize="11" fill="#64748b">{object.layer} · {object.lifecycle}</text><foreignObject x={x+104} y={y+8} width="28" height="28"><button aria-label={`Connect from ${object.label}`} className="h-7 w-7 rounded-full bg-slate-900 text-white text-xs" onClick={() => props.onStartConnect(object.id)}>↗</button></foreignObject></g>)}</svg></div>;
}

function BottomRail({ objectCount, relationshipCount, issueCount, lastDiff, impactPreview, onImpact }: { objectCount: number; relationshipCount: number; issueCount: number; lastDiff: string; impactPreview: boolean; onImpact: () => void }) {
  return <footer className="border-t bg-white px-4 py-3" style={{ borderColor: 'var(--color-border)' }}><div className="flex flex-wrap items-center gap-2 text-xs"><span className={`${pill} border-slate-200`}>{objectCount} objects</span><span className={`${pill} border-slate-200`}>{relationshipCount} relationships</span><span className={`${pill} ${issueCount ? 'border-red-200 bg-red-50 text-red-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{issueCount} validation issues</span><button className="rounded-lg border px-3 py-1 font-semibold" onClick={onImpact}>Preview map impact</button><span className="text-slate-500">{lastDiff}</span></div>{impactPreview && <div role="status" className="mt-2 rounded-xl border border-blue-200 bg-blue-50 p-3 text-xs text-blue-800">Example overlay: this typed namespace has no live instances yet. Preview uses labeled example nodes and never presents them as live data.</div>}</footer>;
}

function SelectionInspector({ profile, selection, focus, issues, impactPreview, onProfileChange, onSelect, onValidateIssue, onStageCandidate }: {
  profile: OntologyProfile; selection?: WorkbenchSelection; focus?: ValidationIssue['focus']; issues: ValidationIssue[]; impactPreview: boolean; onProfileChange: (profile: OntologyProfile, label: string) => void; onSelect: (selection: WorkbenchSelection) => void; onValidateIssue: (issue: ValidationIssue) => void; onStageCandidate: (id: string) => void;
}) {
  const concept = selection?.kind === 'concept' ? profile.conceptTypes[selection.id] : undefined;
  const relationship = selection?.kind === 'relationship' ? profile.relationshipTypes[selection.id] : undefined;
  const candidate = selection?.kind === 'candidate' ? profile.candidates.find((item) => item.id === selection.id) : undefined;
  return <aside className="min-h-0 overflow-auto p-4" aria-label="Contextual ontology editor"><h3 className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Contextual inspector</h3>{issues.length > 0 && <section className="my-3 rounded-xl border border-red-200 bg-red-50 p-3"><h4 className="text-xs font-bold text-red-700">Validation routes</h4>{issues.map((issue) => <button key={issue.id} className="mt-2 block text-left text-xs text-red-800 underline" onClick={() => onValidateIssue(issue)}>{issue.message}</button>)}</section>}{concept ? <ObjectTypeEditor profile={profile} concept={concept} focus={focus} onProfileChange={onProfileChange} /> : relationship ? <RelationshipTypeEditor profile={profile} relationship={relationship} focus={focus} onProfileChange={onProfileChange} onSelect={onSelect} /> : candidate ? <section className="mt-4 space-y-3"><h4 className="text-lg font-semibold">Candidate · {candidate.label}</h4><p className="text-sm text-slate-600">{candidate.source}</p><div className="rounded-lg bg-slate-100 p-2 text-xs">Evidence refs: {candidate.evidenceRefs.join(', ')}</div><button className="rounded-lg bg-slate-900 px-3 py-2 text-xs font-bold text-white" onClick={() => onStageCandidate(candidate.id)}>Stage candidate locally</button></section> : <GovernancePanel profile={profile} impactPreview={impactPreview} />}</aside>;
}

function ObjectTypeEditor({ profile, concept, focus, onProfileChange }: { profile: OntologyProfile; concept: OntologyConceptType; focus?: ValidationIssue['focus']; onProfileChange: (profile: OntologyProfile, label: string) => void }) {
  return <section className="mt-4 space-y-4" aria-label="Object Type editor"><h4 className="text-lg font-semibold">Object Type</h4><Field label="Label" focus={focus === 'identity'}><input className="w-full rounded-lg border px-3 py-2 text-sm" value={concept.label} onChange={(event) => onProfileChange(patchObjectType(profile, concept.id, { label: event.target.value }), 'Edit object label')} /></Field><Field label="Description"><textarea className="w-full rounded-lg border px-3 py-2 text-sm" rows={3} value={concept.description} onChange={(event) => onProfileChange(patchObjectType(profile, concept.id, { description: event.target.value }), 'Edit object description')} /></Field><Field label="Layer / abstraction"><div className="grid grid-cols-2 gap-2"><select className="rounded-lg border px-2 py-2 text-sm" value={concept.layer} onChange={(event) => onProfileChange(patchObjectType(profile, concept.id, { layer: event.target.value as OntologyConceptType['layer'] }), 'Edit layer')}><option value="source">Source</option><option value="semantic">Semantic</option><option value="governance">Governance</option><option value="activation">Activation</option></select><input className="rounded-lg border px-2 py-2 text-sm" value={concept.abstractionLevel} onChange={(event) => onProfileChange(patchObjectType(profile, concept.id, { abstractionLevel: event.target.value }), 'Edit abstraction')} /></div></Field><Field label="Properties"><div className="space-y-2">{concept.metadataFields.map((field) => <span key={field.id} className={`${pill} border-slate-200`}>{field.label} · {field.type}</span>)}<button className="block rounded-lg border px-3 py-1 text-xs" onClick={() => onProfileChange(addMetadataFieldToObjectType(profile, concept.id, { label: 'Name', type: 'text' }), 'Add property')}>Add property</button></div></Field><Field label="Source mappings" focus={focus === 'source'}><div className="space-y-2">{concept.sourceMappings.map((mapping) => <div key={mapping.id} className="rounded-lg bg-slate-100 p-2 text-xs">{mapping.source} · {mapping.selector}<br />{mapping.evidenceRefs.join(', ')}</div>)}<button className="rounded-lg border px-3 py-1 text-xs" onClick={() => onProfileChange(attachSourceMapping(profile, concept.id, { source: 'knowledge graph', selector: concept.label }), 'Attach source')}>Attach source mapping</button></div></Field><Field label="View defaults"><div className="text-xs text-slate-600">GraphInstruction owns visual defaults: {profile.graphInstruction.conceptTypeDefaults[concept.id]?.color} · {profile.graphInstruction.conceptTypeDefaults[concept.id]?.shape}</div></Field></section>;
}

function RelationshipTypeEditor({ profile, relationship, focus, onProfileChange, onSelect }: { profile: OntologyProfile; relationship: OntologyRelationshipType; focus?: ValidationIssue['focus']; onProfileChange: (profile: OntologyProfile, label: string) => void; onSelect: (selection: WorkbenchSelection) => void }) {
  const objects = Object.values(profile.conceptTypes);
  const updateList = (key: 'allowedSourceTypes' | 'allowedTargetTypes', id: string) => {
    const list = relationship[key];
    const nextList = list.includes(id) ? list.filter((item) => item !== id) : [...list, id];
    onProfileChange(patchRelationshipType(profile, relationship.id, { [key]: nextList }), 'Edit relationship endpoints');
  };
  return <section className="mt-4 space-y-4" aria-label="Relationship Type editor"><h4 className="text-lg font-semibold">Relationship Type</h4><Field label="Label"><input className="w-full rounded-lg border px-3 py-2 text-sm" value={relationship.label} onChange={(event) => onProfileChange(patchRelationshipType(profile, relationship.id, { label: event.target.value }), 'Edit relationship label')} /></Field><Field label="Endpoint chips" focus={focus === 'endpoint'}><ChipPicker label="Source Object Types" objects={objects} selected={relationship.allowedSourceTypes} onToggle={(id) => updateList('allowedSourceTypes', id)} /><ChipPicker label="Target Object Types" objects={objects} selected={relationship.allowedTargetTypes} onToggle={(id) => updateList('allowedTargetTypes', id)} /></Field><Field label="Family / cardinality" focus={focus === 'cardinality'}><div className="grid grid-cols-2 gap-2"><input className="rounded-lg border px-2 py-2 text-sm" value={relationship.family} onChange={(event) => onProfileChange(patchRelationshipType(profile, relationship.id, { family: event.target.value }), 'Edit family')} /><select className="rounded-lg border px-2 py-2 text-sm" value={relationship.cardinality} onChange={(event) => onProfileChange(patchRelationshipType(profile, relationship.id, { cardinality: event.target.value as Cardinality }), 'Edit cardinality')}><option value="one_to_one">one_to_one</option><option value="one_to_many">one_to_many</option><option value="many_to_one">many_to_one</option><option value="many_to_many">many_to_many</option></select></div></Field><Field label="Direction / style"><div className="grid grid-cols-3 gap-2"><select className="rounded-lg border px-2 py-2 text-sm" value={relationship.mapDirection} onChange={(event) => onProfileChange(patchRelationshipType(profile, relationship.id, { mapDirection: event.target.value as OntologyRelationshipType['mapDirection'] }), 'Edit direction')}><option value="forward">forward</option><option value="reverse">reverse</option><option value="bidirectional">bidirectional</option></select><select className="rounded-lg border px-2 py-2 text-sm" value={relationship.style} onChange={(event) => onProfileChange(patchRelationshipType(profile, relationship.id, { style: event.target.value as OntologyRelationshipType['style'] }), 'Edit style')}><option value="solid">solid</option><option value="dashed">dashed</option><option value="dotted">dotted</option></select><input aria-label="Relationship weight" className="rounded-lg border px-2 py-2 text-sm" type="number" value={relationship.weight} onChange={(event) => onProfileChange(patchRelationshipType(profile, relationship.id, { weight: Number(event.target.value) }), 'Edit weight')} /></div></Field><RelationshipMatrix profile={profile} relationship={relationship} onProfileChange={onProfileChange} onSelect={onSelect} /><Field label="View defaults"><div className="text-xs text-slate-600">GraphInstruction relationship defaults: {profile.graphInstruction.relationshipTypeDefaults[relationship.id]?.style} · weight {profile.graphInstruction.relationshipTypeDefaults[relationship.id]?.weight}</div></Field></section>;
}

function ChipPicker({ label, objects, selected, onToggle }: { label: string; objects: OntologyConceptType[]; selected: string[]; onToggle: (id: string) => void }) {
  return <div className="mb-2"><div className="mb-1 text-[11px] font-bold text-slate-500">{label}</div><div className="flex flex-wrap gap-1">{objects.map((object) => <button key={object.id} className={`${pill} ${selected.includes(object.id) ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-slate-200 bg-white text-slate-600'}`} onClick={() => onToggle(object.id)}>{object.label}</button>)}</div></div>;
}

function RelationshipMatrix({ profile, relationship, onProfileChange, onSelect }: { profile: OntologyProfile; relationship: OntologyRelationshipType; onProfileChange: (profile: OntologyProfile, label: string) => void; onSelect: (selection: WorkbenchSelection) => void }) {
  const objects = Object.values(profile.conceptTypes);
  return <Field label="Relationship matrix"><div className="overflow-auto rounded-xl border"><table className="w-full min-w-[260px] text-xs"><thead><tr><th className="bg-slate-50 p-2 text-left">Source \ Target</th>{objects.map((target) => <th key={target.id} className="bg-slate-50 p-2">{target.label}</th>)}</tr></thead><tbody>{objects.map((source) => <tr key={source.id}><th className="bg-slate-50 p-2 text-left">{source.label}</th>{objects.map((target) => { const active = relationship.allowedSourceTypes.includes(source.id) && relationship.allowedTargetTypes.includes(target.id); return <td key={target.id} className="p-1 text-center"><button aria-label={`Toggle ${source.label} to ${target.label}`} className={`h-7 w-7 rounded ${active ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-400'}`} onClick={() => { onProfileChange(toggleRelationshipEndpoint(profile, relationship.id, source.id, target.id), 'Toggle matrix endpoint'); onSelect({ kind: 'relationship', id: relationship.id, focus: 'endpoint' }); }}>{active ? '✓' : '+'}</button></td>; })}</tr>)}</tbody></table></div></Field>;
}

function GovernancePanel({ profile, impactPreview }: { profile: OntologyProfile; impactPreview: boolean }) {
  return <section className="mt-4 space-y-3"><h4 className="text-lg font-semibold">Governance home</h4><p className="text-sm text-slate-600">One editor path for Object Types, Relationship Types, Candidates, Source Mappings, and publish governance. Legacy ConceptTypeStudio and RelationshipStudio are intentionally absent from the default authoring path.</p><div className="rounded-xl border p-3 text-xs">Profile: {profile.label}<br />Status: {profile.status}<br />GraphInstruction concept defaults: {Object.keys(profile.graphInstruction.conceptTypeDefaults).length}<br />GraphInstruction relationship defaults: {Object.keys(profile.graphInstruction.relationshipTypeDefaults).length}</div>{impactPreview && <div className="rounded-xl bg-blue-50 p-3 text-xs text-blue-800">Map impact preview is active with example-data honesty for empty namespaces.</div>}</section>;
}

function Field({ label, focus, children }: { label: string; focus?: boolean; children: React.ReactNode }) {
  return <label className={`block rounded-xl p-2 ${focus ? 'ring-2 ring-blue-400' : ''}`}><span className="mb-1 block text-[11px] font-bold uppercase tracking-wider text-slate-500">{label}</span>{children}</label>;
}
