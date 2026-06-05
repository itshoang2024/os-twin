import React from 'react';
import type { WorkbenchFacet } from './model/workbenchModel';

export function HistogramPanel({ facets, onFilterTo, onFilterOut }: { facets: WorkbenchFacet[]; onFilterTo?: (facetId: string, bucketId: string) => void; onFilterOut?: (facetId: string, bucketId: string) => void }) {
  return <section data-testid="workbench-histogram-panel"><h3>Histogram</h3>{facets.map((facet) => <div key={facet.id}><strong>{facet.label}</strong>{facet.buckets.map((bucket) => <div key={bucket.id} className="wb-histogram-row"><span>{bucket.label} ({bucket.count})</span><button type="button" onClick={() => onFilterTo?.(facet.id, bucket.id)}>Filter to</button><button type="button" onClick={() => onFilterOut?.(facet.id, bucket.id)}>Filter out</button></div>)}</div>)}</section>;
}

export default HistogramPanel;
