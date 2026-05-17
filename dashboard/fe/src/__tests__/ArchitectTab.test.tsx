import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import ArchitectTab from '../components/plan/ArchitectTab';

// ── Mocks ───────────────────────────────────────────────────────────

const mockPlanContext: Record<string, unknown> = {};
let mockChatHistory: { role: string; content: string }[] = [];

vi.mock('../components/plan/PlanWorkspace', () => ({
  usePlanContext: () => mockPlanContext,
}));

vi.mock('../hooks/use-plan-refine', () => ({
  usePlanRefine: () => ({
    chatHistory: mockChatHistory,
    isRefining: false,
    streamedResponse: '',
    error: null,
    refine: vi.fn(),
    cancelRefine: vi.fn(),
    clearHistory: vi.fn(),
  }),
}));

vi.mock('../hooks/use-planning-thread', () => ({
  usePlanningThread: () => ({
    thread: null,
    messages: [],
    streamedResponse: '',
    isStreaming: false,
    isLoading: false,
    sendMessage: vi.fn(),
    cancel: vi.fn(),
  }),
}));

vi.mock('../components/chat/AgentResponse', () => ({
  AgentResponse: ({ content }: { content: string }) => <div data-testid="agent-response">{content}</div>,
}));

vi.mock('../lib/extract-plan', () => ({
  extractPlan: (s: string) => s,
}));

vi.mock('../lib/image-utils', () => ({
  processImages: vi.fn(),
  MAX_IMAGES: 5,
}));

// ── Tests ───────────────────────────────────────────────────────────

describe('ArchitectTab', () => {
  beforeEach(() => {
    // jsdom doesn't implement scrollIntoView
    Element.prototype.scrollIntoView = vi.fn();

    mockChatHistory = [];

    // Default plan context: a plan with no thread_id
    Object.assign(mockPlanContext, {
      plan: { plan_id: 'test-plan', title: 'Test' },
      planContent: '# Plan',
      planId: 'test-plan',
      setPlanContent: vi.fn(),
      setActiveTab: vi.fn(),
    });
  });

  it('renders RefineChat when plan has no thread_id', () => {
    render(<ArchitectTab />);
    // RefineChat shows the "AI Plan" header without a "From idea" badge
    expect(screen.getAllByText('AI Plan').length).toBeGreaterThan(0);
    expect(screen.queryByText('From idea')).toBeNull();
  });

  it('renders RefineChat (not ThreadChat) even when plan has a thread_id', () => {
    mockPlanContext.plan = {
      plan_id: 'promoted-plan',
      title: 'Promoted',
      thread_id: 'thread-abc-123',
    };
    render(<ArchitectTab />);
    // Should still show RefineChat, NOT ThreadChat with "From idea" badge
    expect(screen.getAllByText('AI Plan').length).toBeGreaterThan(0);
    expect(screen.queryByText('From idea')).toBeNull();
  });

  it('renders RefineChat when plan has thread_id in meta', () => {
    mockPlanContext.plan = {
      plan_id: 'meta-plan',
      title: 'Meta Thread',
      meta: { thread_id: 'thread-xyz-789' },
    };
    render(<ArchitectTab />);
    expect(screen.getAllByText('AI Plan').length).toBeGreaterThan(0);
    expect(screen.queryByText('From idea')).toBeNull();
  });

  it('shows quick-action chips when chat history is empty', () => {
    render(<ArchitectTab />);
    // RefineChat shows REFINE_PROMPTS chips
    expect(screen.getByText('Break this into epics')).toBeDefined();
    expect(screen.getByText('Add acceptance criteria')).toBeDefined();
  });

  it('renders seeded thread messages as chat bubbles', () => {
    mockPlanContext.plan = {
      plan_id: 'promoted-plan',
      title: 'Promoted',
      thread_id: 'thread-abc-123',
    };
    // Simulate already-seeded history
    mockChatHistory = [
      { role: 'user', content: 'Build a snake game' },
      { role: 'assistant', content: 'Here is a plan for that.' },
    ];

    render(<ArchitectTab />);

    expect(screen.getByText('Build a snake game')).toBeDefined();
    expect(screen.getByText('Here is a plan for that.')).toBeDefined();
    // Apply to Editor should appear for assistant messages
    expect(screen.getByText('Apply to Editor')).toBeDefined();
  });
});
