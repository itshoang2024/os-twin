import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

const navState = vi.hoisted(() => ({ path: '/knowledge/ontology-fixture', search: '' }));

vi.mock('next/navigation', () => ({
  usePathname: () => navState.path,
  useSearchParams: () => new URLSearchParams(navState.search),
}));

vi.mock('@/components/knowledge/KnowledgeTabCore', () => ({
  default: (props: { defaultNamespace?: string; defaultTab?: string }) => (
    <div aria-label="mock knowledge core">
      namespace:{props.defaultNamespace}; tab:{props.defaultTab ?? 'none'}
    </div>
  ),
}));

import NamespaceDetailContent from '@/app/knowledge/[name]/NamespaceDetailContent';

describe('NamespaceDetailContent ontology routing', () => {
  it('opens the ontology workbench for the QA ontology fixture route without a query string', () => {
    navState.path = '/knowledge/ontology-fixture';
    navState.search = '';
    window.history.pushState({}, '', '/knowledge/ontology-fixture');

    render(<NamespaceDetailContent />);

    expect(screen.getByLabelText('mock knowledge core')).toHaveTextContent('namespace:ontology-fixture; tab:ontology');
  });

  it('honors tab=ontology for real knowledge namespaces', () => {
    navState.path = '/knowledge/retention-test';
    navState.search = 'tab=ontology';
    window.history.pushState({}, '', '/knowledge/retention-test?tab=ontology');

    render(<NamespaceDetailContent />);

    expect(screen.getByLabelText('mock knowledge core')).toHaveTextContent('namespace:retention-test; tab:ontology');
  });
});
