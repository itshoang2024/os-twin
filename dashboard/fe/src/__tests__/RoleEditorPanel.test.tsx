import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import '@testing-library/jest-dom';
import RoleEditorPanel from '../components/roles/RoleEditorPanel';
import { Role } from '../types';
import { apiPost } from '../lib/api-client';
import useSWR from 'swr';
import { useModelRegistry, useRole, useRoleDependencies } from '../hooks/use-roles';

// Mock SWR - use vi.fn() so we can control return values per-test
vi.mock('swr', () => {
  const mutateFn = () => Promise.resolve();
  return {
    default: vi.fn(),
    useSWRConfig: vi.fn(() => ({ mutate: mutateFn })),
  };
});

// Mock hooks - use vi.fn() so we can set stable returns in beforeEach
vi.mock('../hooks/use-roles', () => ({
  useModelRegistry: vi.fn(),
  useRole: vi.fn(),
  useRoleDependencies: vi.fn(),
}));

// Mock api-client
vi.mock('../lib/api-client', () => ({
  apiPost: vi.fn().mockResolvedValue({ id: 'new-role', name: 'test' }),
  apiPut: vi.fn().mockResolvedValue({ id: 'existing', name: 'test' }),
}));

// Mock sub-components with minimal implementations
vi.mock('../components/roles/ProviderSelector', () => ({
  default: ({ value }: { value: string }) => (
    <div data-testid="provider-selector">Provider: {value}</div>
  ),
}));

vi.mock('../components/roles/TestConnectionButton', () => ({
  default: () => <div data-testid="test-connection">TestConnection</div>,
}));

vi.mock('../components/roles/SkillChipInput', () => ({
  default: ({ selectedSkillRefs }: { selectedSkillRefs: string[] }) => (
    <div data-testid="skill-chip-input">
      Skills: {selectedSkillRefs.join(', ')}
    </div>
  ),
}));

vi.mock('../components/roles/McpSelector', () => ({
  default: ({ selectedMcpRefs, onChange }: { selectedMcpRefs: string[]; onChange: (refs: string[]) => void }) => (
    <div data-testid="mcp-selector">
      MCPs: {selectedMcpRefs.join(', ')}
      <button type="button" onClick={() => onChange([...selectedMcpRefs, 'test-mcp'])}>
        add-mcp
      </button>
    </div>
  ),
}));

// Stable mock data (defined at module level to avoid new references each render)
const stableApiKeysData = { Claude: true, GPT: false, Gemini: true };
const stableSWRReturn = {
  data: stableApiKeysData,
  error: undefined,
  isLoading: false,
  mutate: vi.fn(),
};

const stableRegistry = {
  claude: [{ id: 'claude-opus-4', context_window: '200k', tier: 'flagship' }],
  gemini: [{ id: 'gemini-flash', context_window: '1M', tier: 'fast' }],
};
const stableRegistryReturn = { 
  registry: stableRegistry, 
  allModels: Object.values(stableRegistry).flat().map(m => ({ ...m, provider_id: 'claude' })), 
  providers: ['Claude', 'Gemini'],
  isLoading: false, 
  isError: undefined 
};
const stableDepsReturn = { dependencies: null, isLoading: false, isError: undefined };
const stableRoleReturn = { role: undefined, isLoading: false, isError: undefined, updateRole: vi.fn(), deleteRole: vi.fn(), testRole: vi.fn(), refresh: vi.fn() };

