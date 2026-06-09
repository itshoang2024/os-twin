import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import OntologyPanel from '@/components/knowledge/ontology/OntologyPanel';
import { makeBlankOntologyProfile, createObjectType, createRelationshipType } from '@/components/knowledge/ontology/ontology-draft-commands';

describe('Workbench TopRail component', () => {
  it('renders namespace and title', () => {
    render(<OntologyPanel selectedNamespace="audit-airline" />);
    expect(screen.getByText(/Ontology Unit/)).toBeInTheDocument();
    expect(screen.getByText(/Spec authoring graph builder/)).toBeInTheDocument();
  });

  it('shows synced state by default', () => {
    render(<OntologyPanel selectedNamespace="ontology-fixture" />);
    expect(screen.getByText('Synced')).toBeInTheDocument();
  });

  it('validate button triggers validation display', () => {
    render(<OntologyPanel selectedNamespace="ontology-fixture" />);
    fireEvent.click(screen.getByRole('button', { name: 'Validate' }));
    expect(screen.getByText(/Validation completed/)).toBeInTheDocument();
  });
});

describe('Workbench Inventory component', () => {
  it('displays inventory sections', () => {
    render(<OntologyPanel selectedNamespace="ontology-fixture" />);
    const candidatesHeadings = screen.getAllByText('Candidates');
    expect(candidatesHeadings.length).toBeGreaterThan(0);
    const objectsHeadings = screen.getAllByText('Objects');
    expect(objectsHeadings.length).toBeGreaterThan(0);
    const relationshipsHeadings = screen.getAllByText('Relationships');
    expect(relationshipsHeadings.length).toBeGreaterThan(0);
    expect(screen.getByText('Properties')).toBeInTheDocument();
    expect(screen.getByText('Sources')).toBeInTheDocument();
    expect(screen.getByText('Templates')).toBeInTheDocument();
  });

  it('shows create buttons for objects and relationships', () => {
    render(<OntologyPanel selectedNamespace="ontology-fixture" />);
    const addButtons = screen.getAllByText('Add Object Type');
    expect(addButtons.length).toBeGreaterThan(0);
    const createButtons = screen.getAllByText('Create Relationship');
    expect(createButtons.length).toBeGreaterThan(0);
  });

  it('inventory lists candidates', () => {
    render(<OntologyPanel selectedNamespace="ontology-fixture" />);
    const policyElements = screen.getAllByText(/Policy/);
    expect(policyElements.length).toBeGreaterThan(0);
    const provesElements = screen.getAllByText(/proves/);
    expect(provesElements.length).toBeGreaterThan(0);
  });
});

describe('Workbench BottomRail component', () => {
  it('displays object and relationship counts as zero initially', () => {
    render(<OntologyPanel selectedNamespace="ontology-fixture" />);
    expect(screen.getByText('0 objects')).toBeInTheDocument();
    expect(screen.getByText('0 relationships')).toBeInTheDocument();
    expect(screen.getByText('0 validation issues')).toBeInTheDocument();
  });

  it('shows updated counts after adding objects and relationships', () => {
    const profile = makeBlankOntologyProfile('counts');
    let next = createObjectType(profile, 'Feature');
    next = createRelationshipType(next.profile, 'depends on', {
      allowedSourceTypes: ['feature'],
      allowedTargetTypes: ['feature'],
    });
    render(<OntologyPanel selectedNamespace="counts" initialProfile={next.profile} />);

    expect(screen.getByText('1 objects')).toBeInTheDocument();
    expect(screen.getByText('1 relationships')).toBeInTheDocument();
  });

  it('toggles map impact preview overlay', () => {
    render(<OntologyPanel selectedNamespace="ontology-fixture" />);
    const previewButton = screen.getByRole('button', { name: 'Preview map impact' });

    fireEvent.click(previewButton);
    expect(screen.getByText(/never presents them as live data/)).toBeInTheDocument();

    fireEvent.click(previewButton);
    expect(screen.queryByText(/never presents them as live data/)).not.toBeInTheDocument();
  });
});

describe('Workbench GovernancePanel component', () => {
  it('shows governance home when nothing is selected', () => {
    render(<OntologyPanel selectedNamespace="ontology-fixture" />);
    expect(screen.getByText('Governance home')).toBeInTheDocument();
    expect(screen.getByText(/Active ontology profile/)).toBeInTheDocument();
    expect(screen.getByText(/Status: draft/)).toBeInTheDocument();
  });
});
