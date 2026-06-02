'use client';

import Sidebar from './Sidebar';
import TopBar from './TopBar';
import { ToastNotification } from '@/components/ui/ToastNotification';
import { useRealtimeSim } from '@/hooks/use-realtime-sim';
import { KeyboardShortcutManager } from '@/components/ui/KeyboardShortcutManager';
import { KeyboardShortcutHelp } from '@/components/ui/KeyboardShortcutHelp';
import { SearchModal } from '@/components/ui/SearchModal';

export default function AppShell({ children }: { children: React.ReactNode }) {
  useRealtimeSim();
  return (
    <div className="h-screen grid overflow-hidden" style={{ gridTemplateColumns: 'auto 1fr', gridTemplateRows: '56px 1fr' }}>
      <KeyboardShortcutManager />
      <KeyboardShortcutHelp />
      <SearchModal />
      <Sidebar className="row-span-2" role="navigation" aria-label="Main Navigation" />
      <TopBar role="navigation" aria-label="Top Bar" />
      <main className="overflow-auto custom-scrollbar" style={{ background: 'var(--color-background)' }} role="main">
        {children}
      </main>
      <ToastNotification />
    </div>
  );
}
