"use client";

import React, { useMemo, useState } from 'react';
import type { CanvasEdge, CanvasNode, GraphSelection, RelationshipTypeRef } from './types';

type ValidationSeverity = 'error' | 'warning';

export interface InstanceValidationIssue {
  field_path: string;
  severity: ValidationSeverity;
  message: string;
  focus_target: string;
}

interface MetadataField {
  path: string;
  label: string;
  type: 'string' | 'number' | 'enum';
  required?: boolean;
  options?: string[];
}

interface ObjectInstanceDraft {
  id?: string;
  typeLabel: string;
  label: string;
  properties: Record<string, string>;
  evidence: string[];
  sourceRecords: string[];
}

interface RelationshipDraft {
  id?: string;
  relationship_type_id: string;
  source: string;
  target: string;
  label: string;
  evidence: string[];
  sourceRecords: string[];
}

interface MutationResult<T> {
  item: T;
  validation_issues: InstanceValidationIssue[];
  audit_event_id?: string;
}

interface InstanceAuthoringPanelProps {
  namespace: string;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  relationshipTypes: RelationshipTypeRef[];
  selectedNode?: CanvasNode;
  selectedEdge?: CanvasEdge;
  onCreateObject: (node: CanvasNode) => void;
  onUpdateObject: (node: CanvasNode) => void;
  onDeleteObject: (nodeId: string) => void;
  onCreateRelationship: (edge: CanvasEdge) => void;
  onUpdateRelationship: (edge: CanvasEdge) => void;
  onDeleteRelationship: (edgeId: string) => void;
  onSelect: (selection: GraphSelection) => void;
  historicalReadonly?: boolean;
}

const objectTypes = ['Customer', 'Policy', 'Claim', 'Agent Session'];
const editableActions = new Set(['edit', 'update', 'delete', 'create_relationship', 'create_instance']);

const fieldMetadataByType: Record<string, MetadataField[]> = {
  Customer: [
    { path: 'properties.name', label: 'Customer name', type: 'string', required: true },
    { path: 'properties.stableId', label: 'Stable ID', type: 'string', required: true },
    { path: 'properties.status', label: 'Lifecycle status', type: 'enum', options: ['active', 'prospect', 'inactive'] },
    { path: 'properties.recordCount', label: 'Record count', type: 'number' },
  ],
  Policy: [
    { path: 'properties.name', label: 'Policy name', type: 'string', required: true },
    { path: 'properties.stableId', label: 'Stable ID', type: 'string', required: true },
    { path: 'properties.status', label: 'Lifecycle status', type: 'enum', options: ['draft', 'active', 'expired'] },
  ],
  Claim: [
    { path: 'properties.name', label: 'Claim name', type: 'string', required: true },
    { path: 'properties.stableId', label: 'Stable ID', type: 'string', required: true },
    { path: 'properties.amount', label: 'Amount', type: 'number' },
  ],
  'Agent Session': [
    { path: 'properties.name', label: 'Session name', type: 'string', required: true },
    { path: 'properties.stableId', label: 'Stable ID', type: 'string', required: true },
  ],
};

function fieldsFor(typeLabel: string): MetadataField[] {
  return fieldMetadataByType[typeLabel] ?? fieldMetadataByType.Customer;
}

function propertyName(path: string) {
  return path.replace('properties.', '');
}

function canMutateNode(node?: CanvasNode) {
  if (!node) return true;
  if (node.redacted || node.permissions.level === 'limited') return false;
  return node.permissions.allowedActions.some((action) => editableActions.has(action)) || node.source === 'search';
}

function sanitizeTypeLabel(label: string) {
  if (label.includes('Customer')) return 'Customer';
  if (label.includes('Policy')) return 'Policy';
  if (label.includes('Claim')) return 'Claim';
  if (label.includes('Agent')) return 'Agent Session';
  return label;
}

