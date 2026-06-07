'use client';

import React, { useState } from 'react';
import { EpicStatus } from '@/types';
import { usePlanContext } from './PlanWorkspace';
import { stateColors } from './EpicCard';

interface StateNodeProps {
  id: string;
  label: string;
  status: EpicStatus;
  x: number;
  y: number;
  role?: string;
  roleInitial?: string;
  roleColor?: string;
  mode?: 'live' | 'authoring';
  isDragging?: boolean;
  dragSourceRef?: string;
  onStartDrag?: (nodeId: string, x: number, y: number) => void;
  onEnterPort?: (nodeId: string, type: 'input' | 'output') => void;
  onLeavePort?: () => void;
  onClick?: (id: string) => void;
  onDoubleClick?: (id: string, targetTab?: 'overview' | 'dod' | 'ac' | 'tasks' | 'deps') => void;
  onContextMenu?: (e: React.MouseEvent, id: string) => void;
  // EPIC-003: Rich metadata props
  tasksDone?: number;
  tasksTotal?: number;
  dodDone?: number;
  dodTotal?: number;
  hasAC?: boolean;
  description?: string;
}

const statusLabels: Record<string, string> = {
  done: 'DONE',
  passed: 'DONE',
  failed: 'FAILED',
  'failed-final': 'FAILED',
  engineering: 'ENGINEERING',
  pending: 'PENDING',
  active: 'ACTIVE',
  blocked: 'BLOCKED',
  'review': 'QA REVIEW',
  optimize: 'OPTIMIZE',
  fixing: 'OPTIMIZE',
  'manager-triage': 'TRIAGE',
  signoff: 'DONE',
};

function normalizeStatus(status: string) {
  if (status === 'passed' || status === 'signoff') return 'done';
  if (status === 'failed-final') return 'failed';
  if (status === 'fixing') return 'optimize';
  return status;
}