describe('RoleEditorPanel', () => {
  const mockOnClose = vi.fn();
  const existingRoles: Role[] = [];

  beforeEach(() => {
    vi.clearAllMocks();
    // Set stable return values to prevent infinite re-render loops
    (useSWR as unknown as ReturnType<typeof vi.fn>).mockReturnValue(stableSWRReturn);
    (useModelRegistry as unknown as ReturnType<typeof vi.fn>).mockReturnValue(stableRegistryReturn);
    (useRole as unknown as ReturnType<typeof vi.fn>).mockReturnValue(stableRoleReturn);
    (useRoleDependencies as unknown as ReturnType<typeof vi.fn>).mockReturnValue(stableDepsReturn);
  });

  it('renders all 6 configuration sections when open', () => {
    render(
      <RoleEditorPanel
        isOpen={true}
        onClose={mockOnClose}
        existingRoles={existingRoles}
      />
    );

    expect(screen.getByText('Identity & Context')).toBeInTheDocument();
    expect(screen.getByText('Model Provider')).toBeInTheDocument();
    expect(screen.getByText('Sampling Parameters')).toBeInTheDocument();
    expect(screen.getByText('Skill Matrix')).toBeInTheDocument();
    expect(screen.getByText('MCP Binding')).toBeInTheDocument();
    expect(screen.getByText('Role Instructions')).toBeInTheDocument();
  });

  it('renders McpSelector component in MCP section', () => {
    render(
      <RoleEditorPanel
        isOpen={true}
        onClose={mockOnClose}
        existingRoles={existingRoles}
      />
    );

    expect(screen.getByTestId('mcp-selector')).toBeInTheDocument();
  });

  it('initializes with empty mcp_refs for new role', () => {
    render(
      <RoleEditorPanel
        isOpen={true}
        onClose={mockOnClose}
        existingRoles={existingRoles}
      />
    );

    const mcpSelector = screen.getByTestId('mcp-selector');
    expect(mcpSelector).toHaveTextContent('MCPs:');
    // Empty mcp_refs means no server names displayed
    expect(mcpSelector.textContent).not.toContain('unity-mcp');
  });

  it('loads existing mcp_refs when editing a role', () => {
    const existingRole: Role = {
      id: 'r1',
      name: 'engineer',
      provider: 'claude',
      version: 'claude-opus-4',
      temperature: 0.3,
      budget_tokens_max: 500000,
      max_retries: 3,
      timeout_seconds: 900,
      skill_refs: ['implement-epic'],
      mcp_refs: ['unity-mcp', 'github-mcp'],
    };

    render(
      <RoleEditorPanel
        role={existingRole}
        isOpen={true}
        onClose={mockOnClose}
        existingRoles={existingRoles}
      />
    );

    const mcpSelector = screen.getByTestId('mcp-selector');
    expect(mcpSelector).toHaveTextContent('unity-mcp');
    expect(mcpSelector).toHaveTextContent('github-mcp');
  });

  it('hydrates edit form from the role detail endpoint', () => {
    const tableRole: Role = {
      id: 'r1',
      name: 'engineer',
      provider: 'claude',
      version: 'claude-opus-4',
      temperature: 0.3,
      budget_tokens_max: 500000,
      max_retries: 3,
      timeout_seconds: 300,
      skill_refs: [],
      mcp_refs: [],
      description: 'table summary',
      instructions: '',
    };
    const detailedRole: Role = {
      ...tableRole,
      max_retries: 7,
      timeout_seconds: 1200,
      skill_refs: ['implement-epic'],
      mcp_refs: ['unity-mcp'],
      description: 'full role detail',
      instructions: 'Detailed ROLE.md instructions',
    };
    (useRole as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      ...stableRoleReturn,
      role: detailedRole,
    });

    render(
      <RoleEditorPanel
        role={tableRole}
        isOpen={true}
        onClose={mockOnClose}
        existingRoles={existingRoles}
      />
    );

    expect(useRole).toHaveBeenCalledWith('r1');
    expect(screen.getByDisplayValue('7')).toBeInTheDocument();
    expect(screen.getByDisplayValue('1200')).toBeInTheDocument();
    expect(screen.getByDisplayValue('full role detail')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Detailed ROLE.md instructions')).toBeInTheDocument();
    expect(screen.getByTestId('skill-chip-input')).toHaveTextContent('implement-epic');
    expect(screen.getByTestId('mcp-selector')).toHaveTextContent('unity-mcp');
  });

  it('includes mcp_refs in save payload when creating a new role', async () => {
    render(
      <RoleEditorPanel
        isOpen={true}
        onClose={mockOnClose}
        existingRoles={existingRoles}
      />
    );

    // Fill required fields
    const nameInput = screen.getByPlaceholderText(/e.g. Frontend Engineer/i);
    fireEvent.change(nameInput, { target: { value: 'test-role' } });

    // Add an MCP via mock selector
    fireEvent.click(screen.getByText('add-mcp'));

    // Click save
    fireEvent.click(screen.getByText('Create Role'));

    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith(
        '/roles',
        expect.objectContaining({
          name: 'test-role',
          mcp_refs: ['test-mcp'],
        })
      );
    });
  });

  it('does not render when panel is closed', () => {
    render(
      <RoleEditorPanel
        isOpen={false}
        onClose={mockOnClose}
        existingRoles={existingRoles}
      />
    );

    expect(screen.queryByText('Identity & Context')).not.toBeInTheDocument();
  });

  it('displays section 05 with number badge for MCP Binding', () => {
    render(
      <RoleEditorPanel
        isOpen={true}
        onClose={mockOnClose}
        existingRoles={existingRoles}
      />
    );

    // Section numbering: 01=Identity, 02=Model, 03=Sampling, 04=Skills, 05=MCP, 06=Instructions
    expect(screen.getByText('05')).toBeInTheDocument();
    expect(screen.getByText('MCP Binding')).toBeInTheDocument();
  });

  it('provides a custom model ID input for non-registry models', () => {
    render(
      <RoleEditorPanel
        isOpen={true}
        onClose={mockOnClose}
        existingRoles={existingRoles}
      />
    );

    // Should have a text input for entering a custom model ID
    expect(screen.getByPlaceholderText(/my-custom-model/i)).toBeInTheDocument();
    expect(screen.getByText('Or Custom Model ID')).toBeInTheDocument();
  });

  it('saves custom model ID when user types one', async () => {
    render(
      <RoleEditorPanel
        isOpen={true}
        onClose={mockOnClose}
        existingRoles={existingRoles}
      />
    );

    // Fill name
    const nameInput = screen.getByPlaceholderText(/e.g. Frontend Engineer/i);
    fireEvent.change(nameInput, { target: { value: 'custom-role' } });

    // Enter a custom model ID
    const customModelInput = screen.getByPlaceholderText(/my-custom-model/i);
    fireEvent.change(customModelInput, { target: { value: 'my-finetuned-model-v2' } });

    // Save
    fireEvent.click(screen.getByText('Create Role'));

    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith(
        '/roles',
        expect.objectContaining({
          name: 'custom-role',
          version: 'my-finetuned-model-v2',
        })
      );
    });
  });
});
