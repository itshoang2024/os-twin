'use client';

import React, { useState, useEffect } from 'react';
import { useClawhubSearch, useClawhubInstalled, ClawhubSkill } from '@/hooks/use-skills';

type InstallState = {
  phase: 'installing' | 'success' | 'error';
  name: string;
  slug: string;
  msg?: string;
};

interface ClawhubMarketplaceProps {
  onInstalled?: () => void;
}

export const ClawhubMarketplace: React.FC<ClawhubMarketplaceProps> = ({ onInstalled }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [installStates, setInstallStates] = useState<Record<string, InstallState>>({});
  const [selectedSkill, setSelectedSkill] = useState<ClawhubSkill | null>(null);

  const { results, isLoading, isError, installSkill } = useClawhubSearch(debouncedSearch);
  const { installedSlugs, refresh: refreshInstalled } = useClawhubInstalled();

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchTerm), 300);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  const handleInstall = async (skill: ClawhubSkill) => {
    const slug = skill.slug || skill.name;
    setInstallStates((prev) => ({
      ...prev,
      [slug]: { phase: 'installing', name: skill.name, slug },
    }));
    try {
      await installSkill(slug);
      setInstallStates((prev) => ({
        ...prev,
        [slug]: { phase: 'success', name: skill.name, slug, msg: 'Installed' },
      }));
      refreshInstalled();
      onInstalled?.();
    } catch (e: any) {
      setInstallStates((prev) => ({
        ...prev,
        [slug]: { phase: 'error', name: skill.name, slug, msg: e?.message || 'Install failed' },
      }));
    }
  };

  const dismissStatus = (slug: string) => {
    setInstallStates((prev) => {
      const next = { ...prev };
      delete next[slug];
      return next;
    });
  };

  // Collect completed install banners
  const banners = Object.values(installStates).filter((s) => s.phase !== 'installing');

  return (
    <div className="space-y-4">
      {/* Search */}
      <div
        className="flex items-center gap-2 px-3 py-2 rounded-lg max-w-md"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <span className="material-symbols-outlined text-base" style={{ color: 'var(--color-text-faint)' }}>
          travel_explore
        </span>
        <input
          type="text"
          placeholder="Search ClawHub marketplace..."
          className="bg-transparent border-none outline-none text-xs w-full"
          style={{ color: 'var(--color-text-main)' }}
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />
      </div>

      {/* Status banners */}
      {banners.length > 0 && (
        <div className="space-y-2">
          {banners.map((s) => (
            <div
              key={s.slug}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition-all"
              style={{
                background: s.phase === 'success' ? 'var(--color-success-light)' : 'var(--color-danger-light)',
                color: s.phase === 'success' ? 'var(--color-success-text)' : 'var(--color-danger-text)',
                border: `1px solid ${s.phase === 'success' ? 'var(--color-success)' : 'var(--color-danger)'}`,
              }}
            >
              <span className="material-symbols-outlined text-sm">
                {s.phase === 'success' ? 'check_circle' : 'error'}
              </span>
              <span className="font-semibold">{s.name}</span> — {s.msg}
              <button onClick={() => dismissStatus(s.slug)} className="ml-auto hover:opacity-70">
                <span className="material-symbols-outlined text-sm">close</span>
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {!debouncedSearch && (
        <div className="p-12 text-center border border-dashed border-border rounded-xl">
          <span className="material-symbols-outlined text-4xl mb-2" style={{ color: 'var(--color-text-faint)' }}>
            store
          </span>
          <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
            Search the ClawHub marketplace to discover and install community skills
          </p>
        </div>
      )}

      {/* Loading */}
      {debouncedSearch && isLoading && (
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))' }}>
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-36 rounded-xl animate-pulse" style={{ background: 'var(--color-surface-hover)' }} />
          ))}
        </div>
      )}

      {/* Error */}
      {isError && (
        <div className="p-8 text-center text-sm" style={{ color: 'var(--color-danger)' }}>
          Failed to search ClawHub. Make sure the service is reachable.
        </div>
      )}

      {/* Results */}
      {debouncedSearch && !isLoading && results && results.length > 0 && (
        <>
          <div className="text-[11px] font-medium" style={{ color: 'var(--color-text-faint)' }}>
            {results.length} result{results.length !== 1 ? 's' : ''} from ClawHub
          </div>
          <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))' }}>
            {results.map((skill) => {
              const slug = skill.slug || skill.name;
              const state = installStates[slug];
              const alreadyInstalled = installedSlugs.has(slug);
              return (
                <ClawhubSkillCard
                  key={slug}
                  skill={skill}
                  installState={state}
                  alreadyInstalled={alreadyInstalled}
                  onInstall={() => handleInstall(skill)}
                  onClick={() => setSelectedSkill(skill)}
                />
              );
            })}
          </div>
        </>
      )}

      {/* No results */}
      {debouncedSearch && !isLoading && results && results.length === 0 && (
        <div className="p-12 text-center border border-dashed border-border rounded-xl">
          <span className="material-symbols-outlined text-4xl mb-2" style={{ color: 'var(--color-text-faint)' }}>
            search_off
          </span>
          <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
            No skills found on ClawHub for &quot;{debouncedSearch}&quot;
          </p>
        </div>
      )}
      {/* Detail Modal */}
      {selectedSkill && (
        <ClawhubDetailModal
          skill={selectedSkill}
          isInstalled={installedSlugs.has(selectedSkill.slug || selectedSkill.name)}
          installState={installStates[selectedSkill.slug || selectedSkill.name]}
          onClose={() => setSelectedSkill(null)}
          onInstall={() => { handleInstall(selectedSkill); }}
        />
      )}
    </div>
  );
};

