import React from 'react';
import type { LayoutMode, RenderMode } from './model/workbenchModel';

const layoutModes: LayoutMode[] = ['auto', 'hierarchy', 'grid', 'row', 'column', 'circular', 'radial', 'cluster', 'cartesian', 'layered'];

export function WorkbenchToolbar({ renderMode = 'extended', layoutMode = 'auto', onRenderModeChange, onLayoutModeChange, onValidate, onPublish, children }: { renderMode?: RenderMode; layoutMode?: LayoutMode; onRenderModeChange?: (mode: RenderMode) => void; onLayoutModeChange?: (mode: LayoutMode) => void; onValidate?: () => void; onPublish?: () => void; children?: React.ReactNode }) {
  return (
    <div data-testid="workbench-toolbar" className="workbench-toolbar wb-toolbar">
      <button type="button">Selection</button>
      <button type="button">Search Around</button>
      <button type="button">Group</button>
      <label>Render <select aria-label="Render mode" value={renderMode} onChange={(event) => onRenderModeChange?.(event.target.value as RenderMode)}><option value="compact">Compact</option><option value="extended">Extended</option></select></label>
      <label>Layout <select aria-label="Layout mode" value={layoutMode} onChange={(event) => onLayoutModeChange?.(event.target.value as LayoutMode)}>{layoutModes.map((mode) => <option key={mode} value={mode}>{mode}</option>)}</select></label>
      <button type="button" onClick={onValidate}>Validate</button>
      <button type="button" onClick={onPublish}>Publish</button>
      {children}
    </div>
  );
}

export default WorkbenchToolbar;
