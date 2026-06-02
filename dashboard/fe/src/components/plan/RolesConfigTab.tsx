'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { usePlanContext } from './PlanWorkspace';
import { apiGet, apiPut } from '@/lib/api-client';
import { useSkills } from '@/hooks/use-skills';
import { useConfiguredModels } from '@/hooks/use-configured-models';
import { ProvenanceChip } from '@/components/settings/ProvenanceChip';
import { ModelSelect } from '@/components/settings/ModelSelect';
import { useNotificationStore } from '@/lib/stores/notificationStore';
import { useWebSocket } from '@/hooks/use-websocket';
import RoleSkillManager from './RoleSkillManager';
import type { RoleSettings } from '@/types/settings';

interface RoleConfig {
  name: string;
  default_model: string;
  description: string;
  skill_refs?: string[];
}

interface ModelInfo {
  id: string;
  label?: string;
  context_window: string;
  tier: string;
}

type ModelsRegistry = Record<string, ModelInfo[]>;

// ── Duration Utilities ───────────────────────────────────────────────

/** Convert seconds into a human-readable duration string (e.g. "1h 30m", "45m", "2h") */
function formatDuration(totalSeconds: number): string {
  if (totalSeconds <= 0) return '0s';
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  const parts: string[] = [];
  if (hours > 0) parts.push(`${hours}h`);
  if (minutes > 0) parts.push(`${minutes}m`);
  if (seconds > 0 && hours === 0) parts.push(`${seconds}s`); // only show seconds if under 1 hour
  return parts.join(' ') || '0s';
}

/** Parse a duration string like "1h 30m", "45m 10s", "2h" into total seconds.
 *  Returns null if the string is not a valid duration. */
function parseDuration(input: string): number | null {
  const trimmed = input.trim().toLowerCase();
  if (!trimmed) return null;

  // Pure number → treat as seconds
  if (/^\d+$/.test(trimmed)) return parseInt(trimmed);

  let total = 0;
  let matched = false;
  const hourMatch = trimmed.match(/(\d+)\s*h/);
  const minMatch = trimmed.match(/(\d+)\s*m(?:in)?/);
  const secMatch = trimmed.match(/(\d+)\s*s(?:ec)?/);

  if (hourMatch) { total += parseInt(hourMatch[1]) * 3600; matched = true; }
  if (minMatch) { total += parseInt(minMatch[1]) * 60; matched = true; }
  if (secMatch) { total += parseInt(secMatch[1]); matched = true; }

  return matched ? total : null;
}

const TIMEOUT_PRESETS = [
  { label: '15m', seconds: 900 },
  { label: '30m', seconds: 1800 },
  { label: '1h', seconds: 3600 },
  { label: '2h', seconds: 7200 },
  { label: '6h', seconds: 21600 },
  { label: '12h', seconds: 43200 },
  { label: '24h', seconds: 86400 },
];

// ── TimeoutInput Component ───────────────────────────────────────────