function typeCompatible(relationship: RelationshipTypeRef | undefined, source?: CanvasNode, target?: CanvasNode) {
  if (!relationship || !source || !target || relationship.retired) return false;
  const sourceLabels = [source.typeLabel, source.label, ...source.badges].map(sanitizeTypeLabel);
  const targetLabels = [target.typeLabel, target.label, ...target.badges].map(sanitizeTypeLabel);
  return relationship.source_types.some((type) => sourceLabels.includes(sanitizeTypeLabel(type))) && relationship.target_types.some((type) => targetLabels.includes(sanitizeTypeLabel(type)));
}

function validateObjectDraft(draft: ObjectInstanceDraft): InstanceValidationIssue[] {
  return fieldsFor(draft.typeLabel).flatMap((field) => {
    const key = propertyName(field.path);
    const value = draft.properties[key]?.trim() ?? '';
    if (field.required && !value) {
      return [{ field_path: field.path, severity: 'error' as const, message: `${field.label} is required.`, focus_target: field.path }];
    }
    if (field.type === 'number' && value && Number.isNaN(Number(value))) {
      return [{ field_path: field.path, severity: 'error' as const, message: `${field.label} must be a number.`, focus_target: field.path }];
    }
    return [];
  });
}

function validateRelationshipDraft(draft: RelationshipDraft, nodes: CanvasNode[], edges: CanvasEdge[], relationshipTypes: RelationshipTypeRef[]): InstanceValidationIssue[] {
  const issues: InstanceValidationIssue[] = [];
  const relationship = relationshipTypes.find((item) => item.id === draft.relationship_type_id);
  const source = nodes.find((node) => node.id === draft.source);
  const target = nodes.find((node) => node.id === draft.target);
  if (!relationship) issues.push({ field_path: 'relationship_type_id', severity: 'error', message: 'Choose a relationship type.', focus_target: 'relationship_type_id' });
  if (!source) issues.push({ field_path: 'source', severity: 'error', message: 'Choose a source object.', focus_target: 'source' });
  if (!target) issues.push({ field_path: 'target', severity: 'error', message: 'Choose a target object.', focus_target: 'target' });
  if (relationship?.retired) issues.push({ field_path: 'relationship_type_id', severity: 'error', message: `${relationship.label} is retired and cannot be authored.`, focus_target: 'relationship_type_id' });
  if (relationship && source && target && !typeCompatible(relationship, source, target)) {
    issues.push({ field_path: 'relationship_type_id', severity: 'error', message: `${relationship.label} is incompatible with ${source.typeLabel} → ${target.typeLabel}.`, focus_target: 'relationship_type_id' });
  }
  if (relationship?.id === 'owns' && source && edges.some((edge) => edge.source === source.id && edge.label.includes('owns') && edge.id !== draft.id)) {
    issues.push({ field_path: 'source', severity: 'error', message: 'Cardinality violation: mock Customer can own only one active policy relationship.', focus_target: 'source' });
  }
  return issues;
}

function duplicateWarnings(draft: ObjectInstanceDraft, nodes: CanvasNode[]): string[] {
  const stableId = draft.properties.stableId?.trim().toLowerCase();
  const label = draft.label.trim().toLowerCase();
  if (!stableId && !label) return [];
  return nodes
    .filter((node) => node.id !== draft.id)
    .filter((node) => node.id.toLowerCase().includes(stableId) || node.label.toLowerCase() === label || String(node.properties.stableId ?? '').toLowerCase() === stableId)
    .map((node) => `${node.label} (${node.id}) may be the same identity.`);
}

