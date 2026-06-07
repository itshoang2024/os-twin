'use client';

import { useMemo, useState } from 'react';
import { usePlanContext } from './PlanWorkspace';
import KanbanColumn from './KanbanColumn';
import EpicCard from './EpicCard';
import { Epic, EpicStatus } from '@/types';
import { useDAG } from '@/hooks/use-epics';
import { useWarRoomProgress } from '@/hooks/use-war-room';
import {
  DndContext,
  DragEndEvent,
  DragOverEvent,
  DragOverlay,
  DragStartEvent,
  PointerSensor,
  useSensor,
  useSensors,
  closestCorners,
  defaultDropAnimationSideEffects,
} from '@dnd-kit/core';

// V2 lifecycle states from Resolve-Pipeline.ps1
const stateMapping = [
  { state: 'pending', label: 'Pending' },
  { state: 'developing', label: 'Developing' },
  { state: 'in-review', label: 'In Review' },     // bucket for dynamic {role}-review states
  { state: 'review', label: 'QA Gate' },            // final QA review gate
  { state: 'optimize', label: 'Optimize' },         // fixing after review feedback
  { state: 'triage', label: 'Triage' },             // manager escalation handling
  { state: 'done', label: 'Done' },                 // terminal: success
  { state: 'failed', label: 'Failed' },             // terminal: failure
];

type ViewMode = 'LIFECYCLE' | 'TIMELINE';

// Valid transitions matching V2 lifecycle state machine from Resolve-Pipeline.ps1
// developing.done → in-review (first reviewer) or review (no reviewer chain)
// optimize.done   → in-review or review
// {role}-review.pass → done
// {role}-review.fail → optimize
// review.pass → done | review.fail → optimize
// triage.fix → optimize | triage.redesign → developing | triage.reject → failed
const validTransitions: Record<string, string[]> = {
  'pending':      ['developing'],
  'developing':   ['in-review', 'review', 'failed'],
  'in-review':    ['review', 'optimize', 'triage', 'done', 'in-review'],
  'review':       ['done', 'optimize', 'triage'],
  'optimize':     ['in-review', 'review', 'failed'],
  'triage':       ['developing', 'optimize', 'failed'],
  'done':         [],
  'failed':       [],
};