function TimeoutInput({ value, onChange, provenance }: {
  value: number | undefined;
  onChange: (val: number) => void;
  provenance?: string;
}) {
  const [inputMode, setInputMode] = useState<'seconds' | 'duration'>('seconds');
  const [durationText, setDurationText] = useState('');

  const seconds = value ?? 0;
  const durationLabel = seconds > 0 ? formatDuration(seconds) : '';

  const handleSecondsChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = parseInt(e.target.value);
    if (!isNaN(val) && val >= 10) {
      onChange(val);
    }
  };

  const handleDurationSubmit = () => {
    const parsed = parseDuration(durationText);
    if (parsed !== null && parsed >= 10) {
      onChange(parsed);
      setInputMode('seconds');
      setDurationText('');
    }
  };

  return (
    <div>
      <label className="text-[10px] font-bold text-text-faint uppercase tracking-wider block mb-1">
        Timeout
      </label>

      {inputMode === 'seconds' ? (
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <input
              type="number"
              min="10"
              step="10"
              value={value ?? ''}
              onChange={handleSecondsChange}
              placeholder="Seconds"
              className="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-sm text-text-main focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary pr-8"
            />
            <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px] text-text-faint font-medium">s</span>
          </div>

        </div>
      ) : (
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={durationText}
            onChange={(e) => setDurationText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleDurationSubmit();
              if (e.key === 'Escape') { setInputMode('seconds'); setDurationText(''); }
            }}
            onBlur={handleDurationSubmit}
            placeholder="e.g. 1h 30m, 45m, 2h"
            autoFocus
            className="flex-1 rounded-lg border border-primary bg-background px-3 py-1.5 text-sm text-text-main focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
          <button
            onClick={() => { setInputMode('seconds'); setDurationText(''); }}
            className="p-1.5 rounded-md border border-border hover:border-primary/40 hover:bg-primary/5 text-text-faint hover:text-primary transition-all"
            title="Switch to seconds input"
          >
            <span className="material-symbols-outlined text-[16px]">pin</span>
          </button>
        </div>
      )}

      {/* Duration chip (always visible when value > 0) */}
      {seconds > 0 && inputMode === 'seconds' && (
        <div className="mt-1.5 flex items-center gap-1.5">
          <span className="material-symbols-outlined text-[13px] text-text-faint">timer</span>
          <span className="text-[11px] font-semibold text-text-muted">{durationLabel}</span>
          <span className="text-[10px] text-text-faint">({seconds.toLocaleString()}s)</span>
        </div>
      )}

      {/* Quick presets */}
      <div className="mt-2 flex flex-wrap gap-1">
        {TIMEOUT_PRESETS.map((p) => (
          <button
            key={p.label}
            onClick={() => onChange(p.seconds)}
            className={`px-2 py-0.5 rounded-full text-[10px] font-bold border transition-all ${
              seconds === p.seconds
                ? 'bg-primary text-white border-primary shadow-sm'
                : 'bg-surface-hover/50 text-text-faint border-border hover:border-primary/40 hover:text-primary hover:bg-primary/5'
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {provenance && (
        <div className="mt-1">
          <ProvenanceChip source={provenance} />
        </div>
      )}
    </div>
  );
}

const AUTOSAVE_DELAY = 800; // ms debounce

export default function RolesConfigTab() {
  const { planId } = usePlanContext();
  const { skills = [], isLoading: skillsLoading } = useSkills();
  const {
    allModels: configuredModels,
    providers: configuredProviders,
    mutate: mutateConfiguredModels,
  } = useConfiguredModels();
  const { addToast } = useNotificationStore();

  const [roles, setRoles] = useState<RoleConfig[]>([]);
  const [effectiveRoleNames, setEffectiveRoleNames] = useState<string[]>([]);
  const [modelsRegistry, setModelsRegistry] = useState<ModelsRegistry>({});
  const [roleConfig, setRoleConfig] = useState<Record<string, RoleSettings>>({});
  const [effectiveSettings, setEffectiveSettings] = useState<Record<string, { effective: Record<string, unknown>; provenance: Record<string, string> }>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedPrompts, setExpandedPrompts] = useState<Record<string, boolean>>({});
  const [savingRoles, setSavingRoles] = useState<Set<string>>(new Set());

  // Debounce timers per role
  const saveTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  // Track the latest config to avoid stale closures
  const latestConfig = useRef(roleConfig);
  latestConfig.current = roleConfig;

  // ── Fetch roles + registry on mount ────────────────────────────────
  useEffect(() => {
    if (!planId) return;
    setIsLoading(true);
    setError(null);

    Promise.all([
      apiGet<{ role_defaults: RoleConfig[]; effective_roles: string[] }>(`/plans/${planId}/roles`).catch(() => ({ role_defaults: [], effective_roles: [] })),
      apiGet<ModelsRegistry>('/models/registry').catch(() => ({})),
    ])
      .then(([rolesResp, registry]) => {
        const rolesArray = rolesResp?.role_defaults ?? [];
        const effective = rolesResp?.effective_roles ?? [];
        setRoles(Array.isArray(rolesArray) ? rolesArray : []);
        setEffectiveRoleNames(Array.isArray(effective) ? effective : []);
        setModelsRegistry(registry && typeof registry === 'object' ? (registry as ModelsRegistry) : ({} as ModelsRegistry));
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load settings');
      })
      .finally(() => setIsLoading(false));
  }, [planId]);

  const refreshModelCatalog = useCallback(async () => {
    await mutateConfiguredModels();
    const registry = await apiGet<ModelsRegistry>('/models/registry').catch(() => ({}));
    setModelsRegistry(registry && typeof registry === 'object' ? (registry as ModelsRegistry) : ({} as ModelsRegistry));
  }, [mutateConfiguredModels]);

  useEffect(() => {
    const handler = () => {
      void refreshModelCatalog();
    };
    window.addEventListener('ostwin:models-updated', handler);
    return () => window.removeEventListener('ostwin:models-updated', handler);
  }, [refreshModelCatalog]);

  // ── Fetch effective settings for each role ─────────────────────────
  const fetchEffective = useCallback(async () => {
    if (roles.length === 0 || !planId) return;

    const results: Record<string, { effective: Record<string, unknown>; provenance: Record<string, string> }> = {};
    const configData: Record<string, RoleSettings> = {};

    await Promise.all(
      roles.map(async (role) => {
        try {
          const params = new URLSearchParams({ role: role.name, plan_id: planId });
          const data = await apiGet<{ effective: Record<string, unknown>; provenance: Record<string, string> }>(
            `/settings/effective?${params.toString()}`
          );
          results[role.name] = data;
          configData[role.name] = {
            default_model: data.effective.default_model as string | undefined,

            timeout_seconds: data.effective.timeout_seconds as number | undefined,
            max_retries: data.effective.max_retries as number | undefined,
            budget_tokens_max: data.effective.budget_tokens_max as number | undefined,
            system_prompt_override: data.effective.system_prompt_override as string | undefined,
            skill_refs: (data.effective.skill_refs as string[]) || [],
            disabled_skills: (data.effective.disabled_skills as string[]) || [],
          };
        } catch {
          results[role.name] = { effective: {}, provenance: {} };
          configData[role.name] = {};
        }
      })
    );

    setEffectiveSettings(results);
    setRoleConfig(configData);
  }, [roles, planId]);

  useEffect(() => { fetchEffective(); }, [fetchEffective]);

  // ── WebSocket refresh ──────────────────────────────────────────────
  const wsUrl = typeof window !== 'undefined'
    ? `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/api/ws`
    : null;
  const { lastMessage } = useWebSocket(wsUrl);

  useEffect(() => {
    if (lastMessage && (lastMessage.type === 'settings_updated' || lastMessage.event === 'settings_updated')) {
      fetchEffective();
      void refreshModelCatalog();
    }
  }, [lastMessage, fetchEffective, refreshModelCatalog]);

  // ── Autosave: persist a single role's config ───────────────────────
  const saveRole = useCallback(async (roleName: string) => {
    const cfg = latestConfig.current[roleName];
    if (!cfg || !planId) return;

    const payload: Record<string, unknown> = {};
    if (cfg.default_model !== undefined) payload.default_model = cfg.default_model;

    if (cfg.timeout_seconds !== undefined) payload.timeout_seconds = cfg.timeout_seconds;
    if (cfg.max_retries !== undefined) payload.max_retries = cfg.max_retries;
    if (cfg.budget_tokens_max !== undefined) payload.budget_tokens_max = cfg.budget_tokens_max;
    if (cfg.system_prompt_override !== undefined) payload.system_prompt_override = cfg.system_prompt_override;
    if (cfg.skill_refs !== undefined) payload.skill_refs = cfg.skill_refs;
    if (cfg.disabled_skills !== undefined) payload.disabled_skills = cfg.disabled_skills;

    setSavingRoles((prev) => new Set(prev).add(roleName));
    try {
      await apiPut(`/settings/plan/${planId}/role/${roleName}`, payload);
    } catch {
      addToast({ type: 'error', title: 'Save failed', message: `Could not save ${roleName} settings`, autoDismiss: true });
    } finally {
      setSavingRoles((prev) => { const next = new Set(prev); next.delete(roleName); return next; });
    }
  }, [planId, addToast]);

  // ── Debounced save trigger ─────────────────────────────────────────
  const scheduleSave = useCallback((roleName: string) => {
    if (saveTimers.current[roleName]) clearTimeout(saveTimers.current[roleName]);
    saveTimers.current[roleName] = setTimeout(() => { saveRole(roleName); }, AUTOSAVE_DELAY);
  }, [saveRole]);

  // Cleanup timers on unmount
  useEffect(() => {
    const timers = saveTimers.current;
    return () => { Object.values(timers).forEach(clearTimeout); };
  }, []);

  // ── Field update + autosave ────────────────────────────────────────
  const updateRoleField = useCallback((roleName: string, field: keyof RoleSettings, value: unknown) => {
    setRoleConfig((prev) => ({
      ...prev,
      [roleName]: { ...prev[roleName], [field]: value },
    }));
    scheduleSave(roleName);
  }, [scheduleSave]);

  const attachSkill = useCallback((roleName: string, skillName: string) => {
    setRoleConfig((prev) => {
      const existing = prev[roleName] || {};
      const refs = [...(existing.skill_refs || [])];
      if (!refs.includes(skillName)) refs.push(skillName);
      return { ...prev, [roleName]: { ...existing, skill_refs: refs } };
    });
    scheduleSave(roleName);
  }, [scheduleSave]);

  const detachSkill = useCallback((roleName: string, skillName: string) => {
    setRoleConfig((prev) => {
      const existing = prev[roleName] || {};
      const refs = (existing.skill_refs || []).filter((s) => s !== skillName);
      const disabled = (existing.disabled_skills || []).filter((s) => s !== skillName);
      return { ...prev, [roleName]: { ...existing, skill_refs: refs, disabled_skills: disabled } };
    });
    scheduleSave(roleName);
  }, [scheduleSave]);

  const toggleSkillDisabled = useCallback((roleName: string, skillName: string) => {
    setRoleConfig((prev) => {
      const existing = prev[roleName] || {};
      const disabled = existing.disabled_skills || [];
      const updated = disabled.includes(skillName)
        ? disabled.filter((s) => s !== skillName)
        : [...disabled, skillName];
      return { ...prev, [roleName]: { ...existing, disabled_skills: updated } };
    });
    scheduleSave(roleName);
  }, [scheduleSave]);

  // ── Render ─────────────────────────────────────────────────────────
  if (isLoading || skillsLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="material-symbols-outlined text-primary animate-spin">progress_activity</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center p-6">
        <span className="material-symbols-outlined text-danger text-3xl mb-2">error</span>
        <p className="text-sm text-text-muted">{error}</p>
      </div>
    );
  }

  return (
    <div className="p-6 overflow-y-auto h-full custom-scrollbar">
      <div className="mb-6">
        <h2 className="text-sm font-bold text-text-main uppercase tracking-wider">Role Overrides</h2>
        <p className="text-xs text-text-muted mt-1">
          Customize models and parameters for each role. Changes are saved automatically.
        </p>
        {effectiveRoleNames.length > 0 && (
          <div className="mt-2 flex items-center gap-2 text-[10px] text-text-faint">
            <span className="material-symbols-outlined text-sm">description</span>
            Showing {roles.length} role{roles.length !== 1 ? 's' : ''} declared in plan:
            <span className="font-semibold text-text-muted">{effectiveRoleNames.join(', ')}</span>
          </div>
        )}
      </div>

      {roles.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <span className="material-symbols-outlined text-4xl text-text-faint mb-3">group</span>
          <p className="text-sm text-text-muted">No roles declared in the plan epics.</p>
          <p className="text-xs text-text-faint mt-1">Add <code className="bg-surface-hover px-1 rounded">Roles: @engineer, @qa</code> to your epic markdown.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {roles.map((role) => {
            const cfg = roleConfig[role.name] || {};
            const provenance = effectiveSettings[role.name]?.provenance || {};
            const attached = cfg.skill_refs || [];
            const isPromptExpanded = expandedPrompts[role.name] || false;
            const isSaving = savingRoles.has(role.name);

            return (
              <div key={role.name} className="bg-surface border border-border rounded-xl p-4">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-sm font-semibold text-text-main">{role.name}</div>
                    <p className="text-xs text-text-muted mt-1 line-clamp-2">{role.description}</p>
                  </div>
                  {isSaving && (
                    <span className="material-symbols-outlined text-primary text-sm animate-spin">progress_activity</span>
                  )}
                </div>

                <div className="mt-4 space-y-4">
                  <div>
                    <label className="text-[10px] font-bold text-text-faint uppercase tracking-wider block mb-1">
                      Model
                    </label>
                    <ModelSelect
                      value={cfg.default_model || ''}
                      onChange={(model) => updateRoleField(role.name, 'default_model', model)}
                      models={configuredModels.length > 0 ? configuredModels : Object.values(modelsRegistry).flat().map((m) => ({ id: m.id, label: m.label || m.id, context_window: m.context_window, tier: m.tier }))}
                      providers={configuredProviders}
                      grouped={false}
                      placeholder="Select a model"
                    />
                    {provenance.default_model && (
                      <div className="mt-1">
                        <ProvenanceChip source={provenance.default_model} />
                      </div>
                    )}
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <TimeoutInput
                      value={cfg.timeout_seconds}
                      onChange={(val) => updateRoleField(role.name, 'timeout_seconds', val)}
                      provenance={provenance.timeout_seconds}
                    />
                    <div>
                      <label className="text-[10px] font-bold text-text-faint uppercase tracking-wider block mb-1">
                        Max Retries
                      </label>
                      <input
                        type="number"
                        min="1"
                        step="1"
                        value={cfg.max_retries ?? ''}
                        onChange={(e) => {
                          const val = parseInt(e.target.value);
                          if (!isNaN(val) && val >= 1) {
                            updateRoleField(role.name, 'max_retries', val);
                          }
                        }}
                        placeholder="Min: 1"
                        className="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-sm text-text-main focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
                      />
                      {provenance.max_retries && (
                        <div className="mt-1">
                          <ProvenanceChip source={provenance.max_retries} />
                        </div>
                      )}
                    </div>
                  </div>

                  <div>
                    <button
                      onClick={() => setExpandedPrompts((prev) => ({ ...prev, [role.name]: !prev[role.name] }))}
                      className="flex items-center gap-1 text-[10px] font-bold text-text-faint uppercase tracking-wider hover:text-text-muted transition-colors"
                    >
                      <span className="material-symbols-outlined text-sm">
                        {isPromptExpanded ? 'expand_less' : 'expand_more'}
                      </span>
                      System Prompt Override
                    </button>
                    {isPromptExpanded && (
                      <div className="mt-2">
                        <textarea
                          maxLength={4000}
                          rows={4}
                          value={cfg.system_prompt_override ?? ''}
                          onChange={(e) => updateRoleField(role.name, 'system_prompt_override', e.target.value)}
                          placeholder="Override the default system prompt for this role..."
                          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-text-main focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary resize-none font-mono"
                        />
                        <div className="flex items-center justify-between mt-1">
                          {provenance.system_prompt_override && (
                            <ProvenanceChip source={provenance.system_prompt_override} />
                          )}
                          <span className="text-[10px] text-text-faint ml-auto">
                            {(cfg.system_prompt_override?.length || 0)}/4000
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                <div className="mt-4 pt-4 border-t border-border">
                  <RoleSkillManager
                    roleName={role.name}
                    overrides={{
                      skill_refs: attached,
                      disabled_skills: cfg.disabled_skills || [],
                    }}
                    allSkills={skills}
                    onToggleDisabled={(name) => toggleSkillDisabled(role.name, name)}
                    onRemove={(name) => detachSkill(role.name, name)}
                    onAdd={(name) => attachSkill(role.name, name)}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
