import React from 'react';
import WorkbenchDock, { type WorkbenchDockTab } from './WorkbenchDock';
import WorkbenchToolbar from './WorkbenchToolbar';
import SelectionInspector from './SelectionInspector';
import LayersStylingPanel from './LayersStylingPanel';
import HistogramPanel from './HistogramPanel';
import type { ColorBy, LayoutMode, RenderMode, WorkbenchModel } from './model/workbenchModel';

const defaultTabs: WorkbenchDockTab[] = [
  { id: 'layers', label: 'Layers', icon: '▦' },
  { id: 'selection', label: 'Selection', icon: '⌖' },
  { id: 'search', label: 'Search', icon: '⌕' },
  { id: 'histogram', label: 'Histogram', icon: '▥' },
  { id: 'info', label: 'Info', icon: 'i' },
];

const specTabs: WorkbenchDockTab[] = [
  { id: 'sources', label: 'Sources', icon: '⇥' },
  { id: 'candidates', label: 'Candidates', icon: '◇' },
  { id: 'object_types', label: 'Object Types', icon: '□' },
  { id: 'properties', label: 'Properties', icon: '≣' },
  { id: 'relationships', label: 'Relationships', icon: '↔' },
  { id: 'validation', label: 'Validation', icon: '✓' },
  { id: 'templates', label: 'Templates', icon: '▤' },
];

