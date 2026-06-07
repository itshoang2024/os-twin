/**
 * Unit tests for StateNode component (EPIC-003 enhancements).
 *
 * Tests the DAG canvas node card with:
 * - Progress bars for tasks/DoD completion
 * - Warning badge for EPICs with no AC
 * - Hover tooltip with EPIC title + description
 * - Double-click to open editor panel
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

// Polyfill ResizeObserver for jsdom
class MockResizeObserver implements ResizeObserver {
  observe() { /* noop */ }
  unobserve() { /* noop */ }
  disconnect() { /* noop */ }
}
globalThis.ResizeObserver = MockResizeObserver;

// ── Mock PlanWorkspace context ───────────────────────────────────────

const mockSetSelectedEpicRef = vi.fn();
const mockSetIsContextPanelOpen = vi.fn();

vi.mock('../components/plan/PlanWorkspace', () => ({
  usePlanContext: () => ({
    planId: 'test-plan',
    selectedEpicRef: null,
    setSelectedEpicRef: mockSetSelectedEpicRef,
    setIsContextPanelOpen: mockSetIsContextPanelOpen,
  }),
}));

vi.mock('../components/plan/EpicCard', () => ({
  stateColors: {
    pending: '#94a3b8',
    done: '#10b981',
    developing: '#3b82f6',
    engineering: '#3b82f6',
    failed: '#ef4444',
  },
}));

// ── Import component AFTER mocks ─────────────────────────────────────

import StateNode from '../components/plan/StateNode';

// ── Tests ────────────────────────────────────────────────────────────