/* ─── Detail Modal ────────────────────────────────────────────────────────── */

interface ClawhubDetailModalProps {
  skill: ClawhubSkill;
  isInstalled: boolean;
  installState?: InstallState;
  onClose: () => void;
  onInstall: () => void;
}

const ClawhubDetailModal: React.FC<ClawhubDetailModalProps> = ({ skill, isInstalled, installState, onClose, onInstall }) => {
  const phase = installState?.phase;
  const installed = phase === 'success' || (!phase && isInstalled);
  const isInstalling = phase === 'installing';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'var(--color-backdrop)' }}
      onClick={onClose}
    >
      <div
        className="rounded-2xl shadow-2xl w-full max-w-lg mx-4 max-h-[80vh] overflow-y-auto"
        style={{ background: 'var(--color-surface)' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between p-5 border-b" style={{ borderColor: 'var(--color-border)' }}>
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded text-white"
              style={{ background: 'var(--color-primary)' }}
            >
              clawhub
            </span>
            <span className="text-lg font-bold" style={{ color: 'var(--color-text-main)' }}>
              {skill.name}
            </span>
            {skill.version && (
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded"
                style={{ background: 'var(--color-surface-hover)', color: 'var(--color-text-faint)' }}
              >
                v{skill.version}
              </span>
            )}
            {installed && (
              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded"
                style={{ background: 'var(--color-success-light)', color: 'var(--color-success-text)', border: '1px solid var(--color-success)' }}
              >
                INSTALLED
              </span>
            )}
          </div>
          <button onClick={onClose} className="p-1 rounded-md transition-colors"
            style={{ background: 'transparent' }}
            onMouseEnter={(e) => e.currentTarget.style.background = 'var(--color-surface-hover)'}
            onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
          >
            <span className="material-symbols-outlined text-lg" style={{ color: 'var(--color-text-muted)' }}>close</span>
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-4">
          {/* Slug */}
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase" style={{ color: 'var(--color-text-faint)' }}>Slug</span>
            <code className="text-xs px-2 py-0.5 rounded"
              style={{ background: 'var(--color-surface-hover)', color: 'var(--color-text-main)' }}
            >
              {skill.slug}
            </code>
          </div>

          {/* Description */}
          <div>
            <span className="text-[10px] font-semibold uppercase block mb-1" style={{ color: 'var(--color-text-faint)' }}>Description</span>
            <p className="text-xs leading-relaxed" style={{ color: 'var(--color-text-muted)' }}>
              {skill.description || 'No description available.'}
            </p>
          </div>

          {/* Stats */}
          <div className="flex items-center gap-4 text-[11px]" style={{ color: 'var(--color-text-faint)' }}>
            {skill.author && (
              <span className="flex items-center gap-1">
                <span className="material-symbols-outlined text-xs">person</span>
                {skill.author}
              </span>
            )}
            {(skill.downloads != null && skill.downloads > 0) && (
              <span className="flex items-center gap-1">
                <span className="material-symbols-outlined text-xs">download</span>
                {skill.downloads.toLocaleString()} downloads
              </span>
            )}
            {(skill.installs != null && skill.installs > 0) && (
              <span className="flex items-center gap-1">
                <span className="material-symbols-outlined text-xs">install_desktop</span>
                {skill.installs.toLocaleString()} installs
              </span>
            )}
            {skill.score != null && (
              <span className="flex items-center gap-1">
                <span className="material-symbols-outlined text-xs">star</span>
                {Math.round(skill.score * 10) / 10} relevance
              </span>
            )}
          </div>

          {/* Tags */}
          {skill.tags && skill.tags.length > 0 && (
            <div>
              <span className="text-[10px] font-semibold uppercase block mb-1" style={{ color: 'var(--color-text-faint)' }}>Tags</span>
              <div className="flex flex-wrap gap-1">
                {skill.tags.map((tag) => (
                  <span key={tag}
                    className="text-[10px] px-2 py-0.5 rounded-sm"
                    style={{ background: 'var(--color-primary-muted)', border: '1px solid var(--color-primary-light)', color: 'var(--color-primary)' }}
                  >
                    #{tag}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Install command */}
          <div>
            <span className="text-[10px] font-semibold uppercase block mb-1" style={{ color: 'var(--color-text-faint)' }}>Install command</span>
            <code className="block text-xs px-3 py-2 rounded-md font-mono"
              style={{ background: 'var(--color-terminal-surface)', color: 'var(--color-terminal-out)' }}
            >
              npx clawhub install {skill.slug || skill.name}
            </code>
          </div>

          {/* Installing progress */}
          {isInstalling && (
            <div className="flex items-center gap-2 px-3 py-2 rounded-md"
              style={{ background: 'var(--color-primary-muted)', border: '1px solid var(--color-primary-light)' }}
            >
              <span className="material-symbols-outlined text-sm animate-spin" style={{ color: 'var(--color-primary)' }}>progress_activity</span>
              <span className="text-xs font-medium" style={{ color: 'var(--color-primary)' }}>Installing...</span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between p-5 border-t" style={{ borderColor: 'var(--color-border)' }}>
          <a
            href={`https://clawhub.ai/skills/${skill.slug || skill.name}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs hover:underline flex items-center gap-1"
            style={{ color: 'var(--color-primary)' }}
          >
            <span className="material-symbols-outlined text-sm">open_in_new</span>
            View on ClawHub
          </a>
          {installed ? (
            <span className="flex items-center gap-1 px-4 py-2 rounded-lg text-xs font-semibold"
              style={{ color: 'var(--color-success-text)', background: 'var(--color-success-light)', border: '1px solid var(--color-success)' }}
            >
              <span className="material-symbols-outlined text-sm">check_circle</span>
              Installed
            </span>
          ) : (
            <button
              onClick={onInstall}
              disabled={isInstalling}
              className="flex items-center gap-1 px-4 py-2 rounded-lg text-xs font-semibold text-white transition-colors disabled:opacity-50"
              style={{ background: 'var(--color-primary)' }}
            >
              <span className={`material-symbols-outlined text-sm ${isInstalling ? 'animate-spin' : ''}`}>
                {isInstalling ? 'progress_activity' : 'download'}
              </span>
              {isInstalling ? 'Installing...' : 'Install Skill'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

/* ─── Card for a ClawHub result ──────────────────────────────────────────── */

interface ClawhubSkillCardProps {
  skill: ClawhubSkill;
  installState?: InstallState;
  alreadyInstalled?: boolean;
  onInstall: () => void;
  onClick?: () => void;
}

const ClawhubSkillCard: React.FC<ClawhubSkillCardProps> = ({ skill, installState, alreadyInstalled, onInstall, onClick }) => {
  const phase = installState?.phase;
  const isInstalling = phase === 'installing';
  const isInstalled = phase === 'success' || (!phase && alreadyInstalled);

  return (
    <div
      className="p-4 rounded-xl border transition-all duration-200 fade-in-up flex flex-col cursor-pointer"
      style={{
        borderColor: isInstalled ? 'var(--color-success)' : 'var(--color-border)',
        background: 'var(--color-surface)',
        boxShadow: 'var(--shadow-card)',
        minHeight: '150px',
      }}
      onClick={onClick}
      onMouseEnter={(e) => {
        e.currentTarget.style.boxShadow = 'var(--shadow-card-hover)';
        e.currentTarget.style.transform = 'translateY(-1px)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = 'var(--shadow-card)';
        e.currentTarget.style.transform = 'translateY(0)';
      }}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded text-white"
              style={{ background: 'var(--color-primary)' }}
          >
            clawhub
          </span>
          <span className="text-sm font-bold" style={{ color: 'var(--color-text-main)' }}>
            {skill.name}
          </span>
          {skill.version && (
            <span
              className="text-[9px] font-mono px-1.5 py-0.5 rounded"
              style={{ background: 'var(--color-surface-hover)', color: 'var(--color-text-faint)' }}
            >
              v{skill.version}
            </span>
          )}
        </div>
      </div>

      {/* Description */}
      <p className="text-[11px] leading-relaxed mb-3 line-clamp-2" style={{ color: 'var(--color-text-muted)' }}>
        {skill.description || 'No description available'}
      </p>

      {/* Tags */}
      {skill.tags && skill.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
          {skill.tags.slice(0, 4).map((tag) => (
            <span
              key={tag}
              className="text-[9px] px-1.5 py-0.5 rounded-sm"
              style={{ background: 'var(--color-primary-muted)', border: '1px solid var(--color-primary-light)', color: 'var(--color-primary)' }}
            >
              #{tag}
            </span>
          ))}
          {skill.tags.length > 4 && <span className="text-[9px]" style={{ color: 'var(--color-text-faint)' }}>+{skill.tags.length - 4}</span>}
        </div>
      )}
      {/* Footer */}
      <div
        className="flex items-center justify-between mt-auto pt-3 border-t border-dashed"
        style={{ borderColor: 'var(--color-border)' }}
      >
        <div className="flex items-center gap-2 text-[10px]" style={{ color: 'var(--color-text-faint)' }}>
          {skill.score != null && (
            <span
              className="px-1 rounded text-[10px]"
              style={{ background: 'var(--color-warning-light)', color: 'var(--color-warning-text)', border: '1px solid var(--color-warning)' }}
              title="Relevance"
            >
              {Math.round(skill.score * 10) / 10}
            </span>
          )}
          {skill.author && (
            <span className="flex items-center gap-0.5">
              <span className="material-symbols-outlined text-[10px]">person</span>
              {skill.author}
            </span>
          )}
          {(skill.downloads != null && skill.downloads > 0) && (
            <span className="flex items-center gap-0.5">
              <span className="material-symbols-outlined text-[10px]">download</span>
              {skill.downloads.toLocaleString()}
            </span>
          )}
          {(skill.installs != null && skill.installs > 0) && (
            <span className="flex items-center gap-0.5">
              <span className="material-symbols-outlined text-[10px]">install_desktop</span>
              {skill.installs.toLocaleString()}
            </span>
          )}
        </div>

        {/* Install button — expands full-width with progress shimmer while installing */}
        <div
          className="relative overflow-hidden rounded-md text-[11px] font-semibold text-white flex items-center gap-1.5 cursor-pointer select-none"
          style={{
            // Expand to fill all remaining width when installing; margin-left auto keeps it right-anchored
            flex: isInstalling ? '1 1 0%' : '0 0 auto',
            marginLeft: 'auto',
            maxWidth: '100%',
            transition: 'flex 0.35s cubic-bezier(0.4,0,0.2,1), background 0.2s',
            background: isInstalled
              ? 'var(--color-success-light)'
              : phase === 'error'
              ? 'var(--color-danger)'
              : 'var(--color-primary)',
            border: isInstalled ? '1px solid var(--color-success)' : 'none',
            color: isInstalled ? 'var(--color-success-text)' : 'white',
            padding: '6px 12px',
            pointerEvents: isInstalling ? 'none' : 'auto',
          }}
          onClick={!isInstalled && !isInstalling ? (e) => { e.stopPropagation(); onInstall(); } : undefined}
          onMouseEnter={(e) => {
            if (!isInstalling && !isInstalled) e.currentTarget.style.opacity = '0.88';
          }}
          onMouseLeave={(e) => { e.currentTarget.style.opacity = '1'; }}
        >
          {/* Shimmer progress bar overlay shown while installing */}
          {isInstalling && (
            <span
              aria-hidden
              style={{
                position: 'absolute',
                inset: 0,
                background:
                  'linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.18) 40%, rgba(255,255,255,0.32) 50%, rgba(255,255,255,0.18) 60%, transparent 100%)',
                backgroundSize: '200% 100%',
                animation: 'clawhub-shimmer 1.4s linear infinite',
              }}
            />
          )}
          {/* Icon */}
          <span
            className="material-symbols-outlined"
            style={{ fontSize: '14px', position: 'relative', flexShrink: 0 }}
          >
            {isInstalled ? 'check_circle' : phase === 'error' ? 'refresh' : isInstalling ? 'downloading' : 'download'}
          </span>
          {/* Label */}
          <span style={{ position: 'relative', whiteSpace: 'nowrap' }}>
            {isInstalled ? 'Installed' : phase === 'error' ? 'Retry' : isInstalling ? `Installing ${skill.slug || skill.name}…` : 'Install'}
          </span>
        </div>
      </div>
      {/* Keyframe for shimmer — injected once via a style tag */}
      <style>{`
        @keyframes clawhub-shimmer {
          0%   { background-position: -100% 0; }
          100% { background-position: 200% 0; }
        }
      `}</style>
    </div>
  );
};
