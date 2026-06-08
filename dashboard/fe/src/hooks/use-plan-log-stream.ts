'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getApiBaseUrl } from '@/lib/runtime-config';

export interface PlanLogRoom {
  plan_id: string;
  room_id: string;
  epic_ref: string;
  status: string;
  active: boolean;
  exists: boolean;
  size: number;
  updated_at: string | null;
}

export interface PlanLogLine {
  id: string;
  plan_id: string;
  room_id: string;
  epic_ref: string;
  status: string;
  text: string;
  offset: number;
  initial: boolean;
  receivedAt: number;
}

interface PlanLogStreamOptions {
  activeOnly?: boolean;
  rooms?: string[];
  tailLines?: number;
  pollMs?: number;
  stripAnsi?: boolean;
  maxLinesPerRoom?: number;
  maxTotalLines?: number;
}

type ConnectionStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error';

interface InitEventPayload {
  rooms?: PlanLogRoom[];
}

interface LineEventPayload extends Omit<PlanLogLine, 'id' | 'receivedAt'> {}

interface RoomStatusPayload {
  room_id: string;
  epic_ref: string;
  status: string;
  active: boolean;
}

function buildStreamUrl(planId: string, options: Required<Pick<PlanLogStreamOptions, 'activeOnly' | 'tailLines' | 'pollMs' | 'stripAnsi'>> & { rooms?: string[] }) {
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost';
  const apiBase = getApiBaseUrl();
  const url = new URL(`${apiBase.replace(/\/$/, '')}/plans/${encodeURIComponent(planId)}/logs/stream`, origin);
  url.searchParams.set('active_only', String(options.activeOnly));
  url.searchParams.set('tail_lines', String(options.tailLines));
  url.searchParams.set('poll_ms', String(options.pollMs));
  url.searchParams.set('strip_ansi', String(options.stripAnsi));
  if (options.rooms && options.rooms.length > 0) {
    url.searchParams.set('rooms', options.rooms.join(','));
  }
  return url.toString();
}

function parseEvent<T>(event: MessageEvent): T | null {
  try {
    return JSON.parse(event.data) as T;
  } catch {
    return null;
  }
}

export function usePlanLogStream(planId: string, options: PlanLogStreamOptions = {}) {
  const {
    activeOnly = true,
    rooms,
    tailLines = 200,
    pollMs = 750,
    stripAnsi = true,
    maxLinesPerRoom = 1000,
    maxTotalLines = 5000,
  } = options;

  const roomKey = rooms?.join(',') ?? '';
  const [status, setStatus] = useState<ConnectionStatus>(planId ? 'connecting' : 'idle');
  const [logRooms, setLogRooms] = useState<PlanLogRoom[]>([]);
  const [linesByRoom, setLinesByRoom] = useState<Record<string, PlanLogLine[]>>({});
  const [lines, setLines] = useState<PlanLogLine[]>([]);
  const [lastError, setLastError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const url = useMemo(() => {
    if (!planId) return null;
    return buildStreamUrl(planId, {
      activeOnly,
      rooms,
      tailLines,
      pollMs,
      stripAnsi,
    });
  }, [planId, activeOnly, roomKey, tailLines, pollMs, stripAnsi]);

  const clear = useCallback(() => {
    setLines([]);
    setLinesByRoom({});
  }, []);

  useEffect(() => {
    if (!url) {
      setStatus('idle');
      setLogRooms([]);
      clear();
      return;
    }

    if (typeof EventSource === 'undefined') {
      setStatus('error');
      setLastError('This browser does not support EventSource/SSE.');
      return;
    }

    setStatus('connecting');
    setLastError(null);

    const eventSource = new EventSource(url, { withCredentials: true });
    eventSourceRef.current = eventSource;

    eventSource.onopen = () => {
      setStatus('open');
      setLastError(null);
    };

    eventSource.onerror = () => {
      setStatus(eventSource.readyState === EventSource.CLOSED ? 'closed' : 'error');
      setLastError('Live log stream disconnected; reconnecting if the server is still available.');
    };

    const handleInit = (event: MessageEvent) => {
      const payload = parseEvent<InitEventPayload>(event);
      setLogRooms(payload?.rooms ?? []);
    };

    const handleRoomStatus = (event: MessageEvent) => {
      const payload = parseEvent<RoomStatusPayload>(event);
      if (!payload) return;
      setLogRooms((current) => current.map((room) => (
        room.room_id === payload.room_id
          ? { ...room, status: payload.status, active: payload.active, epic_ref: payload.epic_ref }
          : room
      )));
    };

    const handleLine = (event: MessageEvent) => {
      const payload = parseEvent<LineEventPayload>(event);
      if (!payload || !payload.room_id) return;
      const line: PlanLogLine = {
        ...payload,
        id: event.lastEventId || `${payload.room_id}:${payload.offset}:${Date.now()}`,
        receivedAt: Date.now(),
      };

      setLinesByRoom((current) => {
        const existing = current[line.room_id] ?? [];
        return {
          ...current,
          [line.room_id]: [...existing, line].slice(-maxLinesPerRoom),
        };
      });
      setLines((current) => [...current, line].slice(-maxTotalLines));
    };

    eventSource.addEventListener('init', handleInit);
    eventSource.addEventListener('line', handleLine);
    eventSource.addEventListener('room_status', handleRoomStatus);

    return () => {
      eventSource.removeEventListener('init', handleInit);
      eventSource.removeEventListener('line', handleLine);
      eventSource.removeEventListener('room_status', handleRoomStatus);
      eventSource.close();
      if (eventSourceRef.current === eventSource) {
        eventSourceRef.current = null;
      }
      setStatus('closed');
    };
  }, [url, clear, maxLinesPerRoom, maxTotalLines]);

  return {
    status,
    rooms: logRooms,
    lines,
    linesByRoom,
    lastError,
    clear,
  };
}
