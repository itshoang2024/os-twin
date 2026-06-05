import { test, expect, type Page } from '@playwright/test';

const screenshotDir = 'artifacts/qa-automation/screenshots';
const pageErrors = new WeakMap<Page, string[]>();

test.describe('EPIC-005 Map Lens truth states', () => {
  test.beforeEach(async ({ page }) => {
    const errors: string[] = [];
    pageErrors.set(page, errors);
    page.on('pageerror', (error) => {
      errors.push(error.message);
    });
    page.on('console', (message) => {
      if (message.type() === 'error') {
        throw new Error(`Console error: ${message.text()}`);
      }
    });
    page.on('response', (response) => {
      const status = response.status();
      const url = response.url();
      if (status >= 400 && !url.includes('/__nextjs')) {
        throw new Error(`Network failure ${status}: ${url}`);
      }
    });
  });

  test.afterEach(async ({ page }) => {
    expect(pageErrors.get(page) ?? []).toEqual([]);
    pageErrors.delete(page);
  });

  test('live state renders confirmed graph without example or empty messaging', async ({ page }) => {
    await page.goto('/knowledge/enterprise-map-fixture?state=live');
    await expect(page.getByTestId('fixture-truth-state')).toHaveText('live');
    await expect(page.getByTestId('enterprise-map-panel')).toBeVisible();
    await expect(page.getByTestId('enterprise-map-graph')).toBeVisible();
    await expect(page.getByTestId('enterprise-node-risk-1')).toBeVisible();
    await expect(page.getByText('[Example Data]')).toHaveCount(0);
    await expect(page.getByText('No graph objects yet')).toHaveCount(0);
    await page.screenshot({ path: `${screenshotDir}/epic-005-live-state.png`, fullPage: true });
  });

  test('example state preserves explicit Example Data banner', async ({ page }) => {
    await page.goto('/knowledge/enterprise-map-fixture?state=example');
    await expect(page.getByTestId('fixture-truth-state')).toHaveText('example');
    await expect(page.getByTestId('enterprise-map-example-banner')).toContainText('[Example Data]');
    await expect(page.getByTestId('enterprise-map-graph')).toBeVisible();
    await expect(page.getByTestId('enterprise-node-example-risk-1')).toBeVisible();
    await expect(page.getByText('No graph objects yet')).toHaveCount(0);
    await page.screenshot({ path: `${screenshotDir}/epic-005-example-state.png`, fullPage: true });
  });

  test('empty state stays empty and exposes import, approve, and sample actions', async ({ page }) => {
    await page.goto('/knowledge/enterprise-map-fixture?state=empty');
    await expect(page.getByTestId('fixture-truth-state')).toHaveText('empty');
    await expect(page.getByTestId('enterprise-map-empty-state')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'No graph objects yet' })).toBeVisible();
    await expect(page.getByTestId('enterprise-map-empty-import')).toBeVisible();
    await expect(page.getByTestId('enterprise-map-empty-approve')).toBeVisible();
    await expect(page.getByTestId('enterprise-map-empty-sample')).toBeVisible();
    await expect(page.getByTestId('enterprise-map-example-banner')).toHaveCount(0);
    await expect(page.getByTestId('enterprise-map-graph')).toHaveCount(0);
    await page.screenshot({ path: `${screenshotDir}/epic-005-empty-state.png`, fullPage: true });
  });
});
