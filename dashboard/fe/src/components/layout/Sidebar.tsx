'use client';

import { useEffect } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useUIStore } from '@/lib/stores/uiStore';
import { usePlanningThreads } from '@/hooks/use-planning-threads';
import { Skeleton } from '@/components/ui/Skeleton';

const navItems = [
  { href: '/', icon: 'home', label: 'Home' },
  { href: '/plans', icon: 'folder', label: 'Plans' },
  { href: '/knowledge', icon: 'auto_stories', label: 'Knowledge' },
  { href: '/roles', icon: 'person', label: 'Roles' },
  { href: '/skills', icon: 'extension', label: 'Skills' },
  { href: '/mcp', icon: 'terminal', label: 'MCP' },
  { href: '/settings', icon: 'settings', label: 'Settings' },
];

export default function Sidebar({ className = '', ...props }: React.ComponentPropsWithoutRef<'aside'>) {
  const pathname = usePathname();
  const { sidebarCollapsed, toggleSidebar } = useUIStore();
  const isFixtureRoute = pathname.includes('-fixture');
  const { threads, isLoading: threadsLoading } = usePlanningThreads(5, 0, !isFixtureRoute);

  // Auto-collapse on narrower desktop widths without overriding manual collapse.
  useEffect(() => {
    const handleResize = () => {
      const width = window.innerWidth;
      const shouldAutoCollapse = width >= 1024 && width <= 1280;
      if (shouldAutoCollapse && !useUIStore.getState().sidebarCollapsed) {
        useUIStore.setState({ sidebarCollapsed: true });
      }
    };

    window.addEventListener('resize', handleResize);
    handleResize();
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const isActive = (href: string) => {
    if (href === '/') return pathname === '/';
    return pathname.startsWith(href);
  };

  return (
    <aside
      {...props}
      className={`shrink-0 flex flex-col border-r transition-all duration-200 ease-out overflow-hidden ${className}`}
      style={{
        width: sidebarCollapsed ? 64 : 240,
        minWidth: sidebarCollapsed ? 64 : 240,
        background: 'var(--color-surface)',
        borderColor: 'var(--color-border)',
      }}
    >
      {/* Logo */}
      <div
        className="h-14 flex items-center gap-3 px-4 border-b shrink-0"
        style={{ borderColor: 'var(--color-border)' }}
      >
        <Image
          src="/logo.svg"
          alt="OsTwin"
          width={32}
          height={32}
          className="shrink-0"
          aria-hidden="true"
        />
        {!sidebarCollapsed && (
          <div className="flex flex-col min-w-0">
            <span className="text-sm font-bold truncate" style={{ color: 'var(--color-text-main)' }}>
              Os<span style={{ background: 'linear-gradient(135deg, #00ff88, #00c4e0, #00d4ff)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>Twin</span>
            </span>
            <span className="text-[10px]" style={{ color: 'var(--color-text-faint)' }}>Command Center</span>
          </div>
        )}
        {!sidebarCollapsed && (
          <button
            onClick={toggleSidebar}
            className="ml-auto flex h-7 w-7 shrink-0 items-center justify-center rounded-lg transition-colors hover:bg-surface-hover"
            style={{ color: 'var(--color-text-muted)' }}
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
          >
            <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
              chevron_left
            </span>
          </button>
        )}
      </div>

      {/* Nav items */}
      <nav className="flex-1 py-3 px-2 space-y-1 overflow-y-auto custom-scrollbar">
        {navItems.map((item) => {
          const active = isActive(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150 group relative"
              style={{
                color: active ? 'var(--color-primary)' : 'var(--color-text-muted)',
                background: active ? 'var(--color-primary-muted)' : 'transparent',
              }}
              title={sidebarCollapsed ? item.label : undefined}
              aria-label={item.label}
              aria-current={active ? 'page' : undefined}
            >
              {active && (
                <div
                  className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full"
                  style={{ background: 'var(--color-primary)' }}
                />
              )}
              <span className="material-symbols-outlined text-xl" style={{ fontSize: 20 }} aria-hidden="true">
                {item.icon}
              </span>
              {!sidebarCollapsed && <span className="truncate">{item.label}</span>}
            </Link>
          );
        })}

        {/* Recent Ideas */}
        {!sidebarCollapsed && (
          <div className="mt-6 mb-4 flex flex-col gap-1">
            <div className="flex items-center gap-2 mb-2 px-3">
              <span className="material-symbols-outlined text-sm" style={{ color: 'var(--color-text-muted)' }}>lightbulb</span>
              <span className="text-xs font-bold uppercase tracking-wider" style={{ color: 'var(--color-text-muted)' }}>Recent Ideas</span>
            </div>
            
            {threadsLoading ? (
              <div className="flex flex-col gap-2 mt-2 px-3">
                <Skeleton className="h-6 w-full rounded" />
                <Skeleton className="h-6 w-3/4 rounded" />
                <Skeleton className="h-6 w-5/6 rounded" />
              </div>
            ) : threads.length === 0 ? (
              <div className="px-3 py-2 text-xs" style={{ color: 'var(--color-text-faint)' }}>
                No ideas yet
              </div>
            ) : (
              <div className="flex flex-col gap-1 px-1">
                {threads.map(thread => {
                  const isActiveIdea = pathname === `/ideas/${thread.id}`;
                  return (
                    <Link
                      key={thread.id}
                      href={`/ideas/${thread.id}`}
                      className="flex items-center justify-between px-2 py-2 rounded-lg text-sm transition-all duration-150 group"
                      style={{
                        color: isActiveIdea ? 'var(--color-primary)' : 'var(--color-text-muted)',
                        background: isActiveIdea ? 'var(--color-primary-muted)' : 'transparent',
                      }}
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="material-symbols-outlined text-[16px] shrink-0 opacity-70">
                          lightbulb
                        </span>
                        <span className="truncate max-w-[140px]" title={thread.title ?? undefined}>
                          {(thread.title ?? 'New Idea').length > 25 ? (thread.title ?? 'New Idea').slice(0, 25) + '...' : (thread.title ?? 'New Idea')}
                        </span>
                      </div>
                      {thread.status === 'promoted' && (
                        <span className="material-symbols-outlined text-[14px] text-green-500 shrink-0" title="Promoted to Plan">
                          check_circle
                        </span>
                      )}
                    </Link>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </nav>

      {/* Collapse toggle */}
      <div
        className="px-2 py-3 border-t shrink-0"
        style={{ borderColor: 'var(--color-border)' }}
      >
        <button
          onClick={toggleSidebar}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition-colors"
          style={{ color: 'var(--color-text-muted)' }}
          aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <span className="material-symbols-outlined text-lg" aria-hidden="true">
            {sidebarCollapsed ? 'chevron_right' : 'chevron_left'}
          </span>
          {!sidebarCollapsed && <span>Collapse</span>}
        </button>
      </div>
    </aside>
  );
}
