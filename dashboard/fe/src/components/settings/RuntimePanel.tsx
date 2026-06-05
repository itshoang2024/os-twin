'use client';

import { useMemo, useState } from 'react';
import { ProvenanceChip } from './ProvenanceChip';
import { ModelSelect } from './ModelSelect';
import type { RuntimeSettings, ModelInfo } from '@/types/settings';

export interface RuntimePanelProps {
  runtime: RuntimeSettings;
  provenance?: Record<string, string>;
  onUpdate: (value: Partial<RuntimeSettings>) => void;
  allModels?: ModelInfo[];
}

const RUNTIME_DEFAULTS: RuntimeSettings = {
  poll_interval_seconds: 5,
  max_concurrent_rooms: 10,
  max_engineer_retries: 3,
  state_timeout_seconds: 900,
  auto_approve_tools: false,
  dynamic_pipelines: true,
  master_agent_model: '',
};

type NumericRuntimeField =
  | 'poll_interval_seconds'
  | 'max_concurrent_rooms'
  | 'max_engineer_retries'
  | 'state_timeout_seconds';

type RuntimeDraft = Pick<RuntimeSettings, NumericRuntimeField>;

function clamp(value: number, min: number, max: number) {
  if (Number.isNaN(value)) return min;
  return Math.min(max, Math.max(min, value));
}

function runtimeDraftFrom(runtime: RuntimeSettings): RuntimeDraft {
  return {
    poll_interval_seconds: runtime.poll_interval_seconds,
    max_concurrent_rooms: runtime.max_concurrent_rooms,
    max_engineer_retries: runtime.max_engineer_retries,
    state_timeout_seconds: runtime.state_timeout_seconds,
  };
}

function runtimeDraftKey(draft: RuntimeDraft) {
  return [
    draft.poll_interval_seconds,
    draft.max_concurrent_rooms,
    draft.max_engineer_retries,
    draft.state_timeout_seconds,
  ].join(':');
}

function NumberSetting({
  label,
  description,
  value,
  min,
  max,
  unit,
  onChange,
  onCommit,
  provenance,
}: {
  label: string;
  description: string;
  value: number;
  min: number;
  max: number;
  unit: string;
  onChange: (value: number) => void;
  onCommit: (value: number) => void;
  provenance?: string;
}) {
  const commit = () => onCommit(clamp(value, min, max));

  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-background)] p-4">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="max-w-xl">
          <label className="text-xs font-bold uppercase text-[var(--color-text-muted)]" htmlFor={label}>
            {label}
          </label>
          <p className="mt-1 text-sm leading-6 text-[var(--color-text-muted)]">{description}</p>
          {provenance && <div className="mt-2"><ProvenanceChip source={provenance} /></div>}
        </div>
        <div className="flex items-center gap-2">
          <input
            id={label}
            type="number"
            min={min}
            max={max}
            value={value}
            onChange={(event) => onChange(clamp(Number.parseInt(event.target.value, 10), min, max))}
            onBlur={commit}
            onKeyDown={(event) => {
              if (event.key === 'Enter') commit();
            }}
            className="h-11 w-28 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-4 text-right text-sm font-black text-[var(--color-text-main)] outline-none transition focus:border-[var(--color-primary)] focus:ring-4 focus:ring-blue-500/10"
          />
          <span className="min-w-12 text-sm font-bold text-[var(--color-text-muted)]">{unit}</span>
        </div>
      </div>
    </div>
  );
}

function ToggleSetting({
  label,
  description,
  checked,
  onChange,
  provenance,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  provenance?: string;
}) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-background)] p-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase text-[var(--color-text-muted)]">{label}</p>
          <p className="mt-1 text-sm leading-6 text-[var(--color-text-muted)]">{description}</p>
          {provenance && <div className="mt-2"><ProvenanceChip source={provenance} /></div>}
        </div>
        <label className="shrink-0 cursor-pointer" aria-label={label}>
          <input
            type="checkbox"
            checked={checked}
            onChange={(event) => onChange(event.target.checked)}
            className="sr-only"
          />
          <span
            className="relative block h-6 w-11 rounded-full transition-colors"
            style={{ background: checked ? 'var(--color-primary)' : 'var(--color-border)' }}
          >
            <span
              className="absolute top-1 h-4 w-4 rounded-full bg-[var(--color-surface)] transition-transform"
              style={{ transform: checked ? 'translateX(23px)' : 'translateX(4px)' }}
            />
          </span>
        </label>
      </div>
    </div>
  );
}