describe('StateNode', () => {
  const defaultProps = {
    id: 'EPIC-001',
    label: 'Auth System',
    status: 'pending' as const,
    x: 100,
    y: 50,
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Basic Rendering', () => {
    it('renders the EPIC id and label', () => {
      render(<StateNode {...defaultProps} />);
      expect(screen.getByText('EPIC-001')).toBeInTheDocument();
      expect(screen.getByText('Auth System')).toBeInTheDocument();
    });

    it('renders the status badge', () => {
      render(<StateNode {...defaultProps} status="done" />);
      expect(screen.getByText('DONE')).toBeInTheDocument();
    });

    it('renders role badge when role info provided', () => {
      render(
        <StateNode
          {...defaultProps}
          role="engineer"
          roleInitial="E"
          roleColor="#3b82f6"
        />
      );
      expect(screen.getByText('E')).toBeInTheDocument();
      expect(screen.getByText('engineer')).toBeInTheDocument();
    });
  });

  describe('Progress Bars (EPIC-003)', () => {
    it('renders task progress bar when tasksTotal > 0', () => {
      render(
        <StateNode
          {...defaultProps}
          tasksDone={2}
          tasksTotal={5}
        />
      );
      expect(screen.getByText('2/5 tasks')).toBeInTheDocument();
    });

    it('renders DoD progress bar when dodTotal > 0', () => {
      render(
        <StateNode
          {...defaultProps}
          dodDone={1}
          dodTotal={4}
        />
      );
      expect(screen.getByText('1/4 DoD')).toBeInTheDocument();
    });

    it('does not render progress section when no stats', () => {
      render(<StateNode {...defaultProps} />);
      expect(screen.queryByText(/tasks/)).not.toBeInTheDocument();
      expect(screen.queryByText(/DoD/)).not.toBeInTheDocument();
    });

    it('renders 0% progress bar for no completed tasks', () => {
      const { container } = render(
        <StateNode
          {...defaultProps}
          tasksDone={0}
          tasksTotal={3}
        />
      );
      // The progress bar div should have width: 0%
      const progressBar = container.querySelector('[style*="width: 0%"]');
      expect(progressBar).toBeInTheDocument();
    });

    it('renders 100% progress bar for all completed tasks', () => {
      const { container } = render(
        <StateNode
          {...defaultProps}
          tasksDone={3}
          tasksTotal={3}
        />
      );
      const progressBar = container.querySelector('[style*="width: 100%"]');
      expect(progressBar).toBeInTheDocument();
    });

    it('renders partial progress bar for some completed tasks', () => {
      const { container } = render(
        <StateNode
          {...defaultProps}
          tasksDone={2}
          tasksTotal={5}
        />
      );
      // 2/5 = 40%
      const progressBar = container.querySelector('[style*="width: 40%"]');
      expect(progressBar).toBeInTheDocument();
    });

    it('renders both task and DoD bars together', () => {
      render(
        <StateNode
          {...defaultProps}
          tasksDone={3}
          tasksTotal={5}
          dodDone={1}
          dodTotal={4}
        />
      );
      expect(screen.getByText('3/5 tasks')).toBeInTheDocument();
      expect(screen.getByText('1/4 DoD')).toBeInTheDocument();
    });
  });

  describe('Warning Badge (EPIC-003)', () => {
    it('shows warning badge when hasAC is false', () => {
      render(
        <StateNode
          {...defaultProps}
          hasAC={false}
        />
      );
      expect(screen.getByText('No AC')).toBeInTheDocument();
    });

    it('does not show warning badge when hasAC is true', () => {
      render(
        <StateNode
          {...defaultProps}
          hasAC={true}
        />
      );
      expect(screen.queryByText('No AC')).not.toBeInTheDocument();
    });

    it('does not show warning badge by default (hasAC defaults to true)', () => {
      render(<StateNode {...defaultProps} />);
      expect(screen.queryByText('No AC')).not.toBeInTheDocument();
    });
  });

  describe('Hover Tooltip (EPIC-003)', () => {
    it('shows tooltip with description on hover', async () => {
      render(
        <StateNode
          {...defaultProps}
          description="Build the authentication system for users"
        />
      );

      const card = screen.getByText('EPIC-001').closest('div[class*="rounded-lg"]')!;
      fireEvent.mouseEnter(card);

      await waitFor(() => {
        expect(screen.getByText('Build the authentication system for users')).toBeInTheDocument();
      });
    });

    it('does not show tooltip when no description and label equals id', async () => {
      render(
        <StateNode
          {...defaultProps}
          label="EPIC-001"
          description=""
        />
      );

      // The tooltip should not render at all when label===id and no description
      const { container } = render(
        <StateNode
          id="EPIC-001"
          label="EPIC-001"
          status="pending"
          x={0}
          y={0}
          description=""
        />
      );

      // No foreignObject for tooltip should exist
      const tooltips = container.querySelectorAll('.shadow-lg');
      expect(tooltips.length).toBe(0);
    });
  });

  describe('Click / Double-click (EPIC-003)', () => {
    it('calls onClick on single click', () => {
      const handleClick = vi.fn();
      render(
        <StateNode
          {...defaultProps}
          onClick={handleClick}
        />
      );

      const card = screen.getByText('EPIC-001').closest('div[class*="rounded-lg"]')!;
      fireEvent.click(card);
      expect(handleClick).toHaveBeenCalledWith('EPIC-001');
    });

    it('calls onDoubleClick on double click', () => {
      const handleDoubleClick = vi.fn();
      render(
        <StateNode
          {...defaultProps}
          onDoubleClick={handleDoubleClick}
        />
      );

      const card = screen.getByText('EPIC-001').closest('div[class*="rounded-lg"]')!;
      fireEvent.doubleClick(card);
      expect(handleDoubleClick).toHaveBeenCalledWith('EPIC-001');
    });

    it('falls back to context panel when no onClick', () => {
      render(<StateNode {...defaultProps} />);
      const card = screen.getByText('EPIC-001').closest('div[class*="rounded-lg"]')!;
      fireEvent.click(card);
      expect(mockSetSelectedEpicRef).toHaveBeenCalledWith('EPIC-001');
      expect(mockSetIsContextPanelOpen).toHaveBeenCalledWith(true);
    });
  });

  describe('Node Dimensions', () => {
    it('uses 200x95 foreignObject dimensions', () => {
      const { container } = render(<StateNode {...defaultProps} />);
      const fo = container.querySelector('foreignObject');
      expect(fo).toHaveAttribute('width', '200');
      expect(fo).toHaveAttribute('height', '95');
    });
  });
});