function makeCanvasNode(draft: ObjectInstanceDraft, index: number, existing?: CanvasNode): CanvasNode {
  const stable = draft.properties.stableId?.trim() || draft.label.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-');
  const id = draft.id ?? `object.instance-${stable}`;
  const label = draft.label.trim() || draft.properties.name?.trim() || `${draft.typeLabel} instance`;
  return {
    id,
    label,
    typeLabel: draft.typeLabel,
    badges: [draft.typeLabel, 'Instance'],
    x: existing?.x ?? 90 + (index % 4) * 190,
    y: existing?.y ?? 520 + Math.floor(index / 4) * 140,
    redacted: false,
    properties: Object.fromEntries(Object.entries(draft.properties).filter(([, value]) => value.trim()).map(([key, value]) => [key, Number.isNaN(Number(value)) || value.trim() === '' ? value : value])),
    permissions: { level: 'read', allowedActions: ['view', 'edit', 'delete', 'create_relationship'] },
    validation: { count: 0, issues: [] },
    provenance: { refs: [...draft.evidence, ...draft.sourceRecords] },
    style: { color: draft.typeLabel === 'Customer' ? '#38bdf8' : draft.typeLabel === 'Policy' ? '#a78bfa' : '#34d399', shape: 'rounded', opacity: 1, stroke: '#22d3ee' },
    source: existing?.source ?? 'search',
    events: existing?.events ?? [],
    activeEventCount: existing?.activeEventCount ?? 0,
    totalEventCount: existing?.totalEventCount ?? 0,
    timeSeries: existing?.timeSeries ?? [],
  };
}

function makeCanvasEdge(draft: RelationshipDraft, nodes: CanvasNode[], relationshipTypes: RelationshipTypeRef[], existing?: CanvasEdge): CanvasEdge {
  const relationship = relationshipTypes.find((item) => item.id === draft.relationship_type_id);
  return {
    id: draft.id ?? `rel.instance-${draft.source}-${draft.target}-${draft.relationship_type_id}`,
    source: draft.source,
    target: draft.target,
    label: draft.label || relationship?.label || 'related to',
    badges: [relationship?.label ?? 'Relationship', 'Instance'],
    redacted: false,
    properties: { relationship_type_id: draft.relationship_type_id, source_label: nodes.find((node) => node.id === draft.source)?.label, target_label: nodes.find((node) => node.id === draft.target)?.label },
    permissions: { level: 'read', allowedActions: ['view', 'edit', 'delete'] },
    validation: { count: 0, issues: [] },
    provenance: { refs: [...draft.evidence, ...draft.sourceRecords] },
    style: existing?.style ?? { color: '#22d3ee', weight: 2, opacity: 0.9 },
    events: existing?.events ?? [],
    activeEventCount: existing?.activeEventCount ?? 0,
    totalEventCount: existing?.totalEventCount ?? 0,
    timeSeries: existing?.timeSeries ?? [],
  };
}

function mockPersist<T>(item: T, issues: InstanceValidationIssue[], action: string): Promise<MutationResult<T>> {
  return new Promise((resolve) => window.setTimeout(() => resolve({ item, validation_issues: issues, audit_event_id: issues.some((issue) => issue.severity === 'error') ? undefined : `audit-${action}-${Date.now()}` }), 20));
}

