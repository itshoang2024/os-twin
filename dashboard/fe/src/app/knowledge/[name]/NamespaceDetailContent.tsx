'use client';

import { useSearchParams, usePathname } from 'next/navigation';
import KnowledgeTabCore from '@/components/knowledge/KnowledgeTabCore';

/**
 * Extract namespace name from a pathname like /knowledge/{name}.
 * Returns '' if the name is missing or is the static-export placeholder '_'.
 */
function extractNamespace(pathname: string): string {
  const segments = pathname.split('/');
  const idx = segments.indexOf('knowledge');
  if (idx >= 0 && segments[idx + 1]) {
    const name = decodeURIComponent(segments[idx + 1]);
    return name === '_' ? '' : name;
  }
  return '';
}

/**
 * Client component that reads route params and renders the detail view.
 */
export default function NamespaceDetailContent() {
  const searchParams = useSearchParams();
  const pathname = usePathname();

  // usePathname() may return the static-export placeholder path (/knowledge/_)
  // during initial hydration. Fall back to window.location.pathname which always
  // reflects the real browser URL.
  const namespaceName = typeof window !== 'undefined'
    ? extractNamespace(window.location.pathname) || extractNamespace(pathname)
    : extractNamespace(pathname);

  // Optional tab query param: /knowledge/my-ns?tab=import
  const tabParam = searchParams.get('tab');
  const defaultTab = tabParam === 'import' ? 'import' as const
    : tabParam === 'research' ? 'research' as const
    : tabParam === 'nexus' ? 'nexus' as const
    : tabParam === 'ontology' ? 'ontology' as const
    : tabParam === 'enterprise-map' ? 'enterprise-map' as const
    : undefined;

  if (!namespaceName) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center space-y-3">
          <span
            className="material-symbols-outlined text-[48px]"
            style={{ color: 'var(--color-text-muted)' }}
          >
            error
          </span>
          <p className="text-sm font-medium" style={{ color: 'var(--color-text-main)' }}>
            Invalid Namespace
          </p>
          <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            No namespace name was provided in the URL.
          </p>
        </div>
      </div>
    );
  }

  return (
    <KnowledgeTabCore
      headerVariant="minimal"
      className="h-full"
      defaultNamespace={namespaceName}
      defaultTab={defaultTab}
    />
  );
}
