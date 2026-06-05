import React from 'react';

export type WorkbenchDockTabId = string;
export interface WorkbenchDockTab { id: WorkbenchDockTabId; label: string; icon?: string }

const fallbackTabs: WorkbenchDockTab[] = [
  { id: 'layers', label: 'Layers' },
  { id: 'selection', label: 'Selection' },
  { id: 'search', label: 'Search' },
  { id: 'histogram', label: 'Histogram' },
  { id: 'info', label: 'Info' },
];

export function WorkbenchDock({ tabs = fallbackTabs, activeTab, onTabChange, children }: { tabs?: WorkbenchDockTab[]; activeTab: WorkbenchDockTabId | string; onTabChange: (tab: WorkbenchDockTabId) => void; children?: React.ReactNode }) {
  return (
    <aside data-testid="workbench-dock" className="workbench-dock">
      <nav aria-label="Workbench dock" className="wb-dock-tabs">
        {tabs.map((tab) => <button key={tab.id} type="button" aria-pressed={activeTab === tab.id} onClick={() => onTabChange(tab.id)}>{tab.icon ? <span aria-hidden="true">{tab.icon} </span> : null}{tab.label}</button>)}
      </nav>
      <div className="wb-dock-body">{children}</div>
    </aside>
  );
}

export default WorkbenchDock;
