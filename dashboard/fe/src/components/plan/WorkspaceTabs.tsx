'use client';

import { Suspense, lazy } from 'react';
import { usePlanContext } from './PlanWorkspace';

// Lazy-load tab components
const KanbanBoard = lazy(() => import('./KanbanBoard'));
const RolesConfigTab = lazy(() => import('./RolesConfigTab'));
const DAGTab = lazy(() => import('./placeholder/DAGTab'));
const PlanEditorTab = lazy(() => import('./PlanEditorTab'));
const PlanHistoryTab = lazy(() => import('./PlanHistoryTab'));
const ArchitectTab = lazy(() => import('./ArchitectTab'));
const MemoryTab = lazy(() => import('./MemoryTab'));
const PlanKnowledgeTab = lazy(() => import('./PlanKnowledgeTab'));
const FileBrowser = lazy(() => import('./FileBrowser'));
const AssetPanel = lazy(() => import('./AssetPanel'));
const PlanLogsTab = lazy(() => import('./PlanLogsTab'));

export default function WorkspaceTabs() {
  const { activeTab, planId, planContent, setPlanContent } = usePlanContext();

  const renderContent = () => {
    switch (activeTab) {
      case 'epics':
        return <KanbanBoard />;
      case 'roles':
        return <RolesConfigTab />;
      case 'dag':
        return <DAGTab />;
      case 'editor':
        return <PlanEditorTab content={planContent} onChange={setPlanContent} />;
      case 'history':
        return <PlanHistoryTab planId={planId} />;
      case 'architect':
        return <ArchitectTab />;
      case 'memory':
        return <MemoryTab />;
      case 'knowledge':
        return <PlanKnowledgeTab />;
      case 'files':
        return <FileBrowser planId={planId} />;
      case 'logs':
        return <PlanLogsTab planId={planId} />;
      case 'assets':
        return <AssetPanel />;
      default:
        return <KanbanBoard />;
    }
  };

  return (
    <div className="flex-1 h-full overflow-hidden">
      <Suspense fallback={
        <div className="p-10 animate-pulse flex flex-col gap-6">
          <div className="h-10 w-64 bg-border/20 rounded-lg" />
          <div className="grid grid-cols-4 gap-4 h-full">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-[500px] bg-border/10 rounded-2xl" />
            ))}
          </div>
        </div>
      }>
        {renderContent()}
      </Suspense>
    </div>
  );
}
