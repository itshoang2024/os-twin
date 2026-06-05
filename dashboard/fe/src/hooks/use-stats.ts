import useSWR from 'swr';
import { DashboardStats } from '@/types';

export function useStats(enabled = true) {
  const isMockRealtime = process.env.NEXT_PUBLIC_ENABLE_MOCK_REALTIME === 'true';
  const { data: rawData, error, mutate, isLoading } = useSWR<Record<string, unknown>>(enabled ? '/stats' : null, {
    refreshInterval: isMockRealtime ? 10000 : 0,
  });

  // Normalize: backend uses "escalations_pending", frontend expects "escalations"
  const stats: DashboardStats | undefined = rawData ? {
    ...rawData,
    escalations: rawData.escalations || rawData.escalations_pending,
  } as DashboardStats : undefined;

  return {
    stats,
    isLoading,
    isError: error,
    refresh: mutate,
  };
}
