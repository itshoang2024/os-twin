import React from 'react';
import type { ColorBy, WorkbenchLayer } from './model/workbenchModel';

export function LayersStylingPanel({ layers, colorBy, propertyName = '', onColorByChange, onPropertyNameChange }: { layers: WorkbenchLayer[]; colorBy: ColorBy; propertyName?: string; onColorByChange?: (value: ColorBy) => void; onPropertyNameChange?: (value: string) => void }) {
  return (
    <section data-testid="layers-styling-panel">
      <label>Color by<select aria-label="Color by" value={colorBy} onChange={(event) => onColorByChange?.(event.target.value as ColorBy)}><option value="fixed">Fixed</option><option value="object_type">Object type</option><option value="property">Property</option></select></label>
      {colorBy === 'property' ? <label>Property <input aria-label="Color property" value={propertyName} onChange={(event) => onPropertyNameChange?.(event.target.value)} /></label> : null}
      <div className="wb-swatches" aria-label="Boolean swatches">{['true', 'false', 'fallback'].map((item) => <span key={item} className="workbench-swatch swatch">{item}</span>)}</div>
      {layers.map((layer) => <div key={layer.id}>{layer.label}{typeof layer.count === 'number' ? ` (${layer.count})` : ''}</div>)}
    </section>
  );
}

export default LayersStylingPanel;
