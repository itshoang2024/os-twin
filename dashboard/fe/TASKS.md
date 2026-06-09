# Tasks for EPIC-002


### Tasks

- [x] TASK-000 -Based on mockup/*.html files, compse the very compelling design for the Ontology Panel to support graph builder. We need to ensure these mock give you the best practice to redesign the current graph operation.
- [x] TASK-001 — Planning and context gathering
  - AC: Loaded Memory, Knowledge, room brief, codegraph context, and mockup references; confirmed `project-docs` namespace is unavailable and documented this in delivery notes.
- [x] TASK-002 — Draft controller extraction
  - AC: `useOntologyDraftController` owns local draft state, undo/redo stacks, commit/reset behavior, and is covered by hook tests.
- [x] TASK-003 — Object Type authoring flow
  - AC: Blank Spec Lens exposes an `Add Object Type` CTA; creating `Feature` stages a local `concept_types.feature`, GraphInstruction concept default, visible Spec Lens node, and opens SelectionInspector without saving.
- [x] TASK-004 — Relationship Type authoring flow
  - AC: Operators can create governed relationships through chips/selectors and canvas connect mode; relationship definitions persist allowed source/target types, family, cardinality, direction, style, weight, GraphInstruction defaults, and visible Spec Lens edges.
- [x] TASK-005 — Single authoring inspector and duplication cleanup
  - AC: Default authoring path uses one contextual SelectionInspector; legacy `ConceptTypeStudio` and `RelationshipStudio` are isolated under `Model Config (Debug)` rather than live default editing.
- [x] TASK-006 — Validation routing and map impact preview
  - AC: Validation issue buttons route to offending concept/relationship editor; Preview map impact switches to Map Lens with selected Object Type filter and example overlay truth-state behavior.
- [x] TASK-007 — Focused tests and build verification
  - AC: `OntologyAuthoringWorkbench`, touched-file ESLint, and production `pnpm build` pass; full-project lint still has pre-existing unrelated failures.
- [x] TASK-008 — Reflect the Graph Builder based on the @mockup/*.html
  - AC: Mockup concepts (layered left inventory, center graph builder, right inspector, bottom impact/series strip, relationship matrix, object/relationship labels) are reflected in the live authoring shell and relationship endpoint chip UX.
- [x] TASK-009 — QA duplicate-key event log fix
  - AC: Repeated local authoring/preview event log messages use stable unique keys and regression coverage proves no React duplicate-key console warnings are emitted.
- [x] TASK-010 — QA route unblock and review clarifications
  - AC: `/knowledge/ontology-fixture` and `/knowledge/{namespace}?tab=ontology` open the authoring workbench; draft resets on source profile changes; template staging creates Risk and Control together; regression tests, targeted ESLint, build, and agent-browser screenshots verify the unblockers.
- [x] TASK-011 — QA connect-mode keyboard fallback fix
  - AC: In canvas connect mode, each non-source Object Type exposes a semantic target button that completes Relationship Type creation without SVG-only clicks; regression tests verify source selection, target button completion, and connect-mode exit.
- [x] TASK-012 — QA ontology fixture auth-overlay bypass
  - AC: `/knowledge/ontology-fixture` skips the local setup/auth overlay so agent-browser can interact with the Ontology Authoring Workbench; all other routes keep the setup gate. Regression tests cover exact fixture route matching.
