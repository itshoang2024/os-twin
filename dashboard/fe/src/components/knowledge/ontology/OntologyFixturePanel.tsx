'use client';

import React from 'react';
import type { DomainPackManifest, OntologyCandidate, OntologyProfile } from '@/hooks/use-ontology';
import { makeBlankOntologyProfile, makeProfileFromPackTemplate, OntologyUnitLauncher, type OntologyUnitDraft } from './OntologyPanel';
import { createObjectType, createRelationshipType } from './ontology-draft-commands';

const fixtureNamespace = 'qa-ontology-fixture';

const fixtureUnitDraft: OntologyUnitDraft = {
  name: 'QA Starting Strategy Ontology',
  purpose: 'Browser-test the EPIC-002 launcher without authenticating to protected APIs.',
  domain: 'quality automation',
  expected_users: ['qa automation', 'engineers'],
  source_material: ['fixture candidate evidence', 'pack manifest'],
  governance_mode: 'assisted',
};

const fixtureSeedProfile: OntologyProfile = {
  ...makeBlankOntologyProfile(fixtureNamespace),
  profile_id: 'qa_ontology_fixture_seed_template',
  version: '1.0.0-template',
  concept_types: {
    service: { id: 'service', label: 'Service', default_layer: 'system', abstraction_level: 'object', color: '#2563eb' },
    incident: { id: 'incident', label: 'Incident', default_layer: 'operations', abstraction_level: 'event', color: '#dc2626' },
  },
  relationship_types: {
    impacts: { id: 'impacts', label: 'Impacts', family: 'dependency', allowed_source_types: ['incident'], allowed_target_types: ['service'] },
  },
  layers: {
    system: { id: 'system', label: 'System', order: 1 },
    operations: { id: 'operations', label: 'Operations', order: 2 },
  },
  abstraction_levels: {
    object: { id: 'object', label: 'Object', order: 1 },
    event: { id: 'event', label: 'Event', order: 2 },
  },
  metadata_fields: {
    owner: { id: 'owner', label: 'Owner', field_type: 'string' },
  },
};

const fixturePack: DomainPackManifest = {
  pack_id: 'qa-starting-strategy-pack',
  name: 'QA Starting Strategy Pack',
  version: '1.0.0',
  concept_types: {
    control: { id: 'control', label: 'Control', default_layer: 'governance', abstraction_level: 'object' },
  },
  relationship_types: {
    validates: { id: 'validates', label: 'Validates', family: 'governance' },
  },
  layers: {
    governance: { id: 'governance', label: 'Governance', order: 1 },
  },
  abstraction_levels: {
    object: { id: 'object', label: 'Object', order: 1 },
  },
  metadata_fields: {
    evidence_ref: { id: 'evidence_ref', label: 'Evidence ref', field_type: 'string' },
  },
  validation_rules: [{ id: 'control_requires_evidence', subject: 'concept_type', concept_type: 'control', rule_type: 'metadata_schema', severity: 'warning' }],
  fixtures: [{ id: 'control-fixture' }],
  migration_notes: ['Fixture-only pack for EPIC-002 browser verification.'],
};

const fixtureCandidates: OntologyCandidate[] = [{
  id: 'cand-fixture-1',
  namespace: fixtureNamespace,
  candidate_type: 'relationship_type',
  source: 'fixture-extractor',
  original_label: 'Blocks',
  normalized_label: 'blocks',
  suggested_canonical: 'impacts',
  confidence: 0.91,
  sample_text: 'Incident A blocks Service B until the control is validated.',
  status: 'pending',
  proposed_payload: { id: 'blocks', label: 'Blocks', family: 'dependency' },
  source_evidence_ref: 'anchor-blocks',
  source_evidence: {
    anchor: { id: 'anchor-blocks', artifact_id: 'artifact-fixture-1', excerpt: 'Incident A blocks Service B until the control is validated.' },
    artifact: { id: 'artifact-fixture-1', source_type: 'document', title: 'QA fixture evidence' },
  },
  created_at: '2026-06-06T00:00:00.000Z',
}];

type FixtureMode = 'launcher' | 'draft' | 'proposal';

function profileCounts(profile: OntologyProfile) {
  return {
    objects: Object.keys(profile.concept_types ?? {}).length,
    relationships: Object.keys(profile.relationship_types ?? {}).length,
    layers: Object.keys(profile.layers ?? {}).length,
    fields: Object.keys(profile.metadata_fields ?? {}).length,
  };
}

