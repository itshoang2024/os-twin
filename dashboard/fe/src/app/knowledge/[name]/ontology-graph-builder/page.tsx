import { Suspense } from 'react';
import OntologyGraphBuilderRouteContent from './route-content';

export function generateStaticParams() {
  return [{ name: '_' }];
}

export default function OntologyGraphBuilderRoutePage() {
  return (
    <div className="h-[calc(100vh-56px)] bg-slate-950">
      <Suspense fallback={<div className="flex h-full items-center justify-center text-sm text-slate-300">Loading graph builder…</div>}>
        <OntologyGraphBuilderRouteContent />
      </Suspense>
    </div>
  );
}
