'use client';

import React, { useMemo, useRef, useState } from 'react';
import type { Cardinality, OntologyConceptType, OntologyLayer, OntologyProfile, OntologyRelationshipType, ValidationIssue, WorkbenchSelection } from './types';
import { addMetadataFieldToObjectType, attachSourceMapping, createObjectType, createRelationshipType, makeBlankOntologyProfile, patchObjectType, patchRelationshipType, toggleRelationshipEndpoint } from './ontology-draft-commands';
import { useOntologyDraftController } from './useOntologyDraftController';

type Props = {
  selectedNamespace: string | null;
  initialProfile?: OntologyProfile;
  saveProfile?: (profile: OntologyProfile, reason: string) => Promise<void> | void;
};

type EventLog = { id: string; message: string };
type FlowStep = 'object' | 'relationship' | 'knowledge';

type LayerMeta = { id: OntologyLayer; label: string; summary: string; tone: string; bg: string; text: string };

const pill = 'rounded-full border px-2 py-0.5 text-[11px] font-semibold';
const softButton = 'rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:border-slate-400 disabled:cursor-not-allowed disabled:opacity-50';

const layerCatalog: LayerMeta[] = [
  { id: 'source', label: 'Source', summary: 'Raw extracted nouns and system records.', tone: 'border-slate-300', bg: 'bg-slate-100', text: 'text-slate-700' },
  { id: 'semantic', label: 'Semantic', summary: 'Managed Object Type units users reason over.', tone: 'border-blue-300', bg: 'bg-blue-50', text: 'text-blue-800' },
  { id: 'governance', label: 'Governance', summary: 'Controls, policies, owners, and evidence rules.', tone: 'border-amber-300', bg: 'bg-amber-50', text: 'text-amber-800' },
  { id: 'activation', label: 'Activation', summary: 'Decision surfaces, actions, metrics, and workflows.', tone: 'border-emerald-300', bg: 'bg-emerald-50', text: 'text-emerald-800' },
];

const layerName = (layer: OntologyLayer) => layerCatalog.find((item) => item.id === layer)?.label ?? layer;
const layerMeta = (layer: OntologyLayer) => layerCatalog.find((item) => item.id === layer) ?? layerCatalog[1];

function initials(label: string) {
  const parts = label.trim().split(/\s+/).filter(Boolean);
  return (parts.length > 1 ? `${parts[0][0]}${parts[1][0]}` : label.slice(0, 2)).toUpperCase();
}

function selectedStep(selection?: WorkbenchSelection): FlowStep {
  if (selection?.kind === 'relationship') return 'relationship';
  if (selection?.kind === 'governance' || selection?.focus === 'governance') return 'knowledge';
  return 'object';
}

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

  const sourceKey = `${sourceProfile.id}:${sourceProfile.updatedAt}`;
  const [activeSourceKey, setActiveSourceKey] = useState(sourceKey);

  if (activeSourceKey !== sourceKey) {
    setActiveSourceKey(sourceKey);
    setSelection(undefined);
    setConnectSource(null);
    setImpactPreview(false);
    setEvents([]);
  }

  const objectTypes = Object.values(draft.conceptTypes);
  const relationships = Object.values(draft.relationshipTypes);

  function log(message: string) {
    eventCounter.current += 1;
    setEvents((items) => [...items.slice(-5), { id: `ontology-event-${Date.now()}-${eventCounter.current}`, message }]);
  }

  function handleAddObject(label = 'Feature') {
    const { profile, concept } = createObjectType(draft, label, { layer: 'semantic', abstractionLevel: 'unit' });
    commitDraft(profile, `Create Object Type ${concept.id}`);
    setSelection({ kind: 'concept', id: concept.id, focus: 'identity' });
    log(`Staged Object Type ${concept.label} locally`);
  }

  function handleUseTemplate() {
    const risk = createObjectType(draft, 'Risk', { layer: 'governance', metadataFields: [{ id: 'risk_score', label: 'Risk score', type: 'number' }] });
    const control = createObjectType(risk.profile, 'Control', { layer: 'governance', metadataFields: [{ id: 'owner', label: 'Owner', type: 'text' }] });
    commitDraft(control.profile, 'Create Risk and Control template Object Types');
    setSelection({ kind: 'concept', id: control.concept.id, focus: 'identity' });
    log('Staged template Object Types Risk and Control locally');
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
    <section className="h-full min-h-[680px] overflow-hidden rounded-2xl border bg-white text-slate-900 shadow-sm" style={{ borderColor: 'var(--color-border)' }} aria-label="Ontology Authoring Workbench">
      <TopRail
        namespace={selectedNamespace ?? draft.namespace}
        isDirty={isDirty}
        undoDisabled={!undoStack.length}
        redoDisabled={!redoStack.length}
        objectCount={objectTypes.length}
        relationshipCount={relationships.length}
        activeStep={selectedStep(selection)}
        onUndo={handleUndoDraft}
        onRedo={handleRedoDraft}
        onValidate={() => { const issues = runValidation(); log(`Validation completed: ${issues.length} issue(s).`); }}
        onDiff={() => log(previewDiff())}
        onReset={resetDraft}
        onPublish={handlePublish}
        publishReason={publishReason}
        onPublishReasonChange={setPublishReason}
      />
      <OntologyMapPanel
        profile={draft}
        objects={objectTypes}
        relationships={relationships}
        selection={selection}
        connectSource={connectSource}
        validationIssues={validationIssues}
        lastDiff={lastDiff}
        impactPreview={impactPreview}
        events={events}
        onAddObject={() => handleAddObject()}
        onUseTemplate={handleUseTemplate}
        onReviewCandidates={() => setSelection(draft.candidates[0] ? { kind: 'candidate', id: draft.candidates[0].id } : undefined)}
        onAddRelationship={() => handleCreateRelationship()}
        onSelect={setSelection}
        onSelectConcept={handleCanvasConceptClick}
        onSelectRelationship={(id) => setSelection({ kind: 'relationship', id })}
        onStartConnect={(id) => setConnectSource(id)}
        onCancelConnect={() => setConnectSource(null)}
        onImpact={() => setImpactPreview((value) => !value)}
        onProfileChange={(next, label) => commitDraft(next, label)}
        onValidateIssue={handleIssue}
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
    </section>
  );
}

