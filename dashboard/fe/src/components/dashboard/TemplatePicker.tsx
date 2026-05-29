import React, { useState, useCallback, useRef, useEffect } from 'react';
import type { TemplateCatalogEntry, TemplateCategoryMeta } from '@/data/template-catalog';

interface TemplatePickerProps {
  categories: TemplateCategoryMeta[];
  onSelectTemplate: (entry: TemplateCatalogEntry) => void;
  /** ID of the template currently being loaded (shows spinner on that row) */
  loadingTemplateId?: string | null;
}

export const TemplatePicker: React.FC<TemplatePickerProps> = ({
  categories,
  onSelectTemplate,
  loadingTemplateId,
}) => {
  const [activeTabId, setActiveTabId] = useState(categories[0]?.id ?? '');
  const [focusedTabIndex, setFocusedTabIndex] = useState(0);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const shouldFocusTabRef = useRef(false);

  const activeCategory = categories.find(c => c.id === activeTabId);

  useEffect(() => {
    if (!shouldFocusTabRef.current) return;
    shouldFocusTabRef.current = false;
    const el = tabRefs.current[focusedTabIndex];
    if (el) el.focus();
  }, [focusedTabIndex]);

  const moveToTab = useCallback((nextIndex: number) => {
    if (categories.length === 0) return;
    shouldFocusTabRef.current = true;
    setFocusedTabIndex(nextIndex);
    setActiveTabId(categories[nextIndex].id);
  }, [categories]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (categories.length === 0) return;
    if (e.key === 'ArrowRight') {
      e.preventDefault();
      moveToTab((focusedTabIndex + 1) % categories.length);
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      moveToTab((focusedTabIndex - 1 + categories.length) % categories.length);
    } else if (e.key === 'Home') {
      e.preventDefault();
      moveToTab(0);
    } else if (e.key === 'End') {
      e.preventDefault();
      moveToTab(categories.length - 1);
    }
  }, [categories, focusedTabIndex, moveToTab]);

  if (categories.length === 0) return null;

  return (
    <div className="w-full mt-12 mb-16">
      <div
        role="tablist"
        aria-label="Plan template categories"
        className="flex overflow-x-auto items-center pb-2 border-b border-[var(--color-border)] mb-6"
        onKeyDown={handleKeyDown}
      >
        {categories.map((cat, idx) => (
          <button
            key={cat.id}
            ref={el => { tabRefs.current[idx] = el; }}
            role="tab"
            id={`tab-${cat.id}`}
            aria-controls={`panel-${cat.id}`}
            aria-selected={activeTabId === cat.id}
            tabIndex={activeTabId === cat.id ? 0 : -1}
            onClick={() => {
              setActiveTabId(cat.id);
              setFocusedTabIndex(idx);
            }}
            className={`flex items-center justify-center gap-1.5 shrink-0 whitespace-nowrap px-3 py-2 text-sm font-medium transition-all border-b-2 -mb-[2px] ${
              activeTabId === cat.id
                ? 'border-[var(--color-primary)] text-[var(--color-primary)]'
                : 'border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text-main)] hover:border-[var(--color-border)]'
            }`}
          >
            <span className="material-symbols-outlined text-sm shrink-0">{cat.icon}</span>
            <span>{cat.name}</span>
          </button>
        ))}
      </div>

      {activeCategory && (
        <div
          role="tabpanel"
          id={`panel-${activeCategory.id}`}
          aria-labelledby={`tab-${activeCategory.id}`}
          className="flex flex-col gap-1"
        >
          {activeCategory.templates.map(entry => (
            <button
              key={entry.id}
              onClick={() => onSelectTemplate(entry)}
              disabled={loadingTemplateId === entry.id}
              className="w-full text-left p-3 hover:bg-[var(--color-surface)] rounded-[var(--radius-lg)] transition-all group flex items-center gap-3 disabled:opacity-60"
            >
              <div className="flex-1 flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-3 min-w-0">
                <div className="font-bold text-[var(--color-text-main)] text-sm group-hover:text-[var(--color-primary)] transition-colors shrink-0">
                  {entry.name}
                </div>
                <div className="text-xs text-[var(--color-text-muted)] truncate">
                  {entry.description}
                </div>
              </div>
              <div className="shrink-0 flex items-center gap-2">
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[var(--color-background)] text-[var(--color-text-faint)] tabular-nums">
                  {entry.fieldCount} fields
                </span>
                {loadingTemplateId === entry.id ? (
                  <span className="material-symbols-outlined text-sm text-[var(--color-primary)] animate-spin">refresh</span>
                ) : (
                  <span className="material-symbols-outlined text-sm text-[var(--color-text-faint)] group-hover:text-[var(--color-primary)] transition-colors">arrow_forward</span>
                )}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