export default function StateNode({
  id, label, status, x, y, role, roleInitial, roleColor, mode,
  isDragging, dragSourceRef,
  onStartDrag, onEnterPort, onLeavePort, onClick, onDoubleClick, onContextMenu,
  tasksDone = 0, tasksTotal = 0, dodDone = 0, dodTotal = 0,
  hasAC = true, description = '',
}: StateNodeProps) {
  const { selectedEpicRef, setSelectedEpicRef, setIsContextPanelOpen } = usePlanContext();
  const isSelected = selectedEpicRef === id;
  const isSource = dragSourceRef === id;
  const canonicalStatus = normalizeStatus(status);
  const stateColor = stateColors[canonicalStatus] || stateColors.pending;
  const statusLabel = statusLabels[canonicalStatus] || canonicalStatus.replace(/-/g, ' ').toUpperCase();

  // Tooltip state
  const [showTooltip, setShowTooltip] = useState(false);

  // Progress calculation
  const tasksPct = tasksTotal > 0 ? Math.round((tasksDone / tasksTotal) * 100) : 0;
  const dodPct = dodTotal > 0 ? Math.round((dodDone / dodTotal) * 100) : 0;
  const hasStats = tasksTotal > 0 || dodTotal > 0;

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (onClick) {
      onClick(id);
    } else {
      setSelectedEpicRef(id);
      setIsContextPanelOpen(true);
    }
  };

  const handleDoubleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (onDoubleClick) {
      onDoubleClick(id);
    }
  };

  const handlePortMouseDown = (e: React.MouseEvent) => {
    e.stopPropagation();
    onStartDrag?.(id, e.clientX, e.clientY);
  };

  const handleMouseEnter = (type: 'input' | 'output') => {
    onEnterPort?.(id, type);
  };

  const handleContextMenuInternal = (e: React.MouseEvent) => {
    if (onContextMenu) {
      onContextMenu(e, id);
    }
  };

  // Tooltip handlers — show on hover over the main card area
  const handleCardMouseEnter = () => {
    setShowTooltip(true);
  };

  const handleCardMouseLeave = () => {
    setShowTooltip(false);
  };

  // Determine progress bar color based on completion
  const getProgressColor = (pct: number) => {
    if (pct >= 100) return '#10b981'; // emerald
    if (pct >= 50) return '#3b82f6';  // blue
    if (pct > 0) return '#f59e0b';    // amber
    return '#e2e8f0';                  // slate-200
  };

  return (
    <g style={{ transform: `translate(${x}px, ${y}px)`, transition: 'transform 300ms ease-out' }}>
    <foreignObject x={0} y={0} width="200" height="95" className="overflow-visible">
      <div
        onClick={handleClick}
        onDoubleClick={handleDoubleClick}
        onContextMenu={handleContextMenuInternal}
        onMouseEnter={handleCardMouseEnter}
        onMouseLeave={handleCardMouseLeave}
        className={`flex flex-col p-2 rounded-lg border bg-surface transition-all duration-200 cursor-pointer shadow-sm hover:shadow-md group relative ${isSelected ? 'border-primary ring-2 ring-primary/20 scale-105' : 'border-border'
          }`}
        style={{ borderLeftWidth: '4px', borderLeftColor: stateColor, minHeight: '95px' }}
      >
        {/* Ports */}
        {mode === 'authoring' && (
          <>
            {/* Input port (Left) - dependency target */}
            <div
              className={`absolute left-[-8px] top-1/2 -translate-y-1/2 w-4 h-4 rounded-full border-2 transition-all cursor-crosshair z-20 ${
                isDragging && !isSource
                  ? 'border-emerald-400 bg-emerald-100 scale-150 shadow-[0_0_8px_rgba(16,185,129,0.6)] animate-pulse opacity-100'
                  : 'border-indigo-400 bg-white/90 hover:scale-125 hover:border-indigo-600 opacity-60 hover:opacity-100'
              }`}
              data-port="input"
              data-node-id={id}
              title="Drag here to add dependency"
              onMouseEnter={() => handleMouseEnter('input')}
              onMouseLeave={onLeavePort}
            />
            {/* Output port (Right) - dependency source */}
            <div
              className="absolute right-[-8px] top-1/2 -translate-y-1/2 w-4 h-4 rounded-full border-2 border-indigo-400 bg-white/90 transition-all cursor-crosshair z-20 opacity-60 hover:opacity-100 hover:scale-125 hover:border-indigo-600"
              data-port="output"
              data-node-id={id}
              title="Drag to create dependency"
              onMouseDown={handlePortMouseDown}
              onMouseEnter={() => handleMouseEnter('output')}
              onMouseLeave={onLeavePort}
            />
          </>
        )}

        {/* Header: ID + Status + Warning Badge */}
        <div className="flex items-center justify-between mb-1">
          <span className="text-[8px] font-bold text-text-faint uppercase tracking-wider">
            {id}
          </span>
          <div className="flex items-center gap-1">
            {/* Warning badge for EPICs with no AC */}
            {!hasAC && (
              <div
                className="flex items-center px-1 py-0.5 rounded-full text-[7px] font-bold bg-amber-500/10 text-amber-600 border border-amber-500/20"
                title="No Acceptance Criteria defined"
              >
                <span className="material-symbols-outlined text-[9px] mr-0.5">warning</span>
                No AC
              </div>
            )}
            <div
              className="flex items-center gap-1 px-1 py-0.5 rounded-full text-[7px] font-bold uppercase"
              style={{ background: `${stateColor}15`, color: stateColor }}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${!['done', 'failed'].includes(canonicalStatus) ? 'animate-pulse' : ''}`}
                style={{ background: stateColor }}
              />
              {statusLabel}
            </div>
          </div>
        </div>

        {/* Label */}
        <h4 className="text-[11px] font-bold text-text-main line-clamp-1 leading-tight">
          {label}
        </h4>

        {/* Progress section: Task + DoD bars */}
        {hasStats && (
          <div className="mt-1 space-y-0.5">
            {/* Tasks progress */}
            {tasksTotal > 0 && (
              <div className="flex items-center gap-1.5">
                <span className="text-[7px] font-semibold text-text-muted w-[38px] shrink-0">
                  {tasksDone}/{tasksTotal} tasks
                </span>
                <div className="flex-1 h-1.5 bg-surface-alt rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${tasksPct}%`,
                      background: getProgressColor(tasksPct),
                    }}
                  />
                </div>
              </div>
            )}
            {/* DoD progress */}
            {dodTotal > 0 && (
              <div className="flex items-center gap-1.5">
                <span className="text-[7px] font-semibold text-text-muted w-[38px] shrink-0">
                  {dodDone}/{dodTotal} DoD
                </span>
                <div className="flex-1 h-1.5 bg-surface-alt rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${dodPct}%`,
                      background: getProgressColor(dodPct),
                    }}
                  />
                </div>
              </div>
            )}
          </div>
        )}

        {/* Footer: Role Badge + Click hint */}
        <div className="flex items-center justify-between mt-1">
          {roleInitial ? (
            <div className="flex items-center gap-1.5">
              <div
                className="w-4 h-4 rounded-full flex items-center justify-center text-[7px] font-extrabold text-white shadow-sm"
                style={{ background: roleColor || '#6366f1' }}
                title={role || 'Unknown Role'}
              >
                {roleInitial}
              </div>
              <span className="text-[8px] font-medium text-text-muted truncate max-w-[80px]">
                {role || 'unknown'}
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-1 text-[8px] font-medium text-text-muted">
              <span className="material-symbols-outlined text-[10px]">ads_click</span>
              Click to View
            </div>
          )}
          <span className="material-symbols-outlined text-[10px] text-text-faint opacity-0 group-hover:opacity-100 transition-opacity">
            open_in_new
          </span>
        </div>
      </div>
    </foreignObject>

    {/* Hover tooltip — EPIC title + description preview */}
    {showTooltip && (description || label !== id) && (
      <foreignObject
        x={-50}
        y={-70}
        width="300"
        height="60"
        className="pointer-events-none overflow-visible"
      >
        <div
          className="bg-surface border border-border rounded-lg shadow-lg px-3 py-2 text-[10px] leading-snug"
          style={{ maxWidth: '280px' }}
        >
          <div className="font-bold text-text-main mb-0.5 line-clamp-1">
            {label !== id ? label : id}
          </div>
          {description && (
            <div className="text-text-muted line-clamp-2">
              {description}
            </div>
          )}
        </div>
      </foreignObject>
    )}
    </g>
  );
}