export function InstanceAuthoringPanel(props: InstanceAuthoringPanelProps) {
  const { namespace, nodes, edges, relationshipTypes, selectedNode, selectedEdge, onCreateObject, onUpdateObject, onDeleteObject, onCreateRelationship, onUpdateRelationship, onDeleteRelationship, onSelect, historicalReadonly = false } = props;
  const [createObjectOpen, setCreateObjectOpen] = useState(false);
  const [editObjectOpen, setEditObjectOpen] = useState(false);
  const [createRelationshipOpen, setCreateRelationshipOpen] = useState(false);
  const [editRelationshipOpen, setEditRelationshipOpen] = useState(false);
  const [auditEventId, setAuditEventId] = useState<string | null>(null);
  const selectionReadOnly = selectedNode ? !canMutateNode(selectedNode) : false;
  const readOnly = historicalReadonly || selectionReadOnly;

  return (
    <section data-testid="instance-authoring-panel" className="mt-5 rounded-xl border border-fuchsia-400/30 bg-fuchsia-950/10 p-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider text-fuchsia-200">Instance authoring</h3>
          <p className="mt-1 text-xs text-slate-500">Mock steward workspace · {namespace}</p>
        </div>
        {auditEventId && <a data-testid="audit-event-link" href={`#${auditEventId}`} className="rounded-full bg-emerald-400/10 px-2 py-1 text-[11px] font-semibold text-emerald-200">Audit {auditEventId}</a>}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <button data-testid="open-instance-create-button" type="button" onClick={() => { if (!historicalReadonly) setCreateObjectOpen(true); }} disabled={historicalReadonly} className="rounded-lg bg-fuchsia-300 px-2 py-1.5 text-xs font-bold text-slate-950 disabled:opacity-40">Create object</button>
        <button data-testid="open-relationship-create-button" type="button" onClick={() => { if (!historicalReadonly) setCreateRelationshipOpen(true); }} disabled={historicalReadonly || nodes.length < 2} className="rounded-lg border border-fuchsia-300 px-2 py-1.5 text-xs font-semibold text-fuchsia-100 disabled:opacity-40">Create relationship</button>
        <button type="button" onClick={() => { if (!readOnly) setEditObjectOpen(true); }} disabled={!selectedNode || readOnly} className="rounded-lg border border-slate-700 px-2 py-1.5 text-xs font-semibold text-slate-200 disabled:opacity-40">Edit selected object</button>
        <button type="button" onClick={() => { if (!historicalReadonly) setEditRelationshipOpen(true); }} disabled={!selectedEdge || historicalReadonly} className="rounded-lg border border-slate-700 px-2 py-1.5 text-xs font-semibold text-slate-200 disabled:opacity-40">Edit selected relationship</button>
      </div>
      {readOnly && <div data-testid="permission-denied-state" className="mt-3 rounded-lg border border-amber-400/40 bg-amber-400/10 p-2 text-xs text-amber-100">{historicalReadonly ? 'Historical version is read-only. Create/edit/delete controls are disabled, but audit and evidence remain visible.' : 'Selected object is read-only for this user. Create/edit/delete controls are disabled, but audit and evidence remain visible.'}</div>}
      <div className="mt-3 rounded-lg border border-slate-800 p-2 text-xs text-slate-400">
        <p className="font-semibold text-slate-200">Bulk edit</p>
        <p>Coming soon: governance-safe batch mutation is disabled until later scenarios.</p>
      </div>
      {createObjectOpen && <ObjectInstanceModal mode="create" readOnly={historicalReadonly} nodes={nodes} onClose={() => setCreateObjectOpen(false)} onSave={async (draft) => { if (historicalReadonly) return [{ field_path: 'readonly', severity: 'error', message: 'Historical versions are read-only.', focus_target: 'readonly' }]; const issues = validateObjectDraft(draft); const item = makeCanvasNode(draft, nodes.length); const result = await mockPersist(item, issues, 'object-create'); if (result.validation_issues.some((issue) => issue.severity === 'error')) return result.validation_issues; onCreateObject(result.item); setAuditEventId(result.audit_event_id ?? null); setCreateObjectOpen(false); onSelect({ kind: 'node', id: result.item.id }); return []; }} />}
      {editObjectOpen && selectedNode && <ObjectInstanceModal mode="edit" readOnly={readOnly} node={selectedNode} nodes={nodes} onClose={() => setEditObjectOpen(false)} onDelete={() => { if (readOnly) return; onDeleteObject(selectedNode.id); setAuditEventId(`audit-object-delete-${Date.now()}`); setEditObjectOpen(false); onSelect(null); }} onSave={async (draft) => { if (readOnly) return [{ field_path: 'readonly', severity: 'error', message: 'This object is read-only.', focus_target: 'readonly' }]; const issues = validateObjectDraft(draft); const item = makeCanvasNode(draft, nodes.length, selectedNode); const result = await mockPersist(item, issues, 'object-update'); if (result.validation_issues.some((issue) => issue.severity === 'error')) return result.validation_issues; onUpdateObject(result.item); setAuditEventId(result.audit_event_id ?? null); setEditObjectOpen(false); return []; }} />}
      {createRelationshipOpen && <RelationshipInstanceModal mode="create" readOnly={historicalReadonly} nodes={nodes} edges={edges} relationshipTypes={relationshipTypes} selectedNode={selectedNode} onClose={() => setCreateRelationshipOpen(false)} onSave={async (draft) => { if (historicalReadonly) return [{ field_path: 'readonly', severity: 'error', message: 'Historical versions are read-only.', focus_target: 'readonly' }]; const issues = validateRelationshipDraft(draft, nodes, edges, relationshipTypes); const item = makeCanvasEdge(draft, nodes, relationshipTypes); const result = await mockPersist(item, issues, 'relationship-create'); if (result.validation_issues.some((issue) => issue.severity === 'error')) return result.validation_issues; onCreateRelationship(result.item); setAuditEventId(result.audit_event_id ?? null); setCreateRelationshipOpen(false); onSelect({ kind: 'edge', id: result.item.id }); return []; }} />}
      {editRelationshipOpen && selectedEdge && <RelationshipInstanceModal mode="edit" readOnly={historicalReadonly} edge={selectedEdge} nodes={nodes} edges={edges} relationshipTypes={relationshipTypes} onClose={() => setEditRelationshipOpen(false)} onDelete={() => { if (historicalReadonly) return; onDeleteRelationship(selectedEdge.id); setAuditEventId(`audit-relationship-delete-${Date.now()}`); setEditRelationshipOpen(false); onSelect(null); }} onSave={async (draft) => { if (historicalReadonly) return [{ field_path: 'readonly', severity: 'error', message: 'Historical versions are read-only.', focus_target: 'readonly' }]; const issues = validateRelationshipDraft(draft, nodes, edges, relationshipTypes); const item = makeCanvasEdge(draft, nodes, relationshipTypes, selectedEdge); const result = await mockPersist(item, issues, 'relationship-update'); if (result.validation_issues.some((issue) => issue.severity === 'error')) return result.validation_issues; onUpdateRelationship(result.item); setAuditEventId(result.audit_event_id ?? null); setEditRelationshipOpen(false); return []; }} />}
    </section>
  );
}

