import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import OntologyPanel from '@/components/knowledge/ontology/OntologyPanel';
import { makeBlankOntologyProfile } from '@/components/knowledge/ontology/ontology-draft-commands';

describe('OntologyPanel', () => {
  it('renders blank draft with add object CTA', () => {
    render(<OntologyPanel selectedNamespace="ontology-fixture" />);
    expect(screen.getByText('Design Object Types before editing arrays')).toBeInTheDocument();
    const addButtons = screen.getAllByRole('button', { name: 'Add Object Type' });
    expect(addButtons.length).toBeGreaterThanOrEqual(1);
  });

  it('calls saveProfile on publish when provided', async () => {
    const saveProfile = vi.fn().mockResolvedValue(undefined);
    render(<OntologyPanel selectedNamespace="ontology-fixture" saveProfile={saveProfile} />);

    fireEvent.click(screen.getByRole('button', { name: 'Publish' }));

    await waitFor(() => {
      expect(saveProfile).toHaveBeenCalledTimes(1);
    });
    const args = saveProfile.mock.calls[0];
    expect(args[0].namespace).toBe('ontology-fixture');
    expect(args[0].status).toBe('published');
    expect(args[1]).toBe('Authoring workbench update');
  });

  it('blocks publish when validation errors exist', async () => {
    const saveProfile = vi.fn();
    const profile = makeBlankOntologyProfile('validation');
    profile.relationshipTypes.rel_test = {
      id: 'rel_test',
      label: 'test rel',
      description: '',
      family: 'dependency',
      allowedSourceTypes: [],
      allowedTargetTypes: [],
      cardinality: 'many_to_many',
      mapDirection: 'forward',
      style: 'solid',
      weight: 1,
      sourceMappings: [],
    };
    render(<OntologyPanel selectedNamespace="validation" initialProfile={profile} saveProfile={saveProfile} />);

    fireEvent.click(screen.getByRole('button', { name: 'Validate' }));
    fireEvent.click(screen.getByRole('button', { name: 'Publish' }));

    expect(saveProfile).not.toHaveBeenCalled();
    expect(screen.getByText(/Publish blocked by validation/)).toBeInTheDocument();
  });

  it('supports undo and redo after adding an object', () => {
    render(<OntologyPanel selectedNamespace="ontology-fixture" />);

    const addButtons = screen.getAllByRole('button', { name: 'Add Object Type' });
    fireEvent.click(addButtons[addButtons.length - 1]);

    expect(screen.getAllByText('Feature').length).toBeGreaterThan(0);

    const undoButton = screen.getByRole('button', { name: 'Undo' });
    expect(undoButton).not.toBeDisabled();
    fireEvent.click(undoButton);

    expect(screen.getByText('Design Object Types before editing arrays')).toBeInTheDocument();

    const redoButton = screen.getByRole('button', { name: 'Redo' });
    expect(redoButton).not.toBeDisabled();
    fireEvent.click(redoButton);

    expect(screen.getAllByText('Feature').length).toBeGreaterThan(0);
  });

  it('resets draft when Reset is clicked', () => {
    render(<OntologyPanel selectedNamespace="ontology-fixture" />);

    const addButtons = screen.getAllByRole('button', { name: 'Add Object Type' });
    fireEvent.click(addButtons[addButtons.length - 1]);

    expect(screen.getAllByText('Feature').length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: 'Reset' }));

    expect(screen.getByText('Design Object Types before editing arrays')).toBeInTheDocument();
  });

  it('stages candidates locally without calling saveProfile', () => {
    const saveProfile = vi.fn();
    render(<OntologyPanel selectedNamespace="ontology-fixture" saveProfile={saveProfile} />);

    fireEvent.click(screen.getByRole('button', { name: 'Review Candidates' }));

    const stageButton = screen.getByRole('button', { name: /Stage candidate locally/i });
    expect(stageButton).toBeInTheDocument();

    fireEvent.click(stageButton);
    expect(saveProfile).not.toHaveBeenCalled();
  });

  it('shows dirty state after edits', () => {
    render(<OntologyPanel selectedNamespace="ontology-fixture" />);

    expect(screen.getByText('Synced')).toBeInTheDocument();

    const addButtons = screen.getAllByRole('button', { name: 'Add Object Type' });
    fireEvent.click(addButtons[addButtons.length - 1]);

    expect(screen.getByText('Local draft')).toBeInTheDocument();
  });
});
