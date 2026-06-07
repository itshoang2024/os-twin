'use client';

import { useUIStore } from '@/lib/stores/uiStore';
import NotificationBell from './NotificationBell';
import { ConnectionStatus } from './ConnectionStatus';
import { useAuth } from '@/components/auth/AuthProvider';

function getInitials(name: string | null): string {
  const parts = (name || 'User')
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return 'U';
  return parts.slice(0, 2).map(part => part[0]?.toUpperCase()).join('');
}

export default function TopBar({ ...props }: React.ComponentPropsWithoutRef<'header'>) {
  const { theme, toggleTheme, setSearchModalOpen } = useUIStore();
  const { username, logout } = useAuth();
  const displayName = username || 'User';

  return (
    <header
      {...props}
      className="h-14 flex items-center justify-between px-6 border-b shrink-0 sticky top-0 z-50"
      style={{
        background: 'var(--color-surface)',
        borderColor: 'var(--color-border)',
        boxShadow: '0 1px 3px rgba(15, 23, 42, 0.04)',
        height: '56px',
      }}
    >
      {/* Search */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => setSearchModalOpen(true)}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-colors group"
          style={{
            background: 'var(--color-background)',
            color: 'var(--color-text-faint)',
            border: '1px solid var(--color-border)',
          }}
          aria-label="Search plans, EPICs, tasks (Cmd+K)"
          role="search"
        >
          <span className="material-symbols-outlined text-base transition-colors group-hover:text-primary" aria-hidden="true">search</span>
          <span>Search plans, EPICs, tasks...</span>
          <kbd
            className="ml-6 px-1.5 py-0.5 rounded text-[10px] font-mono"
            style={{
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text-faint)',
            }}
            aria-hidden="true"
          >
            ⌘K
          </kbd>
        </button>
      </div>

      {/* Right side */}
      <div className="flex items-center gap-3">
        <ConnectionStatus />

        {/* Dark mode toggle */}
        <button
          onClick={toggleTheme}
          className="p-2 rounded-lg transition-colors hover:bg-surface-hover"
          style={{ color: 'var(--color-text-muted)' }}
          title={theme === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
          aria-label={theme === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
        >
          <span className="material-symbols-outlined text-xl" aria-hidden="true">
            {theme === 'light' ? 'dark_mode' : 'light_mode'}
          </span>
        </button>

        {/* Notification bell */}
        <NotificationBell />

        {/* Divider */}
        <div className="w-px h-6 mx-1" style={{ background: 'var(--color-border)' }} />

        {/* User identity */}
        <button
          onClick={logout}
          className="flex items-center gap-2 rounded-full pl-1 pr-2 py-1 hover:bg-surface-hover transition-colors"
          title="Sign out"
          aria-label={`Signed in as ${displayName}. Sign out`}
        >
          <div
            className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold text-white shadow-sm"
            style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}
          >
            {getInitials(displayName)}
          </div>
          <span className="hidden sm:inline max-w-32 truncate text-xs font-bold" style={{ color: 'var(--color-text-main)' }}>
            {displayName}
          </span>
          <span className="material-symbols-outlined text-sm" style={{ color: 'var(--color-text-faint)' }}>logout</span>
        </button>
      </div>
    </header>
  );
}
