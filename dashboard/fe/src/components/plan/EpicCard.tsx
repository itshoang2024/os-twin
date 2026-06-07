'use client';

import React, { useState, useCallback } from 'react';
import { Epic } from '@/types';
import { usePlanContext } from './PlanWorkspace';
import { useDraggable } from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import { getRoleColor, getRoleInitials } from '@/lib/role-utils';

export const stateColors: Record<string, string> = {
  // V2 lifecycle states (from Resolve-Pipeline.ps1)
  pending: '#94a3b8',
  developing: '#3b82f6',
  'in-review': '#8b5cf6',
  review: '#a855f7',          // final QA gate — distinct purple
  optimize: '#f59e0b',
  triage: '#ef4444',
  done: '#10b981',
  failed: '#ef4444',
  passed: '#10b981',
  'failed-final': '#ef4444',
  // Legacy aliases for backward compat
  engineering: '#3b82f6',
  fixing: '#f59e0b',
  'manager-triage': '#ef4444',
  signoff: '#10b981',
  'wave-0': '#64748b',
  'wave-1': '#3b82f6',
  'wave-2': '#10b981',
  'wave-3': '#f59e0b',
  'wave-4': '#8b5cf6',
  'wave-5': '#ec4899',
  'wave-6': '#ef4444',
  'wave-7': '#06b6d4',
  'wave-8': '#14b8a6',
};

const warRoomStatusIcons: Record<string, { icon: string; color: string; label: string }> = {
  // V2 lifecycle states
  pending: { icon: 'schedule', color: '#94a3b8', label: 'Pending' },
  developing: { icon: 'code', color: '#3b82f6', label: 'Developing' },
  'in-review': { icon: 'rate_review', color: '#8b5cf6', label: 'In Review' },
  review: { icon: 'verified', color: '#a855f7', label: 'QA Gate' },
  optimize: { icon: 'build', color: '#f59e0b', label: 'Optimizing' },
  triage: { icon: 'warning', color: '#ef4444', label: 'Triage' },
  done: { icon: 'check_circle', color: '#10b981', label: 'Done' },
  failed: { icon: 'cancel', color: '#ef4444', label: 'Failed' },
  passed: { icon: 'check_circle', color: '#10b981', label: 'Done' },
  'failed-final': { icon: 'cancel', color: '#ef4444', label: 'Failed' },
  // Progress-based statuses
  active: { icon: 'play_circle', color: '#3b82f6', label: 'Active' },
  blocked: { icon: 'block', color: '#f59e0b', label: 'Blocked' },
};

interface EpicCardProps {
  epic: Epic;
  onCriticalPath?: boolean;
  warRoomStatus?: string;
}

function normalizeLifecycleStatus(status = 'pending') {
  if (status === 'passed') return 'done';
  if (status === 'failed-final') return 'failed';
  if (status === 'fixing') return 'optimize';
  if (status === 'signoff') return 'done';
  return status;
}

