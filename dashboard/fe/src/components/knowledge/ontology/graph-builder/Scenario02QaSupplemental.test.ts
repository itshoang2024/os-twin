import { describe, expect, it } from 'vitest';
import {
  getProjectionFixture,
  mockErrorFixtures,
  mockExpandResponse,
  mockSearchResults,
} from './mock-fixtures';

const CANONICAL_SCENARIO_09_CODES = new Set([
  'NOT_FOUND',
  'UNAUTHORIZED',
  'FORBIDDEN',
  'VALIDATION_FAILED',
  'CONFLICT',
  'GRAPH_TOO_LARGE',
  'TIMEOUT',
  'REDACTED',
  'CAP_EXCEEDED',
  'INVALID_TRAVERSAL',
  'SCHEMA_INCOMPATIBLE',
  'FEATURE_DISABLED',
]);

const SENSITIVE_PROBE = /ssn|secret|secret-token|password|dateOfBirth|access[_-]?token|refresh[_-]?token/i;

function expectProjectionEnvelope(value: unknown) {
  expect(value).toEqual(expect.objectContaining({
    nodes: expect.any(Array),
    edges: expect.any(Array),
    stats: expect.any(Object),
    meta: expect.any(Object),
  }));
}

describe('Scenario 02 QA supplemental contract audit', () => {
  it('keeps every mock API error in the canonical Scenario 09 code vocabulary', () => {
    for (const [fixtureName, fixture] of Object.entries(mockErrorFixtures)) {
      expect(fixture, fixtureName).toEqual(expect.objectContaining({
        error: expect.objectContaining({
          code: expect.any(String),
          message: expect.any(String),
        }),
      }));
      expect(fixture, fixtureName).toHaveProperty('request_id');
      expect(fixture, fixtureName).not.toHaveProperty('meta');
      expect(CANONICAL_SCENARIO_09_CODES.has(fixture.error.code), `${fixtureName} uses non-canonical code ${fixture.error.code}`).toBe(true);
    }
  });

  it('keeps redacted projection/search objects property-empty and free of sensitive probes', () => {
    const redactedProjection = getProjectionFixture('redacted', 'qa-contract-ns');
    for (const node of redactedProjection.nodes.filter((item) => item.redacted)) {
      expect(node.properties).toEqual({});
      expect(JSON.stringify(node)).not.toMatch(SENSITIVE_PROBE);
    }
    for (const edge of redactedProjection.edges.filter((item) => item.redacted)) {
      expect(edge.properties).toEqual({});
      expect(JSON.stringify(edge)).not.toMatch(SENSITIVE_PROBE);
    }
    for (const result of mockSearchResults.results.filter((item) => item.redacted)) {
      expect(result.properties).toEqual({});
      expect(JSON.stringify(result)).not.toMatch(SENSITIVE_PROBE);
    }
  });

  it('keeps expand fixture projection-shaped instead of raw internal graph-shaped', () => {
    expectProjectionEnvelope(mockExpandResponse);
    expect(mockExpandResponse).not.toHaveProperty('adjacency');
    expect(mockExpandResponse).not.toHaveProperty('graph');
    expect(mockExpandResponse).not.toHaveProperty('raw_nodes');
    expect(mockExpandResponse).not.toHaveProperty('raw_edges');
  });

  it('keeps capped projection metadata explicit in stats and meta', () => {
    const capped = getProjectionFixture('large', 'qa-contract-ns');
    expect(capped.stats.truncated).toBe(true);
    expect(capped.meta.truncated).toBe(true);
    expect(capped.stats.node_cap ?? capped.stats.limit).toBeGreaterThan(0);
    expect(capped.meta.node_cap ?? capped.meta.limit).toBeGreaterThan(0);
    expect([...(capped.stats.warnings ?? []), ...(capped.meta.warnings ?? [])].length).toBeGreaterThan(0);
  });
});
