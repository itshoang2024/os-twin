'use client';

import { useMemo } from 'react';
import { usePlanContext } from './PlanWorkspace';
import TokenBudgetChart from './TokenBudgetChart';

interface AnalyticsPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function AnalyticsPanel({ isOpen, onClose }: AnalyticsPanelProps) {
  const { epics } = usePlanContext();

  const stats = useMemo(() => {
    if (!epics) return null;

    const breakdown = {
      pending: 0,
      in_progress: 0,
      review: 0,
      done: 0,
      failed: 0,
    };

    epics.forEach((epic) => {
      const status = epic.status === 'passed' || epic.status === 'signoff'
        ? 'done'
        : epic.status === 'failed-final'
          ? 'failed'
          : epic.status === 'fixing'
            ? 'optimize'
            : epic.status;
      if (status === 'pending') {
        breakdown.pending++;
      } else if (status === 'engineering' || status === 'developing' || status === 'optimize') {
        breakdown.in_progress++;
      } else if (status === 'review' || status === 'manager-triage' || status === 'triage') {
        breakdown.review++;
      } else if (status === 'done') {
        breakdown.done++;
      } else if (status === 'failed') {
        breakdown.failed++;
      }
    });

    return {
      breakdown,
      total: epics.length,
    };
  }, [epics]);

  if (!isOpen) return null;

  const { breakdown, total } = stats || { breakdown: {}, total: 0 };

  const getPercentage = (count: number) => (total > 0 ? (count / total) * 100 : 0);

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-background/50 backdrop-blur-sm z-10 animate-fade-in"
        onClick={onClose}
      />

      {/* Panel */}
      <div
        className="fixed bottom-[56px] left-0 right-0 bg-surface border-t border-border shadow-2xl z-20 overflow-hidden animate-slide-up origin-bottom"
        style={{ maxHeight: '480px' }}
      >
        <div className="max-w-[1200px] mx-auto p-6 flex flex-col h-full max-h-[480px]">
          {/* Header */}
          <div className="flex items-center justify-between mb-6">
            <h3 className="text-lg font-bold text-text-main flex items-center gap-2">
              <span className="material-symbols-outlined text-primary">analytics</span>
              Plan Analytics
            </h3>
            <button
              onClick={onClose}
              className="text-text-muted hover:text-text-main transition-colors"
            >
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>

          <div className="flex gap-8 flex-1 min-h-0 overflow-hidden">
            {/* Left Column: Status Breakdown */}
            <div className="flex-1 space-y-6 overflow-y-auto pr-4 custom-scrollbar">
              <div>
                <h4 className="text-xs font-bold uppercase tracking-widest text-text-muted mb-4">Epic Status Breakdown</h4>
                <div className="h-4 w-full flex rounded-full overflow-hidden mb-6 bg-surface-hover shadow-inner">
                  <div className="h-full bg-border transition-all duration-500" style={{ width: `${getPercentage(breakdown.pending || 0)}%` }} />
                  <div className="h-full bg-primary transition-all duration-500" style={{ width: `${getPercentage(breakdown.in_progress || 0)}%` }} />
                  <div className="h-full bg-warning transition-all duration-500" style={{ width: `${getPercentage(breakdown.review || 0)}%` }} />
                  <div className="h-full bg-success transition-all duration-500" style={{ width: `${getPercentage(breakdown.done || 0)}%` }} />
                  <div className="h-full bg-danger transition-all duration-500" style={{ width: `${getPercentage(breakdown.failed || 0)}%` }} />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  {[
                    { label: 'Pending', count: breakdown.pending, color: 'bg-border' },
                    { label: 'In Flight', count: breakdown.in_progress, color: 'bg-primary' },
                    { label: 'Review', count: breakdown.review, color: 'bg-warning' },
                    { label: 'Done', count: breakdown.done, color: 'bg-success' },
                  ].map((item) => (
                    <div key={item.label} className="flex items-center justify-between p-3 bg-background border border-border rounded-lg shadow-sm">
                      <div className="flex items-center gap-2">
                        <div className={`w-2 h-2 rounded-full ${item.color}`} />
                        <span className="text-sm font-medium text-text-main">{item.label}</span>
                      </div>
                      <span className="text-sm font-bold text-text-main">{item.count}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Right Column: Token Budgets */}
            <div className="flex-1 border-l border-border pl-8 flex flex-col min-h-0">
              <h4 className="text-xs font-bold uppercase tracking-widest text-text-muted mb-4">Token Budget Utilization</h4>
              <div className="flex-1 overflow-y-auto pr-4 custom-scrollbar space-y-2">
                {epics && epics.length > 0 ? (
                  epics.map((epic) => (
                    <TokenBudgetChart key={epic.epic_ref} epic={epic} />
                  ))
                ) : (
                  <div className="text-center py-8 text-text-muted italic text-sm">
                    No EPICs available for budget tracking
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
