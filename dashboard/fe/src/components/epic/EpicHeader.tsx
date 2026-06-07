'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Plan, Epic, EpicStatus } from '@/types';
import AdvanceStateDialog from './AdvanceStateDialog';
import { useEpic } from '@/hooks/use-epics';
import { Badge } from '../ui/Badge';

interface EpicHeaderProps {
  plan: Plan | undefined;
  epic: Epic;
}

const lifecycleStates = [
  'pending',
  'developing',
  'review',
  'optimize',
  'triage',
  'done',
];

export default function EpicHeader({ plan, epic }: EpicHeaderProps) {
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const { updateState } = useEpic(epic.plan_id, epic.epic_ref);
  const currentState = normalizeLifecycleState(epic.lifecycle_state || 'pending');

  const currentStateIndex = lifecycleStates.indexOf(currentState);
  const targetState = currentStateIndex < lifecycleStates.length - 1
    ? lifecycleStates[currentStateIndex + 1]
    : currentState;

  const handleAdvanceState = async () => {
    try {
      // For mock purposes, status is same as lifecycle state
      await updateState(targetState, targetState as EpicStatus);
      setIsDialogOpen(false);
    } catch (err) {
      console.error('Failed to advance state:', err);
    }
  };

  return (
    <header className="sticky top-0 z-50 flex items-center justify-between border-b border-border bg-surface px-6 py-3 shrink-0 shadow-sm">
      <div className="flex items-center gap-4">
        <div className="flex flex-col">
          {/* Breadcrumb Navigation */}
          <nav className="flex items-center gap-1 text-[11px] mb-0.5" aria-label="Breadcrumb">
            <Link
              href={`/plans/${epic.plan_id}`}
              className="text-text-muted hover:text-primary transition-colors"
            >
              {plan?.title || 'Plan'}
            </Link>
            <span className="text-border material-symbols-outlined text-[10px]" aria-hidden="true">chevron_right</span>
            <span className="text-text-muted">{epic.epic_ref}</span>
          </nav>

          {/* Epic Title and Status Badge */}
          <h1 className="text-lg font-bold text-text-main flex items-center gap-2">
            {epic.epic_ref} — {epic.title}
            <Badge
              variant={getBadgeVariant(currentState)}
              aria-label={`Status: ${currentState}`}
              className="gap-1.5"
            >
              <span className={`w-1.5 h-1.5 rounded-full ${getDotClass(currentState)}`} aria-hidden="true" />
              {currentState.toUpperCase().replace('-', ' ')}
            </Badge>
          </h1>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setIsDialogOpen(true)}
          disabled={currentState === 'done' || currentState === 'failed'}
          className={`px-3 py-1.5 bg-primary text-white text-xs font-semibold rounded hover:bg-primary-hover transition-colors flex items-center gap-1.5 shadow-sm disabled:opacity-50 disabled:cursor-not-allowed`}
          aria-label="Advance epic to next state"
        >
          <span className="material-symbols-outlined text-sm" aria-hidden="true">play_arrow</span> Advance State
        </button>
        <button
          onClick={() => console.log('Retry click')}
          className="px-3 py-1.5 bg-surface border border-border text-text-main text-xs font-semibold rounded hover:bg-surface-hover transition-colors flex items-center gap-1.5"
          aria-label="Retry current operation"
        >
          <span className="material-symbols-outlined text-sm" aria-hidden="true">refresh</span> Retry
        </button>
        <button
          onClick={() => console.log('Escalate click')}
          className="px-3 py-1.5 bg-surface border border-border text-text-main text-xs font-semibold rounded hover:bg-surface-hover transition-colors flex items-center gap-1.5"
          aria-label="Escalate epic for review"
        >
          <span className="material-symbols-outlined text-sm" aria-hidden="true">priority_high</span> Escalate
        </button>
        <div className="h-6 w-px bg-border mx-1" aria-hidden="true"></div>
        <button
          onClick={() => console.log('Edit click')}
          className="p-1.5 text-text-muted hover:text-text-main hover:bg-surface-hover rounded transition-colors"
          aria-label="Edit epic details"
        >
          <span className="material-symbols-outlined text-xl" aria-hidden="true">edit</span>
        </button>
      </div>

      <AdvanceStateDialog
        isOpen={isDialogOpen}
        onClose={() => setIsDialogOpen(false)}
        onConfirm={handleAdvanceState}
        currentState={currentState}
        targetState={targetState}
        definitionOfDone={epic.definition_of_done || []}
      />
    </header>
  );
}

function getBadgeVariant(status: string): "primary" | "secondary" | "outline" | "success" | "warning" | "danger" | "muted" {
  switch (status) {
    case 'developing':
    case 'engineering':
      return 'primary';
    case 'review':
      return 'secondary';
    case 'done':
    case 'signoff':
      return 'success';
    case 'failed':
      return 'danger';
    case 'optimize':
      return 'warning';
    case 'triage':
      return 'danger';
    case 'pending':
    default:
      return 'warning';
  }
}

function getDotClass(status: string) {
  switch (status) {
    case 'developing':
    case 'engineering':
    case 'review':
    case 'optimize':
    case 'triage':
    case 'pending':
      return 'bg-current animate-pulse';
    default:
      return 'bg-current';
  }
}

function normalizeLifecycleState(status: string) {
  switch (status) {
    case 'engineering':
      return 'developing';
    case 'fixing':
      return 'optimize';
    case 'manager-triage':
      return 'triage';
    case 'passed':
    case 'signoff':
      return 'done';
    case 'failed-final':
      return 'failed';
    default:
      return status;
  }
}
