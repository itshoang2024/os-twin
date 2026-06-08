'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { usePlanLogStream, PlanLogLine } from '@/hooks/use-plan-log-stream';

function statusTone(status: string) {
  if (status === 'failed') return 'text-red-500 bg-red-500/10 border-red-500/20';
  if (status === 'done') return 'text-emerald-600 bg-emerald-500/10 border-emerald-500/20';
  if (status === 'pending') return 'text-slate-500 bg-slate-500/10 border-slate-500/20';
  if (status === 'blocked') return 'text-amber-600 bg-amber-500/10 border-amber-500/20';
  return 'text-blue-600 bg-blue-500/10 border-blue-500/20';
}

function connectionTone(status: string) {
  switch (status) {
    case 'open':
      return { label: 'Live', className: 'text-emerald-600 bg-emerald-500/10 border-emerald-500/20', dot: 'bg-emerald-500 animate-pulse' };
    case 'connecting':
      return { label: 'Connecting', className: 'text-blue-600 bg-blue-500/10 border-blue-500/20', dot: 'bg-blue-500 animate-pulse' };
    case 'error':
      return { label: 'Reconnecting', className: 'text-amber-600 bg-amber-500/10 border-amber-500/20', dot: 'bg-amber-500 animate-pulse' };
    default:
      return { label: 'Closed', className: 'text-text-faint bg-border/20 border-border', dot: 'bg-text-faint' };
  }
}

function lineKey(line: PlanLogLine, index: number) {
  return `${line.id}-${index}`;
}

