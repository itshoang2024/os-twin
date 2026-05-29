import { render, screen, fireEvent } from '@testing-library/react';
import { TemplatePicker } from './TemplatePicker';
import { vi, describe, it, expect } from 'vitest';
import '@testing-library/jest-dom';

const mockCategories = [
  {
    id: 'engineering',
    name: 'Engineering',
    icon: 'engineering',
    description: 'Software, sites, tools',
    templates: [
      { id: 't1', name: 'Frontend App', description: 'React App', fieldCount: 5, covers: ['goal'] },
      { id: 't2', name: 'Backend API', description: 'Node API', fieldCount: 4, covers: ['goal'] },
    ]
  },
  {
    id: 'marketing',
    name: 'Marketing',
    icon: 'campaign',
    description: 'Campaigns, SEO',
    templates: [
      { id: 't3', name: 'Landing Page', description: 'SEO Page', fieldCount: 6, covers: ['goal'] },
    ]
  }
];

describe('TemplatePicker', () => {
  it('renders all category tabs', () => {
    render(<TemplatePicker categories={mockCategories} onSelectTemplate={() => {}} />);
    expect(screen.getByText('Engineering')).toBeInTheDocument();
    expect(screen.getByText('Marketing')).toBeInTheDocument();
  });

  it('renders templates for the active tab', () => {
    render(<TemplatePicker categories={mockCategories} onSelectTemplate={() => {}} />);
    expect(screen.getByText('Frontend App')).toBeInTheDocument();
    expect(screen.getByText('Backend API')).toBeInTheDocument();
    expect(screen.queryByText('Landing Page')).not.toBeInTheDocument();
  });

  it('switches tabs on click', () => {
    render(<TemplatePicker categories={mockCategories} onSelectTemplate={() => {}} />);
    fireEvent.click(screen.getByText('Marketing'));
    expect(screen.getByText('Landing Page')).toBeInTheDocument();
    expect(screen.queryByText('Frontend App')).not.toBeInTheDocument();
  });

  it('calls onSelectTemplate with the catalog entry when clicked', () => {
    const onSelectTemplate = vi.fn();
    render(<TemplatePicker categories={mockCategories} onSelectTemplate={onSelectTemplate} />);
    fireEvent.click(screen.getByText('Frontend App'));
    expect(onSelectTemplate).toHaveBeenCalledWith(mockCategories[0].templates[0]);
  });

  it('shows field count badge for each template', () => {
    render(<TemplatePicker categories={mockCategories} onSelectTemplate={() => {}} />);
    expect(screen.getByText('5 fields')).toBeInTheDocument();
    expect(screen.getByText('4 fields')).toBeInTheDocument();
  });

  it('shows loading spinner on the selected template row', () => {
    render(
      <TemplatePicker
        categories={mockCategories}
        onSelectTemplate={() => {}}
        loadingTemplateId="t1"
      />
    );
    // The loading template row should be disabled
    const row = screen.getByText('Frontend App').closest('button');
    expect(row).toBeDisabled();
  });

  describe('keyboard navigation', () => {
    const getTabs = () => screen.getAllByRole('tab');

    const focusTabList = () => {
      const activeTab = screen.getByRole('tab', { selected: true });
      activeTab.focus();
      return activeTab;
    };

    it('uses a roving tabindex so only the active tab is in the tab order', () => {
      render(<TemplatePicker categories={mockCategories} onSelectTemplate={() => {}} />);
      const [engineering, marketing] = getTabs();
      expect(engineering).toHaveAttribute('aria-selected', 'true');
      expect(engineering).toHaveAttribute('tabindex', '0');
      expect(marketing).toHaveAttribute('aria-selected', 'false');
      expect(marketing).toHaveAttribute('tabindex', '-1');
    });

    it('moves selection and DOM focus on ArrowRight/ArrowLeft', () => {
      render(<TemplatePicker categories={mockCategories} onSelectTemplate={() => {}} />);
      focusTabList();
      let [engineering, marketing] = getTabs();

      fireEvent.keyDown(engineering, { key: 'ArrowRight' });
      [engineering, marketing] = getTabs();
      expect(marketing).toHaveAttribute('aria-selected', 'true');
      expect(document.activeElement).toBe(marketing);
      expect(screen.getByText('Landing Page')).toBeInTheDocument();
      expect(screen.queryByText('Frontend App')).not.toBeInTheDocument();

      fireEvent.keyDown(marketing, { key: 'ArrowLeft' });
      [engineering, marketing] = getTabs();
      expect(engineering).toHaveAttribute('aria-selected', 'true');
      expect(document.activeElement).toBe(engineering);
      expect(screen.getByText('Frontend App')).toBeInTheDocument();
    });

    it('wraps around on ArrowLeft/ArrowRight', () => {
      render(<TemplatePicker categories={mockCategories} onSelectTemplate={() => {}} />);
      focusTabList();
      let [engineering, marketing] = getTabs();

      fireEvent.keyDown(engineering, { key: 'ArrowLeft' });
      [, marketing] = getTabs();
      expect(marketing).toHaveAttribute('aria-selected', 'true');
      expect(document.activeElement).toBe(marketing);

      fireEvent.keyDown(marketing, { key: 'ArrowRight' });
      [engineering] = getTabs();
      expect(engineering).toHaveAttribute('aria-selected', 'true');
      expect(document.activeElement).toBe(engineering);
    });

    it('jumps to first/last with Home/End', () => {
      render(<TemplatePicker categories={mockCategories} onSelectTemplate={() => {}} />);
      focusTabList();
      let [engineering, marketing] = getTabs();

      fireEvent.keyDown(engineering, { key: 'End' });
      [, marketing] = getTabs();
      expect(marketing).toHaveAttribute('aria-selected', 'true');
      expect(document.activeElement).toBe(marketing);

      fireEvent.keyDown(marketing, { key: 'Home' });
      [engineering] = getTabs();
      expect(engineering).toHaveAttribute('aria-selected', 'true');
      expect(document.activeElement).toBe(engineering);
    });
  });

  it('renders nothing when no categories are provided', () => {
    const { container } = render(<TemplatePicker categories={[]} onSelectTemplate={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('tablist uses flex-wrap and not overflow-x-auto', () => {
    render(<TemplatePicker categories={mockCategories} onSelectTemplate={() => {}} />);
    const tablist = screen.getByRole('tablist');
    expect(tablist.className).toContain('flex-wrap');
    expect(tablist.className).not.toContain('overflow-x-auto');
  });

  it('renders all 9 categories including Documents and Creative without hiding any', () => {
    const nineCategories = [
      { id: 'engineering', name: 'Engineering', icon: 'engineering', description: '', templates: [] },
      { id: 'marketing',   name: 'Marketing',   icon: 'campaign',    description: '', templates: [] },
      { id: 'sales',       name: 'Sales',        icon: 'handshake',   description: '', templates: [] },
      { id: 'support',     name: 'Support',      icon: 'support_agent', description: '', templates: [] },
      { id: 'operations',  name: 'Operations',   icon: 'settings',    description: '', templates: [] },
      { id: 'research',    name: 'Research',     icon: 'science',     description: '', templates: [] },
      { id: 'compliance',  name: 'Compliance',   icon: 'verified',    description: '', templates: [] },
      { id: 'documents',   name: 'Documents',    icon: 'description', description: '', templates: [] },
      { id: 'creative',    name: 'Creative',     icon: 'palette',     description: '', templates: [] },
    ];
    render(<TemplatePicker categories={nineCategories} onSelectTemplate={() => {}} />);
    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(9);
    expect(screen.getByRole('tab', { name: /Engineering/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Documents/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Creative/i })).toBeInTheDocument();
  });

  it('renders a Documents tab when included in categories', () => {
    const categoriesWithDocs = [
      ...mockCategories,
      {
        id: 'documents',
        name: 'Documents',
        icon: 'description',
        description: 'Drafts, reports, notes, source-based docs',
        templates: [
          { id: 'document-draft', name: 'Draft a document', description: 'Create a structured document from a brief or notes', fieldCount: 8, covers: ['goal', 'audience', 'scope'] },
          { id: 'meeting-notes', name: 'Meeting notes / minutes', description: 'Turn notes or a transcript into decisions and action items', fieldCount: 7, covers: ['goal', 'audience', 'done-when'] },
        ],
      },
    ];
    render(<TemplatePicker categories={categoriesWithDocs} onSelectTemplate={() => {}} />);
    expect(screen.getByRole('tab', { name: /Documents/i })).toBeInTheDocument();
  });

  it('switches to Documents tab and shows its templates', () => {
    const categoriesWithDocs = [
      ...mockCategories,
      {
        id: 'documents',
        name: 'Documents',
        icon: 'description',
        description: 'Drafts, reports, notes, source-based docs',
        templates: [
          { id: 'document-draft', name: 'Draft a document', description: 'Create a structured document from a brief or notes', fieldCount: 8, covers: ['goal', 'audience', 'scope'] },
          { id: 'meeting-notes', name: 'Meeting notes / minutes', description: 'Turn notes or a transcript into decisions and action items', fieldCount: 7, covers: ['goal', 'audience', 'done-when'] },
        ],
      },
    ];
    render(<TemplatePicker categories={categoriesWithDocs} onSelectTemplate={() => {}} />);
    fireEvent.click(screen.getByRole('tab', { name: /Documents/i }));
    expect(screen.getByText('Draft a document')).toBeInTheDocument();
    expect(screen.getByText('Meeting notes / minutes')).toBeInTheDocument();
    expect(screen.queryByText('Frontend App')).not.toBeInTheDocument();
  });
});