function ObjectInstanceModal({ mode, node, nodes, onClose, onSave, onDelete, readOnly = false }: { mode: 'create' | 'edit'; node?: CanvasNode; nodes: CanvasNode[]; onClose: () => void; onSave: (draft: ObjectInstanceDraft) => Promise<InstanceValidationIssue[]>; onDelete?: () => void; readOnly?: boolean }) {
  const [draft, setDraft] = useState<ObjectInstanceDraft>(() => ({ id: node?.id, typeLabel: sanitizeTypeLabel(node?.typeLabel ?? 'Customer'), label: node?.label ?? '', properties: { name: node?.label ?? '', stableId: String(node?.properties.stableId ?? node?.id?.replace(/^object\./, '') ?? ''), status: String(node?.properties.status ?? ''), recordCount: String(node?.properties.recordCount ?? '') }, evidence: node?.provenance.refs.filter((ref) => ref.startsWith('evidence://')) ?? [], sourceRecords: node?.provenance.refs.filter((ref) => ref.startsWith('source://') || ref.startsWith('doc://')) ?? [] }));
  const [baseDraft, setBaseDraft] = useState(draft);
  const [issues, setIssues] = useState<InstanceValidationIssue[]>([]);
  const [saving, setSaving] = useState(false);
  const fields = fieldsFor(draft.typeLabel);
  const warnings = duplicateWarnings(draft, nodes);
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseDraft);
  const setProp = (key: string, value: string) => setDraft((current) => ({ ...current, label: key === 'name' ? value : current.label, properties: { ...current.properties, [key]: value } }));
  const submit = async () => { if (readOnly) { setIssues([{ field_path: 'readonly', severity: 'error', message: 'This view is read-only. Switch to Current draft/live to author instances.', focus_target: 'readonly' }]); return; } setSaving(true); const localIssues = validateObjectDraft(draft); if (localIssues.length) { setIssues(localIssues); setSaving(false); return; } const responseIssues = await onSave(draft); setIssues(responseIssues); if (!responseIssues.length) setBaseDraft(draft); setSaving(false); };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-6">
      <div data-testid={mode === 'create' ? 'instance-create-modal' : 'instance-edit-form'} className="w-full max-w-3xl rounded-2xl border border-slate-700 bg-slate-950 p-5 shadow-2xl">
        <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">{mode === 'create' ? 'Create object instance' : 'Edit object instance'}</h2><button type="button" onClick={onClose} className="text-slate-400">Close</button></div>
        <div data-testid="dirty-state-indicator" className={`mt-3 rounded-lg border p-2 text-xs ${dirty ? 'border-amber-400/50 bg-amber-400/10 text-amber-100' : 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100'}`}>{dirty ? 'Unsaved draft changes' : 'Draft matches saved state'}</div>
        <label className="mt-4 block text-xs text-slate-400">Object type<select value={draft.typeLabel} onChange={(event) => setDraft((current) => ({ ...current, typeLabel: event.target.value, properties: { name: current.properties.name ?? '', stableId: current.properties.stableId ?? '' } }))} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100">{objectTypes.map((type) => <option key={type}>{type}</option>)}</select></label>
        <div className="mt-4 grid grid-cols-2 gap-3">
          {fields.map((field) => { const key = propertyName(field.path); const issue = issues.find((item) => item.field_path === field.path); return <label key={field.path} data-testid={field.required ? 'required-field' : undefined} className="block text-xs text-slate-400">{field.label}{field.required && <span className="text-rose-300"> *</span>}{field.type === 'enum' ? <select value={draft.properties[key] ?? ''} onChange={(event) => setProp(key, event.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"><option value="">Choose…</option>{field.options?.map((option) => <option key={option}>{option}</option>)}</select> : <input value={draft.properties[key] ?? ''} onChange={(event) => setProp(key, event.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100" />}{issue && <p data-testid="field-validation-error" className="mt-1 text-rose-200">{issue.message}</p>}</label>; })}
        </div>
        <EvidenceAttachmentPanel values={draft.evidence} onChange={(evidence) => setDraft((current) => ({ ...current, evidence }))} />
        <SourceRecordLinker values={draft.sourceRecords} onChange={(sourceRecords) => setDraft((current) => ({ ...current, sourceRecords }))} />
        <DuplicateDetectionPanel warnings={warnings} />
        <IdentityResolutionPanel warnings={warnings} onKeepSeparate={() => setIssues((current) => current.filter((issue) => issue.field_path !== 'identity'))} />
        <div className="mt-5 flex justify-between gap-2"><div>{mode === 'edit' && onDelete && <button type="button" onClick={onDelete} disabled={readOnly} className="rounded-lg border border-rose-400 px-3 py-2 text-sm font-semibold text-rose-100 disabled:opacity-40">Delete</button>}</div><div className="flex gap-2"><button type="button" onClick={() => { setDraft(baseDraft); setIssues([]); }} className="rounded-lg border border-slate-700 px-3 py-2 text-sm">Rollback draft</button><button type="button" onClick={onClose} className="rounded-lg border border-slate-700 px-3 py-2 text-sm">Cancel</button><button data-testid="save-instance-button" type="button" onClick={submit} disabled={saving || readOnly} className="rounded-lg bg-fuchsia-300 px-3 py-2 text-sm font-bold text-slate-950 disabled:opacity-40">{saving ? 'Saving…' : 'Save instance'}</button></div></div>
      </div>
    </div>
  );
}

