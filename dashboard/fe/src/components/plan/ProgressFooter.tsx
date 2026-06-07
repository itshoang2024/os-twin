'use client';

import { useState, useMemo } from 'react';
import { usePlanContext } from './PlanWorkspace';
import { useWarRoomProgress } from '@/hooks/use-war-room';
import { useDAG } from '@/hooks/use-epics';
import AnalyticsPanel from './AnalyticsPanel';

export default function ProgressFooter() {
  const { plan, planId, isLoading, isContextPanelOpen, setIsContextPanelOpen, setSelectedEpicRef } = usePlanContext();
  const { progress } = useWarRoomProgress(planId);
  const { dag } = useDAG(planId);
  const [isPanelOpen, setIsPanelOpen] = useState(false);

  // Use progress.json data if available, fall back to plan data
  const pctComplete = progress?.pct_complete ?? plan?.pct_complete ?? 0;
  
  const criticalPath = useMemo(() => {
    if (progress?.critical_path) {
      if (typeof progress.critical_path === 'object') return progress.critical_path;
      const parts = progress.critical_path.split('/');
      if (parts.length === 2) {
        return { completed: parseInt(parts[0]) || 0, total: parseInt(parts[1]) || 0 };
      }
    }
    return plan?.critical_path ?? { completed: 0, total: 0 };
  }, [progress?.critical_path, plan?.critical_path]);

  // All hooks must be above this guard — React requires consistent hook order
  if (isLoading || !plan) {
    return <div className="h-[56px] bg-surface border-t border-border animate-pulse" />;
  }

  // Status distribution from progress.json
  const statusCounts = progress ? {
    passed: progress.done ?? progress.passed,
    failed: progress.failed,
    active: progress.active,
    pending: progress.pending,
    blocked: progress.blocked,
  } : null;

  // Current wave from DAG
  const currentWave = dag?.waves 
    ? Object.entries(dag.waves).find(([, epics]) => 
        epics.some(e => {
          const room = progress?.rooms?.find(r => r.task_ref === e);
          return room && !['done', 'passed', 'failed', 'failed-final'].includes(room.status);
        })
      )?.[0]
    : null;

  const activeEpics = progress?.active ?? plan.active_epics ?? 0;

  // Progress ring variables
  const radius = 16;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (pctComplete / 100) * circumference;

  // Failed rooms for quick access
  const failedRooms = progress?.rooms?.filter(r => r.status === 'failed' || r.status === 'failed-final') ?? [];

  return (
    <div className="relative">
      {/* Sticky Footer */}
      <footer className="h-[56px] bg-surface border-t border-border flex items-center px-6 gap-8 z-20 relative">
        {/* Collapse toggle */}
        <button 
          className="flex items-center gap-1 text-text-faint hover:text-text-main transition-colors"
          title="Toggle footer"
        >
          <span className="material-symbols-outlined text-[14px]">chevron_left</span>
          <span className="text-[10px] font-bold uppercase">Collapse</span>
        </button>

        <div className="h-6 w-px bg-border" />

        {/* Progress Ring */}
        <div className="flex items-center gap-3">
          <div className="relative flex items-center justify-center w-10 h-10">
            <svg className="w-full h-full transform -rotate-90">
              <circle
                className="text-border"
                strokeWidth="3"
                stroke="currentColor"
                fill="transparent"
                r={radius}
                cx="20"
                cy="20"
              />
              <circle
                className="text-primary transition-all duration-500 ease-out"
                strokeWidth="3"
                strokeDasharray={circumference}
                strokeDashoffset={offset}
                strokeLinecap="round"
                stroke="currentColor"
                fill="transparent"
                r={radius}
                cx="20"
                cy="20"
              />
            </svg>
            <span className="absolute text-[10px] font-bold text-text-main">
              {Math.round(pctComplete)}%
            </span>
          </div>
          <span className="text-sm font-semibold text-text-main">Progress</span>
        </div>

        <div className="h-6 w-px bg-border" />

        {/* Critical Path */}
        <div className="flex flex-col">
          <span className="text-[10px] uppercase tracking-wider text-text-muted font-bold">Critical Path</span>
          <span className="text-sm font-mono text-text-main">
            {criticalPath.completed}/{criticalPath.total}
          </span>
        </div>

        <div className="h-6 w-px bg-border" />

        {/* Current Wave */}
        <div className="flex flex-col">
          <span className="text-[10px] uppercase tracking-wider text-text-muted font-bold">Current Wave</span>
          <span className="text-sm font-mono text-text-main underline decoration-primary underline-offset-4">
            {currentWave ? `Wave ${currentWave}` : 'Wave 1'}
          </span>
        </div>

        <div className="h-6 w-px bg-border" />

        {/* Active EPICs */}
        <div className="flex flex-col">
          <span className="text-[10px] uppercase tracking-wider text-text-muted font-bold">Active EPICs</span>
          <span className="text-sm font-mono text-text-main">{activeEpics} in flight</span>
        </div>

        {/* Status Distribution Chips */}
        {statusCounts && (
          <>
            <div className="h-6 w-px bg-border" />
            <div className="flex items-center gap-1.5">
              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-600 border border-emerald-500/20">
                ✓{statusCounts.passed}
              </span>
              {statusCounts.failed > 0 && (
                <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-red-500/10 text-red-600 border border-red-500/20">
                  ✕{statusCounts.failed}
                </span>
              )}
              {statusCounts.blocked > 0 && (
                <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 border border-amber-500/20">
                  ⚠{statusCounts.blocked}
                </span>
              )}
            </div>
          </>
        )}

        {/* Failed Room alerts */}
        {failedRooms.length > 0 && (
          <>
            <div className="h-6 w-px bg-border" />
            <div className="flex items-center gap-1 text-red-500 animate-pulse">
              <span className="material-symbols-outlined text-sm">warning</span>
              <span className="text-[10px] font-bold">{failedRooms.map(r => r.task_ref).join(', ')}</span>
            </div>
          </>
        )}

        <div className="flex-1" />

        {/* Toggle Context Panel */}
        <button
          onClick={() => {
            if (isContextPanelOpen) {
              setIsContextPanelOpen(false);
            } else {
              setSelectedEpicRef(null); // Show Plan Summary, not an epic
              setIsContextPanelOpen(true);
            }
          }}
          className={`px-4 py-1.5 rounded text-sm font-medium transition-colors flex items-center gap-2 ${
            isContextPanelOpen
              ? 'bg-primary text-white'
              : 'bg-surface-hover text-text-main hover:bg-surface-active border border-border'
          }`}
        >
          <span className="material-symbols-outlined text-[18px]">
            {isContextPanelOpen ? 'right_panel_close' : 'right_panel_open'}
          </span>
          {isContextPanelOpen ? 'Hide Summary' : 'Plan Summary'}
        </button>

        {/* View Analytics Button */}
        <button
          onClick={() => setIsPanelOpen(!isPanelOpen)}
          className={`px-4 py-1.5 rounded text-sm font-medium transition-colors flex items-center gap-2 ${
            isPanelOpen 
              ? 'bg-primary text-white' 
              : 'bg-surface-hover text-text-main hover:bg-surface-active border border-border'
          }`}
        >
          <span className="material-symbols-outlined text-[18px]">
            {isPanelOpen ? 'keyboard_arrow_down' : 'analytics'}
          </span>
          {isPanelOpen ? 'Close Analytics' : 'View Analytics'}
        </button>
      </footer>

      {/* Analytics Panel Overlay */}
      <AnalyticsPanel isOpen={isPanelOpen} onClose={() => setIsPanelOpen(false)} />
    </div>
  );
}
