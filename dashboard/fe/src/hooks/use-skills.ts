import useSWR from 'swr';
import { Skill } from '@/types';
import { apiPost, apiPut, apiDelete, apiPatch } from '@/lib/api-client';

export function useSkills(category?: string, role?: string, query?: string, includeDisabled: boolean = false) {
  let url = '/skills';
  if (query) {
    url = '/skills/search';
  }
  const params = new URLSearchParams();
  if (query) params.append('q', query);
  if (category) params.append('category', category);
  if (role) params.append('role', role);
  if (includeDisabled) params.append('include_disabled', 'true');
  if (params.toString()) url += `?${params.toString()}`;

  const { data, error, mutate, isLoading } = useSWR<Skill[]>(url);

  const createSkill = async (skill: Partial<Skill>) => {
    const newSkill = await apiPost<Skill>('/skills', skill);
    mutate();
    return newSkill;
  };

  const syncWithDisk = async () => {
    const result = await apiPost<{synced_count: number}>('/skills/sync', {});
    mutate();
    return result;
  };

  return {
    skills: data,
    isLoading,
    isError: error,
    createSkill,
    syncWithDisk,
    refresh: mutate,
  };
}


export interface SkillMigrationSourceSummary {
  source_path: string;
  exists: boolean;
  skill_count: number;
}

export interface SkillMigrationItem {
  name: string;
  source_path: string;
  target_path: string;
  relative_path: string;
  conflict: boolean;
}

export interface SkillMigrationPreview {
  target_path: string;
  source_summaries: SkillMigrationSourceSummary[];
  total_skills: number;
  conflicts: number;
  items: SkillMigrationItem[];
  recommended_action: string;
  message: string;
}

export type SkillMigrationStatus = SkillMigrationPreview;

export interface SkillMigrationApplyRequest {
  delete_source?: boolean;
  conflict_strategy?: 'skip' | 'overwrite' | 'fail';
  dry_run?: boolean;
}

export interface SkillMigrationApplyResult {
  target_path: string;
  dry_run: boolean;
  copied: SkillMigrationItem[];
  skipped: SkillMigrationItem[];
  overwritten: SkillMigrationItem[];
  deleted: SkillMigrationItem[];
  errors: Array<{ item?: SkillMigrationItem; error: string }>;
  sync_result: unknown;
}

export function useSkillMigration() {
  const { data, error, mutate, isLoading } = useSWR<SkillMigrationStatus>('/skills/migration/status');

  const previewMigration = async () => {
    const result = await apiPost<SkillMigrationPreview>('/skills/migration/preview', {});
    mutate(result, false);
    return result;
  };

  const applyMigration = async (request: SkillMigrationApplyRequest) => {
    const result = await apiPost<SkillMigrationApplyResult>(
      '/skills/migration/apply',
      request,
      { headers: { 'X-Confirm-Migrate': 'true' } },
    );
    await mutate();
    return result;
  };

  return {
    status: data,
    isLoading,
    isError: error,
    refresh: mutate,
    previewMigration,
    applyMigration,
  };
}

export function useSkillValidation() {
  const validateSkill = async (content: string) => {
    return await apiPost<{valid: boolean, errors: string[], warnings: string[], markers: unknown[]}>('/skills/validate', { content });
  };

  return { validateSkill };
}

export interface ClawhubSkill {
  name: string;
  slug: string;
  description: string;
  author?: string;
  tags?: string[];
  category?: string;
  downloads?: number;
  installs?: number;
  version?: string;
  score?: number;
}

export interface ClawhubInstalledSkill {
  slug: string;
  version?: string;
  installedAt?: number;
}

export function useClawhubInstalled() {
  const { data, mutate } = useSWR<ClawhubInstalledSkill[]>('/skills/clawhub-installed');
  const installedSlugs = new Set((data || []).map((s) => s.slug));
  return { installed: data || [], installedSlugs, refresh: mutate };
}

export function useClawhubSearch(query: string) {
  const url = query ? `/skills/clawhub-search?q=${encodeURIComponent(query)}` : null;
  const { data, error, isLoading } = useSWR<ClawhubSkill[]>(url);

  const installSkill = async (skillName: string) => {
    return await apiPost<{ status: string; skill: string; output: string }>(
      '/skills/clawhub-install',
      { skill_name: skillName },
      { headers: { 'X-Confirm-Install': 'true' } },
    );
  };

  return {
    results: data,
    isLoading,
    isError: error,
    installSkill,
  };
}

export function useSkill(id: string) {
  const { data, error, mutate, isLoading } = useSWR<Skill>(id ? `/skills/${id}` : null);

  const updateSkill = async (updates: Partial<Skill>) => {
    const updatedSkill = await apiPut<Skill>(`/skills/${id}`, updates);
    mutate(updatedSkill, false);
    return updatedSkill;
  };

  const deleteSkill = async () => {
    await apiDelete(`/skills/${id}`);
    mutate(undefined, false);
  };

  const toggleSkill = async () => {
    const updatedSkill = await apiPatch<Skill>(`/skills/${id}/toggle`, {});
    mutate(updatedSkill, false);
    return updatedSkill;
  };

  return {
    skill: data,
    isLoading,
    isError: error,
    updateSkill,
    deleteSkill,
    toggleSkill,
    refresh: mutate,
  };
}
