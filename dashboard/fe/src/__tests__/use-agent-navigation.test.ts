import { describe, expect, it } from 'vitest';
import {
  getAgentPlanRoute,
  shouldNavigateForAgentPlan,
} from '../hooks/use-agent-navigation';

describe('agent navigation helpers', () => {
  it('extracts a plan route from agent plan-created events', () => {
    expect(getAgentPlanRoute({ event: 'agent_plan_created', plan_id: 'video-platform' })).toBe('/plans/video-platform');
    expect(getAgentPlanRoute({ type: 'plan_created', url: '/plans/custom-route' })).toBe('/plans/custom-route');
  });

  it('ignores non-plan events and unsafe routes', () => {
    expect(getAgentPlanRoute({ event: 'settings_updated', plan_id: 'p1' })).toBeNull();
    expect(getAgentPlanRoute({ event: 'agent_plan_created', url: 'https://example.com/plans/p1' })).toBeNull();
  });

  it('auto-navigates only from master-agent surfaces', () => {
    expect(shouldNavigateForAgentPlan('/', '/plans/p1')).toBe(true);
    expect(shouldNavigateForAgentPlan('/ideas', '/plans/p1')).toBe(true);
    expect(shouldNavigateForAgentPlan('/ideas/thread-1', '/plans/p1')).toBe(true);
    expect(shouldNavigateForAgentPlan('/settings', '/plans/p1')).toBe(false);
    expect(shouldNavigateForAgentPlan('/plans/existing', '/plans/p1')).toBe(false);
  });
});
