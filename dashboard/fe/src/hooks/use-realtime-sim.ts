import { useEffect, useRef } from 'react';
import { useNotificationStore } from '@/lib/stores/notificationStore';
import { useStats } from './use-stats';

export function useRealtimeSim(enabled = true) {
  const isMockRealtime = process.env.NEXT_PUBLIC_ENABLE_MOCK_REALTIME === 'true';
  const { addToast } = useNotificationStore();
  const { stats } = useStats(enabled);
  
  const lastStatsRef = useRef(stats);

  useEffect(() => {
    if (!enabled || !isMockRealtime) return;

    // Check for "escalations" or important changes in stats
    if (stats && lastStatsRef.current) {
      if ((stats.active_epics?.value ?? 0) > (lastStatsRef.current.active_epics?.value ?? 0)) {
        addToast({
          type: 'info',
          title: 'New EPIC Started',
          message: `Epic execution has been initiated. Current active: ${stats.active_epics?.value ?? 0}`,
        });
      }
    }
    lastStatsRef.current = stats;
  }, [stats, enabled, isMockRealtime, addToast]);

  useEffect(() => {
    if (!enabled || !isMockRealtime) return;

    // Randomly simulate an escalation every now and then if polling is active
    const interval = setInterval(() => {
      if (Math.random() > 0.8) {
        const types: ('warning' | 'error' | 'info' | 'success')[] = ['warning', 'error', 'info', 'success'];
        const type = types[Math.floor(Math.random() * types.length)];
        
        const messages = {
          warning: { title: 'Risk Detected', msg: 'A potential bottleneck was identified in EPIC-004.' },
          error: { title: 'Escalation', msg: 'Critical dependency failure in Task-012. Action required.' },
          info: { title: 'System Update', msg: 'New knowledge base entry added for React patterns.' },
          success: { title: 'Task Completed', msg: 'Task-008 has been successfully verified.' },
        };

        const content = messages[type as keyof typeof messages];
        
        addToast({
          type,
          title: content.title,
          message: content.msg,
        });
      }
    }, 15000); // Check for random event every 15s

    return () => clearInterval(interval);
  }, [enabled, isMockRealtime, addToast]);
}