'use client';

import { useState, useMemo } from 'react';
import { Role, Skill } from '@/types';
import { useSWRConfig } from 'swr';
import { useModelRegistry } from '@/hooks/use-roles';
import { apiDelete } from '@/lib/api-client';
import { McpServer } from '@/hooks/use-mcp';
import TestConnectionButton from './TestConnectionButton';

interface RolesTableProps {
  roles: Role[];
  skills: Skill[];
  mcpServers: McpServer[];
  onEdit: (role: Role) => void;
  onAdd: () => void;
  isLoading?: boolean;
  totalRoles?: number;
}

type SortKey = 'name' | 'provider';
type SortDir = 'asc' | 'desc';

const providerBranding: Record<string, { color: string; label: string; icon: string }> = {
  claude: { color: '#D97706', label: 'Anthropic', icon: '🟡' },
  gpt: { color: '#10B981', label: 'OpenAI', icon: '🟢' },
  gemini: { color: '#6366F1', label: 'Google', icon: '🟣' },
  custom: { color: '#64748b', label: 'Custom', icon: '⚪' },
};

const RoleSVGs: Record<string, React.ReactNode> = {
  architect: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>
      <polyline points="3.29 7 12 12 20.71 7"></polyline>
      <line x1="12" y1="22" x2="12" y2="12"></line>
    </svg>
  ),
  engineer: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <polyline points="16 18 22 12 16 6"></polyline>
      <polyline points="8 6 2 12 8 18"></polyline>
    </svg>
  ),
  manager: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
      <circle cx="9" cy="7" r="4"></circle>
      <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
      <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
    </svg>
  ),
  qa: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
      <polyline points="22 4 12 14.01 9 11.01"></polyline>
    </svg>
  ),
  audit: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
      <polyline points="14 2 14 8 20 8"></polyline>
      <line x1="16" y1="13" x2="8" y2="13"></line>
      <line x1="16" y1="17" x2="8" y2="17"></line>
      <polyline points="10 9 9 9 8 9"></polyline>
    </svg>
  ),
  reporter: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"></path>
      <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"></path>
    </svg>
  ),
  default: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <circle cx="12" cy="12" r="4"></circle>
      <path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8"></path>
    </svg>
  )
};