function RelationshipInstanceModal({ mode, edge, nodes, edges, relationshipTypes, selectedNode, onClose, onSave, onDelete, readOnly = false }: { mode: 'create' | 'edit'; edge?: CanvasEdge; nodes: CanvasNode[]; edges: CanvasEdge[]; relationshipTypes: RelationshipTypeRef[]; selectedNode?: CanvasNode; onClose: () => void; onSave: (draft: RelationshipDraft) => Promise<InstanceValidationIssue[]>; onDelete?: () => void; readOnly?: boolean }) {
  const [draft, setDraft] = useState<RelationshipDraft>(() => ({ id: edge?.id, relationship_type_id: String(edge?.properties.relationship_type_id ?? relationshipTypes[0]?.id ?? ''), source: edge?.source ?? selectedNode?.id ?? nodes[0]?.id ?? '', target: edge?.target ?? nodes.find((node) => node.id !== (selectedNode?.id ?? nodes[0]?.id))?.id ?? '', label: edge?.label ?? relationshipTypes[0]?.label ?? '', evidence: edge?.provenance.refs.filter((ref) => ref.startsWith('evidence://')) ?? [], sourceRecords: edge?.provenance.refs.filter((ref) => ref.startsWith('source://') || ref.startsWith('doc://')) ?? [] }));
  const [baseDraft, setBaseDraft] = useState(draft);
  const [issues, setIssues] = useState<InstanceValidationIssue[]>([]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseDraft);
  const relationship = relationshipTypes.find((item) => item.id === draft.relationship_type_id);
  const compatibleTargets = useMemo(() => nodes.filter((node) => !relationship || typeCompatible(relationship, nodes.find((source) => source.id === draft.source), node)), [draft.source, nodes, relationship]);
  const submit = async () => { if (readOnly) { setIssues([{ field_path: 'readonly', severity: 'error', message: 'This view is read-only. Switch to Current draft/live to author relationships.', focus_target: 'readonly' }]); return; } const localIssues = validateRelationshipDraft(draft, nodes, edges, relationshipTypes); if (localIssues.length) { setIssues(localIssues); return; } const responseIssues = await onSave(draft); setIssues(responseIssues); if (!responseIssues.length) setBaseDraft(draft); };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-6">
      <div data-testid={mode === 'create' ? 'relationship-create-modal' : 'relationship-edit-form'} className="w-full max-w-3xl rounded-2xl border border-slate-700 bg-slate-950 p-5 shadow-2xl">
        <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">{mode === 'create' ? 'Create relationship instance' : 'Edit relationship instance'}</h2><button type="button" onClick={onClose} className="text-slate-400">Close</button></div>
        <div data-testid="dirty-state-indicator" className={`mt-3 rounded-lg border p-2 text-xs ${dirty ? 'border-amber-400/50 bg-amber-400/10 text-amber-100' : 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100'}`}>{dirty ? 'Unsaved relationship draft changes' : 'Relationship draft clean'}</div>
        <div className="mt-4 grid grid-cols-2 gap-3 text-xs text-slate-400">
          <label>Relationship type<select value={draft.relationship_type_id} onChange={(event) => { const next = relationshipTypes.find((item) => item.id === event.target.value); setDraft((current) => ({ ...current, relationship_type_id: event.target.value, label: next?.label ?? current.label })); }} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100">{relationshipTypes.map((item) => <option key={item.id} value={item.id}>{item.label}{item.retired ? ' (retired)' : ''}</option>)}</select></label>
          <label>Label<input value={draft.label} onChange={(event) => setDraft((current) => ({ ...current, label: event.target.value }))} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100" /></label>
          <label>Source<select value={draft.source} onChange={(event) => setDraft((current) => ({ ...current, source: event.target.value }))} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100">{nodes.map((node) => <option key={node.id} value={node.id}>{node.label} · {node.typeLabel}</option>)}</select></label>
          <label>Target<select value={draft.target} onChange={(event) => setDraft((current) => ({ ...current, target: event.target.value }))} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100">{nodes.map((node) => <option key={node.id} value={node.id}>{node.label} · {compatibleTargets.some((target) => target.id === node.id) ? 'compatible' : 'incompatible'}</option>)}</select></label>
        </div>
        {issues.map((issue) => <p key={`${issue.field_path}-${issue.message}`} data-testid="field-validation-error" className="mt-2 rounded-lg border border-rose-400/40 bg-rose-400/10 p-2 text-xs text-rose-100">{issue.message}</p>)}
        <EvidenceAttachmentPanel values={draft.evidence} onChange={(evidence) => setDraft((current) => ({ ...current, evidence }))} />
        <SourceRecordLinker values={draft.sourceRecords} onChange={(sourceRecords) => setDraft((current) => ({ ...current, sourceRecords }))} />
        <div className="mt-5 flex justify-between gap-2"><div>{mode === 'edit' && onDelete && <button type="button" onClick={onDelete} disabled={readOnly} className="rounded-lg border border-rose-400 px-3 py-2 text-sm font-semibold text-rose-100 disabled:opacity-40">Delete</button>}</div><div className="flex gap-2"><button type="button" onClick={() => { setDraft(baseDraft); setIssues([]); }} className="rounded-lg border border-slate-700 px-3 py-2 text-sm">Rollback draft</button><button type="button" onClick={onClose} className="rounded-lg border border-slate-700 px-3 py-2 text-sm">Cancel</button><button data-testid="save-instance-button" type="button" onClick={submit} disabled={readOnly} className="rounded-lg bg-fuchsia-300 px-3 py-2 text-sm font-bold text-slate-950 disabled:opacity-40">Save relationship</button></div></div>
      </div>
    </div>
  );
}

