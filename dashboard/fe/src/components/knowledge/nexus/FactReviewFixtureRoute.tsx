'use client';

import { useSearchParams } from 'next/navigation';
import FactReviewFixturePanel from './FactReviewFixturePanel';

function isEnabled(value: string | null): boolean {
  return value === '1' || value === 'true';
}

export default function FactReviewFixtureRoute() {
  const params = useSearchParams();
  return (
    <FactReviewFixturePanel
      promoted={isEnabled(params.get('promoted'))}
      candidate={isEnabled(params.get('candidate'))}
      approved={isEnabled(params.get('approved'))}
      rejected={isEnabled(params.get('rejected'))}
    />
  );
}
