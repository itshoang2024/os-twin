'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { usePlanContext } from './PlanWorkspace';
import { StatusBadge } from '@/components/ui/StatusBadge';
import ConfirmDialog from '@/components/ui/ConfirmDialog';

export default function PlanSidebar() {
  const { plan, epics, progress, isProgressLoading, activeTab, setActiveTab, savePlan, isSaving, launchPlan, isLaunching, deletePlan } = usePlanContext();
  const router = useRouter();
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const tabs = [
    { id: 'editor', label: 'Planner', icon: 'edit_document' },
    { id: 'epics', label: 'EPICs', icon: 'view_kanban', count: epics?.length },
    { id: 'files', label: 'Files', icon: 'folder_open' },
    { id: 'logs', label: 'Live Logs', icon: 'terminal', count: progress?.active },
    { id: 'assets', label: 'Assets', icon: 'attach_file' },
    { id: 'roles', label: 'Roles & Config', icon: 'group' },
    { id: 'dag', label: 'DAG View', icon: 'account_tree' },
    { id: 'history', label: 'History', icon: 'history' },
    { id: 'architect', label: 'AI Plan', icon: 'smart_toy' },
    { id: 'memory', label: 'Memory', icon: 'psychology' },
    { id: 'knowledge', label: 'Knowledge', icon: 'auto_stories' },
  ];

  if (!plan) return null;

  // Map PlanStatus to StatusBadge compatible status
  const getStatusVariant = (status: string): "active" | "completed" | "blocked" | "pending" | "failed" => {
    switch (status) {
      case 'active': return 'active';
      case 'completed': return 'completed';
      case 'draft': return 'pending';
      default: return 'pending';
    }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Plan Metadata Section */}
      <div className="p-4 border-b border-border space-y-4">
        <div>
          <div className="flex items-center gap-2 mb-1 justify-between">
            <h2 className="text-sm font-bold text-text-main line-clamp-1 truncate" title={plan.title}>
              {plan.title}
            </h2>
            <StatusBadge status={getStatusVariant(plan.status ?? 'draft')} size="sm" />
          </div>
          <p className="text-[11px] text-text-muted leading-relaxed line-clamp-3 mt-2">
            {plan.goal ?? ''}
          </p>
        </div>

        {/* Simple Progress Mini-bar */}
        <div className="space-y-1.5">
          <div className="flex justify-between text-[10px] font-bold uppercase tracking-wider">
            <span className="text-text-muted">Progress</span>
            <span className={isProgressLoading ? 'animate-pulse text-primary' : 'text-text-main'}>
              {Math.round(progress?.pct_complete ?? plan.pct_complete ?? 0)}%
            </span>
          </div>
          <div className="h-1.5 w-full bg-border/50 rounded-full overflow-hidden">
            <div
              className={`h-full bg-primary transition-all duration-500 ${isProgressLoading ? 'opacity-50' : ''}`}
              style={{ width: `${progress?.pct_complete ?? plan.pct_complete ?? 0}%` }}
            />
          </div>
        </div>
      </div>

      {/* Tab Navigation Section */}
      <nav className="flex-1 overflow-y-auto p-2 space-y-0.5 custom-scrollbar">
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`w-full flex items-center justify-between px-3 py-2 rounded-md transition-all group ${isActive
                ? 'bg-primary/10 text-primary'
                : 'text-text-muted hover:bg-surface-hover hover:text-text-main'
                }`}
            >
              <div className="flex items-center gap-2.5">
                <span className={`material-symbols-outlined text-[18px] transition-colors ${isActive ? 'text-primary' : 'text-text-faint group-hover:text-text-muted'
                  }`}>
                  {tab.icon}
                </span>
                <span className="text-xs font-semibold">{tab.label}</span>
              </div>
              {tab.count !== undefined && (
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${isActive ? 'bg-primary/20 text-primary' : 'bg-border text-text-faint'
                  }`}>
                  {tab.count}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Action Buttons */}
      <div className="p-3 border-t border-border space-y-1.5">
        <button
          onClick={() => launchPlan()}
          disabled={isLaunching}
          className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-xs font-semibold bg-emerald-600 text-white hover:bg-emerald-700 transition-all disabled:opacity-50"
        >
          <span className="material-symbols-outlined text-[18px]">
            {isLaunching ? 'progress_activity' : 'rocket_launch'}
          </span>
          {isLaunching ? 'Launching...' : 'Launch Plan'}
        </button>
        <button
          onClick={() => savePlan()}
          disabled={isSaving}
          className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-xs font-semibold bg-primary/10 text-primary hover:bg-primary/20 transition-all disabled:opacity-50"
        >
          <span className="material-symbols-outlined text-[18px]">
            {isSaving ? 'progress_activity' : 'save'}
          </span>
          {isSaving ? 'Saving...' : 'Save Plan'}
        </button>
        <button
          onClick={() => setShowDeleteConfirm(true)}
          className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-xs font-semibold text-red-600 hover:bg-red-500/10 transition-all"
        >
          <span className="material-symbols-outlined text-[18px]">delete</span>
          Delete Plan
        </button>
      </div>

      <ConfirmDialog
        isOpen={showDeleteConfirm}
        onClose={() => setShowDeleteConfirm(false)}
        onConfirm={async () => {
          setIsDeleting(true);
          try {
            await deletePlan();
            router.push('/plans');
          } finally {
            setIsDeleting(false);
            setShowDeleteConfirm(false);
          }
        }}
        title="Delete Plan"
        message={`Are you sure you want to delete "${plan.title}"? This will permanently remove all plan files, war-rooms, and related data.`}
        isLoading={isDeleting}
      />

      {/* Footer Info */}
      <div className="p-4 bg-surface-alt border-t border-border">
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between text-[10px] text-text-faint uppercase tracking-tighter">
            <span>Created</span>
            <span className="font-bold text-text-muted">
              {new Date(plan.created_at || 0).toLocaleDateString()}
            </span>
          </div>
          <div className="flex items-center justify-between text-[10px] text-text-faint uppercase tracking-tighter">
            <span>Domain</span>
            <span className="font-bold text-text-muted capitalize">
              {plan.domain ?? 'custom'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
