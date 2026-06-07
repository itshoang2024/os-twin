Cypress.on('uncaught:exception', (error) => {
  if (error.message.includes('Hydration failed')) return false;
  return undefined;
});

describe('EPIC-002 ontology authoring workbench fixture', () => {
  beforeEach(() => {
    cy.intercept({ method: /(POST|PUT|PATCH|DELETE)/, url: '**/api/knowledge/ontology**' }).as('ontologyWrite');
    cy.visit('/knowledge/ontology-fixture');
    cy.get('[data-testid="ontology-fixture-panel"]').should('exist');
  });

  it('starts blank, adds Object Types, creates a Relationship Type, validates, and previews map impact without hidden profile writes', () => {
    cy.contains('Blank profile').click();
    cy.get('[data-testid="ontology-schema-canvas"]').should('contain.text', 'Add your first object type');

    cy.get('[aria-label="Fixture object label"]').clear().type('Service');
    cy.contains('button', 'Add Object Type').click();
    cy.get('[aria-label="Fixture object label"]').clear().type('Control');
    cy.contains('button', 'Add Object Type').click();
    cy.get('[data-testid="fixture-object-chips"]').should('contain.text', 'Service').and('contain.text', 'Control');

    cy.get('[aria-label="Fixture relationship label"]').clear().type('Validates');
    cy.contains('button', 'Create Relationship').click();
    cy.get('[data-testid="fixture-relationship-matrix"]').should('contain.text', 'Validates').and('contain.text', 'many_to_many');

    cy.contains('button', 'Validate and preview diff').click();
    cy.get('[data-testid="fixture-validation-focus"]').should('contain.text', 'Validation issue routed');
    cy.get('[data-testid="ontology-fixture-network-log"]').should('contain.text', 'validate called').and('contain.text', 'diff called').and('contain.text', 'save blocked');

    cy.contains('button', 'Preview map impact').click();
    cy.get('[data-testid="enterprise-map-example-banner"]').should('contain.text', 'Examples only');
    cy.get('@ontologyWrite.all').should('have.length', 0);
  });

  it('stages imported candidate evidence and assistant proposals without saving profiles', () => {
    cy.get('[data-testid="imported-knowledge-summary"]').should('contain.text', 'Blocks').and('contain.text', 'anchor-blocks');
    cy.contains('Build from imported knowledge').click();
    cy.get('[data-testid="ontology-fixture-network-log"]').should('contain.text', 'build from imported knowledge selected').and('contain.text', 'profile write skipped');
    cy.contains('Back to launcher').click();
    cy.contains('Ask AI to draft').click();
    cy.get('[data-testid="ontology-assistant-proposals"]').should('contain.text', 'Assistant proposal staged').and('contain.text', 'anchor-blocks');
    cy.get('[data-testid="ontology-fixture-network-log"]').should('contain.text', 'staged proposal not published');
    cy.get('@ontologyWrite.all').should('have.length', 0);
  });
});
