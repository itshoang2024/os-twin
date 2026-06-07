'use client';


import { useAuditLog } from '@/hooks/use-war-room';
import { AuditLogEntry } from '@/types';

interface AuditTimelineProps {
  planId: string;
  epicRef: string;
}

const stateColorMap: Record<string, string> = {
  pending: '#94a3b8',
  developing: '#3b82f6',
  engineering: '#3b82f6',
  'architect-review': '#8b5cf6',
  'review': '#8b5cf6',
  optimize: '#f59e0b',
  fixing: '#f59e0b',
  triage: '#ef4444',
  'manager-triage': '#ef4444',
  done: '#10b981',
  passed: '#10b981',
  signoff: '#10b981',
  failed: '#ef4444',
  'failed-final': '#ef4444',
  'plan-revision': '#f59e0b',
};

export default function AuditTimeline({ planId, epicRef }: AuditTimelineProps) {
  const { auditLog, isLoading, isError } = useAuditLog(planId, epicRef);

  if (isLoading) {
    return (
      <div className="p-4 animate-pulse space-y-4">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="flex gap-3">
            <div className="w-2 h-2 rounded-full bg-border/30 mt-1" />
            <div className="flex-1 space-y-1">
              <div className="h-3 w-24 bg-border/20 rounded" />
              <div className="h-3 w-40 bg-border/20 rounded" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (isError || !auditLog || auditLog.length === 0) {
    return (
      <div className="p-4 text-center text-text-faint">
        <span className="material-symbols-outlined text-2xl mb-2 block">history</span>
        <p className="text-xs">No audit history available.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border bg-surface-hover/30 flex items-center justify-between shrink-0">
        <h3 className="text-[10px] font-bold text-text-muted uppercase tracking-widest flex items-center gap-2">
          <span className="material-symbols-outlined text-sm">history</span>
          Audit History
        </h3>
        <span className="text-[10px] font-mono text-text-faint bg-surface-hover px-1.5 py-0.5 rounded">
          {auditLog.length} transitions
        </span>
      </div>

      {/* Timeline */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-4">
        <div className="relative">
          {/* Vertical line */}
          <div className="absolute left-[7px] top-2 bottom-2 w-0.5 bg-border" />

          <div className="space-y-4">
            {auditLog.map((entry: AuditLogEntry, idx: number) => {
              const toColor = stateColorMap[entry.to_state] || '#94a3b8';
              const fromColor = stateColorMap[entry.from_state] || '#94a3b8';
              const isLatest = idx === auditLog.length - 1;

              return (
                <div key={idx} className={`flex gap-3 relative ${isLatest ? '' : ''}`}>
                  {/* Timeline dot */}
                  <div
                    className={`w-4 h-4 rounded-full border-2 shrink-0 z-10 ${isLatest ? 'ring-2 ring-offset-1' : ''
                      }`}
                    style={{
                      borderColor: toColor,
                      backgroundColor: isLatest ? toColor : 'var(--color-surface)',
                    }}
                  />

                  {/* Content */}
                  <div className="flex-1 min-w-0 -mt-0.5">
                    {/* Timestamp */}
                    <div className="text-[9px] font-mono text-text-faint mb-0.5">
                      {new Date(entry.timestamp).toLocaleString([], {
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                      })}
                    </div>

                    {/* Transition */}
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-[9px] font-bold uppercase tracking-wider">{entry.type}</span>
                      <span
                        className="text-[10px] font-bold px-1.5 py-0.5 rounded-full"
                        style={{ background: `${fromColor}15`, color: fromColor }}
                      >
                        {entry.from_state}
                      </span>
                      <span className="material-symbols-outlined text-[12px] text-text-faint">arrow_forward</span>
                      <span
                        className="text-[10px] font-bold px-1.5 py-0.5 rounded-full"
                        style={{ background: `${toColor}15`, color: toColor }}
                      >
                        {entry.to_state}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