export default function KanbanBoard() {
  const { epics, isLoading, updateEpicState, planId } = usePlanContext();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [overState, setOverState] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('TIMELINE');

  // Fetch DAG and progress for column grouping & status overlay
  const { dag } = useDAG(planId);
  const { progress } = useWarRoomProgress(planId);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    })
  );

  // Build lookup maps from DAG and progress data
  const criticalPathSet = useMemo(() => {
    if (!dag?.critical_path) return new Set<string>();
    return new Set(dag.critical_path);
  }, [dag]);

  const warRoomStatusMap = useMemo(() => {
    if (!progress?.rooms) return new Map<string, string>();
    const map = new Map<string, string>();
    for (const room of progress.rooms) {
      map.set(room.task_ref, room.status);
    }
    return map;
  }, [progress]);


  const groupedEpics = useMemo(() => {
    if (!epics) return {} as Record<string, Epic[]>;
    
    return epics.reduce((acc, epic) => {
      let state = epic.lifecycle_state || 'pending';
      
      // Override with progress status if viewing lifecycle and it exists
      if (viewMode === 'LIFECYCLE' && warRoomStatusMap.has(epic.epic_ref)) {
        state = warRoomStatusMap.get(epic.epic_ref)!;
      }

      // If viewing timeline, group by wave
      if (viewMode === 'TIMELINE' && dag?.waves) {
        const wave = Object.entries(dag.waves).find(([_, refs]) => refs.includes(epic.epic_ref))?.[0];
        state = wave ? `wave-${wave}` : 'unknown';
      } else {
        // Normalize to V2 lifecycle column buckets
        state = normalizeLifecycleState(state);
      }

      if (!acc[state]) acc[state] = [];
      acc[state].push(epic);
      return acc;
    }, {} as Record<string, Epic[]>);
  }, [epics, viewMode, warRoomStatusMap, dag]);

  const columns = useMemo(() => {
    if (viewMode === 'LIFECYCLE') {
      return stateMapping;
    }

    if (dag?.waves) {
      return Object.keys(dag.waves)
        .sort((a, b) => parseInt(a) - parseInt(b))
        .map(wave => ({
          state: `wave-${wave}`,
          label: `WAVE ${wave}`,
        }));
    }

    return [{ state: 'unknown', label: 'Loading Waves...' }];
  }, [viewMode, dag]);

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(event.active.id as string);
  };

  const handleDragOver = (event: DragOverEvent) => {
    const { over } = event;
    if (over) {
      setOverState(over.id as string);
    } else {
      setOverState(null);
    }
  };

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;
    setActiveId(null);
    setOverState(null);

    if (over && epics) {
      const epicRef = active.id as string;
      const newState = over.id as string;
      const epic = epics.find(e => e.epic_ref === epicRef);

      if (epic) {
        const currentNormalized = normalizeLifecycleState(epic.lifecycle_state || 'pending');
        if (currentNormalized !== newState) {
          // Validate transition against V2 state machine
          const allowed = validTransitions[currentNormalized] || [];
          if (allowed.includes(newState)) {
            try {
              await updateEpicState(epicRef, newState, newState as EpicStatus);
            } catch (err) {
              console.error('Failed to move epic:', err);
            }
          }
        }
      }
    }
  };

  if (isLoading && !epics) {
    return (
      <div className="h-full flex flex-col p-6 overflow-hidden">
        <div className="animate-pulse space-y-4">
          <div className="h-8 w-48 bg-border rounded-lg" />
          <div className="flex gap-6 overflow-x-auto pb-4">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="min-w-[280px] h-[600px] bg-border/20 rounded-xl" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  const activeEpic = activeId ? epics?.find(e => e.epic_ref === activeId) : null;

  // Count summary stats — use progress data if available, else count from epics
  const doneCount = progress?.done ?? progress?.passed ?? epics?.filter(e => normalizeLifecycleState(e.lifecycle_state || 'pending') === 'done').length ?? 0;
  const failedCount = progress?.failed ?? epics?.filter(e => normalizeLifecycleState(e.lifecycle_state || 'pending') === 'failed').length ?? 0;
  const activeCount = progress?.active ?? epics?.filter(e => !['pending', 'done', 'failed'].includes(normalizeLifecycleState(e.lifecycle_state || 'pending'))).length ?? 0;

  return (
    <div className="h-full flex flex-col p-6 overflow-hidden">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <h2 className="text-xl font-extrabold text-text-main">
            {viewMode === 'TIMELINE' ? 'EPIC Timeline' : 'EPIC Lifecycle'}
          </h2>
          <span className="text-xs font-bold px-2.5 py-1 rounded-full bg-surface border border-border text-text-muted shadow-sm">
            {progress?.total ?? epics?.length ?? 0} TOTAL
          </span>
          {/* Status summary chips */}
          {doneCount > 0 && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600 border border-emerald-500/20">
              ✓ {doneCount} done
            </span>
          )}
          {activeCount > 0 && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-600 border border-blue-500/20">
              ⚡ {activeCount} active
            </span>
          )}
          {failedCount > 0 && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-red-500/10 text-red-600 border border-red-500/20">
              ✕ {failedCount} failed
            </span>
          )}
        </div>
        
        <div className="flex items-center gap-3">
          <div className="flex p-1 rounded-lg bg-surface border border-border">
            <button
              onClick={() => setViewMode('TIMELINE')}
              className={`px-3 py-1 text-[10px] font-bold rounded-md transition-all ${
                viewMode === 'TIMELINE' ? 'bg-primary text-white shadow-sm' : 'text-text-faint hover:text-text-main'
              }`}
            >
              TIMELINE (WAVES)
            </button>
            <button
              onClick={() => setViewMode('LIFECYCLE')}
              className={`px-3 py-1 text-[10px] font-bold rounded-md transition-all ${
                viewMode === 'LIFECYCLE' ? 'bg-primary text-white shadow-sm' : 'text-text-faint hover:text-text-main'
              }`}
            >
              EXECUTION
            </button>
          </div>
          <div className="h-4 w-[1px] bg-border mx-1" />
          {/* Progress from progress.json */}
          {progress && (
            <span className="text-[10px] font-bold text-text-muted bg-surface-hover px-2 py-1 rounded-md border border-border">
              {progress.pct_complete}% • CP {typeof progress.critical_path === 'object' ? `${progress.critical_path.completed}/${progress.critical_path.total}` : progress.critical_path}
            </span>
          )}
          <div className="flex -space-x-1 hover:space-x-1 transition-all">
            <button className="p-1.5 rounded-md border border-border bg-surface text-text-faint hover:text-text-main hover:bg-surface-hover transition-colors shadow-sm">
              <span className="material-symbols-outlined text-[18px]">search</span>
            </button>
            <button className="p-1.5 rounded-md border border-border bg-surface text-text-faint hover:text-text-main hover:bg-surface-hover transition-colors shadow-sm">
              <span className="material-symbols-outlined text-[18px]">tune</span>
            </button>
          </div>
        </div>
      </div>

      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragEnd={handleDragEnd}
      >
        <div className="flex-1 flex gap-6 overflow-x-auto custom-scrollbar pb-6 min-h-0 select-none">
          {columns.map((item) => {
            const columnEpics = groupedEpics[item.state] || [];
            const isEmpty = columnEpics.length === 0;
            return (
              <KanbanColumn 
                key={item.state} 
                state={item.state} 
                label={item.label} 
                epics={columnEpics}
                isOver={overState === item.state}
                isInvalid={isOverStateInvalid(activeEpic, item.state)}
                criticalPathSet={criticalPathSet}
                warRoomStatusMap={warRoomStatusMap}
                collapsed={viewMode === 'LIFECYCLE' && isEmpty && !activeId}
              />
            );
          })}
          {/* Spacer for overflow end padding */}
          <div className="min-w-[1px] shrink-0" />
        </div>

        <DragOverlay dropAnimation={{
          sideEffects: defaultDropAnimationSideEffects({
            styles: {
              active: {
                opacity: '0.5',
              },
            },
          }),
        }}>
          {activeEpic ? (
            <div className="w-[280px] rotate-3 cursor-grabbing">
              <EpicCard 
                epic={activeEpic} 
                onCriticalPath={criticalPathSet.has(activeEpic.epic_ref)}
                warRoomStatus={warRoomStatusMap.get(activeEpic.epic_ref)}
              />
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>
    </div>
  );
}

function isOverStateInvalid(activeEpic: Epic | null | undefined, overState: string) {
  if (!activeEpic) return false;
  const currentState = normalizeLifecycleState(activeEpic.lifecycle_state || 'pending');
  if (currentState === overState) return false;
  const allowed = validTransitions[currentState] || [];
  return !allowed.includes(overState);
}

// Exported for external use — normalizes any raw lifecycle state to a V2 column key
function normalizeLifecycleState(rawState: string): string {
  const fixedStates = new Set([
    'pending', 'developing', 'optimize', 'review',
    'triage', 'done', 'failed',
  ]);
  if (fixedStates.has(rawState)) return rawState;
  if (rawState.endsWith('-review')) return 'in-review';
  const legacyMap: Record<string, string> = {
    'engineering': 'developing',
    'fixing': 'optimize',
    'passed': 'done',
    'failed-final': 'failed',
    'manager-triage': 'triage',
    'signoff': 'done',
  };
  return legacyMap[rawState] || 'pending';
}