export default function OntologyFixturePanel() {
  const [unitDraft, setUnitDraft] = React.useState<OntologyUnitDraft>(fixtureUnitDraft);
  const [mode, setMode] = React.useState<FixtureMode>('launcher');
  const [draft, setDraft] = React.useState<OntologyProfile | null>(null);
  const [eventLog, setEventLog] = React.useState<string[]>(['fixture loaded: no backend API calls']);
  const [objectLabel, setObjectLabel] = React.useState('Feature');
  const [relationshipLabel, setRelationshipLabel] = React.useState('Depends on');
  const [validationFocus, setValidationFocus] = React.useState(false);
  const [mapPreview, setMapPreview] = React.useState(false);

  const openDraft = (profile: OntologyProfile, event: string) => {
    setDraft(profile);
    setMode('draft');
    setEventLog((current) => [...current, event, 'profile write skipped: preview-only local draft']);
  };

  const handleStartBlank = () => openDraft(makeBlankOntologyProfile(fixtureNamespace), 'start blank selected');
  const handlePreviewSeed = () => openDraft(fixtureSeedProfile, 'seed template preview selected');
  const handlePreviewPack = (pack: DomainPackManifest) => openDraft(makeProfileFromPackTemplate(fixtureNamespace, pack), `pack preview selected: ${pack.name}`);
  const handleBuildFromKnowledge = () => openDraft(makeBlankOntologyProfile(fixtureNamespace), 'build from imported knowledge selected with Blocks → anchor-blocks');
  const handleAskAssistant = () => {
    setDraft(makeBlankOntologyProfile(fixtureNamespace));
    setMode('proposal');
    setEventLog((current) => [...current, 'ask ai selected: staged proposal only', 'candidate context: proposed_payload + anchor-blocks', 'profile write skipped: staged proposal not published']);
  };

  const updateDraft = (updater: (profile: OntologyProfile) => OntologyProfile, event: string) => {
    setDraft((current) => {
      const base = current ?? makeBlankOntologyProfile(fixtureNamespace);
      return updater(base);
    });
    setEventLog((current) => [...current, event, 'profile write skipped: local authoring draft']);
  };

  const addObjectType = () => {
    updateDraft((profile) => createObjectType(profile, { label: objectLabel || 'Object Type' }).profile, `object type staged: ${objectLabel || 'Object Type'}`);
  };

  const createRelationship = () => {
    updateDraft((profile) => {
      const ids = Object.keys(profile.concept_types ?? {});
      return createRelationshipType(profile, { label: relationshipLabel || 'Relationship Type', sourceTypes: [ids[0]], targetTypes: [ids[1] ?? ids[0]], family: 'dependency', cardinality: 'many_to_many' }).profile;
    }, `relationship staged: ${relationshipLabel || 'Relationship Type'}`);
  };

  const validateDraft = () => {
    setValidationFocus(true);
    setEventLog((current) => [...current, 'validate called: focused Object Type editor issue', 'diff called: preview-only', 'save blocked: fixture never persists profiles']);
  };

  if (mode === 'launcher') {
    return (
      <main className="h-full overflow-auto bg-[var(--color-background)]" data-testid="ontology-fixture-panel">
        <div className="border-b p-4" style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)' }}>
          <p className="text-xs font-bold uppercase tracking-[0.2em]" style={{ color: 'var(--color-text-muted)' }}>EPIC-002 QA Fixture</p>
          <h1 className="mt-2 text-2xl font-black" style={{ color: 'var(--color-text-main)' }}>Ontology starting strategy fixture</h1>
          <p className="mt-2 text-sm" style={{ color: 'var(--color-text-muted)' }}>Sanctioned `-fixture` route for browser screenshots and network no-hidden-save checks. This page uses deterministic local data and does not call protected APIs.</p>
        </div>
        <OntologyUnitLauncher
          namespace={fixtureNamespace}
          suggestedProfile={fixtureSeedProfile}
          unitDraft={unitDraft}
          onUnitDraftChange={setUnitDraft}
          candidates={fixtureCandidates}
          packs={[fixturePack]}
          onBuildFromKnowledge={handleBuildFromKnowledge}
          onAskAssistant={handleAskAssistant}
          onPreviewSeed={handlePreviewSeed}
          onPreviewPack={handlePreviewPack}
          onStartBlank={handleStartBlank}
        />
      </main>
    );
  }

  const counts = draft ? profileCounts(draft) : { objects: 0, relationships: 0, layers: 0, fields: 0 };
  return (
    <main className="h-full overflow-auto bg-[var(--color-background)] p-6" data-testid="ontology-fixture-panel">
      <section className="mx-auto max-w-6xl rounded-2xl border p-5" style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)' }}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.2em]" style={{ color: 'var(--color-text-muted)' }}>EPIC-002 QA Fixture</p>
            <h1 className="mt-2 text-2xl font-black" style={{ color: 'var(--color-text-main)' }}>{mode === 'proposal' ? 'Staged assistant proposal' : 'Local preview draft'}</h1>
            <p className="mt-2 text-sm" style={{ color: 'var(--color-text-muted)' }}>No active ontology profile was installed or saved. Explicit publish is intentionally unavailable in this fixture.</p>
          </div>
          <button type="button" onClick={() => setMode('launcher')} className="rounded-lg border px-3 py-2 text-xs font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Back to launcher</button>
        </div>

        <div className="mt-5 rounded-xl border bg-[var(--color-background)] p-4" data-testid="ontology-schema-canvas" style={{ borderColor: 'var(--color-border)' }}>
          <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>Preview canvas</h2>
          <p className="mt-2 text-sm" style={{ color: 'var(--color-text-muted)' }}>{counts.objects === 0 ? 'Add your first object type.' : `${counts.objects} object type(s), ${counts.relationships} relationship(s), ${counts.layers} layer(s), ${counts.fields} field(s).`}</p>
          <div className="mt-3 grid gap-3 md:grid-cols-2" data-testid="fixture-authoring-controls">
            <label className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Object label<input aria-label="Fixture object label" value={objectLabel} onChange={(event) => setObjectLabel(event.target.value)} className="mt-1 w-full rounded border px-3 py-2" /></label>
            <button type="button" onClick={addObjectType} className="rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white">Add Object Type</button>
            <label className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Relationship label<input aria-label="Fixture relationship label" value={relationshipLabel} onChange={(event) => setRelationshipLabel(event.target.value)} className="mt-1 w-full rounded border px-3 py-2" /></label>
            <button type="button" onClick={createRelationship} disabled={counts.objects < 2} className="rounded-lg border px-3 py-2 text-xs font-semibold disabled:opacity-50" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Create Relationship</button>
            <button type="button" onClick={validateDraft} className="rounded-lg border px-3 py-2 text-xs font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Validate and preview diff</button>
            <button type="button" onClick={() => setMapPreview(true)} className="rounded-lg border px-3 py-2 text-xs font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Preview map impact</button>
          </div>
          {Object.values(draft?.concept_types ?? {}).length ? (
            <div className="mt-3 flex flex-wrap gap-2" data-testid="fixture-object-chips">
              {Object.values(draft?.concept_types ?? {}).map((concept) => <span key={concept.id} className="rounded-full border px-3 py-1 text-xs" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>{concept.label ?? concept.id}</span>)}
            </div>
          ) : null}
          {Object.values(draft?.relationship_types ?? {}).length ? <div className="mt-3 rounded border p-3 text-xs" data-testid="fixture-relationship-matrix" style={{ borderColor: 'var(--color-border)' }}>{Object.values(draft?.relationship_types ?? {}).map((rel) => <span key={rel.id}>{rel.label ?? rel.id} · {rel.cardinality ?? 'not specified'}</span>)}</div> : null}
          {validationFocus ? <button type="button" data-testid="fixture-validation-focus" className="mt-3 rounded border px-3 py-2 text-xs" style={{ borderColor: 'var(--color-danger)' }}>Validation issue routed to Object Type editor</button> : null}
          {mapPreview ? <div className="mt-3 rounded border border-amber-300 bg-amber-50 p-3 text-xs text-amber-700" data-testid="enterprise-map-example-banner">[Example Data] Examples only — no confirmed company instances are available for this namespace.</div> : null}
        </div>

        {mode === 'proposal' ? (
          <div className="mt-4 rounded-xl border border-primary/40 bg-primary/10 p-4" data-testid="ontology-assistant-proposals">
            <h2 className="text-sm font-semibold text-primary">Assistant proposal staged — not published</h2>
            <p className="mt-2 text-xs" style={{ color: 'var(--color-text-muted)' }}>Proposal context includes candidate `cand-fixture-1`, proposed_payload `blocks`, and evidence ref `anchor-blocks`. Reviewers can validate this card without a profile PUT.</p>
          </div>
        ) : null}

        <div className="mt-4 rounded-xl border p-4" style={{ borderColor: 'var(--color-border)' }} data-testid="ontology-fixture-network-log">
          <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>Fixture network contract</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs" style={{ color: 'var(--color-text-muted)' }}>
            {eventLog.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
      </section>
    </main>
  );
}