export function OntologyMapPanel(props: {
  profile: OntologyProfile;
  objects: OntologyConceptType[];
  relationships: OntologyRelationshipType[];
  selection?: WorkbenchSelection;
  connectSource: string | null;
  validationIssues: ValidationIssue[];
  lastDiff: string;
  impactPreview: boolean;
  events: EventLog[];
  onAddObject: () => void;
  onUseTemplate: () => void;
  onReviewCandidates: () => void;
  onAddRelationship: () => void;
  onSelect: (selection: WorkbenchSelection) => void;
  onSelectConcept: (id: string) => void;
  onSelectRelationship: (id: string) => void;
  onStartConnect: (id: string) => void;
  onCancelConnect: () => void;
  onImpact: () => void;
  onProfileChange: (profile: OntologyProfile, label: string) => void;
  onValidateIssue: (issue: ValidationIssue) => void;
  onStageCandidate: (id: string) => void;
}) {
  return (
    <div className="flex h-[calc(100%-76px)] min-h-0 flex-col">
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[286px_minmax(520px,1fr)_360px]">
        <Inventory objects={props.objects} relationships={props.relationships} candidates={props.profile.candidates} selected={props.selection} onAddObject={props.onAddObject} onAddRelationship={props.onAddRelationship} onSelect={props.onSelect} />
        <main className="min-w-0 border-x bg-[#f4f7fa]" style={{ borderColor: 'var(--color-border)' }}>
          <GraphBuilder
            objects={props.objects}
            relationships={props.relationships}
            selected={props.selection}
            connectSource={props.connectSource}
            onAddObject={props.onAddObject}
            onUseTemplate={props.onUseTemplate}
            onReviewCandidates={props.onReviewCandidates}
            onSelectConcept={props.onSelectConcept}
            onSelectRelationship={props.onSelectRelationship}
            onStartConnect={props.onStartConnect}
            onCancelConnect={props.onCancelConnect}
          />
          <BottomRail
            objectCount={props.objects.length}
            relationshipCount={props.relationships.length}
            issueCount={props.validationIssues.length}
            lastDiff={props.lastDiff}
            impactPreview={props.impactPreview}
            onImpact={props.onImpact}
          />
        </main>
        <SelectionInspector
          profile={props.profile}
          selection={props.selection}
          focus={props.selection?.focus}
          onProfileChange={props.onProfileChange}
          onSelect={props.onSelect}
          onValidateIssue={props.onValidateIssue}
          issues={props.validationIssues}
          impactPreview={props.impactPreview}
          onStageCandidate={props.onStageCandidate}
        />
      </div>
      <div className="flex flex-wrap gap-2 border-t px-3 py-2 text-[11px] text-slate-500" style={{ borderColor: 'var(--color-border)' }} aria-label="Authoring event log">
        {props.events.length ? props.events.map((event) => <span key={event.id} className="rounded bg-slate-100 px-2 py-1">{event.message}</span>) : <span>No local authoring events yet.</span>}
      </div>
    </div>
  );
}