export default function PlanLogsTab({ planId }: { planId: string }) {
  const [selectedRoomId, setSelectedRoomId] = useState<string>('all');
  const [activeOnly, setActiveOnly] = useState(true);
  const [followTail, setFollowTail] = useState(true);
  const [query, setQuery] = useState('');
  const terminalRef = useRef<HTMLDivElement | null>(null);

  const { status, rooms, lines, linesByRoom, lastError, clear } = usePlanLogStream(planId, {
    activeOnly,
    tailLines: 200,
    pollMs: 750,
    stripAnsi: true,
  });

  const currentLines = useMemo(() => {
    const base = selectedRoomId === 'all' ? lines : (linesByRoom[selectedRoomId] ?? []);
    const q = query.trim().toLowerCase();
    if (!q) return base;
    return base.filter((line) => (
      line.text.toLowerCase().includes(q) ||
      line.epic_ref.toLowerCase().includes(q) ||
      line.room_id.toLowerCase().includes(q)
    ));
  }, [selectedRoomId, lines, linesByRoom, query]);

  const activeRoomCount = rooms.filter((room) => room.active).length;
  const roomsWithLogs = rooms.filter((room) => room.exists).length;
  const tone = connectionTone(status);

  useEffect(() => {
    if (!followTail) return;
    const terminal = terminalRef.current;
    if (!terminal) return;
    terminal.scrollTop = terminal.scrollHeight;
  }, [currentLines.length, followTail]);

  useEffect(() => {
    if (selectedRoomId !== 'all' && rooms.length > 0 && !rooms.some((room) => room.room_id === selectedRoomId)) {
      setSelectedRoomId('all');
    }
  }, [selectedRoomId, rooms]);

  return (
    <div className="h-full flex flex-col bg-background overflow-hidden">
      <div className="p-6 pb-4 border-b border-border bg-surface/60">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="material-symbols-outlined text-primary text-[22px]">terminal</span>
              <h2 className="text-xl font-extrabold text-text-main">Live EPIC Logs</h2>
              <span className={`inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-full border ${tone.className}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${tone.dot}`} />
                {tone.label}
              </span>
            </div>
            <p className="text-xs text-text-muted">
              Streaming <code className="font-mono text-[11px] bg-surface-alt border border-border rounded px-1">~/.ostwin/.agents/plans/{planId}.&lt;room_id&gt;.log</code>
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setActiveOnly((value) => !value)}
              className={`px-3 py-2 rounded-lg border text-[10px] font-extrabold uppercase tracking-wider transition-colors ${
                activeOnly ? 'border-primary/30 bg-primary/10 text-primary' : 'border-border bg-surface text-text-muted hover:text-text-main'
              }`}
            >
              {activeOnly ? 'Active only' : 'All rooms'}
            </button>
            <button
              onClick={() => setFollowTail((value) => !value)}
              className={`px-3 py-2 rounded-lg border text-[10px] font-extrabold uppercase tracking-wider transition-colors ${
                followTail ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600' : 'border-border bg-surface text-text-muted hover:text-text-main'
              }`}
            >
              {followTail ? 'Following' : 'Paused scroll'}
            </button>
            <button
              onClick={clear}
              className="px-3 py-2 rounded-lg border border-border bg-surface text-[10px] font-extrabold uppercase tracking-wider text-text-muted hover:text-text-main hover:border-primary/30 transition-colors"
            >
              Clear buffer
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-5">
          <div className="p-3 rounded-xl bg-surface border border-border">
            <div className="text-[9px] font-bold uppercase tracking-wider text-text-faint">Rooms streamed</div>
            <div className="text-2xl font-black text-text-main mt-1">{rooms.length}</div>
          </div>
          <div className="p-3 rounded-xl bg-surface border border-border">
            <div className="text-[9px] font-bold uppercase tracking-wider text-text-faint">Active EPICs</div>
            <div className="text-2xl font-black text-text-main mt-1">{activeRoomCount}</div>
          </div>
          <div className="p-3 rounded-xl bg-surface border border-border">
            <div className="text-[9px] font-bold uppercase tracking-wider text-text-faint">Log files found</div>
            <div className="text-2xl font-black text-text-main mt-1">{roomsWithLogs}</div>
          </div>
        </div>

        {lastError && (
          <div className="mt-3 p-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-xs text-amber-700 flex items-start gap-2">
            <span className="material-symbols-outlined text-[16px] mt-0.5">sync_problem</span>
            <span>{lastError}</span>
          </div>
        )}
      </div>

      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[280px_1fr] overflow-hidden">
        <aside className="border-r border-border bg-surface/40 p-4 overflow-y-auto custom-scrollbar">
          <div className="mb-3">
            <label htmlFor="plan-log-search" className="text-[9px] font-bold text-text-faint uppercase tracking-wider">Search logs</label>
            <div className="relative mt-1.5">
              <span className="material-symbols-outlined absolute left-2 top-1/2 -translate-y-1/2 text-[15px] text-text-faint">search</span>
              <input
                id="plan-log-search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Filter output..."
                className="w-full pl-8 pr-3 py-2 rounded-lg bg-surface border border-border text-xs text-text-main placeholder:text-text-faint focus:outline-none focus:ring-1 focus:ring-primary/40"
              />
            </div>
          </div>

          <button
            onClick={() => setSelectedRoomId('all')}
            className={`w-full text-left p-3 rounded-xl border mb-2 transition-colors ${
              selectedRoomId === 'all' ? 'border-primary/30 bg-primary/10' : 'border-border bg-surface hover:border-primary/20'
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-extrabold text-text-main">All streamed rooms</span>
              <span className="text-[10px] font-mono text-text-muted">{lines.length}</span>
            </div>
            <div className="text-[10px] text-text-faint mt-1">Merged live feed</div>
          </button>

          <div className="space-y-2">
            {rooms.map((room) => {
              const count = linesByRoom[room.room_id]?.length ?? 0;
              const selected = selectedRoomId === room.room_id;
              return (
                <button
                  key={room.room_id}
                  onClick={() => setSelectedRoomId(room.room_id)}
                  className={`w-full text-left p-3 rounded-xl border transition-colors ${
                    selected ? 'border-primary/30 bg-primary/10' : 'border-border bg-surface hover:border-primary/20'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-extrabold text-text-main truncate">{room.epic_ref}</span>
                    <span className={`shrink-0 px-1.5 py-0.5 rounded-full border text-[8px] font-bold uppercase ${statusTone(room.status)}`}>
                      {room.status}
                    </span>
                  </div>
                  <div className="flex items-center justify-between mt-1 text-[10px] text-text-faint font-mono">
                    <span>{room.room_id}</span>
                    <span>{count} lines</span>
                  </div>
                  {!room.exists && (
                    <div className="mt-2 text-[10px] text-amber-600 flex items-center gap-1">
                      <span className="material-symbols-outlined text-[12px]">schedule</span>
                      Waiting for log file
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </aside>

        <main className="min-h-0 flex flex-col bg-[#070a0f]">
          <div className="px-4 py-2 border-b border-white/10 flex items-center justify-between bg-black/40">
            <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">
              <span className="material-symbols-outlined text-[14px]">data_object</span>
              {selectedRoomId === 'all' ? 'Merged stream' : selectedRoomId}
            </div>
            <div className="text-[10px] font-mono text-slate-500">{currentLines.length} visible lines</div>
          </div>

          <div ref={terminalRef} className="flex-1 overflow-auto custom-scrollbar p-4 font-mono text-[12px] leading-5">
            {currentLines.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center text-slate-500 gap-3">
                <span className="material-symbols-outlined text-[44px] opacity-50">terminal</span>
                <div>
                  <p className="text-sm font-bold text-slate-300">Waiting for EPIC log output</p>
                  <p className="text-xs mt-1 max-w-md">
                    Launch or select a running EPIC and the dashboard will stream appended log lines over SSE.
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-0.5">
                {currentLines.map((line, index) => (
                  <div key={lineKey(line, index)} className="grid grid-cols-[auto_auto_1fr] gap-2 text-slate-300 hover:bg-white/[0.03] px-1 rounded">
                    <span className="text-slate-600 select-none">{String(index + 1).padStart(4, '0')}</span>
                    <span className="text-cyan-400 select-none">[{line.epic_ref}/{line.room_id}]</span>
                    <span className="whitespace-pre-wrap break-words">{line.text || ' '}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
