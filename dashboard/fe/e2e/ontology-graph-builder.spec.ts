import { expect, test, type Page } from '@playwright/test';

async function mockAuth(page: Page) {
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ username: 'qa-automation' }),
    });
  });
}

async function gotoFixture(page: Page, fixture: 'basic' | 'empty' | 'redacted' | 'large' | 'error' = 'basic') {
  await page.goto(`/knowledge/qa-namespace/ontology-graph-builder?fixture=${fixture}`);
  await expect(page.getByTestId('ontology-graph-builder-page').last()).toBeVisible();
}

test.describe('Ontology Graph Builder Scenario 03 MVP', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page);
  });

  test('selects a node, hydrates detail, searches/adds without duplicate nodes, expands, filters, and uses layout/fit controls', async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error' && !/401|favicon|webpack-hmr|api\/ws/.test(message.text())) pageErrors.push(message.text());
    });

    await gotoFixture(page, 'basic');
    const builder = page.getByTestId('ontology-graph-builder-page').last();
    const canvas = builder.getByTestId('graph-canvas');
    await expect(canvas).toBeVisible();
    await expect(builder.getByTestId('visible-node-count')).toHaveText('3');

    await canvas.getByRole('button', { name: /Customer Account/ }).click();
    await expect(builder.getByTestId('expand-node-button')).toBeEnabled();
    await builder.getByTestId('inspector-tab-properties').click();
    await expect(builder.getByTestId('selection-inspector')).toContainText('Data Stewardship');

    await builder.getByRole('button', { name: 'Search objects' }).click();
    await expect(builder.getByTestId('search-modal')).toBeVisible();
    const rows = builder.getByTestId('search-result-row');
    await expect(rows).toHaveCount(3);
    await rows.nth(0).getByRole('checkbox').check();
    await rows.nth(1).getByRole('checkbox').check();
    await builder.getByTestId('add-to-graph-button').click();
    await expect(builder.getByTestId('search-modal')).toHaveCount(0);
    await expect(builder.getByTestId('visible-node-count')).toHaveText('5');
    await expect(canvas.getByRole('button', { name: /Agent Session/ })).toHaveCount(1);
    await expect(canvas.getByRole('button', { name: /Knowledge Namespace/ })).toHaveCount(1);

    await builder.getByRole('button', { name: 'Search objects' }).click();
    await rows.nth(0).getByRole('checkbox').check();
    await rows.nth(1).getByRole('checkbox').check();
    await builder.getByTestId('add-to-graph-button').click();
    await expect(builder.getByTestId('visible-node-count')).toHaveText('5');
    await expect(canvas.getByRole('button', { name: /Agent Session/ })).toHaveCount(1);
    await expect(canvas.getByRole('button', { name: /Knowledge Namespace/ })).toHaveCount(1);

    await builder.getByTestId('expand-node-button').click();
    await expect(canvas.getByRole('button', { name: /observed in/ })).toBeVisible();
    await expect(builder.getByTestId('visible-node-count')).toHaveText('5');
    await expect(canvas.getByRole('button', { name: /Agent Session/ })).toHaveCount(1);

    await builder.getByTestId('filter-chip').filter({ hasText: 'Claim' }).click();
    await expect(builder.getByTestId('visible-node-count')).toHaveText('1');
    await expect(canvas.getByRole('button', { name: /Claim Event/ })).toBeVisible();
    await expect(canvas.getByRole('button', { name: /Customer Account/ })).toHaveCount(0);
    await builder.getByRole('button', { name: 'Clear' }).click();
    await expect(builder.getByTestId('visible-node-count')).toHaveText('5');
    await expect(canvas.getByRole('button', { name: /Agent Session/ })).toHaveCount(1);
    await expect(canvas.getByRole('button', { name: /Knowledge Namespace/ })).toHaveCount(1);
    await expect(canvas.getByRole('button', { name: /observed in/ })).toBeVisible();

    await builder.getByTestId('layout-preset-control').selectOption('layered');
    await expect(builder.getByTestId('layout-preset-control')).toHaveValue('layered');
    const beforeFit = await canvas.getAttribute('data-fit-nonce');
    await builder.getByTestId('fit-view-button').click();
    await expect.poll(async () => canvas.getAttribute('data-fit-nonce')).not.toBe(beforeFit);

    await expect(builder.getByTestId('toolbar-save-graph-button')).toBeEnabled();
    await expect(builder.getByTestId('toolbar-save-as-button')).toBeEnabled();
    await expect(builder.getByRole('combobox', { name: 'Governance role' })).toHaveValue('steward');
    await expect(builder.getByTestId('governance-validate-button')).toBeEnabled();
    await expect(builder.getByTestId('governance-approval-queue-button')).toBeDisabled();
    expect(pageErrors).toEqual([]);
  });

  test('empty, error, redacted, and large fixtures expose required Scenario 03 states', async ({ page }) => {
    await gotoFixture(page, 'empty');
    await expect(page.getByTestId('ontology-graph-builder-page').last().getByTestId('graph-empty-state')).toBeVisible();

    await gotoFixture(page, 'error');
    const errorBuilder = page.getByTestId('ontology-graph-builder-page').last();
    await expect(errorBuilder.getByTestId('graph-error-state')).toBeVisible();
    await expect(errorBuilder.getByTestId('retry-button')).toBeVisible();

    await gotoFixture(page, 'redacted');
    const redactedBuilder = page.getByTestId('ontology-graph-builder-page').last();
    await redactedBuilder.getByTestId('redacted-node').click();
    await redactedBuilder.getByTestId('inspector-tab-properties').click();
    await expect(redactedBuilder.getByText('Properties redacted by permission policy.')).toBeVisible();
    const bodyText = await page.locator('body').innerText();
    expect(bodyText).not.toMatch(/123-45-6789|secret-token|\bssn\b/i);

    await gotoFixture(page, 'large');
    await expect(page.getByTestId('ontology-graph-builder-page').last().getByTestId('truncation-warning')).toBeVisible();
  });

  test('mobile viewport smoke renders the graph builder shell without crashing', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await gotoFixture(page, 'basic');
    await expect(page.getByTestId('ontology-graph-builder-page').last()).toBeVisible();
    await expect(page.getByText('Enterprise map projection').first()).toBeVisible();
  });


  test('Scenario 04 object sets and Search Around flow creates, compares, validates, previews, and merges traversal results', async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error' && !/401|favicon|webpack-hmr|api\/ws/.test(message.text())) pageErrors.push(message.text());
    });

    await gotoFixture(page, 'basic');
    const builder = page.getByTestId('ontology-graph-builder-page').last();
    const canvas = builder.getByTestId('graph-canvas');
    await expect(canvas).toBeVisible();
    await expect(builder.getByTestId('object-set-picker')).toBeVisible();
    await expect(builder.getByTestId('saved-object-set-panel')).toBeVisible();
    await expect(builder.getByTestId('search-around-panel')).toBeVisible();
    await expect(builder.getByTestId('relationship-type-picker')).toBeVisible();
    await expect(builder.getByTestId('direction-picker')).toBeVisible();
    await expect(builder.getByTestId('traversal-step')).toHaveCount(1);
    await expect(builder.getByTestId('traversal-preview-summary')).toContainText('Preview before running traversal');

    await canvas.getByRole('button', { name: /Customer Account/ }).click();
    await builder.getByTestId('create-object-set-button').click();
    await expect(builder.getByText('Customer Account selection').last()).toBeVisible();

    await builder.getByRole('button', { name: 'Search objects' }).click();
    const modal = builder.getByTestId('search-modal');
    await expect(modal.getByTestId('create-object-set-button')).toBeDisabled();
    const rows = modal.getByTestId('search-result-row');
    await rows.nth(0).getByRole('checkbox').check();
    await rows.nth(1).getByRole('checkbox').check();
    await modal.getByTestId('create-object-set-button').click();
    await expect(modal).toHaveCount(0);
    await expect(builder.getByText('Search result object set').last()).toBeVisible();

    await builder.getByRole('button', { name: /Claims review set/ }).click();
    await expect(builder.getByTestId('object-set-compare-summary')).toContainText('Added');
    await expect(builder.getByTestId('object-set-compare-summary')).toContainText('Removed');
    await expect(builder.getByTestId('object-set-compare-summary')).toContainText('Overlap');

    await builder.getByTestId('relationship-type-picker').selectOption('generates');
    await builder.getByTestId('direction-picker').selectOption('inbound');
    await expect(builder.getByTestId('validation-issue')).toContainText('incompatible');
    await expect(builder.getByTestId('run-traversal-button')).toBeDisabled();

    await builder.getByTestId('relationship-type-picker').selectOption('observed_in');
    await builder.getByTestId('direction-picker').selectOption('outbound');
    await builder.getByRole('button', { name: 'Preview' }).click();
    await expect(builder.getByTestId('traversal-preview-summary')).toContainText('objects');
    await expect(builder.getByTestId('traversal-preview-summary')).toContainText('Result capped/truncated');

    await builder.getByTestId('run-traversal-button').click();
    await expect(builder.getByTestId('add-traversal-to-graph-button')).toBeEnabled();
    await builder.getByTestId('add-traversal-to-graph-button').click();
    await expect(builder.getByTestId('visible-node-count')).toHaveText('4');
    await expect(canvas.getByRole('button', { name: /Agent Session/ })).toHaveCount(1);
    await builder.getByTestId('add-traversal-to-graph-button').click();
    await expect(builder.getByTestId('visible-node-count')).toHaveText('4');
    await expect(canvas.getByRole('button', { name: /Agent Session/ })).toHaveCount(1);

    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario04-playwright-flow.png', fullPage: true });
    expect(pageErrors).toEqual([]);
  });


  test('Scenario 05 instance authoring creates, validates, links, deletes, and enforces read-only state', async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error' && !/401|favicon|webpack-hmr|api\/ws/.test(message.text())) pageErrors.push(message.text());
    });
    await page.setViewportSize({ width: 1440, height: 1200 });

    await gotoFixture(page, 'basic');
    const builder = page.getByTestId('ontology-graph-builder-page').last();
    const canvas = builder.getByTestId('graph-canvas');

    await builder.getByTestId('open-instance-create-button').click();
    let objectModal = page.getByTestId('instance-create-modal');
    await expect(objectModal).toBeVisible();
    await expect(objectModal.getByTestId('required-field')).toHaveCount(2);
    await objectModal.getByTestId('save-instance-button').click();
    await expect(objectModal.getByTestId('field-validation-error')).toHaveCount(2);
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario05-playwright-object-validation.png', fullPage: true });

    await objectModal.getByLabel(/Customer name/).fill('Customer Account');
    await objectModal.getByLabel(/Stable ID/).fill('customer');
    await expect(objectModal.getByTestId('dirty-state-indicator')).toContainText('Unsaved draft changes');
    await expect(objectModal.getByTestId('duplicate-detection-panel')).toContainText('may be the same identity');
    await expect(objectModal.getByTestId('identity-resolution-panel')).toBeVisible();
    await objectModal.getByText('Attach').click();
    await objectModal.getByText('Link source').click();
    await expect(objectModal.getByTestId('evidence-attachment-panel')).toContainText('evidence://crm/customer-row-42');
    await expect(objectModal.getByTestId('source-record-linker')).toContainText('source://crm/accounts/42');
    await objectModal.getByTestId('save-instance-button').click();
    await expect(objectModal).toHaveCount(0);
    await expect(builder.getByTestId('audit-event-link')).toContainText('audit-object-create');
    await expect(builder.getByTestId('visible-node-count')).toHaveText('4');

    await canvas.getByRole('button', { name: /Customer Account/ }).last().click();
    await builder.getByRole('button', { name: 'Edit selected object' }).click();
    objectModal = page.getByTestId('instance-edit-form');
    await objectModal.getByLabel(/Customer name/).fill('Customer Account Edited');
    await expect(objectModal.getByTestId('dirty-state-indicator')).toContainText('Unsaved draft changes');
    await objectModal.getByRole('button', { name: 'Rollback draft' }).click();
    await expect(objectModal.getByTestId('dirty-state-indicator')).toContainText('Draft matches saved state');
    await objectModal.getByLabel(/Customer name/).fill('Customer Account Edited');
    await objectModal.getByTestId('save-instance-button').click();
    await expect(objectModal).toHaveCount(0);
    await expect(builder.getByTestId('audit-event-link')).toContainText('audit-object-update');
    await expect(canvas.getByRole('button', { name: /Customer Account Edited/ })).toBeVisible();

    await builder.getByTestId('open-relationship-create-button').click();
    let relationshipModal = page.getByTestId('relationship-create-modal');
    await relationshipModal.getByLabel(/Source/).selectOption('object.customer');
    await relationshipModal.getByLabel(/Target/).selectOption('object.policy');
    await relationshipModal.getByLabel(/Relationship type/).selectOption('generates');
    await relationshipModal.getByTestId('save-instance-button').click();
    await expect(relationshipModal.getByTestId('field-validation-error')).toContainText('incompatible');
    await relationshipModal.getByLabel(/Relationship type/).selectOption('owns');
    await relationshipModal.getByTestId('save-instance-button').click();
    await expect(relationshipModal.getByTestId('field-validation-error')).toContainText('Cardinality violation');
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario05-playwright-relationship-blocked.png', fullPage: true });
    await relationshipModal.getByText('Cancel').click();

    await builder.getByRole('button', { name: 'Search objects' }).click();
    let searchModal = page.getByTestId('search-modal');
    await searchModal.getByTestId('search-result-row').nth(0).getByRole('checkbox').check();
    await searchModal.getByTestId('add-to-graph-button').click();
    await expect(searchModal).toHaveCount(0);

    await builder.getByTestId('open-relationship-create-button').click();
    relationshipModal = page.getByTestId('relationship-create-modal');
    await relationshipModal.getByLabel(/Relationship type/).selectOption('observed_in');
    await relationshipModal.getByLabel(/Target/).selectOption('object.agent-session');
    await relationshipModal.getByTestId('save-instance-button').click();
    await expect(relationshipModal).toHaveCount(0);
    await expect(builder.getByTestId('audit-event-link')).toContainText('audit-relationship-create');
    await expect(canvas.getByRole('button', { name: /observed in/ })).toBeVisible();
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario05-playwright-compatible-edge.png', fullPage: true });

    await canvas.getByRole('button', { name: /observed in/ }).click();
    await builder.getByRole('button', { name: 'Edit selected relationship' }).click();
    const editRelationship = page.getByTestId('relationship-edit-form');
    await editRelationship.getByRole('button', { name: 'Delete' }).click();
    await expect(canvas.getByRole('button', { name: /observed in/ })).toHaveCount(0);
    await expect(builder.getByTestId('audit-event-link')).toContainText('audit-relationship-delete');

    await builder.getByRole('button', { name: 'Search objects' }).click();
    searchModal = page.getByTestId('search-modal');
    await searchModal.getByTestId('search-result-row').nth(2).getByRole('checkbox').check();
    await searchModal.getByTestId('add-to-graph-button').click();
    await expect(searchModal).toHaveCount(0);
    await canvas.getByRole('button', { name: /Restricted Person/ }).click();
    await expect(builder.getByTestId('permission-denied-state')).toContainText('read-only');
    await expect(builder.getByRole('button', { name: 'Edit selected object' })).toBeDisabled();
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario05-playwright-readonly.png', fullPage: true });

    expect(pageErrors).toEqual([]);
  });


  test('Scenario 06 governance validates, approves, publishes, lineages, reverts, and enforces readonly history', async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error' && !/401|favicon|webpack-hmr|api\/ws/.test(message.text())) pageErrors.push(message.text());
    });
    await page.setViewportSize({ width: 1440, height: 1200 });

    await gotoFixture(page, 'basic');
    const builder = page.getByTestId('ontology-graph-builder-page').last();
    const canvas = builder.getByTestId('graph-canvas');
    await expect(builder.getByTestId('validation-summary-banner')).toContainText('Errors 1');
    await expect(builder.getByTestId('changeset-diff-preview')).toContainText('Policy Contract.owner');
    await expect(builder.getByTestId('approval-queue')).toContainText('No submitted changesets');

    await builder.getByTestId('validation-issue-row').first().click();
    await expect(builder.getByTestId('focused-graph-element')).toContainText('Policy Contract');
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario06-playwright-focused-issue.png', fullPage: true });

    await expect(builder.getByRole('button', { name: 'Submit' })).toBeDisabled();
    await builder.getByTestId('validation-summary-banner').getByRole('button', { name: 'Validate' }).click();
    await expect(builder.getByTestId('validation-summary-banner')).toContainText('Errors 0');
    await expect(builder.getByRole('button', { name: 'Submit' })).toBeEnabled();
    await builder.getByRole('button', { name: 'Submit' }).click();
    await expect(builder.getByTestId('approval-queue')).toContainText('1 submitted');

    await builder.getByLabel('Governance role').selectOption('approver');
    await builder.getByRole('button', { name: 'Approval queue' }).click();
    const approvalModal = page.getByTestId('approval-decision-modal');
    await approvalModal.getByLabel('Decision').selectOption('reject');
    await expect(approvalModal.getByText('Reject comment required.')).toBeVisible();
    await expect(approvalModal.getByRole('button', { name: 'Submit decision' })).toBeDisabled();
    await approvalModal.getByLabel('Decision').selectOption('approve');
    await approvalModal.getByTestId('approval-comment-input').fill('Approved with Playwright evidence.');
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario06-playwright-approval-modal.png', fullPage: true });
    await approvalModal.getByRole('button', { name: 'Submit decision' }).click();
    await expect(approvalModal).toHaveCount(0);
    await expect(builder.getByTestId('audit-timeline')).toContainText('changeset.approved');

    await builder.getByLabel('Governance role').selectOption('steward');
    await builder.getByTestId('open-publish-dialog-button').click();
    const publishDialog = page.getByTestId('publish-dialog');
    await expect(publishDialog.getByTestId('publish-diff-preview')).toContainText('Canonical source evidence');
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario06-playwright-publish-dialog.png', fullPage: true });
    await publishDialog.getByRole('button', { name: 'Publish version' }).click();
    await expect(publishDialog).toHaveCount(0);
    await expect(builder.getByTestId('audit-timeline')).toContainText('version.published');

    await builder.getByLabel('Version view').selectOption('version-3');
    await expect(builder.getByTestId('historical-version-readonly-banner')).toContainText('immutable and readonly');
    await expect(builder.getByTestId('open-instance-create-button')).toBeDisabled();
    await expect(builder.getByTestId('open-relationship-create-button')).toBeDisabled();
    await expect(builder.getByRole('button', { name: 'Edit selected object' })).toBeDisabled();
    await canvas.getByRole('button', { name: 'owns' }).click();
    await expect(builder.getByRole('button', { name: 'Edit selected relationship' })).toBeDisabled();
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario06-playwright-historical-readonly.png', fullPage: true });

    await canvas.getByRole('button', { name: /Policy Contract/ }).click();
    await builder.getByTestId('lineage-tab').click();
    await expect(builder.getByText(/Upstream:/)).toBeVisible();
    await expect(builder.getByText(/Downstream:/)).toBeVisible();
    await expect(builder.getByText(/Sources:/)).toBeVisible();

    await builder.getByLabel('Version view').selectOption('current');
    await builder.getByRole('button', { name: 'Revert' }).click();
    const revertDialog = page.getByTestId('revert-dialog');
    await expect(revertDialog).toBeVisible();
    await revertDialog.getByRole('button', { name: 'Create new revert version' }).click();
    await expect(revertDialog).toHaveCount(0);
    await expect(builder.getByTestId('audit-timeline')).toContainText('version.revert_created');
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario06-playwright-revert-audit.png', fullPage: true });

    expect(pageErrors).toEqual([]);
  });


  test('Scenario 07 saved graphs restore state, create history, duplicate, and enforce readonly versions', async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error' && !/401|favicon|webpack-hmr|api\/ws/.test(message.text())) pageErrors.push(message.text());
    });
    await page.setViewportSize({ width: 1440, height: 1200 });

    await gotoFixture(page, 'basic');
    const builder = page.getByTestId('ontology-graph-builder-page').last();
    await expect(builder.getByTestId('saved-graphs-panel')).toBeVisible();
    await expect(builder.getByTestId('saved-selections-panel')).toBeVisible();
    await expect(builder.getByTestId('saved-styles-panel')).toBeVisible();
    await expect(builder.getByTestId('style-legend')).toBeVisible();
    await expect(builder.getByTestId('graph-history-sidebar')).toBeVisible();
    await expect(builder.getByTestId('version-diff-viewer')).toBeVisible();
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario07-playwright-baseline.png', fullPage: true });

    await builder.getByRole('button', { name: 'Search objects' }).click();
    const searchModal = builder.getByTestId('search-modal');
    const rows = searchModal.getByTestId('search-result-row');
    await rows.nth(0).getByRole('checkbox').check();
    await rows.nth(1).getByRole('checkbox').check();
    await searchModal.getByTestId('add-to-graph-button').click();
    await expect(searchModal).toHaveCount(0);
    await expect(builder.getByTestId('visible-node-count')).toHaveText('5');
    await builder.getByTestId('filter-chip').filter({ hasText: 'Claim' }).click();
    await expect(builder.getByTestId('visible-node-count')).toHaveText('1');
    await builder.getByTestId('saved-styles-panel').getByRole('button', { name: /Risk review palette/ }).click();

    await builder.getByRole('button', { name: 'Save as' }).first().click();
    const saveModal = page.getByTestId('save-as-modal');
    await expect(saveModal).toBeVisible();
    await expect(saveModal.getByText('Name is required.')).toBeVisible();
    await saveModal.getByLabel('Graph name').fill('Scenario 07 Saved Graph');
    await saveModal.getByRole('button', { name: 'Save graph' }).click();
    await expect(saveModal).toHaveCount(0);
    const savedPanel = builder.getByTestId('saved-graphs-panel');
    await expect(savedPanel).toContainText('Scenario 07 Saved Graph');
    await expect(savedPanel).toContainText('Missing/deleted refs: object.deleted-demo was deleted');
    await expect(builder.getByTestId('graph-history-sidebar')).toContainText('v1 Scenario 07 Saved Graph');
    await expect(builder.getByTestId('version-diff-viewer')).toContainText('Visible nodes');

    await builder.getByRole('button', { name: 'Clear' }).click();
    await expect(builder.getByTestId('visible-node-count')).toHaveText('5');
    await savedPanel.getByRole('button', { name: /Scenario 07 Saved Graph/ }).click();
    await expect(builder.getByTestId('visible-node-count')).toHaveText('1');
    await builder.getByRole('button', { name: 'Clear' }).click();
    await builder.getByRole('button', { name: 'Save graph' }).first().click();
    await expect(builder.getByTestId('graph-history-sidebar')).toContainText('v2 Scenario 07 Saved Graph');

    await builder.getByTestId('duplicate-graph-button').first().click();
    await expect(savedPanel).toContainText('Scenario 07 Saved Graph copy');
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario07-playwright-save-history.png', fullPage: true });
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario07-rerun-p1-current-actions.png', fullPage: true });

    await builder.getByRole('button', { name: /v1 Scenario 07 Saved Graph/ }).click();
    await expect(builder.getByTestId('historical-version-readonly-banner')).toContainText('immutable and readonly');
    await expect(builder.getByRole('button', { name: 'Save graph' }).first()).toBeDisabled();
    await expect(builder.getByTestId('duplicate-graph-button').first()).toBeDisabled();
    await expect(savedPanel.getByRole('button', { name: 'Save as' })).toBeDisabled();
    // Strict readonly check: every Scenario 07 duplicate entry point should be disabled in historical mode.
    await expect(builder.getByTestId('duplicate-graph-button').last()).toBeDisabled();
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario07-rerun-p1-historical-readonly.png', fullPage: true });
    expect(pageErrors).toEqual([]);
  });

  test('Scenario 07 saved selections, styles, share redaction preview, and missing-ref warnings', async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error' && !/401|favicon|webpack-hmr|api\/ws/.test(message.text())) pageErrors.push(message.text());
    });
    await page.setViewportSize({ width: 1440, height: 1200 });

    await gotoFixture(page, 'redacted');
    const builder = page.getByTestId('ontology-graph-builder-page').last();
    const canvas = builder.getByTestId('graph-canvas');
    const selectionsPanel = builder.getByTestId('saved-selections-panel');
    await expect(selectionsPanel).toContainText('Legacy deleted selection');
    await expect(selectionsPanel).toContainText('object.deleted-demo was deleted');
    await expect(builder.getByTestId('selection-overlay').first()).toBeVisible();
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario07-rerun-p1-overlay-visible.png', fullPage: true });

    await canvas.getByRole('button', { name: /Customer Account/ }).click();
    await selectionsPanel.getByRole('button', { name: 'Save selected' }).click();
    await expect(selectionsPanel).toContainText('Customer Account selection');
    const overlayCount = await builder.getByTestId('selection-overlay').count();
    await selectionsPanel.getByRole('button', { name: 'Hide' }).first().click();
    await expect.poll(async () => builder.getByTestId('selection-overlay').count()).toBeLessThan(overlayCount);
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario07-rerun-p1-overlay-hidden.png', fullPage: true });
    await selectionsPanel.getByRole('button', { name: 'Delete' }).first().click();

    const stylesPanel = builder.getByTestId('saved-styles-panel');
    await stylesPanel.getByRole('button', { name: /Lineage contrast/ }).click();
    await expect(builder.getByTestId('style-legend')).toContainText('Lineage event');

    await builder.getByRole('button', { name: 'Share' }).click();
    const shareModal = page.getByTestId('share-graph-modal');
    await expect(shareModal).toBeVisible();
    await expect(shareModal).toContainText('Limited viewer');
    await expect(shareModal).toContainText('redacted hydration');
    await shareModal.getByRole('button', { name: 'Preview limited viewer' }).click();
    await expect(shareModal.getByText(/Redacted shared view active/)).toBeVisible();
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario07-playwright-selection-style-share.png', fullPage: true });
    await shareModal.getByText('Close').click();
    await builder.getByTestId('redacted-node').click();
    await builder.getByTestId('inspector-tab-properties').click();
    await expect(builder.getByText('Properties redacted by permission policy.')).toBeVisible();
    const bodyText = await page.locator('body').innerText();
    expect(bodyText).not.toMatch(/123-45-6789|secret-token|ssn/i);
    expect(pageErrors).toEqual([]);
  });

  test('Scenario 07 template wizard blocks missing params and valid params generate a graph', async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error' && !/401|favicon|webpack-hmr|api\/ws/.test(message.text())) pageErrors.push(message.text());
    });
    await page.setViewportSize({ width: 1440, height: 1200 });

    await gotoFixture(page, 'basic');
    const builder = page.getByTestId('ontology-graph-builder-page').last();
    await builder.getByRole('button', { name: 'Template' }).click();
    const wizard = page.getByTestId('graph-template-wizard');
    await expect(wizard).toBeVisible();
    await expect(wizard).toContainText('Required params: Root object, Review set');
    await wizard.getByLabel('Template name').fill('Scenario 07 Template');
    await wizard.getByRole('button', { name: 'Create template' }).click();
    await expect(wizard).toHaveCount(0);

    await builder.getByRole('button', { name: /Scenario 07 Template/ }).click();
    const runModal = page.getByTestId('template-run-modal');
    await expect(runModal).toBeVisible();
    await runModal.getByRole('button', { name: 'Generate graph' }).click();
    await expect(runModal.getByText('Root object is required.')).toBeVisible();
    await expect(runModal.getByText('Review set is required.')).toBeVisible();
    await expect(runModal.getByTestId('template-param-input')).toHaveCount(2);
    await runModal.getByTestId('template-param-input').nth(0).fill('object.customer');
    await runModal.getByTestId('template-param-input').nth(1).fill('set-key-accounts');
    await runModal.getByRole('button', { name: 'Generate graph' }).click();
    await expect(runModal).toHaveCount(0);
    await expect(builder.getByText(/Template run run-template-scenario-07-template generated/)).toBeVisible();
    await expect(builder.getByTestId('visible-node-count')).toHaveText('4');
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario07-playwright-template-run.png', fullPage: true });
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario07-rerun-p1-template-run.png', fullPage: true });
    expect(pageErrors).toEqual([]);
  });


  test('Scenario 08 time controls update event badges and Claim Event time-series inspector', async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error' && !/401|favicon|webpack-hmr|api\/ws/.test(message.text())) pageErrors.push(message.text());
    });
    await page.setViewportSize({ width: 1440, height: 1200 });

    await gotoFixture(page, 'basic');
    const builder = page.getByTestId('ontology-graph-builder-page').last();
    const canvas = builder.getByTestId('graph-canvas');
    await expect(builder.getByTestId('time-selection-controls')).toBeVisible();
    await expect(builder.getByTestId('timeline-scrubber')).toBeVisible();
    await expect(builder.getByTestId('events-panel').first()).toContainText('active');
    await expect(builder.getByTestId('event-truncation-warning').first()).toBeVisible();
    await expect(builder.getByTestId('event-badge')).toHaveCount(4);
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario08-playwright-time-events.png', fullPage: true });

    await canvas.getByRole('button', { name: /^Claim Event/ }).click();
    await builder.getByRole('button', { name: 'Events' }).click();
    await expect(builder.getByTestId('events-panel').last()).toContainText('Events active 1 / total 1');
    await builder.getByRole('button', { name: 'Time Series' }).click();
    await expect(builder.getByTestId('time-series-panel')).toContainText('claim_count');
    await expect(builder.getByTestId('time-series-panel')).toContainText('Latest 71 count');

    await builder.getByLabel('Time range start').fill('2026-06-10T00:00:00.000Z');
    await builder.getByLabel('Time range end').fill('2026-06-10T01:00:00.000Z');
    await expect(builder.getByTestId('events-panel').first()).toContainText('No events in this time range');
    await expect(builder.getByTestId('event-badge')).toHaveCount(0);
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario08-playwright-empty-window.png', fullPage: true });

    await builder.getByLabel('Time range start').fill('2026-06-09T08:00:00.000Z');
    await builder.getByLabel('Time range end').fill('2026-06-09T12:00:00.000Z');
    await expect(builder.getByTestId('event-badge')).toHaveCount(4);
    expect(pageErrors).toEqual([]);
  });

  test('Scenario 08 grouping selected, by type/property, grouped edge identities, and ungroup', async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error' && !/401|favicon|webpack-hmr|api\/ws/.test(message.text())) pageErrors.push(message.text());
    });
    await page.setViewportSize({ width: 1440, height: 1200 });

    await gotoFixture(page, 'basic');
    const builder = page.getByTestId('ontology-graph-builder-page').last();
    const canvas = builder.getByTestId('graph-canvas');
    await expect(builder.getByTestId('group-context-menu')).toBeVisible();
    await expect(builder.getByTestId('ungroup-button')).toBeDisabled();

    await canvas.getByRole('button', { name: /^Policy Contract/ }).click();
    await builder.getByRole('button', { name: 'Group selected' }).click();
    await expect(builder.getByTestId('grouped-node')).toBeVisible();
    await builder.getByRole('button', { name: 'Overview' }).click();
    await expect(builder.getByTestId('grouped-object-list')).toContainText('object.policy');
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario08-playwright-group-selected.png', fullPage: true });
    await builder.getByTestId('ungroup-button').click();
    await expect(builder.getByTestId('grouped-node')).toHaveCount(0);

    await builder.getByRole('button', { name: 'Group by type' }).click();
    await expect(builder.getByTestId('grouped-node')).toBeVisible();
    await builder.getByRole('button', { name: 'Group by owner' }).click();
    await expect(builder.getByTestId('grouped-edge')).toBeVisible();
    await builder.getByTestId('grouped-edge').click();
    await builder.getByRole('button', { name: 'Overview' }).click();
    await expect(builder.getByTestId('grouped-edge-object-list')).toContainText('Contained edges: rel.customer-policy');
    await expect(builder.getByTestId('grouped-edge-object-list')).toContainText('object.customer');
    await expect(builder.getByTestId('grouped-edge-object-list')).toContainText('object.policy');
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario08-playwright-grouped-edge.png', fullPage: true });
    await builder.getByTestId('ungroup-button').click();
    await expect(builder.getByTestId('grouped-edge')).toHaveCount(0);
    await expect(builder.getByTestId('grouped-node')).toHaveCount(0);
    expect(pageErrors).toEqual([]);
  });

  test('Scenario 08 redacted grouping remains topology-only and large group lists are capped', async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error' && !/401|favicon|webpack-hmr|api\/ws/.test(message.text())) pageErrors.push(message.text());
    });
    await page.setViewportSize({ width: 1440, height: 1200 });

    await gotoFixture(page, 'redacted');
    let builder = page.getByTestId('ontology-graph-builder-page').last();
    let canvas = builder.getByTestId('graph-canvas');
    await canvas.getByRole('button', { name: /^Restricted Person/ }).click();
    await builder.getByRole('button', { name: 'Group selected' }).click();
    await expect(builder.getByTestId('grouped-node')).toBeVisible();
    await expect(builder.getByTestId('grouped-node')).toContainText('Mixed permissions');
    await builder.getByRole('button', { name: 'Overview' }).click();
    await expect(builder.getByTestId('grouped-object-list')).toContainText('Mixed-permission group');
    await builder.getByRole('button', { name: 'Properties' }).click();
    await expect(builder.getByText('Properties redacted by permission policy.')).toBeVisible();
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario08-playwright-redacted-group.png', fullPage: true });

    await gotoFixture(page, 'large');
    builder = page.getByTestId('ontology-graph-builder-page').last();
    canvas = builder.getByTestId('graph-canvas');
    await expect(canvas).toBeVisible();
    await builder.getByRole('button', { name: 'Group by type' }).click();
    await expect(builder.getByTestId('grouped-node')).toBeVisible();
    await builder.getByRole('button', { name: 'Overview' }).click();
    await expect(builder.getByTestId('grouped-object-list')).toContainText('Group object list capped at 6');
    await expect(builder.getByTestId('grouped-object-list')).toContainText('Group contains');
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario08-playwright-large-group-cap.png', fullPage: true });
    expect(pageErrors).toEqual([]);
  });


  test('Scenario 08 large grouped object lists are capped', async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error' && !/401|favicon|webpack-hmr|api\/ws/.test(message.text())) pageErrors.push(message.text());
    });
    await page.setViewportSize({ width: 1440, height: 1200 });

    await gotoFixture(page, 'large');
    const builder = page.getByTestId('ontology-graph-builder-page').last();
    await expect(builder.getByTestId('graph-canvas')).toBeVisible();
    await builder.getByRole('button', { name: 'Group by type' }).click();
    await expect(builder.getByTestId('grouped-node')).toBeVisible();
    await builder.getByRole('button', { name: 'Overview' }).click();
    await expect(builder.getByTestId('grouped-object-list')).toContainText('Group object list capped at 6');
    await expect(builder.getByTestId('grouped-object-list')).toContainText('Group contains');
    await page.screenshot({ path: '../artifacts/qa-automation/screenshots/scenario08-playwright-large-group-cap.png', fullPage: true });
    expect(pageErrors).toEqual([]);
  });

});