export default function RolesTable({ roles, skills, mcpServers: _mcpServers, onEdit, onAdd, isLoading, totalRoles = 0 }: RolesTableProps) {
  const { mutate } = useSWRConfig();
  const { registry } = useModelRegistry();
  const [sortConfig, setSortConfig] = useState<{ key: SortKey; dir: SortDir }>({ key: 'name', dir: 'asc' });

  const modelMetadata = useMemo(() => {
    if (!registry) return {};
    const meta: Record<string, { tier: string; context_window: string }> = {};
    Object.values(registry).flat().forEach(m => {
      meta[m.id] = { tier: m.tier ?? '', context_window: m.context_window ?? '' };
    });
    return meta;
  }, [registry]);

  const sortedRoles = useMemo(() => {
    return [...roles].sort((a, b) => {
      const valA = a[sortConfig.key] || '';
      const valB = b[sortConfig.key] || '';
      if (valA < valB) return sortConfig.dir === 'asc' ? -1 : 1;
      if (valA > valB) return sortConfig.dir === 'asc' ? 1 : -1;
      return 0;
    });
  }, [roles, sortConfig]);

  const toggleSort = (key: SortKey) => {
    setSortConfig(prev => ({
      key,
      dir: prev.key === key && prev.dir === 'asc' ? 'desc' : 'asc'
    }));
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Are you sure you want to delete this role?')) return;
    try {
      await apiDelete(`/roles/${id}`);
      await mutate('/roles');
    } catch (error) {
      console.error('Failed to delete role:', error);
    }
  };

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center p-20 animate-pulse">
        <div className="w-12 h-12 rounded-full bg-surface-hover mb-4 flex items-center justify-center">
          <span className="material-symbols-outlined text-text-faint animate-spin" aria-hidden="true">refresh</span>
        </div>
        <p className="text-sm font-bold text-text-faint uppercase tracking-widest">Loading roles...</p>
      </div>
    );
  }

  if (roles.length === 0) {
    const isSearching = totalRoles > 0;

    return (
      <div className="flex flex-col items-center justify-center p-20 text-center border-2 border-dashed rounded-2xl bg-surface-hover/30 border-border">
        <div className="w-16 h-16 rounded-2xl bg-surface shadow-sm mb-6 flex items-center justify-center">
          <span className="material-symbols-outlined text-3xl text-text-faint" aria-hidden="true">
            {isSearching ? 'search_off' : 'smart_toy'}
          </span>
        </div>
        <h3 className="text-xl font-extrabold text-text-main mb-2">
          {isSearching ? 'No Matching Roles' : 'No Roles Configured'}
        </h3>
        <p className="text-sm text-text-muted max-w-[320px] mb-8">
          {isSearching 
            ? "We couldn't find any roles matching your current search criteria. Try a different query or clear the search."
            : "Roles define how agents interact with LLMs and what skills they can utilize during plan execution."}
        </p>
        {!isSearching && (
          <button 
            onClick={onAdd}
            className="flex items-center gap-2 px-6 py-3 rounded-xl text-white font-extrabold shadow-lg shadow-primary/20 hover:brightness-105 transition-all"
            style={{ background: 'var(--color-primary)' }}
            aria-label="Create First Role"
          >
            <span className="material-symbols-outlined text-xl" aria-hidden="true">add</span>
            Create First Role
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="rounded-2xl border overflow-hidden shadow-sm" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="sticky top-0 z-10 shadow-[0_1px_0_0_rgba(0,0,0,0.05)]" style={{ background: 'var(--color-surface)' }}>
              <th 
                className="px-6 py-4 text-[11px] font-bold uppercase tracking-widest cursor-pointer hover:bg-slate-50 transition-colors group" 
                onClick={() => toggleSort('name')}
                style={{ color: 'var(--color-text-faint)' }}
              >
                <div className="flex items-center gap-1">
                  Role Identity
                  <span className={`material-symbols-outlined text-sm transition-opacity ${sortConfig.key === 'name' ? 'opacity-100' : 'opacity-0 group-hover:opacity-40'}`}>
                    {sortConfig.dir === 'asc' ? 'expand_less' : 'expand_more'}
                  </span>
                </div>
              </th>
              <th 
                className="px-6 py-4 text-[11px] font-bold uppercase tracking-widest cursor-pointer hover:bg-slate-50 transition-colors group" 
                onClick={() => toggleSort('provider')}
                style={{ color: 'var(--color-text-faint)' }}
              >
                <div className="flex items-center gap-1">
                  Model Provider
                  <span className={`material-symbols-outlined text-sm transition-opacity ${sortConfig.key === 'provider' ? 'opacity-100' : 'opacity-0 group-hover:opacity-40'}`}>
                    {sortConfig.dir === 'asc' ? 'expand_less' : 'expand_more'}
                  </span>
                </div>
              </th>
              <th className="px-6 py-4 text-[11px] font-bold uppercase tracking-widest" style={{ color: 'var(--color-text-faint)' }}>Skills</th>
              <th className="px-6 py-4 text-[11px] font-bold uppercase tracking-widest" style={{ color: 'var(--color-text-faint)' }}>MCPs</th>
              <th className="px-6 py-4 text-[11px] font-bold uppercase tracking-widest text-right" style={{ color: 'var(--color-text-faint)' }}>Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y" style={{ borderColor: 'var(--color-border-light)' }}>
            {sortedRoles.map((role) => {
              const pb = providerBranding[role.provider] || providerBranding.custom;
              const roleSkills = skills.filter((s) => role.skill_refs.includes(s.name));
              const roleMcpRefs = role.mcp_refs || [];
              
              return (
                <tr
                  key={role.id}
                  className="hover:bg-slate-50/80 transition-all duration-200 group"
                >
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div 
                        className="w-12 h-12 rounded-2xl flex items-center justify-center text-white shadow-md ring-4 ring-white transition-transform group-hover:scale-110 group-hover:rotate-3" 
                        style={{ background: `linear-gradient(135deg, ${pb.color}, ${pb.color}dd)` }}
                      >
                        {RoleSVGs[role.name.toLowerCase()] || RoleSVGs.default}
                      </div>
                      <div>
                        <div className="flex items-center gap-1.5">
                          <div className="text-sm font-extrabold capitalize text-slate-800">{role.name}</div>
                          <div 
                            className={`flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[9px] font-black uppercase tracking-tighter shadow-sm border ${
                              role.instance_type === 'evaluator' 
                                ? 'bg-indigo-50 text-indigo-600 border-indigo-100' 
                                : 'bg-amber-50 text-amber-600 border-amber-100'
                            }`}
                          >
                            <span className="material-symbols-outlined text-[10px]">{role.instance_type === 'evaluator' ? 'fact_check' : 'engineering'}</span>
                            {role.instance_type}
                          </div>
                        </div>
                        <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{role.id}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <span className="text-lg">{pb.icon}</span>
                      <div>
                        <div className="flex items-center gap-1.5">
                          <div className="text-xs font-bold text-slate-700">{role.version}</div>
                          {modelMetadata[role.version] && (
                            <span className={`px-1.5 py-0.5 rounded-full text-[9px] font-black uppercase tracking-tighter ${
                              modelMetadata[role.version].tier === 'flagship' ? 'bg-indigo-100 text-indigo-600' : 
                              modelMetadata[role.version].tier === 'fast' ? 'bg-amber-100 text-amber-600' : 
                              'bg-slate-100 text-slate-500'
                            }`}>
                              {modelMetadata[role.version].tier}
                            </span>
                          )}
                        </div>
                        <div className="text-[10px] font-medium text-slate-400 uppercase tracking-widest">{pb.label}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex flex-wrap gap-1.5 max-w-[200px]">
                      {roleSkills.slice(0, 2).map((s) => (
                        <span
                          key={s.name}
                          className="px-2 py-0.5 rounded-full text-[10px] font-bold border"
                          style={{ background: 'var(--color-primary-muted)', color: 'var(--color-primary)', borderColor: 'rgba(var(--color-primary-rgb), 0.1)' }}
                        >
                          {s.name}
                        </span>
                      ))}
                      {roleSkills.length > 2 && (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-100 text-slate-500 border border-slate-200">
                          +{roleSkills.length - 2}
                        </span>
                      )}
                      {roleSkills.length === 0 && (
                        <span className="text-[11px] text-slate-300 italic">No skills</span>
                      )}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex flex-wrap gap-1.5 max-w-[200px]">
                      {roleMcpRefs.slice(0, 2).map((ref) => (
                        <span
                          key={ref}
                          className="px-2 py-0.5 rounded-full text-[10px] font-bold border bg-slate-50 text-slate-600 border-slate-200"
                        >
                          {ref}
                        </span>
                      ))}
                      {roleMcpRefs.length > 2 && (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-100 text-slate-500 border border-slate-200">
                          +{roleMcpRefs.length - 2}
                        </span>
                      )}
                      {roleMcpRefs.length === 0 && (
                        <span className="text-[11px] text-slate-300 italic">No MCPs</span>
                      )}
                    </div>
                  </td>

                  <td className="px-6 py-4">
                    <div className="flex items-center justify-end gap-1">
                      <TestConnectionButton version={role.version} />
                      <button 
                        onClick={() => onEdit(role)}
                        className="p-2 hover:bg-primary/10 hover:text-primary rounded-lg transition-all"
                        title="Edit Role"
                      >
                        <span className="material-symbols-outlined text-lg">edit</span>
                      </button>
                      <button 
                        onClick={() => handleDelete(role.id)}
                        className="p-2 hover:bg-red-50 hover:text-red-500 rounded-lg transition-all"
                        title="Delete Role"
                      >
                        <span className="material-symbols-outlined text-lg">delete</span>
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