export default function WorkbenchShell({ model, children, rightRail, bottomRail, toolbar = true, groupBy: controlledGroupBy, filters: controlledFilters, searchAroundEnabled, onGroupByChange, onFilterDirectiveChange, onSearchAround }: { model: WorkbenchModel; children: React.ReactNode; rightRail?: React.ReactNode; bottomRail?: React.ReactNode; toolbar?: boolean; groupBy?: string; filters?: string[]; searchAroundEnabled?: boolean; onGroupByChange?: (field: string) => void; onFilterDirectiveChange?: (facet: string, bucket: string, mode: 'include' | 'exclude') => void; onSearchAround?: () => void }) {
  const isSpecLens = model.metadata?.lens === 'spec';
  const tabs = isSpecLens ? specTabs : defaultTabs;
  const [activeTab, setActiveTab] = React.useState(isSpecLens ? 'object_types' : 'layers');
  React.useEffect(() => { setActiveTab(isSpecLens ? 'object_types' : 'layers'); }, [isSpecLens, model.id]);
  const [renderMode, setRenderMode] = React.useState<RenderMode>('extended');
  const [layoutMode, setLayoutModeState] = React.useState<LayoutMode>(() => { try { return (typeof window !== 'undefined' && window.localStorage ? (window.localStorage.getItem('workbench.layoutMode') as LayoutMode | null) : null) ?? 'auto'; } catch { return 'auto'; } });
  const [colorBy, setColorBy] = React.useState<ColorBy>('object_type');
  const [groupBy, setGroupBy] = React.useState('');
  const [activeFilters, setActiveFilters] = React.useState<string[]>([]);
  const displayedGroupBy = controlledGroupBy ?? groupBy;
  const displayedFilters = controlledFilters ?? activeFilters;
  const updateGroupBy = React.useCallback((field: string) => { setGroupBy(field); onGroupByChange?.(field); }, [onGroupByChange]);
  const updateFilterDirective = React.useCallback((facet: string, bucket: string, mode: 'include' | 'exclude') => {
    const label = `${facet}:${mode}:${bucket}`;
    setActiveFilters((current) => [...current.filter((item) => !item.startsWith(`${facet}:`)), label]);
    onFilterDirectiveChange?.(facet, bucket, mode);
  }, [onFilterDirectiveChange]);
  const setLayoutMode = React.useCallback((mode: LayoutMode) => { setLayoutModeState(mode); try { if (typeof window !== 'undefined' && window.localStorage) window.localStorage.setItem('workbench.layoutMode', mode); } catch { /* test/browser privacy mode: persistence is best effort */ } }, []);
  const [propertyName, setPropertyName] = React.useState('');
  const enhancedChildren = React.useMemo(() => {
    if (!React.isValidElement(children)) return children;
    if (typeof children.type === 'string') return children;
    return React.cloneElement(children as React.ReactElement<Record<string, unknown>>, { renderMode, layoutMode, colorBy, propertyName });
  }, [children, renderMode, layoutMode, colorBy, propertyName]);
  return (
    <section className="workbench-shell" data-testid="workbench-shell" data-workbench-model={model.id}>
      <style>{`
        .workbench-shell{display:flex;flex-direction:column;min-height:0;border:1px solid rgba(148,163,184,.3);border-radius:16px;overflow:hidden;background:#f8fafc}
        .wb-toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:8px;border-bottom:1px solid rgba(148,163,184,.35);background:white}.wb-toolbar button,.wb-toolbar select{border:1px solid #cbd5e1;border-radius:8px;padding:4px 8px;background:white}
        .wb-shell-grid{display:grid;grid-template-columns:220px minmax(0,1fr) 280px;min-height:0}.wb-dock{border-right:1px solid rgba(148,163,184,.35);background:white}.wb-dock-tabs{display:grid;gap:4px;padding:8px}.wb-dock button{border:1px solid transparent;border-radius:8px;background:transparent;padding:6px;text-align:left}.wb-dock button.active,.wb-dock button[aria-pressed=true]{border-color:#93c5fd;background:#eff6ff}.wb-dock-body,.wb-right,.wb-canvas{padding:10px;min-width:0;overflow:auto}.wb-right{border-left:1px solid rgba(148,163,184,.35);background:white}.wb-bottom{border-top:1px solid rgba(148,163,184,.35);background:white}.wb-swatches{display:flex;gap:4px}.swatch{border:1px solid #cbd5e1;border-radius:999px;padding:2px 6px;font-size:11px}.wb-histogram-row{display:grid;grid-template-columns:1fr 80px auto auto auto;gap:4px;align-items:center}
      `}</style>
      {toolbar ? <WorkbenchToolbar renderMode={renderMode} layoutMode={layoutMode} groupBy={String(model.metadata?.applied_group_by ?? displayedGroupBy)} colorBy={colorBy} filters={displayedFilters} searchAroundEnabled={searchAroundEnabled ?? Boolean(model.selection)} onRenderModeChange={setRenderMode} onLayoutModeChange={setLayoutMode} onGroupByChange={updateGroupBy} onSearchAround={onSearchAround} onClearAll={() => { updateGroupBy(''); setActiveFilters([]); onFilterDirectiveChange?.('', '', 'include'); }} /> : null}
      <div className="wb-shell-grid">
        <WorkbenchDock tabs={tabs} activeTab={activeTab} onTabChange={setActiveTab}>
          {!isSpecLens && activeTab === 'layers' ? <LayersStylingPanel layers={model.layers ?? []} colorBy={colorBy} propertyName={propertyName} onColorByChange={setColorBy} onPropertyNameChange={setPropertyName} /> : null}
          {!isSpecLens && activeTab === 'selection' ? <SelectionInspector model={model} selection={model.selection} /> : null}
          {!isSpecLens && activeTab === 'histogram' ? <HistogramPanel facets={model.facets ?? []} onFilterTo={(facet, bucket) => updateFilterDirective(facet, bucket, 'include')} onFilterOut={(facet, bucket) => updateFilterDirective(facet, bucket, 'exclude')} /> : null}
          {!isSpecLens && activeTab === 'search' ? <div data-testid="workbench-search-panel">Select a graph object, then use the toolbar Search Around control to expand a bounded 1-hop neighborhood (max 3 hops).</div> : null}
          {!isSpecLens && activeTab === 'info' ? <pre data-testid="workbench-info-panel">{JSON.stringify(model.metadata ?? {}, null, 2)}</pre> : null}
          {isSpecLens && activeTab === 'sources' ? <div data-testid="spec-sources-panel">{model.nodes.flatMap((node) => node.sources ?? []).length ? model.nodes.flatMap((node) => node.sources ?? []).map((source) => <div key={source}>{source}</div>) : 'No source mappings yet.'}</div> : null}
          {isSpecLens && activeTab === 'candidates' ? <div data-testid="spec-candidates-panel">Candidate staging is handled by the governance dock.</div> : null}
          {isSpecLens && activeTab === 'object_types' ? <div data-testid="spec-object-types-panel">{model.nodes.map((node) => <div key={node.id}>{node.label}</div>)}</div> : null}
          {isSpecLens && activeTab === 'properties' ? <div data-testid="spec-properties-panel">{model.nodes.map((node) => <div key={node.id}>{node.label}: {String(node.properties?.property_count ?? 0)} properties</div>)}</div> : null}
          {isSpecLens && activeTab === 'relationships' ? <div data-testid="spec-relationships-panel">{model.edges.map((edge) => <div key={edge.id}>{edge.label}</div>)}</div> : null}
          {isSpecLens && activeTab === 'validation' ? <div data-testid="spec-validation-panel">Validation rules: {String(model.metadata?.validation_rule_count ?? 0)}</div> : null}
          {isSpecLens && activeTab === 'templates' ? <div data-testid="spec-templates-panel">Templates stay staged until validate / diff / save.</div> : null}
        </WorkbenchDock>
        <main className="wb-canvas" data-render-mode={renderMode} data-layout-mode={layoutMode}>{enhancedChildren}</main>
        <aside className="wb-right">{rightRail ?? <SelectionInspector model={model} selection={model.selection} />}</aside>
      </div>
      {bottomRail ? <footer className="wb-bottom">{bottomRail}</footer> : null}
    </section>
  );
}