function EvidenceAttachmentPanel({ values, onChange }: { values: string[]; onChange: (values: string[]) => void }) {
  const [value, setValue] = useState('evidence://crm/customer-row-42');
  return <section data-testid="evidence-attachment-panel" className="mt-4 rounded-xl border border-slate-800 p-3"><div className="flex items-center justify-between"><h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">Evidence</h3><button type="button" onClick={() => { if (value.trim()) onChange(Array.from(new Set([...values, value.trim()]))); }} className="text-xs font-semibold text-cyan-300">Attach</button></div><input value={value} onChange={(event) => setValue(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm" />{values.map((item) => <p key={item} className="mt-2 rounded bg-slate-900 p-2 text-xs text-slate-200">{item}</p>)}</section>;
}

function SourceRecordLinker({ values, onChange }: { values: string[]; onChange: (values: string[]) => void }) {
  const [value, setValue] = useState('source://crm/accounts/42');
  return <section data-testid="source-record-linker" className="mt-4 rounded-xl border border-slate-800 p-3"><div className="flex items-center justify-between"><h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">Source records</h3><button type="button" onClick={() => { if (value.trim()) onChange(Array.from(new Set([...values, value.trim()]))); }} className="text-xs font-semibold text-cyan-300">Link source</button></div><input value={value} onChange={(event) => setValue(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm" />{values.map((item) => <p key={item} className="mt-2 rounded bg-slate-900 p-2 text-xs text-slate-200">{item}</p>)}</section>;
}

function DuplicateDetectionPanel({ warnings }: { warnings: string[] }) {
  return <section data-testid="duplicate-detection-panel" className="mt-4 rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 text-xs text-amber-100"><p className="font-semibold">Duplicate warnings</p>{warnings.length ? warnings.map((warning) => <p key={warning} className="mt-1">{warning}</p>) : <p className="mt-1 text-amber-100/70">No duplicate identity detected for this draft.</p>}</section>;
}

function IdentityResolutionPanel({ warnings, onKeepSeparate }: { warnings: string[]; onKeepSeparate: () => void }) {
  return <section data-testid="identity-resolution-panel" className="mt-4 rounded-xl border border-cyan-400/30 bg-cyan-400/10 p-3 text-xs text-cyan-100"><p className="font-semibold">Identity resolution</p><p className="mt-1">{warnings.length ? 'Review duplicates before saving or keep this instance separate.' : 'Identity confidence is clear in mock mode.'}</p><button type="button" onClick={onKeepSeparate} className="mt-2 rounded-lg border border-cyan-300 px-2 py-1 font-semibold">Keep separate</button></section>;
}
