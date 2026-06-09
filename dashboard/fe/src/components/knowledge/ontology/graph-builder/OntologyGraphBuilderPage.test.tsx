import React from 'react';
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import OntologyGraphBuilderPage from './OntologyGraphBuilderPage';

describe('OntologyGraphBuilderPage', () => {
  it('renders basic graph, inspector properties, filters, and add-to-graph search flow', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-namespace" initialFixture="basic" />);
    expect(screen.getByTestId('ontology-graph-builder-page')).toBeInTheDocument();
    expect(screen.getByTestId('graph-loading-state')).toBeInTheDocument();

    await screen.findByTestId('graph-canvas');
    expect(screen.getByTestId('visible-node-count')).toHaveTextContent('3');
    fireEvent.change(screen.getByTestId('layout-preset-control'), { target: { value: 'layered' } });
    fireEvent.click(screen.getByTestId('fit-view-button'));
    expect(screen.getAllByText('Customer Account').length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText('Customer Account'));
    fireEvent.click(screen.getByTestId('inspector-tab-properties'));
    expect(screen.getByText('Data Stewardship')).toBeInTheDocument();

    const customerFilter = screen.getAllByTestId('filter-chip').find((chip) => chip.textContent?.includes('Customer'));
    expect(customerFilter).toBeTruthy();
    fireEvent.click(customerFilter!);
    expect(screen.getAllByText('Customer Account').length).toBeGreaterThan(0);
    fireEvent.click(customerFilter!);

    fireEvent.click(screen.getByText('Search objects'));
    const modal = await screen.findByTestId('search-modal');
    const rows = await within(modal).findAllByTestId('search-result-row');
    fireEvent.click(within(rows[0]).getByRole('checkbox'));
    fireEvent.click(within(rows[1]).getByRole('checkbox'));
    fireEvent.click(screen.getByTestId('add-to-graph-button'));

    await waitFor(() => expect(screen.queryByTestId('search-modal')).not.toBeInTheDocument());
    expect(screen.getByText('Agent Session')).toBeInTheDocument();
    expect(screen.getByText('Knowledge Namespace')).toBeInTheDocument();
  });

  it('expands the selected node with projection merge and deduplicates repeated expand results', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-namespace" initialFixture="basic" />);
    await screen.findByTestId('graph-canvas');
    fireEvent.click(screen.getByText('Customer Account'));
    fireEvent.click(screen.getByTestId('expand-node-button'));
    expect((await screen.findAllByText('Agent Session')).length).toBeGreaterThan(0);
    expect(screen.getByTestId('visible-node-count')).toHaveTextContent('4');

    fireEvent.click(screen.getByTestId('expand-node-button'));
    await waitFor(() => expect(screen.getByTestId('visible-node-count')).toHaveTextContent('4'));
  });

  it('renders empty, error, and truncation overlays', async () => {
    const { unmount } = render(<OntologyGraphBuilderPage namespace="qa-namespace" initialFixture="empty" />);
    expect(await screen.findByTestId('graph-empty-state')).toBeInTheDocument();
    unmount();

    const largeRender = render(<OntologyGraphBuilderPage namespace="qa-namespace" initialFixture="large" />);
    expect(await screen.findByTestId('truncation-warning')).toBeInTheDocument();
    largeRender.unmount();

    render(<OntologyGraphBuilderPage namespace="qa-namespace" initialFixture="error" />);
    expect(await screen.findByTestId('graph-error-state')).toBeInTheDocument();
  });

  it('does not render sensitive redacted properties into the DOM', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-namespace" initialFixture="redacted" />);
    const redactedNode = await screen.findByTestId('redacted-node');
    fireEvent.click(redactedNode);
    fireEvent.click(screen.getByTestId('inspector-tab-properties'));
    expect(screen.getByText('Properties redacted by permission policy.')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('123-45-6789');
    expect(document.body).not.toHaveTextContent('secret-token');
  });

  it('preserves locally added and expanded topology when filters are applied and cleared', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-namespace" initialFixture="basic" />);
    await screen.findByTestId('graph-canvas');

    fireEvent.click(screen.getByText('Customer Account'));
    fireEvent.click(screen.getByText('Search objects'));
    const modal = await screen.findByTestId('search-modal');
    const rows = await within(modal).findAllByTestId('search-result-row');
    fireEvent.click(within(rows[0]).getByRole('checkbox'));
    fireEvent.click(within(rows[1]).getByRole('checkbox'));
    fireEvent.click(screen.getByTestId('add-to-graph-button'));
    await waitFor(() => expect(screen.getByTestId('visible-node-count')).toHaveTextContent('5'));

    fireEvent.click(screen.getByTestId('expand-node-button'));
    await waitFor(() => expect(screen.getByText('observed in')).toBeInTheDocument());
    expect(screen.getByTestId('visible-node-count')).toHaveTextContent('5');

    const claimFilter = screen.getAllByTestId('filter-chip').find((chip) => chip.textContent?.includes('Claim'));
    expect(claimFilter).toBeTruthy();
    fireEvent.click(claimFilter!);
    await waitFor(() => expect(screen.getByTestId('visible-node-count')).toHaveTextContent('1'));
    fireEvent.click(screen.getByText('Clear'));
    await waitFor(() => expect(screen.getByTestId('visible-node-count')).toHaveTextContent('5'));
    expect(screen.getByText('Agent Session')).toBeInTheDocument();
    expect(screen.getByText('Knowledge Namespace')).toBeInTheDocument();
    expect(screen.getByText('observed in')).toBeInTheDocument();
  });


  it('supports object set creation, compare, traversal validation, and merge to graph', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-namespace" initialFixture="basic" />);
    await screen.findByTestId('graph-canvas');
    expect(await screen.findByTestId('object-set-picker')).toBeInTheDocument();
    expect(screen.getByTestId('saved-object-set-panel')).toBeInTheDocument();
    expect(screen.getByTestId('search-around-panel')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Customer Account'));
    fireEvent.click(screen.getAllByTestId('create-object-set-button')[0]);
    await waitFor(() => expect(screen.getByText('Customer Account selection')).toBeInTheDocument());

    fireEvent.click(screen.getByText('Claims review set'));
    expect(await screen.findByTestId('object-set-compare-summary')).toHaveTextContent('Overlap');

    fireEvent.change(screen.getAllByTestId('relationship-type-picker')[0], { target: { value: 'generates' } });
    fireEvent.change(screen.getAllByTestId('direction-picker')[0], { target: { value: 'inbound' } });
    expect(screen.getByTestId('validation-issue')).toHaveTextContent('incompatible');
    expect(screen.getByTestId('run-traversal-button')).toBeDisabled();

    fireEvent.change(screen.getAllByTestId('direction-picker')[0], { target: { value: 'outbound' } });
    fireEvent.click(screen.getByText('Preview'));
    await waitFor(() => expect(screen.getByTestId('traversal-preview-summary')).toHaveTextContent('objects'));
    fireEvent.click(screen.getByTestId('run-traversal-button'));
    await waitFor(() => expect(screen.getByTestId('add-traversal-to-graph-button')).not.toBeDisabled());
    fireEvent.click(screen.getByTestId('add-traversal-to-graph-button'));
    await waitFor(() => expect(screen.getByTestId('visible-node-count')).toHaveTextContent('4'));
  });



  it('creates an object set from selected search rows and exposes required Scenario 04 selectors', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-namespace" initialFixture="basic" />);
    await screen.findByTestId('graph-canvas');
    await waitFor(() => expect(screen.getAllByText(/Key account objects/).length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getAllByText(/owns policy/).length).toBeGreaterThan(0));

    expect(screen.getByTestId('object-set-picker')).toBeInTheDocument();
    expect(screen.getByTestId('saved-object-set-panel')).toBeInTheDocument();
    expect(screen.getByTestId('search-around-panel')).toBeInTheDocument();
    expect(screen.getAllByTestId('relationship-type-picker')).toHaveLength(1);
    expect(screen.getAllByTestId('direction-picker')).toHaveLength(1);
    expect(screen.getAllByTestId('traversal-step')).toHaveLength(1);
    expect(screen.getByTestId('traversal-preview-summary')).toHaveTextContent('Preview before running traversal');
    await waitFor(() => expect(screen.getByTestId('run-traversal-button')).toBeEnabled());
    expect(screen.getByTestId('add-traversal-to-graph-button')).toBeDisabled();

    fireEvent.click(screen.getByText('Search objects'));
    const modal = await screen.findByTestId('search-modal');
    const createButtons = screen.getAllByTestId('create-object-set-button');
    expect(createButtons.length).toBeGreaterThanOrEqual(2);
    const modalCreateButton = within(modal).getByTestId('create-object-set-button');
    expect(modalCreateButton).toBeDisabled();

    const rows = await within(modal).findAllByTestId('search-result-row');
    fireEvent.click(within(rows[0]).getByRole('checkbox'));
    fireEvent.click(within(rows[1]).getByRole('checkbox'));
    expect(modalCreateButton).toBeEnabled();
    fireEvent.click(modalCreateButton);

    await waitFor(() => expect(screen.queryByTestId('search-modal')).not.toBeInTheDocument());
    expect(screen.getByText('Search result object set')).toBeInTheDocument();
    expect(screen.getByText('search · 2 objects')).toBeInTheDocument();
    expect(screen.getByText('Operational Event: 1')).toBeInTheDocument();
    expect(screen.getByText('Knowledge Object: 1')).toBeInTheDocument();
  });

  it('supports saved object-set loading, compare counts, multi-step preview, truncation, validation, and deduped traversal merge', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-namespace" initialFixture="basic" />);
    await screen.findByTestId('graph-canvas');
    await waitFor(() => expect(screen.getAllByText(/Key account objects/).length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getAllByText(/owns policy/).length).toBeGreaterThan(0));
    const canvas = screen.getByTestId('graph-canvas');

    fireEvent.click(await screen.findByRole('button', { name: /Claims review set/ }));
    const compareSummary = await screen.findByTestId('object-set-compare-summary');
    expect(compareSummary).toHaveTextContent('Added');
    expect(compareSummary).toHaveTextContent('Removed');
    expect(compareSummary).toHaveTextContent('Overlap');
    expect(compareSummary).toHaveTextContent('Added1');
    expect(compareSummary).toHaveTextContent('Removed1');
    expect(compareSummary).toHaveTextContent('Overlap1');

    fireEvent.change(screen.getAllByTestId('relationship-type-picker')[0], { target: { value: 'generates' } });
    fireEvent.change(screen.getAllByTestId('direction-picker')[0], { target: { value: 'inbound' } });
    expect(screen.getByTestId('validation-issue')).toHaveTextContent('Inbound generates traversal is incompatible');
    expect(screen.getByTestId('run-traversal-button')).toBeDisabled();

    fireEvent.change(screen.getAllByTestId('relationship-type-picker')[0], { target: { value: 'observed_in' } });
    fireEvent.change(screen.getAllByTestId('direction-picker')[0], { target: { value: 'outbound' } });
    fireEvent.click(screen.getByText('+ Step'));
    expect(screen.getAllByTestId('traversal-step')).toHaveLength(2);
    fireEvent.change(screen.getAllByTestId('relationship-type-picker')[1], { target: { value: 'owns' } });
    fireEvent.change(screen.getAllByTestId('direction-picker')[1], { target: { value: 'either' } });

    fireEvent.click(screen.getByText('Preview'));
    await waitFor(() => expect(screen.getByTestId('traversal-preview-summary')).toHaveTextContent('3 objects'));
    expect(screen.getByTestId('traversal-preview-summary')).toHaveTextContent('2 relationships');
    expect(screen.getByTestId('traversal-preview-summary')).toHaveTextContent('Agent Session: 1');
    expect(screen.getByTestId('traversal-preview-summary')).toHaveTextContent('Result capped/truncated at 3 objects');

    fireEvent.click(screen.getByTestId('run-traversal-button'));
    await waitFor(() => expect(screen.getByTestId('add-traversal-to-graph-button')).toBeEnabled());
    expect(screen.getByText('Traversal result')).toBeInTheDocument();
    expect(screen.getByTestId('traversal-preview-summary')).toHaveTextContent('Result capped/truncated at 4 objects');

    fireEvent.click(screen.getByTestId('add-traversal-to-graph-button'));
    await waitFor(() => expect(screen.getByTestId('visible-node-count')).toHaveTextContent('4'));
    expect(within(canvas).getAllByText('Agent Session')).toHaveLength(1);

    fireEvent.click(screen.getByTestId('add-traversal-to-graph-button'));
    await waitFor(() => expect(screen.getByTestId('visible-node-count')).toHaveTextContent('4'));
    expect(within(canvas).getAllByText('Agent Session')).toHaveLength(1);
  });

  it('disables traversal run for retired relationship types', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-namespace" initialFixture="basic" />);
    await screen.findByTestId('graph-canvas');
    await waitFor(() => expect(screen.getAllByText(/retired identity link/).length).toBeGreaterThan(0));
    fireEvent.change(screen.getAllByTestId('relationship-type-picker')[0], { target: { value: 'retired_identity_link' } });
    expect(screen.getByTestId('validation-issue')).toHaveTextContent('retired identity link is retired');
    expect(screen.getByTestId('run-traversal-button')).toBeDisabled();
  });


  it('supports Scenario 05 object instance authoring with validation, evidence, duplicates, dirty state, and audit', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-namespace" initialFixture="basic" />);
    await screen.findByTestId('graph-canvas');

    fireEvent.click(screen.getByTestId('open-instance-create-button'));
    const modal = await screen.findByTestId('instance-create-modal');
    expect(within(modal).getAllByTestId('required-field').length).toBeGreaterThanOrEqual(2);
    expect(within(modal).getByTestId('dirty-state-indicator')).toHaveTextContent('Draft matches saved state');

    fireEvent.click(within(modal).getByTestId('save-instance-button'));
    expect(await within(modal).findAllByTestId('field-validation-error')).toHaveLength(2);

    fireEvent.change(within(modal).getByLabelText(/Customer name/), { target: { value: 'Customer Account' } });
    fireEvent.change(within(modal).getByLabelText(/Stable ID/), { target: { value: 'customer' } });
    expect(within(modal).getByTestId('dirty-state-indicator')).toHaveTextContent('Unsaved draft changes');
    expect(within(modal).getByTestId('duplicate-detection-panel')).toHaveTextContent('may be the same identity');
    expect(within(modal).getByTestId('identity-resolution-panel')).toBeInTheDocument();
    fireEvent.click(within(modal).getByText('Attach'));
    fireEvent.click(within(modal).getByText('Link source'));
    expect(within(modal).getByTestId('evidence-attachment-panel')).toHaveTextContent('evidence://crm/customer-row-42');
    expect(within(modal).getByTestId('source-record-linker')).toHaveTextContent('source://crm/accounts/42');
    fireEvent.click(within(modal).getByTestId('save-instance-button'));

    await waitFor(() => expect(screen.queryByTestId('instance-create-modal')).not.toBeInTheDocument());
    expect(screen.getByTestId('audit-event-link')).toHaveTextContent('audit-object-create');
  });

  it('supports Scenario 05 relationship validation, cardinality handling, save, edit, and permission denied states', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-namespace" initialFixture="basic" />);
    await screen.findByTestId('graph-canvas');
    await waitFor(() => expect(screen.getAllByText(/retired identity link/).length).toBeGreaterThan(0));

    fireEvent.click(screen.getByTestId('open-relationship-create-button'));
    const relModal = await screen.findByTestId('relationship-create-modal');
    fireEvent.change(within(relModal).getByLabelText(/Relationship type/), { target: { value: 'generates' } });
    fireEvent.click(within(relModal).getByTestId('save-instance-button'));
    expect(await within(relModal).findByTestId('field-validation-error')).toHaveTextContent('incompatible');

    fireEvent.change(within(relModal).getByLabelText(/Relationship type/), { target: { value: 'owns' } });
    fireEvent.click(within(relModal).getByTestId('save-instance-button'));
    expect(await within(relModal).findByTestId('field-validation-error')).toHaveTextContent('Cardinality violation');

    fireEvent.change(within(relModal).getByLabelText(/Relationship type/), { target: { value: 'observed_in' } });
    fireEvent.change(within(relModal).getByLabelText(/Target/), { target: { value: 'object.claim' } });
    fireEvent.click(within(relModal).getByTestId('save-instance-button'));
    expect(await within(relModal).findByTestId('field-validation-error')).toHaveTextContent('incompatible');

    fireEvent.change(within(relModal).getByLabelText(/Target/), { target: { value: 'object.agent-session' } });
    // Add the compatible target via search first, then reopen relationship authoring.
    fireEvent.click(within(relModal).getByText('Cancel'));
    fireEvent.click(screen.getByText('Search objects'));
    const searchModal = await screen.findByTestId('search-modal');
    const rows = await within(searchModal).findAllByTestId('search-result-row');
    fireEvent.click(within(rows[0]).getByRole('checkbox'));
    fireEvent.click(screen.getByTestId('add-to-graph-button'));
    await waitFor(() => expect(screen.queryByTestId('search-modal')).not.toBeInTheDocument());

    fireEvent.click(screen.getByTestId('open-relationship-create-button'));
    const compatibleModal = await screen.findByTestId('relationship-create-modal');
    fireEvent.change(within(compatibleModal).getByLabelText(/Relationship type/), { target: { value: 'observed_in' } });
    fireEvent.change(within(compatibleModal).getByLabelText(/Target/), { target: { value: 'object.agent-session' } });
    fireEvent.click(within(compatibleModal).getByTestId('save-instance-button'));
    await waitFor(() => expect(screen.queryByTestId('relationship-create-modal')).not.toBeInTheDocument());
    expect(screen.getByTestId('audit-event-link')).toHaveTextContent('audit-relationship-create');
    expect(screen.getAllByText('observed in').length).toBeGreaterThan(0);

    fireEvent.click(screen.getByText('Search objects'));
    const restrictedSearchModal = await screen.findByTestId('search-modal');
    const restrictedRows = await within(restrictedSearchModal).findAllByTestId('search-result-row');
    fireEvent.click(within(restrictedRows[2]).getByRole('checkbox'));
    fireEvent.click(screen.getByTestId('add-to-graph-button'));
    await waitFor(() => expect(screen.queryByTestId('search-modal')).not.toBeInTheDocument());
    fireEvent.click(screen.getByText('Restricted Person'));
    expect(screen.getByTestId('permission-denied-state')).toHaveTextContent('read-only');
  });

  it('supports Scenario 05 delete behavior for created object and relationship instances', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-namespace" initialFixture="basic" />);
    await screen.findByTestId('graph-canvas');

    fireEvent.click(screen.getByTestId('open-instance-create-button'));
    const objectModal = await screen.findByTestId('instance-create-modal');
    fireEvent.change(within(objectModal).getByLabelText(/Customer name/), { target: { value: 'Delete Candidate' } });
    fireEvent.change(within(objectModal).getByLabelText(/Stable ID/), { target: { value: 'delete-candidate' } });
    fireEvent.click(within(objectModal).getByTestId('save-instance-button'));
    await waitFor(() => expect(screen.queryByTestId('instance-create-modal')).not.toBeInTheDocument());
    expect(screen.getAllByText('Delete Candidate').length).toBeGreaterThan(0);
    expect(screen.getByTestId('visible-node-count')).toHaveTextContent('4');

    fireEvent.click(within(screen.getByTestId('graph-canvas')).getByRole('button', { name: /Delete Candidate/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Edit selected object' }));
    const editObject = await screen.findByTestId('instance-edit-form');
    fireEvent.click(within(editObject).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(screen.queryAllByText('Delete Candidate')).toHaveLength(0));
    expect(screen.getByTestId('audit-event-link')).toHaveTextContent('audit-object-delete');
    expect(screen.getByTestId('visible-node-count')).toHaveTextContent('3');

    fireEvent.click(screen.getByText('Search objects'));
    const searchModal = await screen.findByTestId('search-modal');
    const rows = await within(searchModal).findAllByTestId('search-result-row');
    fireEvent.click(within(rows[0]).getByRole('checkbox'));
    fireEvent.click(screen.getByTestId('add-to-graph-button'));
    await waitFor(() => expect(screen.queryByTestId('search-modal')).not.toBeInTheDocument());

    fireEvent.click(screen.getByTestId('open-relationship-create-button'));
    const relationshipModal = await screen.findByTestId('relationship-create-modal');
    fireEvent.change(within(relationshipModal).getByLabelText(/Relationship type/), { target: { value: 'observed_in' } });
    fireEvent.change(within(relationshipModal).getByLabelText(/Target/), { target: { value: 'object.agent-session' } });
    fireEvent.click(within(relationshipModal).getByTestId('save-instance-button'));
    await waitFor(() => expect(screen.queryByTestId('relationship-create-modal')).not.toBeInTheDocument());
    expect(screen.getAllByText('observed in').length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: 'observed in' }));
    fireEvent.click(screen.getByRole('button', { name: 'Edit selected relationship' }));
    const editRelationship = await screen.findByTestId('relationship-edit-form');
    fireEvent.click(within(editRelationship).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'observed in' })).not.toBeInTheDocument());
    expect(screen.getByTestId('audit-event-link')).toHaveTextContent('audit-relationship-delete');
  });


  it('supports Scenario 06 governance validation, approval, publish, readonly history, lineage, and revert flow', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-governance" initialFixture="basic" />);
    await screen.findByTestId('graph-canvas');

    expect(await screen.findByTestId('validation-summary-banner')).toHaveTextContent('Errors 1');
    expect(screen.getAllByTestId('validation-issue-row')[0]).toHaveTextContent('Policy Contract');
    fireEvent.click(screen.getAllByTestId('validation-issue-row')[0]);
    expect(await screen.findByTestId('focused-graph-element')).toHaveTextContent('Policy Contract');
    expect(screen.getByTestId('changeset-diff-preview')).toHaveTextContent('Policy Contract.owner');
    expect(screen.getByTestId('approval-queue')).toHaveTextContent('No submitted changesets');
    expect(screen.getByTestId('audit-timeline')).toHaveTextContent('changeset.created');

    fireEvent.click(screen.getByRole('button', { name: 'Validate' }));
    await waitFor(() => expect(screen.getByTestId('validation-summary-banner')).toHaveTextContent('Errors 0'));
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    await waitFor(() => expect(screen.getByTestId('approval-queue')).toHaveTextContent('1 submitted'));

    fireEvent.change(screen.getByLabelText('Governance role'), { target: { value: 'approver' } });
    fireEvent.click(screen.getByRole('button', { name: 'Approval queue' }));
    const approvalModal = await screen.findByTestId('approval-decision-modal');
    fireEvent.change(within(approvalModal).getByLabelText('Decision'), { target: { value: 'reject' } });
    expect(within(approvalModal).getByText('Reject comment required.')).toBeInTheDocument();
    expect(within(approvalModal).getByRole('button', { name: 'Submit decision' })).toBeDisabled();
    fireEvent.change(within(approvalModal).getByLabelText('Decision'), { target: { value: 'approve' } });
    fireEvent.change(within(approvalModal).getByTestId('approval-comment-input'), { target: { value: 'Approved with lineage evidence.' } });
    fireEvent.click(within(approvalModal).getByRole('button', { name: 'Submit decision' }));
    await waitFor(() => expect(screen.queryByTestId('approval-decision-modal')).not.toBeInTheDocument());

    fireEvent.change(screen.getByLabelText('Governance role'), { target: { value: 'steward' } });
    fireEvent.click(screen.getByTestId('open-publish-dialog-button'));
    const publishDialog = await screen.findByTestId('publish-dialog');
    expect(within(publishDialog).getByTestId('publish-diff-preview')).toHaveTextContent('Canonical source evidence');
    fireEvent.click(within(publishDialog).getByRole('button', { name: 'Publish version' }));
    await waitFor(() => expect(screen.queryByTestId('publish-dialog')).not.toBeInTheDocument());
    expect(screen.getByTestId('audit-timeline')).toHaveTextContent('version.published');

    fireEvent.change(screen.getByLabelText('Version view'), { target: { value: 'version-3' } });
    expect(await screen.findByTestId('historical-version-readonly-banner')).toHaveTextContent('immutable and readonly');
    fireEvent.click(screen.getByTestId('lineage-tab'));
    expect(screen.getByText(/Upstream:/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Version view'), { target: { value: 'current' } });
    fireEvent.click(screen.getByRole('button', { name: 'Revert' }));
    const revertDialog = await screen.findByTestId('revert-dialog');
    fireEvent.click(within(revertDialog).getByRole('button', { name: 'Create new revert version' }));
    await waitFor(() => expect(screen.queryByTestId('revert-dialog')).not.toBeInTheDocument());
    expect(screen.getByTestId('audit-timeline')).toHaveTextContent('version.revert_created');
  });


  it('enforces Scenario 06 submit, reject-with-comment, auditor, and stale publish rules', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-governance-rules" initialFixture="basic" />);
    await screen.findByTestId('graph-canvas');

    expect(screen.getByTestId('validation-summary-banner')).toHaveTextContent('Errors 1');
    expect(screen.getByRole('button', { name: 'Submit' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Validate' }));
    await waitFor(() => expect(screen.getByTestId('validation-summary-banner')).toHaveTextContent('Errors 0'));
    expect(screen.getByRole('button', { name: 'Submit' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    await waitFor(() => expect(screen.getByTestId('approval-queue')).toHaveTextContent('1 submitted'));

    fireEvent.change(screen.getByLabelText('Governance role'), { target: { value: 'auditor' } });
    expect(screen.getByRole('button', { name: 'Validate' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Submit' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Approval queue' })).toBeDisabled();
    screen.getAllByRole('button', { name: 'Publish' }).forEach((button) => expect(button).toBeDisabled());
    expect(screen.getByRole('button', { name: 'Revert' })).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Governance role'), { target: { value: 'approver' } });
    fireEvent.click(screen.getByRole('button', { name: 'Approval queue' }));
    let approvalModal = await screen.findByTestId('approval-decision-modal');
    fireEvent.change(within(approvalModal).getByLabelText('Decision'), { target: { value: 'reject' } });
    fireEvent.change(within(approvalModal).getByTestId('approval-comment-input'), { target: { value: 'Missing steward evidence note.' } });
    fireEvent.click(within(approvalModal).getByRole('button', { name: 'Submit decision' }));
    await waitFor(() => expect(screen.queryByTestId('approval-decision-modal')).not.toBeInTheDocument());
    expect(screen.getByTestId('approval-queue')).toHaveTextContent('Rejected: Missing steward evidence note.');
    expect(screen.getByTestId('audit-timeline')).toHaveTextContent('changeset.rejectd');

    fireEvent.change(screen.getByLabelText('Governance role'), { target: { value: 'steward' } });
    expect(screen.getByRole('button', { name: 'Submit' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    await waitFor(() => expect(screen.getByTestId('approval-queue')).toHaveTextContent('1 submitted'));
    fireEvent.change(screen.getByLabelText('Governance role'), { target: { value: 'approver' } });
    fireEvent.click(screen.getByRole('button', { name: 'Approval queue' }));
    approvalModal = await screen.findByTestId('approval-decision-modal');
    fireEvent.change(within(approvalModal).getByLabelText('Decision'), { target: { value: 'approve' } });
    fireEvent.change(within(approvalModal).getByTestId('approval-comment-input'), { target: { value: 'Approved after rejection fix.' } });
    fireEvent.click(within(approvalModal).getByRole('button', { name: 'Submit decision' }));
    await waitFor(() => expect(screen.queryByTestId('approval-decision-modal')).not.toBeInTheDocument());

    fireEvent.change(screen.getByLabelText('Governance role'), { target: { value: 'steward' } });
    fireEvent.click(screen.getByLabelText(/Simulate stale publish/));
    fireEvent.click(screen.getByTestId('open-publish-dialog-button'));
    expect(await screen.findByTestId('publish-dialog')).toHaveTextContent('STALE_CHANGESET_CONFLICT');
    fireEvent.click(screen.getByRole('button', { name: 'Publish version' }));
    await waitFor(() => expect(document.body).toHaveTextContent('STALE_CHANGESET_CONFLICT: This changeset is stale because another version was published. Rebase before publishing.'));
    expect(screen.getByTestId('audit-timeline')).not.toHaveTextContent('version.published');
  });

  it('keeps historical versions readonly by disabling graph editing controls', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-governance-history" initialFixture="basic" />);
    const canvas = await screen.findByTestId('graph-canvas');

    fireEvent.click(screen.getByTestId('open-instance-create-button'));
    const objectModal = await screen.findByTestId('instance-create-modal');
    fireEvent.change(within(objectModal).getByLabelText(/Customer name/), { target: { value: 'Mutable History Object' } });
    fireEvent.change(within(objectModal).getByLabelText(/Stable ID/), { target: { value: 'mutable-history' } });
    fireEvent.click(within(objectModal).getByTestId('save-instance-button'));
    await waitFor(() => expect(screen.queryByTestId('instance-create-modal')).not.toBeInTheDocument());

    fireEvent.click(within(canvas).getByRole('button', { name: /Mutable History Object/ }));
    expect(screen.getByRole('button', { name: 'Edit selected object' })).toBeEnabled();

    fireEvent.change(screen.getByLabelText('Version view'), { target: { value: 'version-3' } });
    expect(await screen.findByTestId('historical-version-readonly-banner')).toHaveTextContent('immutable and readonly');
    expect(screen.getByTestId('open-instance-create-button')).toBeDisabled();
    expect(screen.getByTestId('open-relationship-create-button')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Edit selected object' })).toBeDisabled();

    fireEvent.click(within(canvas).getByRole('button', { name: /owns policy/ }));
    expect(screen.getByRole('button', { name: 'Edit selected relationship' })).toBeDisabled();
  });

  it('makes already-open authoring modals readonly after switching to a historical version', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-governance-history-open-modal" initialFixture="basic" />);
    const canvas = await screen.findByTestId('graph-canvas');

    fireEvent.click(screen.getByTestId('open-instance-create-button'));
    let objectModal = await screen.findByTestId('instance-create-modal');
    fireEvent.change(within(objectModal).getByLabelText(/Customer name/), { target: { value: 'Mutable Modal Object' } });
    fireEvent.change(within(objectModal).getByLabelText(/Stable ID/), { target: { value: 'mutable-modal' } });
    fireEvent.click(within(objectModal).getByTestId('save-instance-button'));
    await waitFor(() => expect(screen.queryByTestId('instance-create-modal')).not.toBeInTheDocument());

    fireEvent.click(within(canvas).getByRole('button', { name: /Mutable Modal Object/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Edit selected object' }));
    objectModal = await screen.findByTestId('instance-edit-form');
    expect(within(objectModal).getByTestId('save-instance-button')).toBeEnabled();
    expect(within(objectModal).getByRole('button', { name: 'Delete' })).toBeEnabled();

    fireEvent.change(screen.getByLabelText('Version view'), { target: { value: 'version-3' } });
    expect(await screen.findByTestId('historical-version-readonly-banner')).toHaveTextContent('immutable and readonly');
    objectModal = screen.getByTestId('instance-edit-form');
    expect(within(objectModal).getByTestId('save-instance-button')).toBeDisabled();
    expect(within(objectModal).getByRole('button', { name: 'Delete' })).toBeDisabled();

    fireEvent.click(within(objectModal).getByText('Close'));
    fireEvent.change(screen.getByLabelText('Version view'), { target: { value: 'current' } });
    fireEvent.click(within(canvas).getByRole('button', { name: /owns policy/ }));
    expect(screen.getByRole('button', { name: 'Edit selected relationship' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Edit selected relationship' }));
    let relationshipModal = await screen.findByTestId('relationship-edit-form');
    expect(within(relationshipModal).getByTestId('save-instance-button')).toBeEnabled();
    expect(within(relationshipModal).getByRole('button', { name: 'Delete' })).toBeEnabled();

    fireEvent.change(screen.getByLabelText('Version view'), { target: { value: 'version-3' } });
    expect(await screen.findByTestId('historical-version-readonly-banner')).toHaveTextContent('immutable and readonly');
    relationshipModal = screen.getByTestId('relationship-edit-form');
    expect(within(relationshipModal).getByTestId('save-instance-button')).toBeDisabled();
    expect(within(relationshipModal).getByRole('button', { name: 'Delete' })).toBeDisabled();
  });


  it('supports Scenario 07 save-as, update, duplicate, reopen, history, and readonly saved versions', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-scenario07-save" initialFixture="basic" />);
    await screen.findByTestId('graph-canvas');
    fireEvent.click(screen.getAllByRole('button', { name: 'Save as' })[0]);
    const saveModal = await screen.findByTestId('save-as-modal');
    expect(within(saveModal).getByText('Name is required.')).toBeInTheDocument();
    fireEvent.change(within(saveModal).getByLabelText('Graph name'), { target: { value: 'Claims saved graph' } });
    fireEvent.click(within(saveModal).getByRole('button', { name: 'Save graph' }));
    await waitFor(() => expect(screen.queryByTestId('save-as-modal')).not.toBeInTheDocument());
    expect(screen.getByTestId('saved-graphs-panel')).toHaveTextContent('Claims saved graph');
    await waitFor(() => expect(screen.getByTestId('graph-history-sidebar')).toHaveTextContent('v1 Claims saved graph'));
    await waitFor(() => expect(screen.getByTestId('version-diff-viewer')).toHaveTextContent('Visible nodes'));

    fireEvent.click(screen.getByText('Search objects'));
    const searchModal = await screen.findByTestId('search-modal');
    const rows = await within(searchModal).findAllByTestId('search-result-row');
    fireEvent.click(within(rows[0]).getByRole('checkbox'));
    fireEvent.click(screen.getByTestId('add-to-graph-button'));
    await waitFor(() => expect(screen.getByTestId('visible-node-count')).toHaveTextContent('4'));
    fireEvent.click(screen.getAllByRole('button', { name: 'Save graph' })[0]);
    await waitFor(() => expect(screen.getByTestId('graph-history-sidebar')).toHaveTextContent('v2 Claims saved graph'));

    fireEvent.click(screen.getAllByTestId('duplicate-graph-button')[0]);
    await waitFor(() => expect(screen.getByTestId('saved-graphs-panel')).toHaveTextContent('Claims saved graph copy'));
    fireEvent.click(screen.getByRole('button', { name: /v1 Claims saved graph/ }));
    expect(await screen.findByTestId('historical-version-readonly-banner')).toHaveTextContent('immutable and readonly');
    expect(screen.getByRole('button', { name: 'Save graph' })).toBeDisabled();
    const savedGraphsPanel = screen.getByTestId('saved-graphs-panel');
    expect(within(savedGraphsPanel).getByRole('button', { name: 'Save as' })).toBeDisabled();
    expect(screen.getAllByTestId('duplicate-graph-button').every((button) => button.hasAttribute('disabled'))).toBe(true);
  });

  it('supports Scenario 07 saved selections, overlay rendering, missing-ref warnings, and delete', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-scenario07-selections" initialFixture="basic" />);
    await screen.findByTestId('graph-canvas');
    const panel = screen.getByTestId('saved-selections-panel');
    expect(panel).toHaveTextContent('Legacy deleted selection');
    expect(panel).toHaveTextContent('object.deleted-demo was deleted');
    expect(screen.getAllByTestId('selection-overlay').length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText('Customer Account'));
    fireEvent.click(within(panel).getByRole('button', { name: 'Save selected' }));
    await waitFor(() => expect(screen.getByTestId('saved-selections-panel')).toHaveTextContent('Customer Account selection'));
    fireEvent.click(within(screen.getByTestId('saved-selections-panel')).getAllByRole('button', { name: 'Hide' })[0]);
    fireEvent.click(within(screen.getByTestId('saved-selections-panel')).getAllByRole('button', { name: 'Delete' })[0]);
    expect(screen.getByTestId('saved-selections-panel')).toBeInTheDocument();
  });

  it('supports Scenario 07 saved styles, legend, share modal, and limited-viewer redaction preview', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-scenario07-style-share" initialFixture="redacted" />);
    await screen.findByTestId('graph-canvas');
    const stylesPanel = await screen.findByTestId('saved-styles-panel');
    expect(stylesPanel).toHaveTextContent('Risk review palette');
    fireEvent.click(within(stylesPanel).getByRole('button', { name: /Lineage contrast/ }));
    expect(screen.getByTestId('style-legend')).toHaveTextContent('Lineage event');
    fireEvent.click(screen.getByRole('button', { name: 'Share' }));
    const shareModal = await screen.findByTestId('share-graph-modal');
    expect(shareModal).toHaveTextContent('Limited viewer');
    expect(shareModal).toHaveTextContent('redacted hydration');
    fireEvent.click(within(shareModal).getByRole('button', { name: 'Preview limited viewer' }));
    expect(await within(shareModal).findByText(/Redacted shared view active/)).toBeInTheDocument();
    fireEvent.click(within(shareModal).getByText('Close'));
    fireEvent.click(screen.getByTestId('redacted-node'));
    fireEvent.click(screen.getByTestId('inspector-tab-properties'));
    expect(screen.getByText('Properties redacted by permission policy.')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('123-45-6789');
  });

  it('supports Scenario 07 template wizard validation, required params, and generated graph restoration', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-scenario07-template" initialFixture="basic" />);
    await screen.findByTestId('graph-canvas');
    fireEvent.click(screen.getByRole('button', { name: 'Template' }));
    const wizard = await screen.findByTestId('graph-template-wizard');
    expect(wizard).toHaveTextContent('Required params: Root object, Review set');
    fireEvent.change(within(wizard).getByLabelText('Template name'), { target: { value: 'Scenario template' } });
    fireEvent.click(within(wizard).getByRole('button', { name: 'Create template' }));
    await waitFor(() => expect(screen.queryByTestId('graph-template-wizard')).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /Scenario template/ }));
    const runModal = await screen.findByTestId('template-run-modal');
    fireEvent.click(within(runModal).getByRole('button', { name: 'Generate graph' }));
    expect(within(runModal).getAllByText(/is required/).length).toBeGreaterThan(0);
    const inputs = within(runModal).getAllByTestId('template-param-input');
    fireEvent.change(inputs[0], { target: { value: 'object.customer' } });
    fireEvent.change(inputs[1], { target: { value: 'set-key-accounts' } });
    fireEvent.click(within(runModal).getByRole('button', { name: 'Generate graph' }));
    await waitFor(() => expect(screen.queryByTestId('template-run-modal')).not.toBeInTheDocument());
    expect(screen.getByText(/Template run run-template-scenario-template generated/)).toBeInTheDocument();
    expect(screen.getByTestId('visible-node-count')).toHaveTextContent('4');
  });


  it('supports Scenario 08 time controls, event badges, event panel, and time-series inspector', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-scenario08-events" initialFixture="basic" />);
    await screen.findByTestId('graph-canvas');
    expect(screen.getByTestId('time-selection-controls')).toBeInTheDocument();
    expect(screen.getByTestId('timeline-scrubber')).toBeInTheDocument();
    expect(screen.getAllByTestId('event-badge').length).toBeGreaterThan(0);
    expect(screen.getByTestId('events-panel')).toHaveTextContent('active');
    expect(screen.getByTestId('event-truncation-warning')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Time range start'), { target: { value: '2026-06-10T00:00:00.000Z' } });
    fireEvent.change(screen.getByLabelText('Time range end'), { target: { value: '2026-06-10T01:00:00.000Z' } });
    await waitFor(() => expect(screen.getByTestId('events-panel')).toHaveTextContent('No events in this time range'));

    fireEvent.change(screen.getByLabelText('Time range start'), { target: { value: '2026-06-09T08:00:00.000Z' } });
    fireEvent.change(screen.getByLabelText('Time range end'), { target: { value: '2026-06-09T12:00:00.000Z' } });
    fireEvent.click(await screen.findByText('Claim Event'));
    fireEvent.click(screen.getByRole('button', { name: 'Time Series' }));
    expect(screen.getByTestId('time-series-panel')).toHaveTextContent('claim_count');
  });

  it('supports Scenario 08 grouping, grouped nodes/edges, contained object lists, and ungroup', async () => {
    render(<OntologyGraphBuilderPage namespace="qa-scenario08-grouping" initialFixture="basic" />);
    await screen.findByTestId('graph-canvas');
    expect(screen.getByTestId('group-context-menu')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Policy Contract'));
    fireEvent.click(screen.getByRole('button', { name: 'Group selected' }));
    expect(await screen.findByTestId('grouped-node')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Overview' }));
    expect(screen.getByTestId('grouped-object-list')).toHaveTextContent('object.policy');
    fireEvent.click(screen.getByTestId('ungroup-button'));
    await waitFor(() => expect(screen.queryByTestId('grouped-node')).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Group by type' }));
    await screen.findByTestId('grouped-node');
    fireEvent.click(screen.getByRole('button', { name: 'Group by owner' }));
    expect(await screen.findByTestId('grouped-edge')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('grouped-edge'));
    fireEvent.click(screen.getByRole('button', { name: 'Overview' }));
    expect(screen.getByTestId('grouped-edge-object-list')).toHaveTextContent('object.customer');
    fireEvent.click(screen.getByTestId('ungroup-button'));
    await waitFor(() => expect(screen.queryByTestId('grouped-edge')).not.toBeInTheDocument());
  });


  it('supports Scenario 08 redacted grouping warnings and large grouped list caps', async () => {
    const redactedRender = render(<OntologyGraphBuilderPage namespace="qa-scenario08-redacted" initialFixture="redacted" />);
    await screen.findByTestId('graph-canvas');
    fireEvent.click(screen.getByText('Restricted Person'));
    fireEvent.click(screen.getByRole('button', { name: 'Group selected' }));
    expect(await screen.findByTestId('grouped-node')).toHaveTextContent('Mixed permissions');
    fireEvent.click(screen.getByRole('button', { name: 'Overview' }));
    expect(screen.getByTestId('grouped-object-list')).toHaveTextContent('object.restricted-person');
    expect(screen.getByTestId('grouped-object-list')).toHaveTextContent('Mixed-permission group');
    fireEvent.click(screen.getByRole('button', { name: 'Properties' }));
    await waitFor(() => expect(screen.queryByTestId('node-detail-loading')).not.toBeInTheDocument());
    expect(screen.getByText('Properties redacted by permission policy.')).toBeInTheDocument();
    expect(screen.queryByText('No properties supplied.')).not.toBeInTheDocument();
    redactedRender.unmount();

    render(<OntologyGraphBuilderPage namespace="qa-scenario08-large" initialFixture="large" />);
    await screen.findByTestId('graph-canvas');
    fireEvent.click(screen.getByRole('button', { name: 'Group by type' }));
    expect(await screen.findByTestId('grouped-node')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Overview' }));
    expect(screen.getByTestId('grouped-object-list')).toHaveTextContent('Group object list capped at 6');
    expect(screen.getByTestId('grouped-object-list')).toHaveTextContent('Group contains');
  });

});
