'use client';

import { useState } from 'react';
import { Epic } from '@/types';
import { useEpicRoles } from '@/hooks/use-epics';
import { useSkills } from '@/hooks/use-skills';
import Modal from '@/components/ui/Modal';
import Button from '@/components/ui/Button';

interface RoleOverridesPanelProps {
  epic: Epic;
}

interface EpicRoleConfig {
  name: string;
  description?: string;
  default_model?: string;
  temperature?: number;
  skill_refs?: string[];
  system_prompt_override?: string;
}

interface EditingRoleConfig extends EpicRoleConfig {
  model: string;
  temperature: number;
  skill_refs: string[];
  system_prompt_override: string;
}

export default function RoleOverridesPanel({ epic }: RoleOverridesPanelProps) {
  const { roles, roomOverrides, candidateRoles, markdownRoles, effectiveRoles, updateRoleConfig, updateEpicAssignment, isLoading } = useEpicRoles(epic.plan_id, epic.epic_ref);
  const { skills: allSkills } = useSkills();
  const [editingRole, setEditingRole] = useState<EditingRoleConfig | null>(null);
  const [previewRole, setPreviewRole] = useState<EpicRoleConfig | null>(null);
  const [previewContent, setPreviewContent] = useState<string>('');
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const [isAssignmentModalOpen, setIsAssignmentModalOpen] = useState(false);
  const [roleSearch, setRoleSearch] = useState('');

  const handleEditRole = (role: EpicRoleConfig) => {
    const overrides = roomOverrides[role.name] || {};
    setEditingRole({
      ...role,
      model: overrides.default_model || role.default_model || '',
      temperature: overrides.temperature !== undefined ? overrides.temperature : (role.temperature || 0.7),
      skill_refs: overrides.skill_refs || role.skill_refs || [],
      system_prompt_override: overrides.system_prompt_override ?? role.system_prompt_override ?? ''
    });
  };

  const handleSaveRole = async () => {
    if (!editingRole) return;
    
    await updateRoleConfig(editingRole.name, {
      default_model: editingRole.model,
      temperature: editingRole.temperature,
      skill_refs: editingRole.skill_refs,
      system_prompt_override: editingRole.system_prompt_override || ''
    });
    setEditingRole(null);
  };

  const handlePreviewPrompt = async (role: EpicRoleConfig) => {
    setPreviewRole(role);
    setIsPreviewLoading(true);
    try {
      const resp = await fetch(`/api/plans/${epic.plan_id}/epics/${epic.epic_ref}/roles/${role.name}/preview`);
      const data = await resp.json();
      setPreviewContent(data.prompt || 'Failed to generate preview.');
    } catch {
      setPreviewContent('Error fetching preview.');
    } finally {
      setIsPreviewLoading(false);
    }
  };

  if (isLoading) {
    return <div className="p-8 text-center text-text-faint">Loading role configurations...</div>;
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Panel Header */}
      <div className="p-4 border-b border-border bg-surface-hover/30 shrink-0 flex items-center justify-between">
        <h2 className="text-xs font-bold text-text-muted uppercase tracking-widest flex items-center gap-2">
          <span className="material-symbols-outlined text-sm" aria-hidden="true">settings_input_component</span> Epic Roles
        </h2>
        <button
          onClick={() => setIsAssignmentModalOpen(true)}
          className="flex items-center justify-center w-6 h-6 rounded bg-surface hover:bg-surface-hover border border-border text-text-muted hover:text-primary transition-colors hover:border-primary/50"
          title="Assign Roles"
        >
          <span className="material-symbols-outlined text-[15px]">add</span>
        </button>
      </div>

      {/* Role Overrides Content */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-4">
        {(roles as EpicRoleConfig[]).filter(r => effectiveRoles.includes(r.name)).length === 0 && (
          <div className="text-center p-4 text-xs text-text-faint border border-dashed border-border rounded-lg bg-surface/50">
            No roles assigned to this epic yet.<br/>
            Click the &quot;+&quot; button to assign roles.
          </div>
        )}
        {(roles as EpicRoleConfig[]).filter(r => effectiveRoles.includes(r.name)).map((role) => {
          const isOverridden = !!roomOverrides[role.name];
          const isFromMarkdown = markdownRoles.includes(role.name) && !candidateRoles.includes(role.name);
          return (
            <div 
              key={role.name} 
              className={`p-3 rounded border ${
                isOverridden 
                  ? 'border-primary/30 bg-primary-muted/20' 
                  : 'border-border bg-surface'
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-bold text-text-main">{role.name}</span>
                <div className="flex items-center gap-2">
                   <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold uppercase ${
                    isOverridden 
                      ? 'bg-primary text-white' 
                      : isFromMarkdown
                        ? 'bg-amber-100 text-amber-700'
                        : 'bg-surface-hover text-text-muted'
                  }`}>
                    {isOverridden ? 'Overridden' : isFromMarkdown ? 'From Plan' : 'Inherited'}
                  </span>
                  <button 
                    onClick={() => handleEditRole(role)}
                    className="p-1 hover:bg-surface-hover rounded text-text-faint hover:text-primary transition-colors"
                    title="Edit Overrides"
                  >
                    <span className="material-symbols-outlined text-sm">edit</span>
                  </button>
                   <button 
                    onClick={() => handlePreviewPrompt(role)}
                    className="p-1 hover:bg-surface-hover rounded text-text-faint hover:text-secondary transition-colors"
                    title="Preview System Prompt"
                  >
                    <span className="material-symbols-outlined text-sm">visibility</span>
                  </button>
                </div>
              </div>

              <div className="space-y-2">
                <div className="flex flex-col">
                  <span className="text-[9px] text-text-faint uppercase font-bold tracking-tighter">Model</span>
                  <div className="text-[11px] font-medium text-text-muted">
                    {role.default_model}
                  </div>
                </div>
                <div className="flex flex-col">
                   <span className="text-[9px] text-text-faint uppercase font-bold tracking-tighter">Temperature</span>
                   <div className="text-[11px] font-medium text-text-muted">
                    {role.temperature !== undefined ? role.temperature : 0.7}
                  </div>
                </div>
                <div className="flex flex-col">
                  <span className="text-[9px] text-text-faint uppercase font-bold tracking-tighter">Skills</span>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {(role.skill_refs || []).length > 0 ? (
                      (role.skill_refs || []).map((skill: string) => (
                        <span key={skill} className="px-1.5 py-0.5 bg-surface border border-primary/20 text-primary text-[9px] rounded">
                          {skill}
                        </span>
                      ))
                    ) : (
                      <span className="text-[9px] text-text-faint italic">No extra skills attached</span>
                    )}
                  </div>
                </div>
                {role.system_prompt_override && (
                  <div className="flex flex-col">
                    <span className="text-[9px] text-text-faint uppercase font-bold tracking-tighter">System Prompt Override</span>
                    <div className="text-[10px] text-text-muted line-clamp-2 whitespace-pre-wrap">
                      {role.system_prompt_override}
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Edit Override Modal */}
      {editingRole && (
        <Modal 
          isOpen={!!editingRole} 
          onClose={() => setEditingRole(null)}
          title={`Override Configuration: ${editingRole.name}`}
        >
          <div className="space-y-4 p-4">
            <div>
              <label className="block text-[11px] font-bold text-text-muted uppercase mb-1">Model</label>
              <input 
                type="text" 
                className="w-full bg-surface border border-border rounded px-3 py-2 text-xs focus:ring-1 focus:ring-primary outline-none"
                value={editingRole.model}
                onChange={(e) => setEditingRole({ ...editingRole, model: e.target.value })}
              />
            </div>
            <div>
              <label className="block text-[11px] font-bold text-text-muted uppercase mb-1">Temperature ({editingRole.temperature})</label>
              <input 
                type="range" 
                min="0" 
                max="2" 
                step="0.1"
                className="w-full accent-primary"
                value={editingRole.temperature}
                onChange={(e) => setEditingRole({ ...editingRole, temperature: parseFloat(e.target.value) })}
              />
            </div>
            <div>
              <label className="block text-[11px] font-bold text-text-muted uppercase mb-1">Attached Skills</label>
              <div className="max-h-40 overflow-y-auto border border-border rounded p-2 space-y-1 bg-surface-hover/10">
                {allSkills?.map(skill => {
                  const isChecked = editingRole.skill_refs.includes(skill.name);
                  return (
                    <label key={skill.name} className="flex items-center gap-2 px-2 py-1 hover:bg-surface-hover rounded cursor-pointer group">
                      <input 
                        type="checkbox" 
                        className="accent-primary"
                        checked={isChecked}
                        onChange={(e) => {
                          const refs = e.target.checked 
                            ? [...editingRole.skill_refs, skill.name]
                            : editingRole.skill_refs.filter((r: string) => r !== skill.name);
                          setEditingRole({ ...editingRole, skill_refs: refs });
                        }}
                      />
                      <div className="flex flex-col overflow-hidden">
                        <span className="text-xs font-medium text-text-main group-hover:text-primary transition-colors truncate">{skill.name}</span>
                        <span className="text-[10px] text-text-faint truncate">{skill.description}</span>
                      </div>
                    </label>
                  );
                })}
              </div>
            </div>
            <div>
              <label className="block text-[11px] font-bold text-text-muted uppercase mb-1">System Prompt Override</label>
              <textarea
                className="w-full min-h-32 bg-surface border border-border rounded px-3 py-2 text-xs focus:ring-1 focus:ring-primary outline-none font-mono leading-relaxed"
                placeholder="Additional instructions appended to the end of this role's system prompt for the whole plan..."
                value={editingRole.system_prompt_override || ''}
                onChange={(e) => setEditingRole({ ...editingRole, system_prompt_override: e.target.value })}
              />
              <p className="mt-1 text-[10px] text-text-faint">
                Saved to the plan roles config and appended after the generated role prompt.
              </p>
            </div>
            <div className="flex justify-end gap-2 pt-4">
              <Button variant="ghost" onClick={() => setEditingRole(null)}>Cancel</Button>
              <Button variant="primary" onClick={handleSaveRole}>Save Overrides</Button>
            </div>
          </div>
        </Modal>
      )}

      {/* Preview Modal */}
      {previewRole && (
        <Modal
          isOpen={!!previewRole}
          onClose={() => setPreviewRole(null)}
          title={`System Prompt Preview: ${previewRole.name}`}
          size="lg"
        >
          <div className="p-4">
            {isPreviewLoading ? (
               <div className="h-60 flex items-center justify-center">
                 <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin"></div>
               </div>
            ) : (
              <div className="bg-background-dark/5 rounded border border-border p-4 h-96 overflow-y-auto custom-scrollbar">
                <pre className="text-xs text-text-main whitespace-pre-wrap font-mono leading-relaxed">
                  {previewContent}
                </pre>
              </div>
            )}
            <div className="flex justify-end pt-4">
              <Button variant="primary" onClick={() => setPreviewRole(null)}>Close</Button>
            </div>
          </div>
        </Modal>
      )}
      {/* Assign Roles Modal */}
      {isAssignmentModalOpen && (() => {
        // Sort: markdown-declared roles first, then the rest alphabetically
        const sortedRoles = ([...(roles || [])] as EpicRoleConfig[]).sort((a, b) => {
          const aInMd = markdownRoles.includes(a.name) ? 0 : 1;
          const bInMd = markdownRoles.includes(b.name) ? 0 : 1;
          if (aInMd !== bInMd) return aInMd - bInMd;
          return a.name.localeCompare(b.name);
        });
        const filtered = sortedRoles.filter(r =>
          r.name.toLowerCase().includes(roleSearch.toLowerCase()) ||
          (r.description && r.description.toLowerCase().includes(roleSearch.toLowerCase()))
        );
        // Split into declared (from markdown) and other roles
        const declaredRoles = filtered.filter(r => markdownRoles.includes(r.name));
        const otherRoles = filtered.filter(r => !markdownRoles.includes(r.name));

        return (
        <Modal
          isOpen={isAssignmentModalOpen}
          onClose={() => setIsAssignmentModalOpen(false)}
          title={`Assign Roles: ${epic.epic_ref}`}
        >
          <div className="space-y-4 p-4">
            <div>
              {markdownRoles.length > 0 && (
                <div className="mb-3 px-3 py-2 rounded bg-amber-50 border border-amber-200 text-[11px] text-amber-800 flex items-center gap-2">
                  <span className="material-symbols-outlined text-sm">description</span>
                  Plan declares: <strong>{markdownRoles.join(', ')}</strong>
                </div>
              )}

              <label className="block text-[11px] font-bold text-text-muted uppercase mb-2">
                Candidate Roles ({roles?.length || 0} total)
              </label>
              
              <div className="mb-3 relative">
                <span className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-[16px] text-text-faint">search</span>
                <input
                  type="text"
                  placeholder="Search roles by name or description..."
                  value={roleSearch}
                  onChange={(e) => setRoleSearch(e.target.value)}
                  className="w-full bg-surface border border-border rounded-md pl-8 pr-3 py-1.5 text-xs text-text-main focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/20 placeholder:text-text-faint"
                />
              </div>

              <div className="max-h-60 overflow-y-auto border border-border rounded p-2 space-y-0.5 bg-surface-hover/10 custom-scrollbar">
                {/* Markdown-declared roles section */}
                {declaredRoles.length > 0 && (
                  <>
                    <div className="px-2 pt-1 pb-1.5 text-[9px] font-bold uppercase tracking-wider text-amber-600">
                      Declared in plan
                    </div>
                    {declaredRoles.map(role => {
                      const isChecked = candidateRoles.includes(role.name);
                      return (
                        <label key={role.name} className="flex items-center gap-2 px-2 py-1.5 hover:bg-surface-hover rounded cursor-pointer group bg-amber-50/30">
                          <input 
                            type="checkbox" 
                            className="accent-primary"
                            checked={isChecked}
                            onChange={async (e) => {
                              const newCandidates = e.target.checked 
                                ? [...candidateRoles, role.name]
                                : candidateRoles.filter(r => r !== role.name);
                              await updateEpicAssignment(newCandidates);
                            }}
                          />
                          <div className="flex flex-col overflow-hidden flex-1">
                            <span className="text-xs font-medium text-text-main group-hover:text-primary transition-colors truncate">{role.name}</span>
                            <span className="text-[10px] text-text-faint truncate">{role.description || `Assign the ${role.name} role.`}</span>
                          </div>
                          <span className="text-[8px] px-1 py-0.5 rounded bg-amber-100 text-amber-600 font-bold uppercase shrink-0">plan</span>
                        </label>
                      );
                    })}
                  </>
                )}
                {/* Other available roles */}
                {otherRoles.length > 0 && declaredRoles.length > 0 && (
                  <div className="px-2 pt-3 pb-1.5 text-[9px] font-bold uppercase tracking-wider text-text-faint border-t border-border mt-1">
                    Other available roles
                  </div>
                )}
                {otherRoles.map(role => {
                  const isChecked = candidateRoles.includes(role.name);
                  return (
                    <label key={role.name} className="flex items-center gap-2 px-2 py-1.5 hover:bg-surface-hover rounded cursor-pointer group">
                      <input 
                        type="checkbox" 
                        className="accent-primary"
                        checked={isChecked}
                        onChange={async (e) => {
                          const newCandidates = e.target.checked 
                            ? [...candidateRoles, role.name]
                            : candidateRoles.filter(r => r !== role.name);
                          await updateEpicAssignment(newCandidates);
                        }}
                      />
                      <div className="flex flex-col overflow-hidden">
                        <span className="text-xs font-medium text-text-main group-hover:text-primary transition-colors truncate">{role.name}</span>
                        <span className="text-[10px] text-text-faint truncate">{role.description || `Assign the ${role.name} role.`}</span>
                      </div>
                    </label>
                  );
                })}
              </div>
            </div>
            <div className="flex justify-end pt-2">
              <Button variant="primary" onClick={() => setIsAssignmentModalOpen(false)}>Done</Button>
            </div>
          </div>
        </Modal>
        );
      })()}
    </div>
  );
}