export function RuntimePanel({ runtime, provenance = {}, onUpdate, allModels = [] }: RuntimePanelProps) {
  const effectiveRuntime = { ...RUNTIME_DEFAULTS, ...(runtime ?? {}) };
  const sourceDraft = runtimeDraftFrom(effectiveRuntime);
  const sourceDraftKey = runtimeDraftKey(sourceDraft);
  const [draftState, setDraftState] = useState(() => ({
    sourceKey: sourceDraftKey,
    value: sourceDraft,
  }));
  const draft = draftState.sourceKey === sourceDraftKey ? draftState.value : sourceDraft;
  const pollIntervalInput = draft.poll_interval_seconds;
  const maxRoomsInput = draft.max_concurrent_rooms;
  const maxRetriesInput = draft.max_engineer_retries;
  const stateTimeoutInput = draft.state_timeout_seconds;

  const chatModels = useMemo(
    () => allModels.filter((m) => !m.id.toLowerCase().includes('embed')),
    [allModels],
  );

  const setDraftField = (field: NumericRuntimeField, value: number) => {
    setDraftState({
      sourceKey: sourceDraftKey,
      value: {
        ...draft,
        [field]: value,
      },
    });
  };

  const commitNumber = (field: NumericRuntimeField, value: number, min: number, max: number) => {
    const clamped = clamp(value, min, max);
    setDraftField(field, clamped);
    onUpdate({ [field]: clamped } as Partial<RuntimeSettings>);
  };

  return (
    <div className="space-y-8">
      <section className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-[0_12px_36px_rgba(15,23,42,0.07)] md:p-6">
        <div className="flex flex-col gap-3 border-b border-[var(--color-border)] pb-5 md:flex-row md:items-start md:justify-between">
          <div>
            <p className="text-xs font-bold uppercase text-[var(--color-text-muted)]">Master agent model</p>
            <h3 className="mt-2 text-xl font-black text-[var(--color-text-main)]">Planning and orchestration brain</h3>
          </div>
          <span className="rounded-full bg-[var(--color-primary-muted)] px-3 py-1 text-xs font-bold uppercase text-[var(--color-primary)]">
            Global default
          </span>
        </div>
        <div className="mt-5">
          <ModelSelect
            value={effectiveRuntime.master_agent_model || ''}
            onChange={(model) => onUpdate({ master_agent_model: model })}
            models={chatModels}
            showTier={true}
            showContext={true}
            placeholder="- Use server default -"
          />
          {chatModels.length === 0 && (
            <p className="mt-3 text-sm font-semibold text-amber-700">
              No providers configured. Add one in Provider Config.
            </p>
          )}
          <p className="mt-3 text-xs text-[var(--color-text-muted)]">
            Effective model:{' '}
            <code className="rounded border border-[var(--color-border)] bg-[var(--color-background)] px-2 py-1 text-[11px] font-bold text-[var(--color-text-main)]">
              {effectiveRuntime.master_agent_model || '(server default)'}
            </code>
          </p>
        </div>
      </section>

      <section className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-[0_12px_36px_rgba(15,23,42,0.07)] md:p-6">
        <div className="flex flex-col gap-3 border-b border-[var(--color-border)] pb-5 md:flex-row md:items-start md:justify-between">
          <div>
            <p className="text-xs font-bold uppercase text-[var(--color-text-muted)]">Operational settings</p>
            <h3 className="mt-2 text-xl font-black text-[var(--color-text-main)]">Manager loop defaults</h3>
          </div>
          <span className="rounded-full border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-1 text-xs font-bold uppercase text-[var(--color-text-muted)]">
            New rooms only
          </span>
        </div>

        <div className="mt-5 space-y-4">
          <NumberSetting
            label="State Timeout"
            description="Seconds before an active developing, review, or triage state is restarted."
            value={stateTimeoutInput}
            min={1}
            max={86400}
            unit="seconds"
            onChange={(value) => setDraftField('state_timeout_seconds', value)}
            onCommit={(value) => commitNumber('state_timeout_seconds', value, 1, 86400)}
            provenance={provenance.state_timeout_seconds}
          />

          <NumberSetting
            label="Max War-Room Retries"
            description="Total retry attempts available to each new room lifecycle before failed-final."
            value={maxRetriesInput}
            min={0}
            max={100}
            unit="retries"
            onChange={(value) => setDraftField('max_engineer_retries', value)}
            onCommit={(value) => commitNumber('max_engineer_retries', value, 0, 100)}
            provenance={provenance.max_engineer_retries}
          />

          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-background)] p-4">
            <label className="text-xs font-bold uppercase text-[var(--color-text-muted)]">
              Poll Interval
            </label>
            <input
              type="range"
              min={1}
              max={300}
              value={pollIntervalInput}
              onChange={(event) => setDraftField('poll_interval_seconds', Number.parseInt(event.target.value, 10))}
              onMouseUp={(event) => commitNumber('poll_interval_seconds', Number.parseInt(event.currentTarget.value, 10), 1, 300)}
              onTouchEnd={(event) => commitNumber('poll_interval_seconds', Number.parseInt(event.currentTarget.value, 10), 1, 300)}
              className="mt-4 h-2 w-full cursor-pointer appearance-none rounded-full"
              style={{ background: 'color-mix(in oklch, var(--color-primary), var(--color-border) 82%)' }}
            />
            <div className="mt-2 flex justify-between text-xs font-bold text-[var(--color-text-muted)]">
              <span>1s</span>
              <span className="text-[var(--color-text-main)]">{pollIntervalInput}s</span>
              <span>300s</span>
            </div>
            {provenance.poll_interval_seconds && <div className="mt-2"><ProvenanceChip source={provenance.poll_interval_seconds} /></div>}
          </div>

          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-background)] p-4">
            <label className="text-xs font-bold uppercase text-[var(--color-text-muted)]">
              Max Concurrent Rooms
            </label>
            <input
              type="range"
              min={1}
              max={10000}
              value={maxRoomsInput}
              onChange={(event) => setDraftField('max_concurrent_rooms', Number.parseInt(event.target.value, 10))}
              onMouseUp={(event) => commitNumber('max_concurrent_rooms', Number.parseInt(event.currentTarget.value, 10), 1, 10000)}
              onTouchEnd={(event) => commitNumber('max_concurrent_rooms', Number.parseInt(event.currentTarget.value, 10), 1, 10000)}
              className="mt-4 h-2 w-full cursor-pointer appearance-none rounded-full"
              style={{ background: 'color-mix(in oklch, var(--color-primary), var(--color-border) 82%)' }}
            />
            <div className="mt-2 flex justify-between text-xs font-bold text-[var(--color-text-muted)]">
              <span>1</span>
              <span className="text-[var(--color-text-main)]">{maxRoomsInput}</span>
              <span>10000</span>
            </div>
            {provenance.max_concurrent_rooms && <div className="mt-2"><ProvenanceChip source={provenance.max_concurrent_rooms} /></div>}
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <ToggleSetting
              label="Auto Approve Tools"
              description="Allow trusted tool calls to proceed without an approval pause."
              checked={effectiveRuntime.auto_approve_tools}
              onChange={(value) => onUpdate({ auto_approve_tools: value })}
              provenance={provenance.auto_approve_tools}
            />
            <ToggleSetting
              label="Dynamic Pipelines"
              description="Let plan capability hints shape per-room lifecycle pipelines."
              checked={effectiveRuntime.dynamic_pipelines}
              onChange={(value) => onUpdate({ dynamic_pipelines: value })}
              provenance={provenance.dynamic_pipelines}
            />
          </div>
        </div>
      </section>
    </div>
  );
}
