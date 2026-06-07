import React from 'react';
import type { ColorBy, LayoutMode, RenderMode } from './model/workbenchModel';

export const layoutModes: Array<{ value: LayoutMode; label: string; title: string }> = [
  { value: 'auto', label: 'Auto', title: 'Chooses hierarchy for connected graphs, grid otherwise' },
  { value: 'hierarchy', label: 'Hierarchy', title: 'Levelled by incoming relationships' },
  { value: 'grid', label: 'Grid', title: 'Uniform grid' },
  { value: 'row', label: 'Row', title: 'Single horizontal row' },
  { value: 'column', label: 'Column', title: 'Single vertical column' },
  { value: 'circular', label: 'Circular', title: 'Circular layout' },
  { value: 'layered', label: 'Layered / grouped', title: 'Rows by layer or group' },
];

export const groupableFields = ['concept_type', 'layer', 'pack_id', 'abstraction_level', 'owner'] as const;

export function WorkbenchToolbar({ renderMode = 'extended', layoutMode = 'auto', groupBy = '', colorBy, filters = [], searchAroundEnabled = false, onRenderModeChange, onLayoutModeChange, onGroupByChange, onSearchAround, onClearAll, onValidate, onPublish, children }: { renderMode?: RenderMode; layoutMode?: LayoutMode; groupBy?: string; colorBy?: ColorBy; filters?: string[]; searchAroundEnabled?: boolean; onRenderModeChange?: (mode: RenderMode) => void; onLayoutModeChange?: (mode: LayoutMode) => void; onGroupByChange?: (field: string) => void; onSearchAround?: () => void; onClearAll?: () => void; onValidate?: () => void; onPublish?: () => void; children?: React.ReactNode }) {
  return (
    <div data-testid="workbench-toolbar" className="workbench-toolbar wb-toolbar" aria-label="Workbench toolbar">
      <button type="button">Selection</button>
      <button type="button" disabled={!searchAroundEnabled} onClick={onSearchAround}>Search Around</button>
      <label>Group <select aria-label="Group by" value={groupBy} onChange={(event) => onGroupByChange?.(event.target.value)}><option value="">Instruction default</option>{groupableFields.map((field) => <option key={field} value={field}>{field.replace(/_/g, ' ')}</option>)}</select></label>
      <label>Render <select aria-label="Render mode" value={renderMode} onChange={(event) => onRenderModeChange?.(event.target.value as RenderMode)}><option value="compact">Compact</option><option value="extended">Extended</option></select></label>
      <label>Layout <select aria-label="Layout mode" value={layoutMode} onChange={(event) => onLayoutModeChange?.(event.target.value as LayoutMode)}>{layoutModes.map((mode) => <option key={mode.value} value={mode.value} title={mode.title}>{mode.label}</option>)}</select></label>
      <span data-testid="workbench-applied-chips" className="wb-applied-chips">{groupBy ? <button type="button" onClick={() => onGroupByChange?.('')}>group: {groupBy} ×</button> : null}{colorBy ? <span>color: {colorBy}</span> : null}{filters.map((filter) => <span key={filter}>{filter}</span>)}{(groupBy || filters.length) && onClearAll ? <button type="button" onClick={onClearAll}>Clear all</button> : null}</span>
      <button type="button" onClick={onValidate}>Validate</button>
      <button type="button" onClick={onPublish}>Publish</button>
      {children}
    </div>
  );
}

export default WorkbenchToolbar;
