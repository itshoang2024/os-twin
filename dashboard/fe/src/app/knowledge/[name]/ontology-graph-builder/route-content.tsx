'use client';

import { usePathname, useSearchParams } from 'next/navigation';
import OntologyGraphBuilderPage from '@/components/knowledge/ontology/graph-builder/OntologyGraphBuilderPage';
import type { GraphFixtureKey } from '@/components/knowledge/ontology/graph-builder/types';

function extractNamespace(pathname: string): string {
  const segments = pathname.split('/');
  const idx = segments.indexOf('knowledge');
  if (idx >= 0 && segments[idx + 1]) {
    const name = decodeURIComponent(segments[idx + 1]);
    return name === '_' ? '' : name;
  }
  return '';
}

function parseFixture(value: string | null): GraphFixtureKey {
  return value === 'empty' || value === 'redacted' || value === 'large' || value === 'error' || value === 'basic' ? value : 'basic';
}

export default function OntologyGraphBuilderRouteContent() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const namespace = extractNamespace(pathname) || (typeof window !== 'undefined' ? extractNamespace(window.location.pathname) : '');

  if (!namespace) {
    return <div className="flex h-full items-center justify-center text-sm text-slate-300">Invalid namespace for graph builder.</div>;
  }

  return <OntologyGraphBuilderPage namespace={namespace} initialFixture={parseFixture(searchParams.get('fixture'))} />;
}
