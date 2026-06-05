'use client';

import { useWebSocket } from '@/hooks/use-websocket';

export interface LiveStatusBadgeProps {
  className?: string;
}

export function LiveStatusBadge({ className = '' }: LiveStatusBadgeProps) {
  const wsUrl = typeof window !== 'undefined'
    ? `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/api/ws`
    : null;

  const { isConnected } = useWebSocket(wsUrl);

  return (
    <div
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-bold uppercase ${
        isConnected
          ? 'border-emerald-200 bg-emerald-500/10 text-emerald-700'
          : 'border-amber-200 bg-amber-500/10 text-amber-700'
      } ${className}`}
    >
      <span className={`h-2 w-2 rounded-full animate-pulse ${
        isConnected ? 'bg-green-500' : 'bg-orange-500'
      }`} />
      {isConnected ? 'LIVE' : 'STALE'}
    </div>
  );
}
