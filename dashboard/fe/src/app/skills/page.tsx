'use client';

import { useState } from 'react';
import { Skill } from '@/types';
import { apiPut, apiDelete } from '@/lib/api-client';
import { SkillLibrary } from '@/components/skills/SkillLibrary';
import { SkillEditorModal } from '@/components/skills/SkillEditorModal';
import {
  SkillMigrationApplyRequest,
  SkillMigrationPreview,
  useSkillMigration,
  useSkills,
} from '@/hooks/use-skills';

function getErrorMessage(error: unknown) {
  if (error && typeof error === 'object' && 'data' in error) {
    const data = (error as { data?: { detail?: unknown; message?: string } }).data;
    if (typeof data?.detail === 'string') return data.detail;
    if (data?.detail && typeof data.detail === 'object' && 'message' in data.detail) {
      return String((data.detail as { message?: string }).message);
    }
    if (data?.message) return data.message;
  }
  return error instanceof Error ? error.message : 'Request failed';
}

export default function SkillsPage() {
  const { syncWithDisk, createSkill, refresh } = useSkills();
  const { status: migrationStatus, previewMigration, applyMigration, refresh: refreshMigration } = useSkillMigration();
  const [isSyncing, setIsSyncing] = useState(false);
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<Skill | null>(null);
  const [isMigrationOpen, setIsMigrationOpen] = useState(false);
  const [migrationPreview, setMigrationPreview] = useState<SkillMigrationPreview | null>(null);
  const [isPreviewingMigration, setIsPreviewingMigration] = useState(false);
  const [isApplyingMigration, setIsApplyingMigration] = useState(false);
  const [migrationError, setMigrationError] = useState<string | null>(null);
  const [deleteSource, setDeleteSource] = useState(true);
  const [conflictStrategy, setConflictStrategy] = useState<NonNullable<SkillMigrationApplyRequest['conflict_strategy']>>('skip');

  const handleSync = async () => {
    setIsSyncing(true);
    try {
      const res = await syncWithDisk();
      alert(`Synced ${res.synced_count} skills!`);
      refresh();
    } catch {
      alert('Sync failed');
    } finally {
      setIsSyncing(false);
    }
  };

  const handleCreate = async (skill: Partial<Skill>) => {
    await createSkill(skill);
    refresh();
  };

  const handleUpdate = async (name: string, skill: Partial<Skill>) => {
    await apiPut(`/skills/${name}`, skill);
    refresh();
  };

  const handleDelete = async (name: string) => {
    await apiDelete(`/skills/${name}`);
    refresh();
  };

  const handleEdit = (skill: Skill) => {
    setEditingSkill(skill);
    setIsEditorOpen(true);
  };

  const openMigrationPreview = async () => {
    setIsMigrationOpen(true);
    setMigrationError(null);
    setIsPreviewingMigration(true);
    try {
      setMigrationPreview(await previewMigration());
    } catch (error) {
      setMigrationError(getErrorMessage(error));
    } finally {
      setIsPreviewingMigration(false);
    }
  };

  const handleApplyMigration = async () => {
    setMigrationError(null);
    setIsApplyingMigration(true);
    try {
      const result = await applyMigration({
        delete_source: deleteSource,
        conflict_strategy: conflictStrategy,
        dry_run: false,
      });
      try {
        await syncWithDisk();
      } catch {
        // The migration endpoint already attempts sync; keep the UI refresh best-effort.
      }
      await refresh();
      await refreshMigration();
      setMigrationPreview(await previewMigration());
      alert(`Migration complete. Copied ${result.copied.length}, overwritten ${result.overwritten.length}, skipped ${result.skipped.length}, deleted ${result.deleted.length}. Restart running sessions for context list changes to take effect.`);
    } catch (error) {
      setMigrationError(getErrorMessage(error));
    } finally {
      setIsApplyingMigration(false);
    }
  };

  const showMigrationBanner = (migrationStatus?.total_skills || 0) > 0;
  const preview = migrationPreview || migrationStatus;

  return (
    <div className="p-6 max-w-[1600px] mx-auto fade-in-up">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-extrabold" style={{ color: 'var(--color-text-main)' }}>Skill Library</h1>
            <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
              Browse, search, and manage prompt-instruction packs for agent roles
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button 
              onClick={handleSync}
              disabled={isSyncing}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200 disabled:opacity-50"
            >
              <span className={`material-symbols-outlined text-base ${isSyncing ? 'animate-spin' : ''}`}>sync</span>
              {isSyncing ? 'Syncing...' : 'Sync with Disk'}
            </button>
            <button
              onClick={() => { setEditingSkill(null); setIsEditorOpen(true); }}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold text-white" style={{ background: 'var(--color-primary)' }}>
              <span className="material-symbols-outlined text-base">add</span>
              Create Skill
            </button>
          </div>
        </div>

        {showMigrationBanner && (
          <div className="mb-6 rounded-2xl border border-amber-200 bg-amber-50 p-4 shadow-sm">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="flex items-center gap-2 text-sm font-bold text-amber-950">
                  <span className="material-symbols-outlined text-base">cleaning_services</span>
                  Move local skill context into the global Ostwin store
                </div>
                <p className="mt-1 text-xs leading-5 text-amber-900">
                  Found {migrationStatus?.total_skills} project-local or legacy skill folder(s). Migrate them to
                  <span className="mx-1 rounded bg-white/70 px-1.5 py-0.5 font-mono">~/.ostwin/.agents/skills</span>
                  to reduce project-local context flooding. Restart running sessions after migration.
                </p>
              </div>
              <button
                onClick={openMigrationPreview}
                className="shrink-0 rounded-lg bg-amber-900 px-4 py-2 text-xs font-semibold text-white hover:bg-amber-800"
              >
                Preview Migration
              </button>
            </div>
          </div>
        )}

        {/* Skill Library Container */}
        <SkillLibrary onEdit={handleEdit} />

        {isMigrationOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4">
            <div className="max-h-[86vh] w-full max-w-3xl overflow-y-auto rounded-2xl bg-white p-5 shadow-2xl">
              <div className="mb-4 flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-lg font-extrabold text-slate-950">Skill Migration Preview</h2>
                  <p className="mt-1 text-xs text-slate-500">Target: <span className="font-mono">~/.ostwin/.agents/skills</span></p>
                </div>
                <button onClick={() => setIsMigrationOpen(false)} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
                  <span className="material-symbols-outlined text-base">close</span>
                </button>
              </div>

              {migrationError && (
                <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-3 text-xs font-medium text-red-700">
                  {migrationError}
                </div>
              )}

              {isPreviewingMigration && (
                <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-600">Loading migration preview...</div>
              )}

              {preview && !isPreviewingMigration && (
                <div className="space-y-4">
                  <div className="grid gap-3 sm:grid-cols-3">
                    <div className="rounded-xl border border-slate-200 p-3">
                      <div className="text-[11px] uppercase tracking-wide text-slate-500">Skills</div>
                      <div className="mt-1 text-2xl font-black text-slate-950">{preview.total_skills}</div>
                    </div>
                    <div className="rounded-xl border border-slate-200 p-3">
                      <div className="text-[11px] uppercase tracking-wide text-slate-500">Conflicts</div>
                      <div className="mt-1 text-2xl font-black text-slate-950">{preview.conflicts}</div>
                    </div>
                    <div className="rounded-xl border border-slate-200 p-3">
                      <div className="text-[11px] uppercase tracking-wide text-slate-500">Action</div>
                      <div className="mt-2 text-xs font-semibold text-slate-700">{preview.recommended_action}</div>
                    </div>
                  </div>

                  <p className="rounded-xl bg-slate-50 p-3 text-xs leading-5 text-slate-600">{preview.message}</p>

                  <div>
                    <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500">Sources</h3>
                    <div className="space-y-2">
                      {preview.source_summaries.map((source) => (
                        <div key={source.source_path} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 px-3 py-2 text-xs">
                          <span className="truncate font-mono text-slate-600">{source.source_path}</span>
                          <span className={source.exists ? 'font-semibold text-slate-900' : 'text-slate-400'}>
                            {source.exists ? `${source.skill_count} skill(s)` : 'missing'}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div>
                    <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500">Items</h3>
                    <div className="max-h-48 overflow-y-auto rounded-xl border border-slate-200">
                      {preview.items.length === 0 ? (
                        <div className="p-3 text-xs text-slate-500">No migratable skills found.</div>
                      ) : preview.items.map((item) => (
                        <div key={`${item.source_path}-${item.target_path}`} className="flex items-center justify-between gap-3 border-b border-slate-100 px-3 py-2 text-xs last:border-b-0">
                          <div className="min-w-0">
                            <div className="font-semibold text-slate-900">{item.name}</div>
                            <div className="truncate font-mono text-slate-500">{item.relative_path}</div>
                          </div>
                          {item.conflict && <span className="rounded-full bg-amber-100 px-2 py-1 font-semibold text-amber-800">conflict</span>}
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="grid gap-3 rounded-xl border border-slate-200 p-3 sm:grid-cols-2">
                    <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
                      <input type="checkbox" checked={deleteSource} onChange={(event) => setDeleteSource(event.target.checked)} />
                      Delete source folders after verified copy
                    </label>
                    <label className="text-xs font-semibold text-slate-700">
                      Conflict strategy
                      <select
                        value={conflictStrategy}
                        onChange={(event) => setConflictStrategy(event.target.value as NonNullable<SkillMigrationApplyRequest['conflict_strategy']>)}
                        className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs"
                      >
                        <option value="skip">Skip existing targets</option>
                        <option value="overwrite">Overwrite existing targets</option>
                        <option value="fail">Fail if any conflict exists</option>
                      </select>
                    </label>
                  </div>

                  <div className="flex items-center justify-end gap-2 pt-2">
                    <button onClick={openMigrationPreview} disabled={isPreviewingMigration || isApplyingMigration} className="rounded-lg bg-slate-100 px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-200 disabled:opacity-50">
                      Refresh Preview
                    </button>
                    <button onClick={handleApplyMigration} disabled={isApplyingMigration || preview.total_skills === 0} className="rounded-lg px-4 py-2 text-xs font-semibold text-white disabled:opacity-50" style={{ background: 'var(--color-primary)' }}>
                      {isApplyingMigration ? 'Migrating...' : 'Migrate Now'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Editor Modal */}
        <SkillEditorModal
          isOpen={isEditorOpen}
          skill={editingSkill}
          onClose={() => { setIsEditorOpen(false); setEditingSkill(null); }}
          onSave={handleCreate}
          onUpdate={handleUpdate}
          onDelete={handleDelete}
        />
      </div>
  );
}
