'use client';

import { useState, useEffect, useMemo } from 'react';
import useSWR, { useSWRConfig } from 'swr';
import { Role } from '@/types';
import { apiPost, apiPut } from '@/lib/api-client';
import { ModelSelect } from '@/components/settings/ModelSelect';
import type { ModelInfo } from '@/types/settings';

import SkillChipInput from './SkillChipInput';
import McpSelector from './McpSelector';
import TestConnectionButton from './TestConnectionButton';
import { useModelRegistry, useRole, useRoleDependencies } from '@/hooks/use-roles';


interface RoleEditorPanelProps {
  role?: Role;
  isOpen: boolean;
  onClose: () => void;
  existingRoles: Role[];
}

const GOOGLE_PREFIXES = ['google-vertex', 'google-vertex-anthropic'] as const;

const PROVIDER_ID_TO_ROLE: Record<string, Role['provider']> = {
  google: 'gemini',
  anthropic: 'claude',
  openai: 'gpt',
};

export default function RoleEditorPanel({ role, isOpen, onClose, existingRoles }: RoleEditorPanelProps) {
  const { mutate } = useSWRConfig();
  const { registry, allModels, providers: registryProviders } = useModelRegistry();
  const { data: apiKeysStatus, isLoading: isLoadingKeys } = useSWR<Record<string, boolean>>('/providers/api-keys');
  const { role: detailedRole } = useRole(isOpen && role?.id ? role.id : '');
  const { dependencies } = useRoleDependencies(role?.id || '');
  const [activeTab] = useState<'config' | 'dependencies'>('config');
  const [formData, setFormData] = useState<Partial<Role>>({
    name: '',
    provider: undefined,
    version: '',
    temperature: 0.3,
    budget_tokens_max: 500000,
    max_retries: 3,
    timeout_seconds: 900,
    skill_refs: [],
    mcp_refs: [],
    description: '',
    instructions: '',
    instance_type: 'worker',
    system_prompt_override: '',
  });

  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSaving, setIsSaving] = useState(false);

  const [googleCustomPrefix, setGoogleCustomPrefix] = useState<string>(GOOGLE_PREFIXES[0]);

  // Whether the current version is a known catalog model
  const isKnownModel = useMemo(
    () => !!formData.version && allModels.some(m => m.id === formData.version),
    [allModels, formData.version],
  );

  // Parse Google custom model name from version
  const googleCustomModelName = useMemo(() => {
    if (formData.provider !== 'gemini' || !formData.version || isKnownModel) return '';
    const v = formData.version;
    // Check longer prefix first (google-vertex-anthropic before google-vertex)
    for (const pfx of [...GOOGLE_PREFIXES].sort((a, b) => b.length - a.length)) {
      if (v.startsWith(pfx + '/')) return v.slice(pfx.length + 1);
    }
    return v;
  }, [formData.version, formData.provider, isKnownModel]);

  // Sync prefix selector when loading existing role with prefixed version
  useEffect(() => {
    if (!formData.version) return;
    for (const pfx of [...GOOGLE_PREFIXES].sort((a, b) => b.length - a.length)) {
      if (formData.version.startsWith(pfx + '/')) {
        setGoogleCustomPrefix(pfx);
        return;
      }
    }
  }, [formData.version]);

  // Normalize backend registry keys (Claude -> claude)
  // Alias "google" <-> "gemini" so lookups work regardless of
  // whether the dynamic catalog ("Google") or static fallback ("Gemini")
  // is active.
  const normalizedRegistry = useMemo(() => {
    if (!registry) return null;
    const normalized: Record<string, ModelInfo[]> = {};
    Object.entries(registry).forEach(([provider, models]) => {
      normalized[provider.toLowerCase()] = models;
    });
    if (normalized['google'] && !normalized['gemini']) {
      normalized['gemini'] = normalized['google'];
    } else if (normalized['gemini'] && !normalized['google']) {
      normalized['google'] = normalized['gemini'];
    }
    return normalized;
  }, [registry]);

  const defaultProvider = useMemo((): Role['provider'] => {
    const priority: { keys: string[]; provider: Role['provider'] }[] = [
      { keys: ['Claude', 'Anthropic'], provider: 'claude' },
      { keys: ['Google', 'Gemini'], provider: 'gemini' },
      { keys: ['GPT', 'OpenAI'], provider: 'gpt' },
    ];
    if (apiKeysStatus) {
      const configured = priority.find(p => p.keys.some(k => apiKeysStatus[k]));
      if (configured) return configured.provider;
    }
    return 'claude';
  }, [apiKeysStatus]);

  useEffect(() => {
    const selectedRole = detailedRole || role;
    if (selectedRole) {
      setFormData({
        ...selectedRole,
        provider: (selectedRole.provider?.toLowerCase() as Role['provider']) || defaultProvider,
        temperature: selectedRole.temperature ?? 0.3,
        budget_tokens_max: selectedRole.budget_tokens_max ?? 500000,
        max_retries: selectedRole.max_retries ?? 3,
        timeout_seconds: selectedRole.timeout_seconds ?? 900,
        skill_refs: selectedRole.skill_refs ?? [],
        mcp_refs: selectedRole.mcp_refs ?? [],
        description: selectedRole.description ?? '',
        instructions: selectedRole.instructions ?? '',
        instance_type: selectedRole.instance_type || 'worker',
        system_prompt_override: selectedRole.system_prompt_override ?? '',
      });
    } else if (!isLoadingKeys) {
      setFormData({
        name: '',
        provider: defaultProvider,
        version: normalizedRegistry?.[defaultProvider]?.[0]?.id || '',
        temperature: 0.3,
        budget_tokens_max: 500000,
        max_retries: 3,
        timeout_seconds: 900,
        skill_refs: [],
        mcp_refs: [],
        description: '',
        instructions: '',
        instance_type: 'worker',
        system_prompt_override: '',
      });
    }
    setErrors({});
  }, [detailedRole, role, isOpen, normalizedRegistry, defaultProvider, isLoadingKeys]);

  const validate = () => {
    const newErrors: Record<string, string> = {};
    if (!formData.name) newErrors.name = 'Name is required';
    if (existingRoles.some(r => r.name.toLowerCase() === formData.name?.toLowerCase() && r.id !== role?.id)) {
      newErrors.name = 'Role name already exists';
    }
    if (formData.temperature === undefined || formData.temperature < 0 || formData.temperature > 2) {
      newErrors.temperature = 'Temperature must be between 0 and 2';
    }
    if (!formData.version) newErrors.version = 'Model version is required';
    
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSave = async () => {
    if (!validate()) return;

    setIsSaving(true);
    try {
      if (role) {
        await apiPut(`/roles/${role.id}`, formData);
      } else {
        await apiPost('/roles', formData);
      }
      await mutate('/roles', undefined, { revalidate: true });
      if (role) await mutate(`/roles/${role.id}`, undefined, { revalidate: true });
      onClose();
    } catch (error) {
      console.error('Failed to save role:', error);
    } finally {
      setIsSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center animate-in fade-in duration-300">
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm"
        onClick={onClose}
      />
      
      {/* Panel */}
      <div 
        className="relative w-full max-w-3xl max-h-[85vh] shadow-2xl flex flex-col animate-in slide-in-from-bottom duration-500 overflow-hidden rounded-t-2xl"
        style={{ background: 'var(--color-surface)' }}
      >
        {/* Drag handle */}
        <div className="flex justify-center pt-3 pb-1">
          <div className="w-10 h-1 rounded-full bg-slate-300" />
        </div>

        {/* Header */}
        <div className="px-6 pb-4 pt-2 border-b flex items-center justify-between sticky top-0 z-10" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
          <div>
            <h2 className="text-xl font-extrabold" style={{ color: 'var(--color-text-main)' }}>{role ? 'Edit Role' : 'New Role'}</h2>
            <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>Configure agent identity and model provider</p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-slate-100 rounded-lg transition-colors">
            <span className="material-symbols-outlined text-base" style={{ color: 'var(--color-text-muted)' }}>close</span>
          </button>
        </div>


        {/* Tabs — Where Used tab hidden for now, coming in a future release */}

        {/* Form Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-8 custom-scrollbar pb-24">
          {activeTab === 'config' ? (
            <>
          {/* Section: Identity */}
          <div className="space-y-4">
            <div className="flex items-center gap-2 mb-4">
              <span className="w-6 h-6 rounded bg-primary/10 text-primary flex items-center justify-center font-bold text-[10px]">01</span>
              <h3 className="text-[11px] font-bold uppercase tracking-widest text-text-faint">Identity & Context</h3>
            </div>
            
            <div className="space-y-1.5">
              <label className="text-[11px] font-bold text-text-muted px-1 uppercase tracking-wider">Role Name</label>
              <input 
                type="text"
                placeholder="e.g. Frontend Engineer"
                className={`w-full p-3 rounded-xl border text-sm font-semibold transition-all focus:ring-4 focus:ring-primary/10 ${errors.name ? 'border-red-500 bg-red-50' : 'bg-white'}`}
                value={formData.name}
                onChange={e => setFormData({ ...formData, name: e.target.value })}
              />
              {errors.name && <p className="text-[10px] font-bold text-red-500 px-1">{errors.name}</p>}
            </div>

            <div className="space-y-1.5">
              <label className="text-[11px] font-bold text-text-muted px-1 uppercase tracking-wider">Description</label>
              <textarea
                rows={2}
                placeholder="Brief description of what this role does..."
                className="w-full p-3 rounded-xl border bg-white text-xs resize-none focus:ring-4 focus:ring-primary/10 transition-all"
                value={formData.description || ''}
                onChange={e => setFormData({ ...formData, description: e.target.value })}
              />
            </div>

            <div className="space-y-1.5 pt-2">
              <label className="text-[11px] font-bold text-text-muted px-1 uppercase tracking-wider">Role Type / Function</label>
              <div className="grid grid-cols-2 gap-3">
                <button
                  type="button"
                  onClick={() => setFormData({ ...formData, instance_type: 'worker' })}
                  className={`flex flex-col items-center gap-2 p-4 rounded-xl border-2 transition-all ${
                    formData.instance_type === 'worker' 
                      ? 'border-primary bg-primary/5 text-primary scale-[1.02] shadow-sm' 
                      : 'border-slate-100 bg-slate-50 text-slate-400 hover:border-slate-200'
                  }`}
                >
                  <span className="material-symbols-outlined text-3xl">engineering</span>
                  <div className="flex flex-col items-center">
                    <span className="text-[11px] font-black uppercase tracking-widest leading-none">Worker</span>
                    <span className="text-[9px] font-bold opacity-60 mt-1 uppercase">Task Execution</span>
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => setFormData({ ...formData, instance_type: 'evaluator' })}
                  className={`flex flex-col items-center gap-2 p-4 rounded-xl border-2 transition-all ${
                    formData.instance_type === 'evaluator' 
                      ? 'border-indigo-500 bg-indigo-50 text-indigo-600 scale-[1.02] shadow-sm' 
                      : 'border-slate-100 bg-slate-50 text-slate-400 hover:border-slate-200'
                  }`}
                >
                  <span className="material-symbols-outlined text-3xl">fact_check</span>
                  <div className="flex flex-col items-center">
                    <span className="text-[11px] font-black uppercase tracking-widest leading-none">Evaluator</span>
                    <span className="text-[9px] font-bold opacity-60 mt-1 uppercase">Quality Audit</span>
                  </div>
                </button>
              </div>
            </div>
          </div>

          {/* Section: Model Provider */}
          <div className="space-y-4">
            <div className="flex items-center gap-2 mb-4">
              <span className="w-6 h-6 rounded bg-primary/10 text-primary flex items-center justify-center font-bold text-[10px]">02</span>
              <h3 className="text-[11px] font-bold uppercase tracking-widest text-text-faint">Model Provider</h3>
            </div>
            
            <div className="space-y-1.5">
              <label className="text-[11px] font-bold text-text-muted px-1 uppercase tracking-wider">Model</label>
              <ModelSelect
                value={formData.version || ''}
                onChange={(modelId) => {
                  // Auto-detect provider from selected model, mapping
                  // dynamic provider_ids (e.g. "google") to Role values
                  // (e.g. "gemini").
                  const model = allModels.find(m => m.id === modelId);
                  const rawPid = model?.provider_id || '';
                  const detectedProvider = PROVIDER_ID_TO_ROLE[rawPid] ?? rawPid as Role['provider'];
                  setFormData({
                    ...formData,
                    version: modelId,
                    ...(detectedProvider ? { provider: detectedProvider } : {}),
                  });
                }}
                models={allModels}
                providers={registryProviders}
                placeholder="Search models or providers..."
              />
              {errors.version && <p className="text-[10px] font-bold text-red-500 px-1">{errors.version}</p>}
            </div>

            <div className="space-y-1.5 mt-3">
              <label className="text-[11px] font-bold text-text-muted px-1 uppercase tracking-wider">Or Custom Model ID</label>
              {formData.provider === 'gemini' ? (
                /* Google: inline prefix selector + model name input */
                <div className="flex items-stretch gap-0">
                  <select
                    className="px-2.5 py-3 rounded-l-xl border border-r-0 bg-slate-50 text-[11px] font-mono font-semibold text-slate-600 focus:outline-none focus:ring-2 focus:ring-primary/10"
                    value={googleCustomPrefix}
                    onChange={e => {
                      const pfx = e.target.value;
                      setGoogleCustomPrefix(pfx);
                      if (googleCustomModelName) {
                        setFormData({ ...formData, version: `${pfx}/${googleCustomModelName}` });
                      }
                    }}
                  >
                    {GOOGLE_PREFIXES.map(pfx => (
                      <option key={pfx} value={pfx}>{pfx}/</option>
                    ))}
                  </select>
                  <input
                    type="text"
                    placeholder="e.g. gemini-3-flash-preview"
                    className="flex-1 p-3 rounded-r-xl border border-l-0 bg-white text-sm font-mono font-semibold shadow-sm focus:ring-4 focus:ring-primary/10 transition-all min-w-0"
                    value={googleCustomModelName}
                    onChange={e => {
                      const name = e.target.value;
                      if (name) {
                        setFormData({ ...formData, version: `${googleCustomPrefix}/${name}` });
                      } else {
                        setFormData({ ...formData, version: '' });
                      }
                    }}
                  />
                </div>
              ) : (
                /* Non-Google: plain text input */
                <input
                  type="text"
                  placeholder="e.g. my-custom-model or provider/model-name"
                  className="w-full p-3 rounded-xl border bg-white text-sm font-mono font-semibold shadow-sm focus:ring-4 focus:ring-primary/10 transition-all"
                  value={!isKnownModel ? formData.version || '' : ''}
                  onChange={e => {
                    if (e.target.value) {
                      setFormData({ ...formData, version: e.target.value });
                    }
                  }}
                />
              )}
            </div>
            
            <TestConnectionButton version={formData.version || ''} />
          </div>

          {/* Section: Parameters */}
          <div className="space-y-6">
            <div className="flex items-center gap-2 mb-4">
              <span className="w-6 h-6 rounded bg-primary/10 text-primary flex items-center justify-center font-bold text-[10px]">03</span>
              <h3 className="text-[11px] font-bold uppercase tracking-widest text-text-faint">Sampling Parameters</h3>
            </div>

            <div className="space-y-4">
              <div className="flex items-center justify-between px-1">
                <label className="text-[11px] font-bold text-text-muted uppercase tracking-wider">Temperature</label>
                <span className="text-xs font-mono font-bold text-primary">{formData.temperature}</span>
              </div>
              <input 
                type="range"
                min="0"
                max="2"
                step="0.1"
                className="w-full h-1.5 bg-slate-100 rounded-lg appearance-none cursor-pointer accent-primary"
                value={formData.temperature}
                onChange={e => setFormData({ ...formData, temperature: parseFloat(e.target.value) })}
              />
              <div className="flex justify-between text-[10px] font-bold text-text-faint px-1">
                <span>Deterministic</span>
                <span>Balanced</span>
                <span>Creative</span>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              {/* Budget Tokens — hidden for now, coming in a future release */}
              <div className="space-y-1.5">
                <label className="text-[11px] font-bold text-text-muted px-1 uppercase tracking-wider">Retries</label>
                <input 
                  type="number"
                  min="1"
                  max="10"
                  className="w-full p-3 rounded-xl border bg-white text-sm font-mono font-semibold"
                  value={formData.max_retries}
                  onChange={e => setFormData({ ...formData, max_retries: parseInt(e.target.value) || 0 })}
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-[11px] font-bold text-text-muted px-1 uppercase tracking-wider">Timeout (s)</label>
                <input 
                  type="number"
                  className="w-full p-3 rounded-xl border bg-white text-sm font-mono font-semibold"
                  value={formData.timeout_seconds}
                  onChange={e => setFormData({ ...formData, timeout_seconds: parseInt(e.target.value) || 0 })}
                />
              </div>
            </div>
          </div>

          {/* Section: Skills */}
          <div className="space-y-4">
            <div className="flex items-center gap-2 mb-4">
              <span className="w-6 h-6 rounded bg-primary/10 text-primary flex items-center justify-center font-bold text-[10px]">04</span>
              <h3 className="text-[11px] font-bold uppercase tracking-widest text-text-faint">Skill Matrix</h3>
            </div>
            
            <SkillChipInput 
              selectedSkillRefs={formData.skill_refs || []}
              onChange={refs => setFormData({ ...formData, skill_refs: refs })}
            />
          </div>

          {/* Section: MCP Binding */}
          <div className="space-y-4">
            <div className="flex items-center gap-2 mb-4">
              <span className="w-6 h-6 rounded bg-primary/10 text-primary flex items-center justify-center font-bold text-[10px]">05</span>
              <h3 className="text-[11px] font-bold uppercase tracking-widest text-text-faint">MCP Binding</h3>
            </div>
            
            <McpSelector 
              selectedMcpRefs={formData.mcp_refs || []}
              onChange={refs => setFormData({ ...formData, mcp_refs: refs })}
            />
          </div>

          {/* Section: Instructions */}
          <div className="space-y-4">
            <div className="flex items-center gap-2 mb-4">
              <span className="w-6 h-6 rounded bg-primary/10 text-primary flex items-center justify-center font-bold text-[10px]">06</span>
              <h3 className="text-[11px] font-bold uppercase tracking-widest text-text-faint">Role Instructions</h3>
            </div>

            <div className="space-y-1.5">
              <label className="text-[11px] font-bold text-text-muted px-1 uppercase tracking-wider">Instructions (ROLE.md)</label>
              <textarea
                rows={10}
                placeholder="Define responsibilities, guidelines, and output format for this role..."
                className="w-full p-3 rounded-xl border bg-white text-xs font-mono resize-none focus:ring-4 focus:ring-primary/10 transition-all"
                value={formData.instructions || ''}
                onChange={e => setFormData({ ...formData, instructions: e.target.value })}
              />
            </div>

            {/* System Prompt Override — hidden for now, coming in a future release */}
          </div>
          </>
          ) : (
            <div className="space-y-6">
              <div className="p-4 rounded-xl border bg-slate-50/50 space-y-4">
                <h4 className="text-[11px] font-bold uppercase tracking-widest text-text-faint">Active War-Rooms</h4>
                {(dependencies?.active_warrooms?.length ?? 0) === 0 ? (
                  <p className="text-xs text-text-faint italic">No active war-rooms using this role.</p>
                ) : (
                  <div className="space-y-2">
                    {dependencies?.active_warrooms.map(room => (
                      <div key={room.id} className="flex items-center justify-between p-2 rounded-lg bg-white border shadow-sm">
                        <span className="text-xs font-bold">{room.id}</span>
                        <span className="px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-600 text-[10px] font-bold uppercase">{room.status}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="p-4 rounded-xl border bg-slate-50/50 space-y-4">
                <h4 className="text-[11px] font-bold uppercase tracking-widest text-text-faint">Associated Plans</h4>
                {(dependencies?.plans?.length ?? 0) === 0 ? (
                  <p className="text-xs text-text-faint italic">No plans explicitly referencing this role.</p>
                ) : (
                  <div className="grid grid-cols-1 gap-2">
                    {dependencies?.plans.map(plan => (
                      <div key={plan} className="flex items-center gap-2 p-2 rounded-lg bg-white border shadow-sm">
                        <span className="material-symbols-outlined text-base text-primary">description</span>
                        <span className="text-xs font-bold">{plan}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {(dependencies?.inactive_warrooms?.length ?? 0) > 0 && (
                <div className="p-4 rounded-xl border bg-slate-50/50 space-y-4">
                  <h4 className="text-[11px] font-bold uppercase tracking-widest text-text-faint">Historical Usage</h4>
                  <p className="text-[10px] text-text-muted">Used in {dependencies?.inactive_warrooms?.length} completed war-rooms.</p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="p-6 border-t sticky bottom-0 z-10 flex gap-3 shadow-[0_-10px_20px_-10px_rgba(0,0,0,0.1)]" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
          <button 
            type="button"
            onClick={onClose}
            className="flex-1 py-3 rounded-xl border text-sm font-bold hover:bg-slate-50 transition-all"
            style={{ color: 'var(--color-text-main)', borderColor: 'var(--color-border)' }}
          >
            Cancel
          </button>
          <button 
            type="button"
            onClick={handleSave}
            disabled={isSaving}
            className="flex-[2] py-3 rounded-xl text-white text-sm font-extrabold flex items-center justify-center gap-2 shadow-lg shadow-primary/20 hover:brightness-105 active:scale-95 transition-all"
            style={{ background: 'var(--color-primary)' }}
          >
            {isSaving && <span className="material-symbols-outlined text-base animate-spin">refresh</span>}
            {role ? 'Update Role' : 'Create Role'}
          </button>
        </div>
      </div>
    </div>
  );
}