export default function EpicCard({ epic, onCriticalPath, warRoomStatus }: EpicCardProps) {
  const { selectedEpicRef, setSelectedEpicRef, setIsContextPanelOpen, uploadAssets, setIsEditingEpic } = usePlanContext();
  const [isHoveringFile, setIsHoveringFile] = useState(false);

  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: epic.epic_ref,
  });

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.types.includes('Files')) {
      setIsHoveringFile(true);
    }
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsHoveringFile(false);
  }, []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    setIsHoveringFile(false);
    if (e.dataTransfer.files.length > 0) {
      try {
        await uploadAssets(e.dataTransfer.files, epic.epic_ref);
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : 'Unknown error';
        alert(`Upload failed: ${message}`);
      }
    }
  }, [uploadAssets, epic.epic_ref]);

  const style = transform ? {
    transform: CSS.Translate.toString(transform),
    opacity: isDragging ? 0.3 : undefined,
    zIndex: isDragging ? 100 : undefined,
  } : undefined;

  const isSelected = selectedEpicRef === epic.epic_ref;

  // Determine state color, prioritizing the current room status if available
  const lifecycleState = normalizeLifecycleStatus(epic.lifecycle_state || 'pending');
  const activeState = normalizeLifecycleStatus(warRoomStatus || lifecycleState);
  const stateColor = stateColors[activeState] ||
    (activeState.startsWith('wave-') ? stateColors[activeState] : stateColors.pending) ||
    stateColors.pending;

  const roleColor = getRoleColor(epic.role || '');
  const wrStatus = warRoomStatus ? warRoomStatusIcons[activeState] : null;

  const handleClick = () => {
    setSelectedEpicRef(epic.epic_ref);
    setIsContextPanelOpen(true);
  };

  const handleEditClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedEpicRef(epic.epic_ref);
    setIsContextPanelOpen(true);
    setIsEditingEpic(true);
  };

  const completedTasks = (epic.tasks || []).filter(t => t.completed).length;
  const totalTasks = (epic.tasks || []).length;
  const progressPercent = totalTasks > 0 ? (completedTasks / totalTasks) * 100 : 0;

  return (
    <div
      ref={setNodeRef}
      onClick={handleClick}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={`group relative p-3 rounded-lg border bg-surface transition-all duration-200 cursor-pointer shadow-sm hover:shadow-md hover:-translate-y-0.5 ${isSelected ? 'border-primary ring-1 ring-primary/20 shadow-md' : 'border-border hover:border-text-faint'
        } ${isHoveringFile ? 'ring-2 ring-primary bg-primary/5 scale-[1.02] shadow-lg z-10' : ''}`}
      style={{ ...style, borderLeftWidth: '3px', borderLeftColor: stateColor }}
      role="button"
      aria-pressed={isSelected}
      aria-label={`Epic ${epic.epic_ref}: ${epic.title}`}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          handleClick();
        }
      }}
    >
      {isHoveringFile && (
        <div className="absolute inset-0 bg-primary/10 flex flex-col items-center justify-center rounded-lg backdrop-blur-[1px] z-[30] border-2 border-primary border-dashed">
          <span className="material-symbols-outlined text-primary text-3xl animate-bounce">upload</span>
          <span className="text-[10px] font-bold text-primary uppercase tracking-wider">Drop to Bind Asset</span>
        </div>
      )}
      {/* Drag Handle */}
      <div
        {...attributes}
        {...listeners}
        className="absolute -left-1 top-1/2 -translate-y-1/2 w-4 h-8 flex items-center justify-center opacity-0 group-hover:opacity-100 cursor-grab active:cursor-grabbing transition-opacity z-20"
        aria-label="Drag to reorder epic"
        role="button"
      >
        <span className="material-symbols-outlined text-xs text-text-faint" aria-hidden="true">drag_indicator</span>
      </div>

      {/* Critical Path Badge */}
      {onCriticalPath && (
        <div className="absolute -top-1.5 -right-1.5 z-10">
          <div className="flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/30 shadow-sm" title="On Critical Path">
            <span className="material-symbols-outlined text-[10px] text-amber-500">local_fire_department</span>
            <span className="text-[7px] font-extrabold text-amber-600 uppercase tracking-wider">Critical</span>
          </div>
        </div>
      )}

      {/* Ref & State Badge */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <span className="text-[9px] font-bold text-text-faint tracking-wider uppercase">
            {epic.epic_ref}
          </span>
          {/* War Room Status indicator */}
          {wrStatus && (
            <span
              className="material-symbols-outlined text-[12px]"
              style={{ color: wrStatus.color }}
              title={`Room: ${wrStatus.label}`}
            >
              {wrStatus.icon}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {/* Edit button (visible on hover) */}
          <button
            onClick={handleEditClick}
            className="opacity-0 group-hover:opacity-100 p-0.5 hover:bg-primary/10 rounded text-text-faint hover:text-primary transition-all"
            title="Edit EPIC"
          >
            <span className="material-symbols-outlined text-[14px]">edit</span>
          </button>
          <div
            className="flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-bold uppercase"
            style={{ background: `${stateColor}15`, color: stateColor }}
          >
            <span className={`w-1 h-1 rounded-full ${!['done', 'failed'].includes(lifecycleState) ? 'animate-pulse' : ''}`} style={{ background: stateColor }} />
            {lifecycleState.replace('-', ' ')}
          </div>
        </div>
      </div>

      {/* Title */}
      <h4 className="text-[12px] font-bold text-text-main line-clamp-2 leading-tight mb-3 group-hover:text-primary transition-colors h-8">
        {epic.title}
      </h4>

      {/* Progress Bar */}
      <div className="space-y-1 mb-3">
        <div className="flex justify-between text-[9px] font-bold text-text-faint uppercase">
          <span>Progress</span>
          <span>{Math.round(progressPercent)}%</span>
        </div>
        <div className="h-1 w-full bg-border/50 rounded-full overflow-hidden">
          <div
            className={`h-full transition-all duration-500 ${progressPercent === 100 ? 'bg-success' : 'bg-primary'}`}
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </div>

      {/* Footer: Role, Room & Tasks */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 min-w-0">
          <div
            className="w-5 h-5 rounded-full flex items-center justify-center text-[8px] font-bold text-white shadow-inner shrink-0"
            style={{ background: roleColor }}
            title={epic.role || 'Unassigned'}
          >
            {getRoleInitials(epic.role || '??')}
          </div>
          <span className="text-[10px] font-medium text-text-muted truncate">{epic.role || 'Unassigned'}</span>
        </div>

        <div className="flex items-center gap-2 ml-2 shrink-0">
          {/* Room ID */}
          {epic.room_id && (
            <span className="text-[9px] font-mono text-text-faint bg-surface-hover px-1 py-0.5 rounded" title={`War Room: ${epic.room_id}`}>
              #{epic.room_id}
            </span>
          )}
          {/* Task Count indicator */}
          <div className="flex items-center gap-0.5 text-text-faint">
            <span className="material-symbols-outlined text-[12px]">checklist</span>
            <span className="text-[10px] font-bold">{completedTasks}/{totalTasks}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