function TopRail(props: {
  namespace: string;
  isDirty: boolean;
  undoDisabled: boolean;
  redoDisabled: boolean;
  publishReason: string;
  objectCount: number;
  relationshipCount: number;
  activeStep: FlowStep;
  onUndo: () => void;
  onRedo: () => void;
  onValidate: () => void;
  onDiff: () => void;
  onReset: () => void;
  onPublish: () => void;
  onPublishReasonChange: (value: string) => void;
}) {
  const steps: { id: FlowStep; label: string; helper: string }[] = [
    { id: 'object', label: '1 Object unit', helper: 'Name nouns and properties' },
    { id: 'relationship', label: '2 Relationship', helper: 'Draw governed endpoints' },
    { id: 'knowledge', label: '3 Knowledge', helper: 'Validate, diff, publish' },
  ];
  return (
    <header className="border-b bg-white px-4 py-3" style={{ borderColor: 'var(--color-border)' }}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="mr-auto min-w-[260px]">
          <div className="text-[10px] font-bold uppercase tracking-[0.22em] text-slate-500">Ontology Unit · {props.namespace}</div>
          <h2 className="text-lg font-semibold">Spec authoring graph builder</h2>
          <p className="mt-1 text-xs text-slate-500">Simplified flow: create Object Type units, connect governed relationships, then promote the draft into knowledge.</p>
        </div>
        <span className={`${pill} ${props.isDirty ? 'border-amber-300 bg-amber-50 text-amber-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{props.isDirty ? 'Local draft' : 'Synced'}</span>
        <span className={`${pill} border-slate-200 bg-slate-50`}>{props.objectCount} object units</span>
        <span className={`${pill} border-slate-200 bg-slate-50`}>{props.relationshipCount} governed relations</span>
        <button className={softButton} onClick={props.onUndo} disabled={props.undoDisabled}>Undo</button>
        <button className={softButton} onClick={props.onRedo} disabled={props.redoDisabled}>Redo</button>
        <button className={softButton} onClick={props.onValidate}>Validate</button>
        <button className={softButton} onClick={props.onDiff}>Preview diff</button>
        <input aria-label="Publish reason" className="w-44 rounded-lg border px-2 py-1 text-xs" value={props.publishReason} onChange={(event) => props.onPublishReasonChange(event.target.value)} />
        <button className="rounded-lg bg-slate-900 px-4 py-1.5 text-xs font-bold text-white" onClick={props.onPublish}>Publish</button>
        <button className={softButton} onClick={props.onReset}>Reset</button>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-3" aria-label="Ontology development flow">
        {steps.map((step, index) => {
          const active = props.activeStep === step.id;
          return <div key={step.id} className={`rounded-xl border p-3 ${active ? 'border-blue-300 bg-blue-50' : 'border-slate-200 bg-slate-50'}`}><div className="flex items-center gap-2"><span className={`grid h-6 w-6 place-items-center rounded-full text-[11px] font-bold ${active ? 'bg-blue-600 text-white' : 'bg-white text-slate-500'}`}>{index + 1}</span><strong className="text-sm">{step.label}</strong></div><p className="mt-1 text-xs text-slate-500">{step.helper}</p></div>;
        })}
      </div>
    </header>
  );
}

function Inventory({ objects, relationships, candidates, selected, onAddObject, onAddRelationship, onSelect }: {
  objects: OntologyConceptType[];
  relationships: OntologyRelationshipType[];
  candidates: OntologyProfile['candidates'];
  selected?: WorkbenchSelection;
  onAddObject: () => void;
  onAddRelationship: () => void;
  onSelect: (selection: WorkbenchSelection) => void;
}) {
  const objectsByLayer = layerCatalog.map((layer) => ({ layer, objects: objects.filter((object) => object.layer === layer.id) }));
  return (
    <aside className="min-h-0 overflow-auto border-r bg-white p-3" style={{ borderColor: 'var(--color-border)' }} aria-label="Model inventory">
      <div className="mb-3 grid grid-cols-2 rounded-lg border bg-slate-50 p-1 text-xs font-bold" style={{ borderColor: 'var(--color-border)' }}>
        <button className="rounded-md bg-white px-2 py-2 text-blue-700 shadow-sm">Object Types</button>
        <button className="rounded-md px-2 py-2 text-slate-500">Relations</button>
      </div>
      <div className="mb-3 rounded-lg border border-blue-100 bg-blue-50 p-3 text-xs text-blue-900"><strong className="block">Draft unit</strong>Layer groups orient the graph. Object Type rows are the authored units.</div>
      <InventorySection title="Objects" count={objects.length} actionLabel="Add Object Type" onAction={onAddObject}>
        {objectsByLayer.map(({ layer, objects: layerObjects }) => (
          <section key={layer.id} className="rounded-xl border border-slate-200 bg-white">
            <div className={`flex items-center justify-between rounded-t-xl border-b px-3 py-2 ${layer.bg}`}><span className={`text-[11px] font-bold uppercase tracking-wider ${layer.text}`}>{layer.label}</span><span className="text-[10px] font-semibold text-slate-400">{layerObjects.length} units</span></div>
            <div className="space-y-1 p-2">
              {layerObjects.length ? layerObjects.map((object) => <button key={object.id} className={`grid w-full grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-2 rounded-lg px-2 py-2 text-left text-xs hover:bg-slate-50 ${selected?.kind === 'concept' && selected.id === object.id ? 'bg-blue-50 ring-1 ring-blue-200' : ''}`} onClick={() => onSelect({ kind: 'concept', id: object.id })}><span className={`grid h-7 w-7 place-items-center rounded-md text-[10px] font-black text-white ${layer.id === 'governance' ? 'bg-amber-600' : layer.id === 'activation' ? 'bg-emerald-600' : layer.id === 'source' ? 'bg-slate-500' : 'bg-blue-600'}`}>{initials(object.label)}</span><span className="min-w-0"><strong className="block truncate">{object.label}</strong><span className="text-slate-500">{object.abstractionLevel} · {object.metadataFields.length} props</span></span><span className="font-mono text-[10px] text-slate-400">unit</span></button>) : <div className="px-2 py-2 text-[11px] text-slate-400">No units in this layer yet.</div>}
            </div>
          </section>
        ))}
      </InventorySection>
      <InventorySection title="Relationships" count={relationships.length} actionLabel="Create Relationship" onAction={onAddRelationship}>
        {relationships.map((relationship) => <button key={relationship.id} className={`w-full rounded-lg border bg-white px-3 py-2 text-left text-xs hover:border-slate-400 ${selected?.kind === 'relationship' && selected.id === relationship.id ? 'border-blue-300 bg-blue-50' : 'border-slate-200'}`} onClick={() => onSelect({ kind: 'relationship', id: relationship.id })}><strong>{relationship.label}</strong><br /><span className="text-slate-500">{relationship.family} · {relationship.cardinality}</span></button>)}
      </InventorySection>
      <InventorySection title="Properties" count={objects.reduce((sum, object) => sum + object.metadataFields.length, 0)} />
      <InventorySection title="Candidates" count={candidates.length}>
        {candidates.map((candidate) => <button key={candidate.id} className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-left text-xs" onClick={() => onSelect({ kind: 'candidate', id: candidate.id })}>{candidate.label}<br /><span className="text-slate-500">{candidate.kind} · evidence {candidate.evidenceRefs.length}</span></button>)}
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
  objects: OntologyConceptType[];
  relationships: OntologyRelationshipType[];
  selected?: WorkbenchSelection;
  connectSource: string | null;
  onAddObject: () => void;
  onUseTemplate: () => void;
  onReviewCandidates: () => void;
  onSelectConcept: (id: string) => void;
  onSelectRelationship: (id: string) => void;
  onStartConnect: (id: string) => void;
  onCancelConnect: () => void;
}) {
  if (!props.objects.length) {
    return <div className="flex min-h-[520px] items-center justify-center p-8"><div className="max-w-lg rounded-3xl border bg-white p-8 text-center shadow-sm"><div className="text-[10px] font-bold uppercase tracking-[0.3em] text-slate-400">First run</div><h3 className="mt-2 text-2xl font-semibold">Design Object Types before editing arrays</h3><p className="mt-3 text-sm text-slate-600">Start with nouns, then draw governed Relationship Types between them. Nothing is saved until Publish.</p><div className="mt-6 flex flex-wrap justify-center gap-2"><button className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-bold text-white" onClick={props.onAddObject}>Add Object Type</button><button className="rounded-xl border px-4 py-2 text-sm" onClick={props.onUseTemplate}>Use Template</button><button className="rounded-xl border px-4 py-2 text-sm" onClick={props.onReviewCandidates}>Review Candidates</button></div></div></div>;
  }

  const layersWithObjects = layerCatalog.filter((layer) => props.objects.some((object) => object.layer === layer.id));
  const positions = props.objects.map((object) => {
    const layerIndex = Math.max(0, layersWithObjects.findIndex((layer) => layer.id === object.layer));
    const peerIndex = props.objects.filter((peer) => peer.layer === object.layer).findIndex((peer) => peer.id === object.id);
    return { object, x: 80 + peerIndex * 220, y: 116 + layerIndex * 142 };
  });
  const positionById = new Map(positions.map((item) => [item.object.id, item]));
  const canvasHeight = Math.max(460, 168 + layersWithObjects.length * 142);
  const canvasWidth = Math.max(760, 180 + Math.max(...layersWithObjects.map((layer) => props.objects.filter((object) => object.layer === layer.id).length), 1) * 230);

  return (
    <div className="relative min-h-[520px] overflow-auto bg-[#f4f7fa] p-6" aria-label="Ontology graph canvas" style={{ backgroundImage: 'radial-gradient(#dfe7ef 1px, transparent 1px)', backgroundSize: '24px 24px' }}>
      <div className="sticky top-0 z-10 mb-3 flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white/90 p-2 shadow-sm backdrop-blur">
        <span className={`${pill} border-blue-200 bg-blue-50 text-blue-700`}>Layered graph builder</span>
        <button className={softButton}>Group by Layer</button>
        <button className={softButton}>Search Around</button>
        {props.connectSource && <><span className="text-xs text-slate-600">Connect mode: choose a target Object Type</span><button className="rounded border px-2 py-1 text-xs" onClick={props.onCancelConnect}>Cancel connect</button><span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Targets</span>{props.objects.filter((object) => object.id !== props.connectSource).map((object) => <button key={object.id} className="rounded border border-blue-200 bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500" onClick={() => props.onSelectConcept(object.id)}>Use {object.label} as relationship target</button>)}</>}
      </div>
      <svg width={canvasWidth} height={canvasHeight} role="img" aria-label="Ontology object relationship canvas">
        <defs><marker id="ontology-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#64748b" /></marker></defs>
        {layersWithObjects.map((layer, index) => <g key={layer.id}><rect x="20" y={82 + index * 142} width={canvasWidth - 50} height="116" rx="14" fill="rgba(255,255,255,.58)" stroke="#d4dce5" /><text x="36" y={106 + index * 142} fontSize="11" fontWeight="800" fill="#64748b">LAYER: {layer.label.toUpperCase()}</text></g>)}
        {props.relationships.flatMap((rel) => rel.allowedSourceTypes.flatMap((source) => rel.allowedTargetTypes.map((target) => ({ rel, source: positionById.get(source), target: positionById.get(target) })))).filter((edge) => edge.source && edge.target).map((edge) => {
          const sx = edge.source!.x + 82; const sy = edge.source!.y + 36; const tx = edge.target!.x + 82; const ty = edge.target!.y + 36;
          const selected = props.selected?.kind === 'relationship' && props.selected.id === edge.rel.id;
          return <g key={`${edge.rel.id}-${edge.source!.object.id}-${edge.target!.object.id}`} onClick={() => props.onSelectRelationship(edge.rel.id)} className="cursor-pointer"><path d={`M ${sx} ${sy} C ${(sx + tx) / 2} ${sy}, ${(sx + tx) / 2} ${ty}, ${tx} ${ty}`} fill="none" markerEnd="url(#ontology-arrow)" stroke={selected ? '#2563eb' : '#64748b'} strokeWidth={selected ? 4 : 2} strokeDasharray={edge.rel.style === 'solid' ? undefined : edge.rel.style === 'dashed' ? '6 4' : '2 4'} /><rect x={(sx + tx) / 2 - 42} y={(sy + ty) / 2 - 18} width="84" height="22" rx="4" fill="#e0f2fe" stroke="#bae6fd" /><text x={(sx + tx) / 2} y={(sy + ty) / 2 - 3} textAnchor="middle" fontSize="11" fontWeight="700" fill="#334155">{edge.rel.label}</text></g>;
        })}
        {positions.map(({ object, x, y }) => {
          const meta = layerMeta(object.layer);
          const isSource = props.connectSource === object.id;
          const isTargetChoice = Boolean(props.connectSource && props.connectSource !== object.id);
          const selected = props.selected?.kind === 'concept' && props.selected.id === object.id;
          const connectLabel = isSource ? `${object.label} selected as relationship source` : isTargetChoice ? `Use ${object.label} as relationship target` : `Connect from ${object.label}`;
          const handleConnectButton = () => {
            if (isTargetChoice) {
              props.onSelectConcept(object.id);
              return;
            }
            props.onStartConnect(object.id);
          };
          return <g key={object.id} className="cursor-pointer"><rect x={x} y={y} width="164" height="72" rx="12" fill={selected ? '#dbeafe' : '#fff'} stroke={isSource ? '#f59e0b' : selected ? '#2563eb' : '#cfd9e2'} strokeWidth={selected ? 3 : 2} filter="drop-shadow(0 4px 5px rgba(30,42,56,.13))" onClick={() => props.onSelectConcept(object.id)} /><rect x={x + 12} y={y + 14} width="36" height="36" rx="8" fill={meta.id === 'governance' ? '#d97706' : meta.id === 'activation' ? '#059669' : meta.id === 'source' ? '#64748b' : '#2563eb'} /><text x={x + 30} y={y + 37} textAnchor="middle" fontSize="11" fontWeight="900" fill="#fff">{initials(object.label)}</text><text x={x + 60} y={y + 28} fontSize="14" fontWeight="800" fill="#0f172a">{object.label}</text><text x={x + 60} y={y + 48} fontSize="11" fill="#64748b">Object Type Unit</text><text x={x + 12} y={y + 64} fontSize="10" fontWeight="700" fill="#8796a6">layer.{object.layer}</text><foreignObject x={x + 126} y={y + 8} width="36" height="36"><button aria-label={connectLabel} title={connectLabel} className={`h-8 w-8 rounded-full text-xs font-bold focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 ${isSource ? 'bg-amber-500 text-white' : isTargetChoice ? 'bg-blue-600 text-white' : 'bg-slate-900 text-white'}`} onClick={handleConnectButton}>{isSource ? '✓' : isTargetChoice ? '→' : '↗'}</button></foreignObject></g>;
        })}
      </svg>
    </div>
  );
}

function BottomRail({ objectCount, relationshipCount, issueCount, lastDiff, impactPreview, onImpact }: { objectCount: number; relationshipCount: number; issueCount: number; lastDiff: string; impactPreview: boolean; onImpact: () => void }) {
  return <footer className="border-t bg-white px-4 py-3" style={{ borderColor: 'var(--color-border)' }}><div className="flex flex-wrap items-center gap-2 text-xs"><span className={`${pill} border-slate-200`}>{objectCount} objects</span><span className={`${pill} border-slate-200`}>{relationshipCount} relationships</span><span className={`${pill} ${issueCount ? 'border-red-200 bg-red-50 text-red-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{issueCount} validation issues</span><button className="rounded-lg border px-3 py-1 font-semibold" onClick={onImpact}>Preview map impact</button><span className="text-slate-500">{lastDiff}</span></div>{impactPreview && <div role="status" className="mt-2 rounded-xl border border-blue-200 bg-blue-50 p-3 text-xs text-blue-800">Example overlay: this typed namespace has no live instances yet. Preview uses labeled example nodes and never presents them as live data.</div>}</footer>;
}

function SelectionInspector({ profile, selection, focus, issues, impactPreview, onProfileChange, onSelect, onValidateIssue, onStageCandidate }: {
  profile: OntologyProfile;
  selection?: WorkbenchSelection;
  focus?: ValidationIssue['focus'];
  issues: ValidationIssue[];
  impactPreview: boolean;
  onProfileChange: (profile: OntologyProfile, label: string) => void;
  onSelect: (selection: WorkbenchSelection) => void;
  onValidateIssue: (issue: ValidationIssue) => void;
  onStageCandidate: (id: string) => void;
}) {
  const concept = selection?.kind === 'concept' ? profile.conceptTypes[selection.id] : undefined;
  const relationship = selection?.kind === 'relationship' ? profile.relationshipTypes[selection.id] : undefined;
  const candidate = selection?.kind === 'candidate' ? profile.candidates.find((item) => item.id === selection.id) : undefined;
  return <aside className="min-h-0 overflow-auto bg-white p-4" aria-label="Contextual ontology editor"><h3 className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Contextual inspector</h3>{issues.length > 0 && <section className="my-3 rounded-xl border border-red-200 bg-red-50 p-3"><h4 className="text-xs font-bold text-red-700">Validation routes</h4>{issues.map((issue) => <button key={issue.id} className="mt-2 block text-left text-xs text-red-800 underline" onClick={() => onValidateIssue(issue)}>{issue.message}</button>)}</section>}{concept ? <ObjectTypeEditor profile={profile} concept={concept} focus={focus} onProfileChange={onProfileChange} /> : relationship ? <RelationshipTypeEditor profile={profile} relationship={relationship} focus={focus} onProfileChange={onProfileChange} onSelect={onSelect} /> : candidate ? <section className="mt-4 space-y-3"><h4 className="text-lg font-semibold">Candidate · {candidate.label}</h4><p className="text-sm text-slate-600">{candidate.source}</p><div className="rounded-lg bg-slate-100 p-2 text-xs">Evidence refs: {candidate.evidenceRefs.join(', ')}</div><button className="rounded-lg bg-slate-900 px-3 py-2 text-xs font-bold text-white" onClick={() => onStageCandidate(candidate.id)}>Stage candidate locally</button></section> : <GovernancePanel profile={profile} impactPreview={impactPreview} />}</aside>;
}

function ObjectTypeEditor({ profile, concept, focus, onProfileChange }: { profile: OntologyProfile; concept: OntologyConceptType; focus?: ValidationIssue['focus']; onProfileChange: (profile: OntologyProfile, label: string) => void }) {
  const related = Object.values(profile.relationshipTypes).filter((rel) => rel.allowedSourceTypes.includes(concept.id) || rel.allowedTargetTypes.includes(concept.id));
  return <section className="mt-4 space-y-4" aria-label="Object Type editor"><div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="flex items-center gap-3"><span className={`grid h-10 w-10 place-items-center rounded-lg text-xs font-black text-white ${layerMeta(concept.layer).id === 'governance' ? 'bg-amber-600' : 'bg-blue-600'}`}>{initials(concept.label)}</span><div><h4 className="text-lg font-semibold">Object Type</h4><p className="text-xs text-slate-500">{concept.label} is a unit inside {layerName(concept.layer)}.</p></div></div></div><Field label="Label" focus={focus === 'identity'}><input className="w-full rounded-lg border px-3 py-2 text-sm" value={concept.label} onChange={(event) => onProfileChange(patchObjectType(profile, concept.id, { label: event.target.value }), 'Edit object label')} /></Field><Field label="Description"><textarea className="w-full rounded-lg border px-3 py-2 text-sm" rows={3} value={concept.description} onChange={(event) => onProfileChange(patchObjectType(profile, concept.id, { description: event.target.value }), 'Edit object description')} /></Field><Field label="Layer / abstraction"><div className="grid grid-cols-2 gap-2"><select className="rounded-lg border px-2 py-2 text-sm" value={concept.layer} onChange={(event) => onProfileChange(patchObjectType(profile, concept.id, { layer: event.target.value as OntologyConceptType['layer'] }), 'Edit layer')}><option value="source">Source</option><option value="semantic">Semantic</option><option value="governance">Governance</option><option value="activation">Activation</option></select><input className="rounded-lg border px-2 py-2 text-sm" value={concept.abstractionLevel} onChange={(event) => onProfileChange(patchObjectType(profile, concept.id, { abstractionLevel: event.target.value }), 'Edit abstraction')} /></div></Field><Field label="Properties"><div className="space-y-2"><div className="flex flex-wrap gap-2">{concept.metadataFields.map((field) => <span key={field.id} className={`${pill} border-slate-200`}>{field.label} · {field.type}</span>)}</div><button className="block rounded-lg border px-3 py-1 text-xs" onClick={() => onProfileChange(addMetadataFieldToObjectType(profile, concept.id, { label: 'Name', type: 'text' }), 'Add property')}>Add property</button></div></Field><Field label="Allowed relation coverage"><div className="space-y-2">{related.length ? related.map((rel) => <div key={rel.id} className="rounded-lg border border-slate-200 p-2 text-xs"><strong>{rel.label}</strong><div className="text-slate-500">source {rel.allowedSourceTypes.includes(concept.id) ? 'yes' : 'no'} · target {rel.allowedTargetTypes.includes(concept.id) ? 'yes' : 'no'}</div></div>) : <p className="text-xs text-slate-500">No governed relationships touch this Object Type yet. Use the node connect control to create one.</p>}</div></Field><Field label="Source mappings" focus={focus === 'source'}><div className="space-y-2">{concept.sourceMappings.map((mapping) => <div key={mapping.id} className="rounded-lg border p-2 text-xs"><strong>{mapping.source}</strong><br /><span className="text-slate-500">{mapping.selector}</span></div>)}<button className="rounded-lg border px-3 py-1 text-xs" onClick={() => onProfileChange(attachSourceMapping(profile, concept.id, { source: 'knowledge graph', selector: concept.label }), 'Attach source mapping')}>Attach source mapping</button></div></Field></section>;
}

function RelationshipTypeEditor({ profile, relationship, focus, onProfileChange, onSelect }: { profile: OntologyProfile; relationship: OntologyRelationshipType; focus?: ValidationIssue['focus']; onProfileChange: (profile: OntologyProfile, label: string) => void; onSelect: (selection: WorkbenchSelection) => void }) {
  const objects = Object.values(profile.conceptTypes);
  const updateList = (key: 'allowedSourceTypes' | 'allowedTargetTypes', id: string) => {
    const list = relationship[key];
    const nextList = list.includes(id) ? list.filter((item) => item !== id) : [...list, id];
    onProfileChange(patchRelationshipType(profile, relationship.id, { [key]: nextList }), 'Edit relationship endpoints');
  };
  return <section className="mt-4 space-y-4" aria-label="Relationship Type editor"><div className="rounded-xl border border-blue-200 bg-blue-50 p-3"><h4 className="text-lg font-semibold">Relationship Type</h4><p className="text-xs text-blue-800">A relation is created by choosing source Object Type units, target Object Type units, and cardinality.</p></div><Field label="Label"><input className="w-full rounded-lg border px-3 py-2 text-sm" value={relationship.label} onChange={(event) => onProfileChange(patchRelationshipType(profile, relationship.id, { label: event.target.value }), 'Edit relationship label')} /></Field><Field label="Endpoint chips" focus={focus === 'endpoint'}><ChipPicker label="Source Object Types" objects={objects} selected={relationship.allowedSourceTypes} onToggle={(id) => updateList('allowedSourceTypes', id)} /><ChipPicker label="Target Object Types" objects={objects} selected={relationship.allowedTargetTypes} onToggle={(id) => updateList('allowedTargetTypes', id)} /></Field><Field label="Family / cardinality" focus={focus === 'cardinality'}><div className="grid grid-cols-2 gap-2"><input className="rounded-lg border px-2 py-2 text-sm" value={relationship.family} onChange={(event) => onProfileChange(patchRelationshipType(profile, relationship.id, { family: event.target.value }), 'Edit family')} /><select className="rounded-lg border px-2 py-2 text-sm" value={relationship.cardinality} onChange={(event) => onProfileChange(patchRelationshipType(profile, relationship.id, { cardinality: event.target.value as Cardinality }), 'Edit cardinality')}><option value="one_to_one">one_to_one</option><option value="one_to_many">one_to_many</option><option value="many_to_one">many_to_one</option><option value="many_to_many">many_to_many</option></select></div></Field><Field label="Direction / style"><div className="grid grid-cols-3 gap-2"><select className="rounded-lg border px-2 py-2 text-sm" value={relationship.mapDirection} onChange={(event) => onProfileChange(patchRelationshipType(profile, relationship.id, { mapDirection: event.target.value as OntologyRelationshipType['mapDirection'] }), 'Edit direction')}><option value="forward">forward</option><option value="reverse">reverse</option><option value="bidirectional">bidirectional</option></select><select className="rounded-lg border px-2 py-2 text-sm" value={relationship.style} onChange={(event) => onProfileChange(patchRelationshipType(profile, relationship.id, { style: event.target.value as OntologyRelationshipType['style'] }), 'Edit style')}><option value="solid">solid</option><option value="dashed">dashed</option><option value="dotted">dotted</option></select><input className="rounded-lg border px-2 py-2 text-sm" type="number" min="0" max="1" step="0.1" value={relationship.weight} onChange={(event) => onProfileChange(patchRelationshipType(profile, relationship.id, { weight: Number(event.target.value) }), 'Edit weight')} /></div></Field><RelationshipMatrix profile={profile} relationship={relationship} onProfileChange={onProfileChange} onSelect={onSelect} /></section>;
}

function ChipPicker({ label, objects, selected, onToggle }: { label: string; objects: OntologyConceptType[]; selected: string[]; onToggle: (id: string) => void }) {
  return <div className="mb-2"><div className="mb-1 text-[11px] font-bold text-slate-500">{label}</div><div className="flex flex-wrap gap-1">{objects.map((object) => <button key={object.id} className={`${pill} ${selected.includes(object.id) ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-slate-200 bg-white text-slate-600'}`} onClick={() => onToggle(object.id)}>{object.label}</button>)}</div></div>;
}

function RelationshipMatrix({ profile, relationship, onProfileChange, onSelect }: { profile: OntologyProfile; relationship: OntologyRelationshipType; onProfileChange: (profile: OntologyProfile, label: string) => void; onSelect: (selection: WorkbenchSelection) => void }) {
  const objects = Object.values(profile.conceptTypes);
  return <Field label="Relationship matrix"><p className="mb-2 text-[11px] text-slate-500">Endpoint sets create all source-target combinations for this Relationship Type.</p><div className="overflow-auto rounded-xl border"><table className="w-full min-w-[260px] text-xs"><thead><tr><th className="bg-slate-50 p-2 text-left">Source \ Target</th>{objects.map((target) => <th key={target.id} className="bg-slate-50 p-2">{target.label}</th>)}</tr></thead><tbody>{objects.map((source) => <tr key={source.id}><th className="bg-slate-50 p-2 text-left">{source.label}</th>{objects.map((target) => { const active = relationship.allowedSourceTypes.includes(source.id) && relationship.allowedTargetTypes.includes(target.id); return <td key={target.id} className="p-1 text-center"><button aria-label={`Toggle ${source.label} to ${target.label}`} className={`h-7 w-7 rounded ${active ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-400'}`} onClick={() => { onProfileChange(toggleRelationshipEndpoint(profile, relationship.id, source.id, target.id), 'Toggle matrix endpoint'); onSelect({ kind: 'relationship', id: relationship.id, focus: 'endpoint' }); }}>{active ? '✓' : '+'}</button></td>; })}</tr>)}</tbody></table></div></Field>;
}

function GovernancePanel({ profile, impactPreview }: { profile: OntologyProfile; impactPreview: boolean }) {
  return <section className="mt-4 space-y-3"><h4 className="text-lg font-semibold">Governance home</h4><p className="text-sm text-slate-600">One editor path for Object Types, Relationship Types, Candidates, Source Mappings, and publish governance. Legacy ConceptTypeStudio and RelationshipStudio are intentionally absent from the default authoring path.</p><div className="rounded-xl border p-3 text-xs">Profile: {profile.label}<br />Status: {profile.status}<br />GraphInstruction concept defaults: {Object.keys(profile.graphInstruction.conceptTypeDefaults).length}<br />GraphInstruction relationship defaults: {Object.keys(profile.graphInstruction.relationshipTypeDefaults).length}</div><div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600"><strong className="block text-slate-800">Knowledge development flow</strong>Extract candidate nouns → stage Object Type units → connect relationship endpoints → validate governance → publish as knowledge.</div>{impactPreview && <div className="rounded-xl bg-blue-50 p-3 text-xs text-blue-800">Map impact preview is active with example-data honesty for empty namespaces.</div>}</section>;
}

function Field({ label, focus, children }: { label: string; focus?: boolean; children: React.ReactNode }) {
  return <label className={`block rounded-xl p-2 ${focus ? 'ring-2 ring-blue-400' : ''}`}><span className="mb-1 block text-[11px] font-bold uppercase tracking-wider text-slate-500">{label}</span>{children}</label>;
}
