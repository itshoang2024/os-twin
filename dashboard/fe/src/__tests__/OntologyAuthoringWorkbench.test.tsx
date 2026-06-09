import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import OntologyPanel from '@/components/knowledge/ontology/OntologyPanel';
import { createObjectType, createRelationshipType, makeBlankOntologyProfile, removeObjectTypeSafely } from '@/components/knowledge/ontology/ontology-draft-commands';

describe('Ontology authoring workbench', () => {
  it('starts blank with Add Object Type CTA and stages locally without saving', () => {
    const saveProfile = vi.fn();
    render(<OntologyPanel selectedNamespace="ontology-fixture" saveProfile={saveProfile} />);

    fireEvent.click(screen.getAllByRole('button', { name: 'Add Object Type' }).at(-1)!);

    expect(screen.getAllByText('Feature').length).toBeGreaterThan(0);
    expect(screen.getByLabelText('Object Type editor')).toBeInTheDocument();
    expect(screen.getByText(/Staged Object Type Feature locally/)).toBeInTheDocument();
    expect(saveProfile).not.toHaveBeenCalled();
  });

  it('creates a governed relationship with endpoint chips and visible edge label', () => {
    render(<OntologyPanel selectedNamespace="ontology-fixture" />);

    fireEvent.click(screen.getAllByRole('button', { name: 'Add Object Type' }).at(-1)!);
    fireEvent.change(screen.getByDisplayValue('Feature'), { target: { value: 'Risk' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Add Object Type' }).at(-1)!);
    fireEvent.click(screen.getByRole('button', { name: 'Create Relationship' }));

    expect(screen.getByLabelText('Relationship Type editor')).toBeInTheDocument();
    expect(screen.getAllByText('depends on').length).toBeGreaterThan(0);
    expect(screen.getByText('Endpoint chips')).toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue('many_to_many'), { target: { value: 'one_to_many' } });
    expect(screen.getByDisplayValue('one_to_many')).toBeInTheDocument();
  });

  it('stages both template Object Types from one local draft action', () => {
    render(<OntologyPanel selectedNamespace="ontology-fixture" />);

    fireEvent.click(screen.getByRole('button', { name: 'Use Template' }));

    expect(screen.getAllByText('Risk').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Control').length).toBeGreaterThan(0);
    expect(screen.getByText(/Staged template Object Types Risk and Control locally/)).toBeInTheDocument();
  });

  it('resets the draft when the source profile changes', async () => {
    const first = makeBlankOntologyProfile('first');
    const second = makeBlankOntologyProfile('second');
    second.updatedAt = new Date(Date.now() + 1000).toISOString();
    const { rerender } = render(<OntologyPanel selectedNamespace="first" initialProfile={first} />);
    fireEvent.click(screen.getAllByRole('button', { name: 'Add Object Type' }).at(-1)!);
    expect(screen.getAllByText('Feature').length).toBeGreaterThan(0);

    rerender(<OntologyPanel selectedNamespace="second" initialProfile={second} />);

    await waitFor(() => expect(screen.getByText('No local authoring events yet.')).toBeInTheDocument());
    expect(screen.queryByLabelText('Object Type editor')).not.toBeInTheDocument();
    expect(screen.getByText('Design Object Types before editing arrays')).toBeInTheDocument();
  });

  it('supports keyboard accessible canvas connect mode', () => {
    render(<OntologyPanel selectedNamespace="ontology-fixture" />);
    fireEvent.click(screen.getAllByRole('button', { name: 'Add Object Type' }).at(-1)!);
    fireEvent.click(screen.getAllByRole('button', { name: 'Add Object Type' }).at(-1)!);

    const connectButtons = screen.getAllByRole('button', { name: /Connect from/ });
    fireEvent.click(connectButtons[0]);
    expect(screen.getByText(/Connect mode/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /selected as relationship source/ })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: /Use .* as relationship target/ })[0]);

    expect(screen.getByLabelText('Relationship Type editor')).toBeInTheDocument();
    expect(screen.queryByText(/Connect mode/)).not.toBeInTheDocument();
    expect(screen.getAllByText('depends on').length).toBeGreaterThan(0);
  });

  it('routes validation issues to the offending relationship section', () => {
    const profile = makeBlankOntologyProfile('validation');
    const { profile: withRel } = createRelationshipType(profile, 'depends on', { allowedSourceTypes: [], allowedTargetTypes: [] });
    render(<OntologyPanel selectedNamespace="validation" initialProfile={withRel} />);

    fireEvent.click(screen.getByRole('button', { name: 'Validate' }));
    fireEvent.click(screen.getByText(/needs at least one source Object Type/));

    expect(screen.getByLabelText('Relationship Type editor')).toBeInTheDocument();
    expect(screen.getByText('Endpoint chips').closest('label')).toHaveClass('ring-2');
  });

  it('shows map impact example-data banner and stable event keys on repeated previews', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    render(<OntologyPanel selectedNamespace="ontology-fixture" />);

    const preview = screen.getByRole('button', { name: 'Preview map impact' });
    fireEvent.click(preview);
    expect(screen.getByText(/never presents them as live data/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Preview diff' }));
    fireEvent.click(screen.getByRole('button', { name: 'Preview diff' }));

    expect(errorSpy.mock.calls.flat().join('\n')).not.toContain('Encountered two children with the same key');
    errorSpy.mockRestore();
  });
});

describe('ontology draft command invariants', () => {
  it('creates Feature with GraphInstruction defaults and blocks unsafe removal', () => {
    let profile = makeBlankOntologyProfile('commands');
    const created = createObjectType(profile, 'Feature');
    profile = created.profile;
    expect(profile.conceptTypes.feature.label).toBe('Feature');
    expect(profile.graphInstruction.conceptTypeDefaults.feature).toBeDefined();

    profile = createRelationshipType(profile, 'depends on', { allowedSourceTypes: ['feature'], allowedTargetTypes: ['feature'] }).profile;
    const removal = removeObjectTypeSafely(profile, 'feature');
    expect(removal.removed).toBe(false);
    expect(removal.blockers).toHaveLength(1);
  });
});
