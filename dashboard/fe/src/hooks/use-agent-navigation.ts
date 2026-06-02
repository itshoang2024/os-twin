import { useEffect, useMemo } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { getWebSocketUrl } from '@/lib/runtime-config';
import { useWebSocket } from './use-websocket';

type AgentNavigationMessage = {
  event?: string;
  type?: string;
  plan_id?: string;
  url?: string;
};

export function getAgentPlanRoute(message: AgentNavigationMessage | null | undefined): string | null {
  if (!message) return null;
  const eventType = message.event || message.type;
  if (eventType !== 'agent_plan_created' && eventType !== 'plan_created') return null;

  if (message.url?.startsWith('/plans/')) return message.url;
  if (message.plan_id) return `/plans/${message.plan_id}`;
  return null;
}

export function shouldNavigateForAgentPlan(pathname: string | null, targetRoute: string): boolean {
  if (!targetRoute.startsWith('/plans/')) return false;
  if (!pathname || pathname === '/') return true;
  if (pathname === '/ideas') return true;
  if (pathname.startsWith('/ideas/')) return true;
  return false;
}

export function useAgentNavigation() {
  const router = useRouter();
  const pathname = usePathname();
  const wsUrl = useMemo(
    () => (typeof window === 'undefined' ? null : getWebSocketUrl()),
    [],
  );
  const { lastMessage } = useWebSocket(wsUrl);

  useEffect(() => {
    const targetRoute = getAgentPlanRoute(lastMessage);
    if (!targetRoute || pathname === targetRoute) return;
    if (!shouldNavigateForAgentPlan(pathname, targetRoute)) return;
    router.push(targetRoute);
  }, [lastMessage, pathname, router]);
}
