'use client';

import { createContext, useContext, useCallback, useEffect, useMemo, useState } from 'react';
import { usePathname } from 'next/navigation';
import { usePlan } from '@/hooks/use-plans';
import { useEpics, useDAG } from '@/hooks/use-epics';
import { useWarRoomProgress } from '@/hooks/use-war-room';
import { usePlanRefine } from '@/hooks/use-plan-refine';
import { useAssets } from '@/hooks/use-assets';
import { apiPost } from '@/lib/api-client';
import { useNotificationStore } from '@/lib/stores/notificationStore';
import { Plan, Epic, EpicStatus, DAGNodeRaw, WarRoomProgress } from '@/types';
import { parseEpicMarkdown, serializeEpicMarkdown, EpicDocument } from '@/lib/epic-parser';
import PlanSidebar from './PlanSidebar';
import WorkspaceTabs from './WorkspaceTabs';
import ContextPanel from './ContextPanel';

import PlanBreadcrumb from './PlanBreadcrumb';
import ProgressFooter from './ProgressFooter';

interface PlanContextType {
  planId: string;
  plan: Plan | undefined;
  epics: Epic[] | undefined;
  progress: WarRoomProgress | undefined;
  isLoading: boolean;
  isProgressLoading: boolean;
  isError: unknown;
  selectedEpicRef: string | null;
  setSelectedEpicRef: (ref: string | null) => void;
  updateEpicState: (ref: string, lifecycle_state: string, status: EpicStatus) => Promise<Epic | undefined>;
  isContextPanelOpen: boolean;
  setIsContextPanelOpen: (open: boolean | ((prev: boolean) => boolean)) => void;
  activeTab: string;
  setActiveTab: (tab: string) => void;
  planContent: string;
  setPlanContent: (content: string) => void;
  savePlan: () => Promise<void>;
  launchPlan: () => Promise<void>;
  reloadFromDisk: () => Promise<void>;
  syncStatus: { in_sync: boolean; disk_mtime: number; zvec_mtime: number } | undefined;
  isSaving: boolean;
  isLaunching: boolean;
  isAIChatOpen: boolean;
  setIsAIChatOpen: (open: boolean | ((prev: boolean) => boolean)) => void;
  isRefining: boolean;
  parsedPlan: EpicDocument | null;
  updateParsedPlan: (updater: (doc: EpicDocument) => void) => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  refreshProgress: () => void;
  uploadAssets: (files: FileList | File[], epicRef?: string) => Promise<unknown>;
  isUploadingAssets: boolean;
  // EPIC-007: Memory-Knowledge Bridge - highlight note on cross-tab navigation
  highlightNoteId: string | null;
  setHighlightNoteId: (id: string | null) => void;
  // Edit Epic Drawer — signal edit mode from context menu / card
  isEditingEpic: boolean;
  setIsEditingEpic: (editing: boolean) => void;
  deletePlan: () => Promise<void>;
}

export const PlanContext = createContext<PlanContextType | undefined>(undefined);

export function usePlanContext() {
  const context = useContext(PlanContext);
  if (!context) {
    throw new Error('usePlanContext must be used within a PlanProvider');
  }
  return context;
}

// Read initial tab from URL query string client-side (avoids useSearchParams Suspense issue)
function getInitialTab(): string {
  if (typeof window === 'undefined') return 'epics';
  const params = new URLSearchParams(window.location.search);
  const tab = params.get('tab');
  return tab === 'dag' ? 'editor' : tab || 'epics';
}

