'use client';

import { useState } from 'react';
import type { SettingsNamespace } from '@/types/settings';

export interface SettingsSidebarProps {
  activeNamespace: SettingsNamespace;
  onNamespaceChange: (namespace: SettingsNamespace) => void;
}

const NAMESPACE_ITEMS: { id: SettingsNamespace; icon: string; label: string }[] = [
  { id: 'providers',     icon: 'memory',               label: 'Provider Config' },
  { id: 'runtime',       icon: 'settings',             label: 'Runtime' },
  { id: 'memory',        icon: 'storage',              label: 'Memory' },
  { id: 'knowledge',     icon: 'school',               label: 'Knowledge' },
  { id: 'channels',      icon: 'hub',                  label: 'Channels' },
  { id: 'ai-monitor',    icon: 'monitoring',           label: 'AI Monitor' },
];

export function SettingsSidebar({
  activeNamespace,
  onNamespaceChange,
}: SettingsSidebarProps) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const activeLabel = NAMESPACE_ITEMS.find((item) => item.id === activeNamespace)?.label;

  return (
    <>
      <div className="lg:hidden">
        <button
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          className="flex w-full items-center justify-between rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3 text-sm font-bold text-[var(--color-text-main)] shadow-[0_12px_36px_rgba(15,23,42,0.07)]"
        >
          <span>{activeLabel}</span>
          <span className="material-symbols-outlined text-sm">
            {mobileMenuOpen ? 'expand_less' : 'expand_more'}
          </span>
        </button>

        {mobileMenuOpen && (
          <div className="mt-3 flex flex-wrap gap-2">
            {NAMESPACE_ITEMS.map((item) => {
              const isActive = activeNamespace === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => { onNamespaceChange(item.id); setMobileMenuOpen(false); }}
                  className={`flex items-center gap-2 rounded-full border px-3 py-2 text-sm font-bold transition hover:-translate-y-0.5 ${
                    isActive
                      ? 'border-[var(--color-text-main)] bg-[var(--color-text-main)] text-[var(--color-surface)]'
                      : 'border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-muted)]'
                  }`}
                >
                  <span className="material-symbols-outlined text-[18px]">{item.icon}</span>
                  {item.label}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <aside className="hidden w-72 shrink-0 lg:block">
        <div className="sticky top-8 space-y-4">
          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 shadow-[0_12px_36px_rgba(15,23,42,0.07)]">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--color-primary-muted)]">
                <span className="material-symbols-outlined text-[20px] text-[var(--color-primary)]">memory</span>
              </div>
              <div>
                <p className="text-xs font-black uppercase text-[var(--color-text-main)]">Core engine</p>
                <p className="text-[11px] font-bold text-[var(--color-text-muted)]">Runtime command center</p>
              </div>
            </div>
          </div>

          <nav className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-2 shadow-[0_12px_36px_rgba(15,23,42,0.07)]" aria-label="Settings sections">
            {NAMESPACE_ITEMS.map((item) => {
              const isActive = activeNamespace === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => onNamespaceChange(item.id)}
                  className={`mb-1 flex w-full items-center justify-between rounded-full border px-3 py-2.5 text-left transition last:mb-0 hover:-translate-y-0.5 ${
                    isActive
                      ? 'border-[var(--color-text-main)] bg-[var(--color-text-main)] text-[var(--color-surface)]'
                      : 'border-transparent text-[var(--color-text-muted)] hover:border-[var(--color-border)] hover:bg-[var(--color-background)]'
                  }`}
                >
                  <span className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-[18px]">{item.icon}</span>
                    <span className="text-xs font-bold uppercase">{item.label}</span>
                  </span>
                  {isActive && <span className="material-symbols-outlined text-[16px]">arrow_forward</span>}
                </button>
              );
            })}
          </nav>

          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm leading-6 text-[var(--color-text-muted)] shadow-[0_12px_36px_rgba(15,23,42,0.07)]">
            <p className="text-xs font-bold uppercase text-[var(--color-text-faint)]">Active section</p>
            <p className="mt-2 font-black text-[var(--color-text-main)]">{activeLabel}</p>
          </div>
        </div>
      </aside>
    </>
  );
}
