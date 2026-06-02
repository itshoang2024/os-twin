/**
 * Tests for KnowledgePage (Global Knowledge Base — Grid Homepage).
 * Using Vitest + React Testing Library.
 *
 * The global knowledge homepage shows a card grid of all namespaces.
 * Clicking a card navigates to /knowledge/{name} (master-detail view).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import KnowledgePage from '@/app/knowledge/page';

// Mock ResizeObserver for jsdom
class MockResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
global.ResizeObserver = MockResizeObserver as unknown as typeof ResizeObserver;

// Router mock
const mockPush = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({
    push: mockPush,
    replace: vi.fn(),
  })),
}));

vi.mock('@/components/knowledge/MetricsStrip', () => ({
  default: ({ className = '' }: { className?: string }) => (
    <div data-testid="metrics-strip" className={className}>Metrics</div>
  ),
}));

// Mock the hooks
vi.mock('@/hooks/use-knowledge-namespaces', () => ({
  useKnowledgeNamespaces: vi.fn(() => ({
    namespaces: [
      {
        schema_version: 1,
        name: 'test-namespace',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        language: 'English',
        description: 'Test namespace',
        embedding_model: 'text-embedding-3-small',
        embedding_dimension: 1536,
        stats: {
          files_indexed: 10,
          chunks: 100,
          entities: 50,
          relations: 25,
          vectors: 100,
          bytes_on_disk: 1024000,
        },
        imports: [],
        ontology_profile_version: '1.0.0',
      },
      {
        schema_version: 1,
        name: 'another-namespace',
        created_at: '2024-01-02T00:00:00Z',
        updated_at: '2024-01-02T00:00:00Z',
        language: 'English',
        description: null,
        embedding_model: 'text-embedding-3-small',
        embedding_dimension: 1536,
        stats: {
          files_indexed: 0,
          chunks: 0,
          entities: 0,
          relations: 0,
          vectors: 0,
          bytes_on_disk: 0,
        },
        imports: [],
        ontology_profile_version: null,
      },
    ],
    isLoading: false,
    isError: null,
    createNamespace: vi.fn(),
    refresh: vi.fn(),
  })),
}));

vi.mock('@/lib/stores/notificationStore', () => ({
  useNotificationStore: vi.fn((selector) => {
    const state = { addToast: vi.fn() };
    return selector ? selector(state) : state;
  }),
}));

describe('KnowledgePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the knowledge base page header', async () => {
    render(<KnowledgePage />);

    expect(screen.getByText('Knowledge Base')).toBeInTheDocument();
    expect(screen.getByText(/shape each graph with an ontology profile/i)).toBeInTheDocument();
  });

  it('renders ontology-aware landing metrics', async () => {
    render(<KnowledgePage />);

    expect(screen.getByText('Profiled namespaces')).toBeInTheDocument();
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
    expect(screen.getByText('Ontology readiness')).toBeInTheDocument();
  });

  it('shows namespace cards in a grid', async () => {
    render(<KnowledgePage />);

    // Should show both namespaces as cards
    const manager = within(screen.getByTestId('namespace-manager'));
    expect(manager.getByText('test-namespace')).toBeInTheDocument();
    expect(manager.getByText('another-namespace')).toBeInTheDocument();
  });

  it('navigates to /knowledge/{name} when card is clicked', async () => {
    render(<KnowledgePage />);

    // Click on a namespace card
    const manager = within(screen.getByTestId('namespace-manager'));
    fireEvent.click(manager.getByText('test-namespace'));

    // Should navigate to the detail page
    expect(mockPush).toHaveBeenCalledWith('/knowledge/test-namespace');
  });

  it('filters the namespace manager by ontology readiness', async () => {
    render(<KnowledgePage />);

    const manager = within(screen.getByTestId('namespace-manager'));
    expect(manager.getByText('test-namespace')).toBeInTheDocument();
    expect(manager.getByText('another-namespace')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Empty' }));

    expect(manager.queryByText('test-namespace')).not.toBeInTheDocument();
    expect(manager.getByText('another-namespace')).toBeInTheDocument();
  });

  it('shows the + New button for creating namespaces', async () => {
    render(<KnowledgePage />);

    expect(screen.getByText('New')).toBeInTheDocument();
  });

  it('opens create modal when + New is clicked', async () => {
    render(<KnowledgePage />);

    fireEvent.click(screen.getByText('New'));

    await waitFor(() => {
      expect(screen.getByText('Create Namespace')).toBeInTheDocument();
    });
  });
});