export default function PlanWorkspace({ planId: propId }: { planId: string }) {
  // In static export mode, the prop contains the template's baked ID (e.g. "plan-001").
  // usePathname() reads the actual browser URL so we can extract the real plan ID.
  const pathname = usePathname();
  const pathSegments = pathname?.split('/').filter(Boolean);
  // URL format: /plans/{id} → pathSegments = ['plans', '{id}']
  const planId = (pathSegments?.[0] === 'plans' && pathSegments?.[1]) ? pathSegments[1] : propId;

  const { plan, syncStatus, isLoading: planLoading, isError: planError, reloadFromDisk, deletePlan } = usePlan(planId);
  const { epics: apiEpics, isLoading: epicsLoading, isError: epicsError, updateEpicState } = useEpics(planId);
  const { dag } = useDAG(planId);
  const { progress, isLoading: isProgressLoading, refresh: refreshProgress } = useWarRoomProgress(planId);
  const { uploadAssets, uploading: isUploadingAssets } = useAssets(planId);
  
  const [selectedEpicRef, setSelectedEpicRef] = useState<string | null>(null);
  const [isContextPanelOpen, setIsContextPanelOpen] = useState(false);
  const [isAIChatOpen, setIsAIChatOpen] = useState(false);
  // Initialize tab from URL ?tab= param, then manage via React state (SPA — no reloads)
  const [activeTab, setActiveTab] = useState(getInitialTab);
  const [planContent, setPlanContent] = useState('');
  const [parsedPlan, setParsedPlan] = useState<EpicDocument | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isLaunching, setIsLaunching] = useState(false);
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  // EPIC-007: Memory-Knowledge Bridge - highlight note on cross-tab navigation
  const [highlightNoteId, setHighlightNoteId] = useState<string | null>(null);
  const [isEditingEpic, setIsEditingEpic] = useState(false);

  // Undo/Redo Stack
  const [undoStack, setUndoStack] = useState<{ past: string[]; future: string[] }>({ past: [], future: [] });

  const pushToUndo = useCallback((content: string) => {
    setUndoStack(prev => ({
      past: [content, ...prev.past].slice(0, 50),
      future: []
    }));
  }, []);

  const handleGlobalDragOver = useCallback((e: React.DragEvent) => {
    if (e.dataTransfer.types.includes('Files')) {
      e.preventDefault();
      setIsDraggingFile(true);
    }
  }, []);

  const handleGlobalDragLeave = useCallback((e: React.DragEvent) => {
    // Only set to false if we're leaving the window/container
    if (e.currentTarget === e.target) {
      setIsDraggingFile(false);
    }
  }, []);

  const handleGlobalDrop = useCallback(async (e: React.DragEvent) => {
    if (e.dataTransfer.files.length > 0) {
      e.preventDefault();
      setIsDraggingFile(false);
      try {
        await uploadAssets(e.dataTransfer.files);
        setActiveTab('assets'); // Switch to assets tab to show the upload
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : 'Unknown error';
        alert(`Upload failed: ${message}`);
      }
    }
  }, [uploadAssets]);

  const undo = useCallback(() => {
    if (undoStack.past.length === 0) return;
    const nextContent = undoStack.past[0];
    const newPast = undoStack.past.slice(1);
    const newFuture = [planContent, ...undoStack.future].slice(0, 50);
    
    setUndoStack({ past: newPast, future: newFuture });
    setPlanContent(nextContent);
  }, [undoStack, planContent]);

  const redo = useCallback(() => {
    if (undoStack.future.length === 0) return;
    const nextContent = undoStack.future[0];
    const newFuture = undoStack.future.slice(1);
    const newPast = [planContent, ...undoStack.past].slice(0, 50);
    
    setUndoStack({ past: newPast, future: newFuture });
    setPlanContent(nextContent);
  }, [undoStack, planContent]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
        if (e.shiftKey) {
          redo();
        } else {
          undo();
        }
      } else if ((e.ctrlKey || e.metaKey) && e.key === 'y') {
        redo();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [undo, redo]);

  useEffect(() => {
    if (planContent) {
      try {
        const parsed = parseEpicMarkdown(planContent);
        setParsedPlan(parsed);
      } catch (err) {
        console.error('Failed to parse plan:', err);
        setParsedPlan(null);
      }
    }
  }, [planContent]);

  const updateParsedPlan = useCallback((updater: (doc: EpicDocument) => void) => {
    if (!parsedPlan) return;
    
    // Save current content to undo stack BEFORE updating
    pushToUndo(planContent);
    
    // We create a new doc object and shallow copy epics to allow the updater to replace them.
    const docCopy: EpicDocument = {
      ...parsedPlan,
      epics: parsedPlan.epics.map(e => ({
        ...e,
        frontmatter: new Map(e.frontmatter),
        sections: e.sections.map(s => ({
          ...s,
          items: s.items ? s.items.map(i => ({ ...i })) : undefined,
          tasks: s.tasks ? s.tasks.map(t => ({ ...t })) : undefined,
        }))
      }))
    };
    
    updater(docCopy);
    const newContent = serializeEpicMarkdown(docCopy);
    setPlanContent(newContent);
    setParsedPlan(docCopy);
  }, [parsedPlan, planContent, pushToUndo]);
  const addToast = useNotificationStore((state) => state.addToast);

  const {
    isRefining,
  } = usePlanRefine();

  useEffect(() => {
    if (plan?.content !== undefined && planContent === '') {
      setPlanContent(plan.content);
    }
  }, [plan?.content]);  // eslint-disable-line react-hooks/exhaustive-deps

  const savePlan = useCallback(async () => {
    setIsSaving(true);
    try {
      await apiPost(`/plans/${planId}/save`, { content: planContent });
      addToast({
        type: 'success',
        title: 'Plan Saved',
        message: 'Your plan changes have been successfully persisted.',
        autoDismiss: true,
      });
    } catch (err: unknown) {
      addToast({
        type: 'error',
        title: 'Save Failed',
        message: err instanceof Error ? err.message : 'There was an error saving your plan. Please try again.',
        autoDismiss: false,
      });
    } finally {
      setIsSaving(false);
    }
  }, [planId, planContent, addToast]);

  const launchPlan = useCallback(async () => {
    setIsLaunching(true);
    try {
      await apiPost('/run', { plan: planContent, plan_id: planId });
      addToast({
        type: 'success',
        title: 'Plan Launched',
        message: 'Your plan has been launched successfully.',
        autoDismiss: true,
      });
    } catch (err: unknown) {
      addToast({
        type: 'error',
        title: 'Launch Failed',
        message: err instanceof Error ? err.message : 'There was an error launching your plan. Please try again.',
        autoDismiss: false,
      });
    } finally {
      setIsLaunching(false);
    }
  }, [planId, planContent, addToast]);

  // Synthesize epics from progress + DAG when the /epics API returns empty
  const epics = useMemo(() => {
    const result: Epic[] = [];
    const seenRefs = new Set<string>();

    // Build a live status map from progress.rooms — this is the source of truth
    const progressStatusMap = new Map<string, { status: string; room_id: string }>();
    if (progress?.rooms) {
      for (const room of progress.rooms) {
        progressStatusMap.set(room.task_ref, { status: room.status, room_id: room.room_id });
      }
    }

    // 1. Add Epics from API, overriding status/lifecycle_state from live progress data
    if (apiEpics) {
      for (const e of apiEpics) {
        // The /epics API may return 'epic_ref' or 'task_ref' depending on code path
        const ref = e.epic_ref || (e as Epic & { task_ref?: string }).task_ref || '';
        const liveRoom = progressStatusMap.get(ref);
        result.push({
          ...e,
          epic_ref: ref, // normalize — ensure epic_ref is always set
          role: e.role || (dag?.nodes ? dag.nodes[ref]?.role : 'unknown') || 'unknown',
          // Override stale API status with live status from progress.json
          ...(liveRoom ? {
            lifecycle_state: liveRoom.status,
            status: liveRoom.status as EpicStatus,
            room_id: liveRoom.room_id || e.room_id,
          } : {}),
        });
        seenRefs.add(ref);
      }
    }

    // 2. Synthesize missing epics from progress rooms (e.g. PLAN-REVIEW)
    if (progress?.rooms && dag?.nodes) {
      for (const room of progress.rooms) {
        if (!seenRefs.has(room.task_ref)) {
          const dagNode = dag.nodes[room.task_ref];
          result.push({
            epic_ref: room.task_ref,
            plan_id: planId,
            title: room.task_ref,
            lifecycle_state: room.status,
            status: room.status as EpicStatus,
            role: dagNode?.role || 'unknown',
            room_id: room.room_id,
            depends_on: dagNode ? (Array.isArray(dagNode.depends_on) ? dagNode.depends_on : dagNode.depends_on ? [dagNode.depends_on] : []) : [],
            dependents: dagNode?.dependents || [],
            tasks: [],
          });
          seenRefs.add(room.task_ref);
        }
      }
    }

    // 3. Synthesize epics from DAG nodes alone (pending plans — no war-rooms or progress yet)
    if (result.length === 0 && dag?.nodes && typeof dag.nodes === 'object' && !Array.isArray(dag.nodes)) {
      for (const [ref, node] of Object.entries(dag.nodes)) {
        if (!seenRefs.has(ref)) {
          const dagNode = node as DAGNodeRaw;
          const depsRaw = dagNode.depends_on;
          result.push({
            epic_ref: ref,
            plan_id: planId,
            title: ref,
            lifecycle_state: 'pending',
            status: 'pending' as EpicStatus,
            role: dagNode.role || 'unknown',
            room_id: dagNode.room_id || '',
            depends_on: Array.isArray(depsRaw) ? depsRaw : depsRaw ? [depsRaw] : [],
            dependents: dagNode.dependents || [],
            tasks: [],
          });
          seenRefs.add(ref);
        }
      }
    }

    return result.length > 0 ? result : apiEpics;
  }, [apiEpics, progress, dag, planId]);

  const contextValue: PlanContextType = {
    planId,
    plan,
    epics,
    progress,
    isLoading: planLoading || epicsLoading,
    isProgressLoading,
    isError: planError || epicsError,
    selectedEpicRef,
    setSelectedEpicRef,
    updateEpicState,
    isContextPanelOpen,
    setIsContextPanelOpen,
    activeTab,
    setActiveTab,
    planContent,
    setPlanContent,
    savePlan,
    launchPlan,
    reloadFromDisk,
    syncStatus,
    isSaving,
    isLaunching,
    isAIChatOpen,
    setIsAIChatOpen,
    isRefining,
    parsedPlan,
    updateParsedPlan,
    undo,
    redo,
    canUndo: undoStack.past.length > 0,
    canRedo: undoStack.future.length > 0,
    refreshProgress: () => refreshProgress(),
    uploadAssets,
    isUploadingAssets,
    // EPIC-007: Memory-Knowledge Bridge
    highlightNoteId,
    setHighlightNoteId,
    // Edit Epic Drawer
    isEditingEpic,
    setIsEditingEpic,
    deletePlan,
  };

  if (planLoading && !plan) {
    return <div className="p-8 animate-pulse">Loading plan...</div>;
  }

  if (planError) {
    return (
      <div className="p-8 flex flex-col items-center justify-center h-full">
        <span className="material-symbols-outlined text-danger text-4xl mb-2">error</span>
        <h2 className="text-xl font-bold text-text-main">Failed to load plan</h2>
        <p className="text-text-muted mt-2">The requested plan could not be found or there was a server error.</p>
      </div>
    );
  }

  return (
    <PlanContext.Provider value={contextValue}>
      <div 
        className={`flex flex-col h-[calc(100vh-56px)] bg-background relative transition-all duration-300 ${
          isDraggingFile ? 'ring-4 ring-primary/20 ring-inset' : ''
        }`}
        onDragOver={handleGlobalDragOver}
        onDragLeave={handleGlobalDragLeave}
        onDrop={handleGlobalDrop}
      >
        {isDraggingFile && (
          <div className="absolute top-4 right-4 bg-primary text-white px-4 py-2 rounded-lg shadow-xl z-[9999] flex items-center gap-2 animate-in slide-in-from-top-4 duration-300 pointer-events-none">
            <span className="material-symbols-outlined text-[20px] animate-bounce">upload</span>
            <span className="text-xs font-bold uppercase tracking-wider">Drop anywhere to upload to Plan</span>
          </div>
        )}
        {/* Breadcrumb Header */}
        <div className="px-6 py-2 border-b bg-surface border-border shrink-0">
          <PlanBreadcrumb />
        </div>

        {/* Three Panel Layout */}
        <div className="flex-1 flex overflow-hidden">
          {/* Left Panel: Sidebar (Metadata + Tab Nav) */}
          <aside className="w-[240px] border-r bg-surface border-border flex flex-col shrink-0">
            <PlanSidebar />
          </aside>

          {/* Center Panel: Content Area */}
          <main className="flex-1 flex flex-col overflow-hidden bg-background">
            {syncStatus && !syncStatus.in_sync && (
              <div className="bg-amber-50 border-b border-amber-200 px-4 py-2 flex items-center justify-between animate-in fade-in slide-in-from-top duration-300">
                <div className="flex items-center gap-2 text-amber-800 text-sm font-medium">
                  <span className="material-symbols-outlined text-amber-500" style={{ fontSize: '20px' }}>warning</span>
                  Plan changed on disk externally.
                </div>
                <button 
                  onClick={() => reloadFromDisk()}
                  className="px-3 py-1 bg-amber-600 hover:bg-amber-700 text-white text-xs font-bold rounded shadow-sm transition-colors flex items-center gap-1"
                >
                  <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>sync</span>
                  Reload from Disk
                </button>
              </div>
            )}
            <WorkspaceTabs />
          </main>

          {/* Right Panel: Contextual Panel */}
          <aside
            className={`border-l bg-surface border-border flex flex-col shrink-0 transition-all duration-300 overflow-hidden ${
              isContextPanelOpen ? 'w-[396px]' : 'w-0 border-l-0'
            }`}
          >
            <div className="w-[396px] h-full">
              <ContextPanel />
            </div>
          </aside>

          {/* Right Panel: AI Chat (moved to AI Plan tab) */}
        </div>

        {/* Progress Footer */}
        <ProgressFooter />
      </div>
    </PlanContext.Provider>
  );
}
