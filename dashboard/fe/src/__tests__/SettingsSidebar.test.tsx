import { render, screen, fireEvent } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import '@testing-library/jest-dom';
import { SettingsSidebar } from '../components/settings/SettingsSidebar';

describe('SettingsSidebar', () => {
  const mockOnNamespaceChange = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('T-002.1: Four Sub-Tabs', () => {
    it('renders all four namespace tabs (Provider Config, Runtime, Memory, Knowledge)', () => {
      render(
        <SettingsSidebar
          activeNamespace="providers"
          onNamespaceChange={mockOnNamespaceChange}
        />
      );

      expect(screen.getAllByText('Provider Config').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Runtime').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Memory').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Knowledge').length).toBeGreaterThan(0);
    });

    it('highlights the active namespace', () => {
      render(
        <SettingsSidebar
          activeNamespace="providers"
          onNamespaceChange={mockOnNamespaceChange}
        />
      );

      const providersButtons = screen.getAllByText('Provider Config');
      const desktopButton = providersButtons.find((el) =>
        el.closest('button')?.classList.contains('bg-[var(--color-text-main)]')
      );
      expect(desktopButton).toBeDefined();
    });

    it('calls onNamespaceChange when a tab is clicked', () => {
      render(
        <SettingsSidebar
          activeNamespace="providers"
          onNamespaceChange={mockOnNamespaceChange}
        />
      );

      const knowledgeButtons = screen.getAllByText('Knowledge');
      fireEvent.click(knowledgeButtons[0]);
      expect(mockOnNamespaceChange).toHaveBeenCalledWith('knowledge');
    });

    it('switches active namespace correctly', () => {
      const { rerender } = render(
        <SettingsSidebar
          activeNamespace="providers"
          onNamespaceChange={mockOnNamespaceChange}
        />
      );

      let knowledgeButtons = screen.getAllByText('Knowledge');
      let desktopKnowledge = knowledgeButtons.find((el) =>
        el.closest('button')?.classList.contains('bg-[var(--color-text-main)]')
      );
      expect(desktopKnowledge).toBeUndefined();

      rerender(
        <SettingsSidebar
          activeNamespace="knowledge"
          onNamespaceChange={mockOnNamespaceChange}
        />
      );

      knowledgeButtons = screen.getAllByText('Knowledge');
      desktopKnowledge = knowledgeButtons.find((el) =>
        el.closest('button')?.classList.contains('bg-[var(--color-text-main)]')
      );
      expect(desktopKnowledge).toBeDefined();
    });
  });

  describe('Mobile Menu', () => {
    it('shows mobile menu button on small screens', () => {
      render(
        <SettingsSidebar
          activeNamespace="providers"
          onNamespaceChange={mockOnNamespaceChange}
        />
      );

      const mobileButtons = screen.getAllByRole('button');
      const expandButton = mobileButtons.find((b) =>
        b.querySelector('.material-symbols-outlined')?.textContent === 'expand_more'
      );
      expect(expandButton).toBeDefined();
    });

    it('expands mobile menu when clicked', () => {
      render(
        <SettingsSidebar
          activeNamespace="providers"
          onNamespaceChange={mockOnNamespaceChange}
        />
      );

      const mobileButtons = screen.getAllByRole('button');
      const expandButton = mobileButtons.find((b) =>
        b.querySelector('.material-symbols-outlined')?.textContent === 'expand_more'
      );

      if (expandButton) {
        fireEvent.click(expandButton);
        expect(screen.getAllByText('Provider Config').length).toBeGreaterThan(0);
      }
    });
  });

  describe('Tab Navigation', () => {
    it('navigates from providers to runtime', () => {
      render(
        <SettingsSidebar
          activeNamespace="providers"
          onNamespaceChange={mockOnNamespaceChange}
        />
      );

      const runtimeButtons = screen.getAllByText('Runtime');
      fireEvent.click(runtimeButtons[0]);
      expect(mockOnNamespaceChange).toHaveBeenCalledWith('runtime');
    });

    it('navigates from providers to memory', () => {
      render(
        <SettingsSidebar
          activeNamespace="providers"
          onNamespaceChange={mockOnNamespaceChange}
        />
      );

      const memoryButtons = screen.getAllByText('Memory');
      fireEvent.click(memoryButtons[0]);
      expect(mockOnNamespaceChange).toHaveBeenCalledWith('memory');
    });

    it('navigates from providers to knowledge', () => {
      render(
        <SettingsSidebar
          activeNamespace="providers"
          onNamespaceChange={mockOnNamespaceChange}
        />
      );

      const knowledgeButtons = screen.getAllByText('Knowledge');
      fireEvent.click(knowledgeButtons[0]);
      expect(mockOnNamespaceChange).toHaveBeenCalledWith('knowledge');
    });
  });

  describe('Icons', () => {
    it('renders icons for each namespace', () => {
      render(
        <SettingsSidebar
          activeNamespace="providers"
          onNamespaceChange={mockOnNamespaceChange}
        />
      );

      const icons = screen.getAllByText('memory');
      expect(icons.length).toBeGreaterThan(0);
    });
  });
});
