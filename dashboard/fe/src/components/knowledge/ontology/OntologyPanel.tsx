'use client';

import React from 'react';
import { useNotificationStore } from '@/lib/stores/notificationStore';
import { useOntologyCandidates, useOntologyHistory, useOntologyPacks, useOntologyProfile, useOntologySummary, useOntologyValidation } from '@/hooks/use-ontology';
import type { OntologyCandidate, OntologyProfile, OntologyValidationIssue } from '@/hooks/use-ontology';
import AliasManager from './AliasManager';
import CandidateReview from './CandidateReview';
import ConceptTypeStudio from './ConceptTypeStudio';
import GraphInstructionStudio from './GraphInstructionStudio';
import ProfileSummary from './ProfileSummary';
import RelationshipStudio from './RelationshipStudio';
import { cloneProfile, IssueList, validationErrorCount } from './ontology-ui';

export default function OntologyPanel({ selectedNamespace }: { selectedNamespace: string | null }) {
  const addToast = useNotificationStore((state) => state.addToast);
  const { data, profile, profileExists, defaultSuggested, isLoading, error, saveProfile, resetDefault, refresh } = useOntologyProfile(selectedNamespace);
  const { validateProfile } = useOntologyValidation(selectedNamespace);
  const { summary, refresh: refreshSummary } = useOntologySummary(selectedNamespace);
  const { diffProfile } = useOntologyHistory(selectedNamespace);
  const { packs, installed, installPack, uninstallPack } = useOntologyPacks(selectedNamespace);
  const { candidates, isLoading: candidatesLoading, approveCandidate, mapCandidate, rejectCandidate, bulkUpdateCandidates } = useOntologyCandidates(selectedNamespace, 'pending');
  const [draft, setDraft] = React.useState<OntologyProfile | null>(null);
  const [issues, setIssues] = React.useState<OntologyValidationIssue[]>([]);
  const [isSaving, setIsSaving] = React.useState(false);
  const [isBootstrapping, setIsBootstrapping] = React.useState(false);
  const [diffPreview, setDiffPreview] = React.useState<Record<string, unknown> | null>(null);
  const [migrationIssues, setMigrationIssues] = React.useState<Array<Record<string, unknown>>>([]);
  const [saveReason, setSaveReason] = React.useState('Governed ontology profile update');
  const [overrideTicket, setOverrideTicket] = React.useState('');
  const [overrideApprovedBy, setOverrideApprovedBy] = React.useState('');

  React.useEffect(() => { setDraft(profile ? cloneProfile(profile) : null); setIssues(data?.validation_issues ?? []); }, [profile, data?.validation_issues]);

  const isDirty = React.useMemo(() => Boolean(draft && profile && JSON.stringify(draft) !== JSON.stringify(profile)), [draft, profile]);
  const runValidation = async (candidate: OntologyProfile) => {
    const result = await validateProfile(candidate);
    setIssues(result.issues ?? []);
    return result;
  };
  const handlePreviewDiff = async (candidate: OntologyProfile = draft as OntologyProfile) => {
    if (!candidate) return null;
    const preview = await diffProfile(candidate, profile ?? undefined);
    setDiffPreview(preview.diff ?? null);
    setMigrationIssues(preview.migration_issues ?? []);
    return preview;
  };
  const handleBootstrap = async () => {
    setIsBootstrapping(true);
    try {
      await resetDefault();
      await Promise.all([refresh(), refreshSummary()]);
      addToast({ type: 'success', title: 'Ontology profile created', message: 'Default ontology profile is now active.', autoDismiss: true });
    } catch (err) {
      addToast({ type: 'error', title: 'Bootstrap failed', message: err instanceof Error ? err.message : 'Unable to create ontology profile.', autoDismiss: false });
    } finally { setIsBootstrapping(false); }
  };
  const handleSave = async () => {
    if (!draft) return;
    setIsSaving(true);
    try {
      const validation = await runValidation(draft);
      if (!validation.valid || validationErrorCount(validation.issues) > 0) {
        addToast({ type: 'error', title: 'Validation blocked save', message: 'Fix ontology validation errors before saving.', autoDismiss: false });
        return;
      }
      const preview = await handlePreviewDiff(draft);
      const dangerous = (preview?.migration_issues ?? []).filter((issue) => String(issue.severity) === 'error');
      if (dangerous.length > 0 && (!overrideTicket.trim() || !overrideApprovedBy.trim())) {
        addToast({ type: 'error', title: 'Migration override required', message: 'Dangerous profile changes require preview plus override ticket and approver metadata.', autoDismiss: false });
        return;
      }
      await saveProfile(draft, {
        reason: saveReason || 'Governed ontology profile update',
        validation_override: dangerous.length > 0 ? { ticket: overrideTicket, approved_by: overrideApprovedBy, reason: saveReason, previewed: true } : null,
      });
      await Promise.all([refresh(), refreshSummary()]);
      addToast({ type: 'success', title: 'Ontology profile saved', message: 'Profile changes were validated and persisted.', autoDismiss: true });
    } catch (err) {
      addToast({ type: 'error', title: 'Save failed', message: err instanceof Error ? err.message : 'Unable to save ontology profile.', autoDismiss: false });
    } finally { setIsSaving(false); }
  };
  const handleReset = async () => {
    if (!window.confirm('Reset this namespace ontology profile to the default seed profile? Existing custom enum and metadata edits may be replaced.')) return;
    await handleBootstrap();
  };
  const handlePackInstall = async (packId: string) => {
    try {
      await installPack(packId);
      await Promise.all([refresh(), refreshSummary()]);
      addToast({ type: 'success', title: 'Domain pack installed', message: `${packId} is now active for ${selectedNamespace}.`, autoDismiss: true });
    } catch (err) {
      addToast({ type: 'error', title: 'Pack install failed', message: err instanceof Error ? err.message : `Unable to install ${packId}.`, autoDismiss: false });
    }
  };
  const handlePackUninstall = async (packId: string) => {
    try {
      await uninstallPack(packId);
      await Promise.all([refresh(), refreshSummary()]);
      addToast({ type: 'success', title: 'Domain pack disabled', message: `${packId} was disabled for ${selectedNamespace}.`, autoDismiss: true });
    } catch (err) {
      addToast({ type: 'error', title: 'Pack uninstall failed', message: err instanceof Error ? err.message : `Unable to uninstall ${packId}.`, autoDismiss: false });
    }
  };
  const handleCandidateAction = async (kind: 'approve' | 'map' | 'reject', candidate: OntologyCandidate, canonicalId?: string) => {
    if (kind === 'approve') await approveCandidate(candidate.id, { canonical_id: candidate.suggested_canonical ?? candidate.normalized_label, payload: candidate.metadata ?? {} });
    if (kind === 'map' && canonicalId) await mapCandidate(candidate.id, canonicalId);
    if (kind === 'reject') await rejectCandidate(candidate.id, 'Rejected from Ontology UI');
    await Promise.all([refresh(), refreshSummary()]);
  };

  if (!selectedNamespace) return <div className="p-6 text-sm" style={{ color: 'var(--color-text-muted)' }}>Select a namespace to manage its ontology profile.</div>;
  if (isLoading) return <div className="flex h-full items-center justify-center text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading ontology profile…</div>;
  if (error) return <div className="p-6 text-sm text-danger">Failed to load ontology profile: {error}</div>;
  if (!draft) return <div className="p-6 text-sm" style={{ color: 'var(--color-text-muted)' }}>No ontology profile data is available.</div>;

  return (
    <div className="h-full overflow-auto" style={{ background: 'var(--color-background)' }}>
      <div className="mx-auto max-w-7xl space-y-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border p-4" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
          <div>
            <div className="flex items-center gap-2"><span className="material-symbols-outlined text-[22px]" style={{ color: 'var(--color-primary)' }}>schema</span><h2 className="text-base font-semibold" style={{ color: 'var(--color-text-main)' }}>Ontology Operations</h2>{isDirty && <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[11px] font-semibold text-amber-600">Unsaved changes</span>}</div>
            <p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>Manage relationship enums, concept types, aliases, domain packs, and extracted candidates for <strong>{selectedNamespace}</strong>.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {!profileExists && <button onClick={handleBootstrap} disabled={isBootstrapping} className="rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">{isBootstrapping ? 'Creating…' : 'Create default ontology profile'}</button>}
            <button onClick={() => runValidation(draft)} className="rounded-lg border px-3 py-2 text-xs font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Validate</button>
            <button onClick={() => handlePreviewDiff()} disabled={!isDirty} className="rounded-lg border px-3 py-2 text-xs font-semibold disabled:opacity-50" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}>Preview diff</button>
            <button onClick={handleSave} disabled={!isDirty || isSaving} className="rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">{isSaving ? 'Saving…' : 'Validate & save'}</button>
            <button onClick={handleReset} className="rounded-lg border px-3 py-2 text-xs font-semibold text-danger" style={{ borderColor: 'var(--color-border)' }}>Reset to default</button>
          </div>
        </div>

        {defaultSuggested && <div className="rounded-xl border border-amber-300 bg-amber-500/10 p-3 text-sm text-amber-700">This namespace has no active ontology profile yet. Review the suggested defaults, then create the profile or save your edits.</div>}
        <IssueList issues={issues} />
        <ProfileSummary profile={draft} summary={summary} profileExists={profileExists} defaultSuggested={defaultSuggested} />
        <div className="rounded-2xl border p-4" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
          <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>Domain packs</h3>
          <p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>Install governed packs to extend concept types, relationship semantics, Graph Instruction defaults, fixtures, and audit metadata.</p>
          <div className="mt-3 grid gap-2 md:grid-cols-2">{packs.map((pack) => {
            const isInstalled = Boolean(installed?.installed_packs?.[pack.pack_id]);
            return <div key={pack.pack_id} className="rounded-xl border p-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}><div className="flex items-start justify-between gap-2"><div><div className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>{pack.name}</div><div className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>{pack.pack_id} · v{pack.version}</div></div>{isInstalled ? <button onClick={() => handlePackUninstall(pack.pack_id)} className="rounded-lg border px-2.5 py-1.5 text-xs font-semibold text-danger" style={{ borderColor: 'var(--color-border)' }}>Disable</button> : <button onClick={() => handlePackInstall(pack.pack_id)} className="rounded-lg bg-primary px-2.5 py-1.5 text-xs font-semibold text-white">Install</button>}</div><p className="mt-2 text-xs" style={{ color: 'var(--color-text-muted)' }}>{(pack.migration_notes ?? [])[0] ?? 'Adds domain-specific ontology definitions.'}</p>{isInstalled && <span className="mt-2 inline-flex rounded-full bg-primary/10 px-2 py-0.5 text-[11px] text-primary">Installed</span>}</div>;
          })}</div>
        </div>
        {diffPreview && <div className="rounded-2xl border p-4" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}><h3 className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>Profile diff and migration safety preview</h3><p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>Preview is side-effect-free. Error-severity migration issues require override metadata before save.</p><pre className="mt-3 max-h-56 overflow-auto rounded-xl border p-3 text-xs" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)', color: 'var(--color-text-main)' }}>{JSON.stringify({ diff: diffPreview, migration_issues: migrationIssues }, null, 2)}</pre><div className="mt-3 grid gap-3 md:grid-cols-3"><label className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Reason<input value={saveReason} onChange={(event) => setSaveReason(event.target.value)} className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} /></label><label className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Override ticket<input value={overrideTicket} onChange={(event) => setOverrideTicket(event.target.value)} placeholder="Required for dangerous changes" className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} /></label><label className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Approved by<input value={overrideApprovedBy} onChange={(event) => setOverrideApprovedBy(event.target.value)} placeholder="Required for dangerous changes" className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" style={{ background: 'var(--color-background)', borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} /></label></div></div>}
        <GraphInstructionStudio profile={draft} onChange={setDraft} onValidate={async (candidate) => { await runValidation(candidate); }} />
        <RelationshipStudio profile={draft} onChange={setDraft} />
        <ConceptTypeStudio profile={draft} onChange={setDraft} />
        <AliasManager profile={draft} onChange={setDraft} />
        <CandidateReview profile={draft} candidates={candidates} isLoading={candidatesLoading} onApprove={(candidate) => handleCandidateAction('approve', candidate)} onMap={(candidate, canonicalId) => handleCandidateAction('map', candidate, canonicalId)} onReject={(candidate) => handleCandidateAction('reject', candidate)} onBulkReject={async (items) => { await bulkUpdateCandidates(items.map((candidate) => ({ candidate_id: candidate.id, action: 'reject', reason: 'Bulk rejected from Ontology UI' }))); await Promise.all([refresh(), refreshSummary()]); }} />
      </div>
    </div>
  );
}
