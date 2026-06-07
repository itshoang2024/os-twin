// @ts-nocheck
Cypress.on('uncaught:exception', (error) => {
  if (error.message.includes('Hydration failed')) return false;
  return undefined;
});

describe('EPIC-002 ontology map builder', () => {
  beforeEach(() => {
    cy.visit('/knowledge/enterprise-map-fixture');
    cy.get('[data-testid="workbench-shell"]').should('exist');
    cy.get('[data-testid="enterprise-map-panel"]').should('exist');
    cy.get('[data-testid="graph-canvas"]').should('exist');
  });

  it('renders the live Map Lens through GraphCanvas with selectable objects and Series/Time rail', () => {
    cy.contains('Enterprise Ontology Map').should('exist');
    cy.get('[data-testid="enterprise-map-safeguards"]').within(() => {
      cy.contains(/of .* objects shown/i).should('exist');
      cy.get('select').contains('option', 'Compact').parent().select('Compact');
    });
    cy.get('[data-testid="graph-node-risk-1"]').click({ force: true });
    cy.get('[role="dialog"][aria-label="Detail drawer"]').within(() => {
      cy.contains(/Vendor outage risk/i).should('exist');
      cy.contains(/source-backed/i).should('exist');
    });
    cy.get('[data-testid="series-time-panel"]').within(() => {
      cy.contains(/Series \/ Time/i).should('exist');
    });
  });

  it('round-trips view-plane group/filter/search controls and keeps simulation honest', () => {
    cy.get('[aria-label="Group by"]').select('concept_type', { force: true });
    cy.get('[aria-label="Group by"]').should('exist');
    cy.contains('button', /Histogram/i).click();
    cy.contains('button', 'Filter to').click();
    cy.get('[data-testid="workbench-applied-chips"]').should('contain.text', 'object_type:include');
    cy.get('[data-testid="graph-node-risk-1"]').click({ force: true });
    cy.contains('button', /Search Around/i).should('not.be.disabled');
    cy.contains('button', /Simulation/i).click();
    cy.get('[data-testid="simulation-rail"]').within(() => {
      cy.contains(/Provider required/i).should('exist');
    });
  });
});
