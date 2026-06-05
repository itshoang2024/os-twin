import { Suspense } from 'react';
import FactReviewFixturePanel from '@/components/knowledge/nexus/FactReviewFixturePanel';
import FactReviewFixtureRoute from '@/components/knowledge/nexus/FactReviewFixtureRoute';

export const metadata = { title: 'Facts Review Fixture | Ostwin' };

export default function FactsFixturePage() {
  return (
    <Suspense fallback={<FactReviewFixturePanel />}>
      <FactReviewFixtureRoute />
    </Suspense>
  );
}
