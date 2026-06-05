# Plan: Ontology Workbench — Palantir-Aligned Refactor

> Created: 2026-06-04
> Status: draft
> Author: Engineering (design review of Palantir Foundry Object Explorer → mapped to the Governed Ontology Schema Builder Flow)
> Supersedes UI direction in: docs/ontology-plan-latest.md (this plan is the *frontend/workbench* execution cut; the six-plane data model in that doc remains the backend contract)

working_dir: /Users/paulaan/PycharmProjects/agent-os/dashboard


## EPIC-001: Ontology Unit Cold Start

Roles: @engineer, @qa
### The problem (stated by the product owner)

> "The current design codebase is messy for `OntologySchemaBuilder.tsx`. We need the next version of how the schema builder supports building an Ontology Profile. This profile can be extended in any domain — Build Software, Audit Airline, Audit Legal company process. It becomes the ontology layer. But the current design doesn't allow us to design the Ontology profile properly."

### Root cause (from codebase review)

The app already declares two lenses — `LensMode = 'spec' | 'map'` (`fe/src/components/knowledge/ontology/OntologyPanel.tsx:20`) — but they are **two unrelated implementations**:

- **Map Lens** (`fe/src/components/knowledge/EnterpriseMapPanel.tsx`, ~104 KB) already speaks fluent "Palantir": left dock (Layers/Selection/Search/Histogram), top toolbar (Group/Layout/Search-Around), color-by-property styling, faceted histogram, layout modes, time selection, and honest `live`/`example` truth-states.
- **Spec Lens** (`fe/src/components/knowledge/ontology/OntologySchemaBuilder.tsx`, ~38 KB) is hand-drawn SVG with a 3-mode rail (`schema|layers|properties`), a private chat assistant that bypasses governance, and a second overlapping inspector (`ObjectWorkbench`) mounted beside it.

That mismatch **is** the mess. The schema builder cannot "design the profile properly" because it speaks a cruder dialect than the rest of the product, and because the backend type contract is missing the fields real domains need (`cardinality`, `source_mappings`).

### The thesis

> **Make the Spec Lens render through the *same* Palantir shell as the Map Lens. It simply projects _types_ ("what can exist") instead of _instances_ ("what exists").**

Once both lenses sit on one shell, the master-plan promise — *"one governed ontology contract renders as graph, detail, histogram, … without domain-specific frontend rewrites"* — becomes structurally guaranteed, because there is only one renderer. A profile authored for **Build Software**, **Audit Airline**, or **Audit Legal** renders identically; only the projected types differ.

### Key decisions to lock before Phase 1

1. **Spec-Lens default render mode** — recommend **card with extended labels** (G8) showing 2–3 key metadata fields + a source-mapping badge (types are fewer/richer than instances). Decision owner: @principal-engineer.
2. **Styling home** — commit to **`GraphInstruction`-only** for new profiles (DM-04); `ConceptType.color/shape` becomes read-only legacy fallback. Migration touch-point. Owner: @database-architect.
3. **Search Around in Spec** — keep it (traverse relationship types from a concept) rather than dropping to save scope; valuable for large ontologies. Owner: @principal-engineer.
4. **`cardinality` vocabulary** — `one_to_one|one_to_many|many_to_one|many_to_many` (nullable, open to extension). Owner: @database-architect.
5. **`SourceMapping` shape** — minimum viable: `{ source_type, source_uri?, field_path?, transform?, evidence_ref? }`, strict. Owner: @database-architect.

###  Risks

- **Strict models block UI.** Any missed field declaration fails profile load; all model changes go through @database-architect with migration notes (Phase 0 first).
- **Shell extraction regressions.** FW-1 must be behavior-preserving for the Map Lens; gate on the existing `EnterpriseMapPanel.test.tsx` suite + screenshot parity before Spec Lens work.
- **Two-dialect relapse.** If Spec Lens work starts before FW-1, the grammar gets reimplemented. Enforce the phase order.
- **Auto-seed vs. empty honesty.** Gating the seed (`EnterpriseMapPanel.tsx:725`) may affect demo flows that relied on it; coordinate with @program-manager.
- **Assistant mutation surface.** Builder AI moving to staged proposals must keep `candidate_actions`/`fact_actions` advisory-only (`assistant-proposals.ts:35-37`).

### Appendix A — File inventory (touch map)

| Area | File | Phase / EPIC |
|---|---|---|
| Unit model | `knowledge/ontology/models.py:77` | P0 / E1 |
| Type fields | `knowledge/ontology/models.py:212` (Relationship), `:179` (Concept), `:126` (Metadata) | P0 / E3 |
| Store | `knowledge/ontology/store.py:45,111,131` | P0 / E1,E4 |
| Routes | `routes/knowledge.py`, `routes/knowledge_models.py` | P0 / E1,E6 |
| Hooks | `fe/src/hooks/use-ontology.ts` | P0–P3 / E1,E3 |
| Shared shell | `fe/src/components/knowledge/workbench/*` (NEW) | P1 / FW-1 |
| Map Lens | `fe/src/components/knowledge/EnterpriseMapPanel.tsx` | P1,P4 / FW-1,E5 |
| Spec Lens | `fe/src/components/knowledge/ontology/OntologySchemaBuilder.tsx` (retire) | P2 / E3 |
| Object editor | `fe/src/components/knowledge/ontology/ObjectWorkbench.tsx` (absorb) | P2 / E3 |
| Staged AI | `fe/src/components/knowledge/ontology/assistant-proposals.ts` | P2 / E3 |
| Shell host | `fe/src/components/knowledge/ontology/OntologyPanel.tsx` | P2–P4 / E1–E5 |
| Tests | `fe/src/__tests__/*`, `tests/test_ontology_*.py` | P5 / E6 |

### Context & Palantir mapping
Palantir's **Info tab** (G2) and the **template title** (G12) carry the identity of the thing being explored. That identity is your `OntologyUnit`. Cold start must show the launcher and **never** auto-render the default graph; a Unit must be able to exist as governance/identity metadata *before* any profile is published.

### Current state (grounded)
- `OntologyUnit` exists (`knowledge/ontology/models.py:77`) but `active_profile_id: str` is **required** (validated identifier) and there is **no** `name/purpose/domain/expected_users/source_material/governance_mode`.
- Legacy synthesis works: `OntologyProfileStore.get_unit()` fabricates a Unit from `profile.json` when `unit.json` is absent (`knowledge/ontology/store.py:45`).
- **No** `/ontology/unit` route, **no** `OntologyUnitResponse`, **no** `useOntologyUnit` hook (units are backend-only today).
- Cold-start gate already correct: `OntologyPanel.tsx:1201` returns `<OntologyUnitLauncher>` when `!profileExists && !draft`; default is a banner (`:1277`), not a rendered graph.
- Launcher already exists with "No active ontology unit", Ask AI / Preview seed / Start blank (`OntologyPanel.tsx:190`).

### Definition of Done
- [ ] `OntologyUnit.active_profile_id` is nullable; a Unit can persist before a profile exists.
- [ ] Unit carries `name`, `purpose`, `domain`, `expected_users`, `source_material`, `governance_mode` (all strict-declared).
- [ ] `GET/PUT /namespaces/{ns}/ontology/unit` exists and returns `OntologyUnitResponse`.
- [ ] `useOntologyUnit` hook reads/writes the unit; the Info tab renders unit identity.
- [ ] A cold namespace shows the launcher and **never** renders the default graph automatically.

### Acceptance Criteria
- [ ] Creating a unit records name/purpose/domain/expected users/source material/governance mode and persists with `active_profile_id = null`.
- [ ] Legacy namespaces with `profile.json` but no `unit.json` synthesize an active unit with no migration break (existing `get_unit()` behavior preserved + extended).
- [ ] `PUT /ontology/profile` remains backward compatible (no required new request fields).
- [ ] Strict-model validation still rejects undeclared fields on `OntologyUnit`.
- [ ] `OntologyUnit.active_profile_id` (when non-null) cannot point outside the namespace (preserve `models.py:121` invariant).

### Tasks
- [ ] @database-architect: change `active_profile_id: str | None = None`; relax `_derive_and_validate_id`/`_active_profile_id_is_identifier` to allow null; add the six metadata fields with safe defaults (`knowledge/ontology/models.py:77-123`).
- [ ] @database-architect: extend `store.get_unit()` synthesis to populate new fields with defaults; ensure `write_unit()` tolerates null `active_profile_id` (`knowledge/ontology/store.py:45,131`).
- [ ] @engineer: add `OntologyUnitResponse` + `GET/PUT /namespaces/{ns}/ontology/unit` (`routes/knowledge.py`, `routes/knowledge_models.py`); add service methods (`knowledge/service.py`).
- [ ] @engineer: add `useOntologyUnit(namespace)` to `fe/src/hooks/use-ontology.ts` (mirror `useOntologyProfile` shape).
- [ ] @engineer: render unit identity in the **Info** dock tab; have the launcher write unit metadata on create.
- [ ] @qa: contract tests for draft-unit (null profile), active-unit, and legacy synthesis (`tests/test_ontology_profile.py`, `tests/test_knowledge_ontology_api.py`).

### Data / API / Model impact
- New strict fields on `OntologyUnit`; nullable `active_profile_id`. New `unit.json` shape (back-compatible — synthesis fills gaps).
- New routes `GET/PUT …/ontology/unit`; new `OntologyUnitResponse` model.

### Other aspects
- Treat unit creation as **governance/identity state**, not profile publication.
- Keep candidate-entity status terminology distinct from unit/profile lifecycle (DM-05).

depends_on: []

---

## EPIC-002: Starting Strategy Pipeline

Roles: @engineer, @qa-automation-engineer

## Part III — Target architecture

Extract the Palantir shell out of `EnterpriseMapPanel`, then feed it from two thin lens adapters.

```
fe/src/components/knowledge/workbench/          ← NEW shared shell (Palantir grammar)
  WorkbenchShell.tsx         selector + dock + toolbar + canvas + right rail + bottom rails
  WorkbenchDock.tsx          Layers · Selection · Search · Histogram · Info
  WorkbenchToolbar.tsx       Selection · Search Around · Group · Layout · Undo/Redo · Validate/Publish
  SelectionInspector.tsx     Properties · Sources · Validation · Lifecycle · Relationships
  LayersStylingPanel.tsx     color-by (property/fixed/type) · subtitle · extended labels · badges
  HistogramPanel.tsx         faceted, binning, filter-to/out   (shared logic)
  GraphCanvas.tsx            card/chip nodes + typed icons + edge labels
  layout/engine.ts           Auto/Hierarchy/Grid/Row/Column/Circular/Radial/Cluster/Cartesian
  model/workbenchModel.ts    WorkbenchNode/Edge/Selection shared types (lens-agnostic)
  adapters/
    specLensAdapter.ts       OntologyProfile      → type-nodes + relationship-type-edges
    mapLensAdapter.ts        projection/instances → object-nodes + edges (wraps existing)
```

End-state component roles:

- `OntologyPanel` → **shell host** (master-plan EPIC-009): owns namespace, lens toggle, draft, selection sync, publish.
- `OntologySchemaBuilder` → **retired**; canvas folds into `GraphCanvas`+`specLensAdapter`, inspector into `SelectionInspector`, private chat **deleted** for the shell's staged `AssistantProposalPanel`.
- `ObjectWorkbench` → **absorbed** into `SelectionInspector` (kills the two-editor problem).
- `EnterpriseMapPanel` → **re-homed** onto `WorkbenchShell` via `mapLensAdapter` (behavior-preserving).

### Context & Palantir mapping
Frame 4's `Flight Delay Template*` is the model: a **template** is a reusable, preview-only starting point — not an installed graph. Every launcher path must produce a **local draft or a staged proposal**, never a hidden write.

### Current state (grounded)
- Launcher offers Ask AI / Preview seed / Start blank (`OntologyPanel.tsx:190`); `handlePreviewSeedTemplate` clones the seed into a **local draft** with correct copy ("validate, preview diff, and save before it becomes active", `:958-975`).
- `makeBlankOntologyProfile` exists (`:153`).
- AI path is genuinely governed: `assistant-proposals.ts` parses fenced JSON, enforces `ALLOWED_SECTIONS` + `FIELD_ALLOWLIST`, marks `candidate_actions`/`fact_actions` advisory-only, and only `applyOntologyProposalToDraft` touches local state.
- 8 packs available via `useOntologyPacks`; assistant fallback returns a structured `proposed_changes` envelope (`routes/knowledge.py:~815-980`).
- `OntologyCandidate` already carries `proposed_payload` + `source_evidence` (`use-ontology.ts:371`).

### Definition of Done
- [ ] Template gallery shows built-in packs **plus** blank, each labelled "Template preview — not installed yet."
- [ ] Every launcher path creates/loads a draft (or staged proposal) without mutating active state.
- [ ] "Build from imported knowledge" summarizes pending candidates + evidence refs.

### Acceptance Criteria
- [ ] Template cards are backed by `useOntologyPacks` pack manifests + the blank profile; selecting one loads a **preview draft**, not an install.
- [ ] "Start blank" opens an empty canvas with "Add your first object type."
- [ ] "Ask AI" opens a draft and produces a staged proposal card (no direct profile write).
- [ ] AI requests include candidate/evidence `context` (proposed_payload + source_evidence_ref).
- [ ] No launcher path issues a `PUT /ontology/profile` before explicit publish.

### Tasks
- [ ] @engineer: build template gallery cards from pack manifests + blank; "preview not installed" copy; load into local draft (extend launcher in `OntologyPanel.tsx:190`).
- [ ] @engineer: inject candidate/evidence context into `askAssistant` request (`fe/src/hooks/use-ontology.ts:714` consumers).
- [ ] @engineer: "Build from imported knowledge" path renders pending-candidate + evidence summary before draft creation.
- [ ] @qa-automation-engineer: tests per starting strategy proving **no hidden profile save** (extend `OntologyPanel.test.tsx`).

### Data / API / Model impact
- No new persisted models. Reuses packs, candidates, evidence, assistant endpoints.

### Other aspects
- Existing default enterprise profile remains a **template**, not a cold-start graph.
- Candidate extraction stays evidence-linked and reviewable.

depends_on: [EPIC-001]

---

## EPIC-003: Schema Builder Workspace (the heart of the refactor)

Roles: @engineer, @qa-automation-engineer

### Context & Palantir mapping
This is where the Palantir grammar lands on the Spec Lens. The schema builder becomes the **Spec Lens adapter on `WorkbenchShell`** (FW-1): same 5-tab dock (G2), same toolbar (G6), same layout engine (G7), same node cards (G8), same styling (G5) — projecting **types** instead of instances.

### Current state (grounded — the mess)
- Spec lens renders `OntologySchemaBuilder` in center canvas (`OntologyPanel.tsx:1294`) **and** a second editor `ObjectWorkbench` in the right dock (`:1350`) — two inspectors over one draft.
- Builder AI is raw chat: `askAssistant` → append to `chatTurns` (`OntologySchemaBuilder.tsx:307,424`); it never calls `parseOntologyAssistantResponse`/`applyOntologyProposalToDraft` — **bypasses governance**.
- Canvas is hand-coded SVG with manual `x/y` in `buildSchemaGraph`; rail is a 3-mode toggle (`:313`).
- `RelationshipType` has **no `cardinality` field** (the only `cardinality` is a `ValidationRuleType` literal, `models.py:60`); `source_mappings` exists **nowhere** — so domains like audit/ingestion can't map a type/relationship/property to a data source.
- Frontend `BUILDER_FAMILIES` (`OntologySchemaBuilder.tsx:40`) is missing `classification/causality/temporal` vs. the backend 12-value `RelationshipFamily` union (`models.py:39`).

### Definition of Done
- [ ] Spec Lens renders through `WorkbenchShell` via `specLensAdapter`; `OntologySchemaBuilder.tsx` is retired.
- [ ] Exactly **one** selection inspector (`SelectionInspector`) edits a type; `ObjectWorkbench` is absorbed.
- [ ] Builder AI routes through the shell's staged `AssistantProposalPanel` — no private chat path.
- [ ] `RelationshipType.cardinality` and `source_mappings` (on concept, relationship, metadata) exist as strict-declared fields and are editable in the inspector.

### Acceptance Criteria
- [ ] Left dock exposes Sources, Candidates, Object Types, Properties, Relationships, Validation, Templates (as dock tabs / inspector sections), not a 3-mode rail.
- [ ] Center canvas renders **schema type nodes + relationship-type edges only** (no fake instance maps); edges display cardinality.
- [ ] Object inspector edits label, description, icon/color/shape, properties, **source mappings**, validation, lifecycle.
- [ ] Relationship inspector edits endpoints, direction, **cardinality**, label, style, source mappings, validation.
- [ ] Type styling writes `GraphInstruction` defaults (View plane, DM-04); `ConceptType.color/shape` becomes legacy read-only fallback.
- [ ] All edits stay in local draft until validate/diff/save; pack-ownership badges preserved.
- [ ] Canvas has empty / loading / validation / overflow states.

### Tasks
- [ ] @database-architect: add `RelationshipType.cardinality` (e.g. `one_to_one|one_to_many|many_to_one|many_to_many`, nullable) and `source_mappings: list[SourceMapping]` to `ConceptType`/`RelationshipType`/`MetadataField` (`knowledge/ontology/models.py`); declare `SourceMapping` strict model; add validator coverage; migration note (DM rules).
- [ ] @engineer: sync FE families to the 12-value union; extend FE types in `fe/src/hooks/use-ontology.ts` for `cardinality`/`source_mappings`.
- [ ] @principal-engineer: implement `specLensAdapter.ts` (`OntologyProfile` → `WorkbenchModel` type-nodes + relationship-type-edges, default layout Hierarchy L→R).
- [ ] @engineer: build `SelectionInspector` sections (Properties/Sources/Validation/Lifecycle/Relationships); migrate logic from `SchemaInspector` (`OntologySchemaBuilder.tsx:563`) + `ObjectWorkbench.tsx`.
- [ ] @engineer: mount Spec Lens on `WorkbenchShell`; delete builder private chat (`OntologySchemaBuilder.tsx:307-436`); wire builder AI actions to `AssistantProposalPanel` (`OntologyPanel.tsx:712`).
- [ ] @engineer: type styling → `GraphInstruction` writer in `LayersStylingPanel`; ConceptType color/shape read-only fallback.
- [ ] @qa-automation-engineer: tests for inspector edits, staged-AI apply, cardinality/source-mapping round-trip, single-inspector invariant.

### Data / API / Model impact
- New strict fields: `RelationshipType.cardinality`; `source_mappings` on concept/relationship/metadata; new `SourceMapping` model.
- `assistant-proposals.ts` `FIELD_ALLOWLIST` updated to allow `cardinality`/`source_mappings` (`:49-55`).

### Other aspects
- Keep `OntologyProfile` cross-reference validators intact (`models.py:293`).
- Preserve current pack ownership badges (`packOwnership`, `OntologyPanel.tsx:1295`).

depends_on: [EPIC-001, EPIC-002, FW-1]

---

## EPIC-004: Validate, Diff, and Publish Profile

Roles: @engineer, @qa

### Context & Palantir mapping
`Flight Delay Template*` (dirty asterisk, G12) + toolbar `Undo/Redo` (G6) are Palantir's governance affordances. Publishing makes a validated draft the unit's **active** profile.

### Current state (grounded — pipeline already exists)
- Full API present: `useOntologyValidation.validateProfile`, `useOntologyHistory.diffProfile` (`would_mutate` + `migration_issues`), `saveProfile({reason, validation_override})` → `PUT /ontology/profile` (`use-ontology.ts:435,480,492`).
- History records carry `changed_paths`, `validation_override`, `migration_entries` (`use-ontology.ts:169`).
- `store.write(profile, set_active=…)` updates manifest version **and** rewrites unit `active_profile_id` (`store.py:111`).
- UI panels exist: `GraphDiffOverlay` (`OntologyPanel.tsx:333`), `HistoryPanel` (`:347`).

### Definition of Done
- [ ] Publish runs validate → diff → migration preview → save, in order.
- [ ] Draft saves as active **only** on explicit publish; nothing persists earlier.
- [ ] Header shows active version only after publish; dirty drafts show an asterisk/"Unsaved draft".
- [ ] Profile history records reason, actor, changed paths, migration issues, override metadata (already supported — assert wired).

### Acceptance Criteria
- [ ] First activation button reads "Publish profile"; subsequent reads "Save profile update."
- [ ] Publish sends `status: active`; updates unit `active_profile_id` (EPIC-001 nullable → set on publish).
- [ ] Dangerous migration impact stays blocked without `validation_override` metadata.
- [ ] Header transitions "Ontology unit draft" (`OntologyPanel.tsx:1231`) → "{unit name} · Active profile v0.1" post-publish.

### Tasks
- [ ] @engineer: implement Publish action orchestrating validate→diff→migration-preview→save with the dirty-asterisk affordance in `WorkbenchToolbar`.
- [ ] @engineer: rename Save → "Publish profile"/"Save profile update"; ensure `status:'active'` on publish.
- [ ] @engineer: on successful publish, set unit `active_profile_id` via `useOntologyUnit`.
- [ ] @database-architect: confirm `store.write(set_active=True)` unit linkage covers the null→active transition (`store.py:111-128`).
- [ ] @qa: tests for validation-block, diff-preview, override-required, successful publish (`tests/test_ontology_profile.py`, `OntologyPanel.test.tsx`).

### Data / API / Model impact
- Reuses existing endpoints. Unit `active_profile_id` flips null→profile on publish.

### Other aspects
- Use existing profile save endpoint for v1 (no dedicated publish op unless audit demands).
- Do not auto-approve candidates during publish.

depends_on: [EPIC-003]

---

## EPIC-005: Map Lens Truth States and Operations

Roles: @engineer, @qa-automation-engineer

### Context & Palantir mapping
Palantir's `[Example Data]` prefix (G11) is the explicit example-vs-real marker. Map Lens must truthfully distinguish **live / example / empty**; view-ops (G6) stay view-state-first until saved as a `GraphInstruction`.

### Current state (grounded)
- Two states exist: `mapSourceKind: 'live' | 'example'` from `shouldUseFallbackMap` (`EnterpriseMapPanel.tsx:711-712,793`); example nodes tagged `review_state:'example'` via `buildExampleMapFromProfile` (`OntologyPanel.tsx:553`); example banner at `EnterpriseMapPanel.tsx:845`.
- **Missing `empty` state**: zero live + zero fallback nodes currently renders an empty live map.
- **Auto-seed effect** injects demo nodes when empty (`EnterpriseMapPanel.tsx:725`) — this would contradict an honest "No graph objects yet" state.
- View-ops already local-first (`visualDraft`, search-around, histogram, saved views).

### Definition of Done
- [ ] Explicit map-state derivation: `live | example | empty`.
- [ ] If only examples/fixtures exist → "Example Data" banner (preserve).
- [ ] If nothing exists → "No graph objects yet" with import / approve-candidates / create-sample actions.
- [ ] No default enterprise map appears as real data for a new namespace.

### Acceptance Criteria
- [ ] Map-state is a single derived discriminator consumed by the panel (not ad-hoc booleans).
- [ ] Auto-seed is gated/removed so `empty` stays empty until the user acts.
- [ ] Search-around, histogram, group-by, layout, style, saved-views, selection-sync do not mutate the profile until saved.
- [ ] Spec↔Map selection stays in sync across lens switches; draft edits preserved across switches.

### Tasks
- [ ] @engineer: add explicit `mapState: 'live'|'example'|'empty'` derivation in `EnterpriseMapPanel`/`mapLensAdapter`.
- [ ] @engineer: build the `empty` state component with the three actions; gate the auto-seed effect (`EnterpriseMapPanel.tsx:725`).
- [ ] @engineer: preserve draft + selection across Spec/Map switches via the shared shell selection model.
- [ ] @qa-automation-engineer: E2E for live, example, and empty map states (Playwright under `fe/`).
- [ ] @data-scientist: validate example/live projection fidelity (no fabricated metrics; Series stays honest, `EnterpriseMapPanel.tsx:1463`).

### Data / API / Model impact
- No new persisted models; example data only from `GraphInstruction`/template fixtures when labeled. Live graph stays sourced from Kuzu/projection.

### Other aspects
- Release gate should flag **unlabeled** example data as a blocker (ties to EPIC-006).

depends_on: [EPIC-004, FW-1]

---

## EPIC-006: QA, Release Evidence, and Documentation

Roles: @qa, @qa-automation-engineer, @technical-writer, @program-manager

### Context
Lock the unified shell, the truth-states, and the governed lifecycle with coverage and docs.

### Definition of Done
- [ ] Unit/profile/builder/assistant/template/candidate/publish/Map-Lens flow has test coverage.
- [ ] Release observability includes unit/profile/candidate/fallback health.
- [ ] Docs explain the governed ontology lifecycle and Palantir-aligned workbench.

### Acceptance Criteria
- [ ] Unit API contract tests cover draft unit, active unit, legacy synthesis.
- [ ] Frontend tests cover all launcher paths, staged AI proposals, schema edits, publish, lens switching.
- [ ] Browser test verifies **no default graph appears before user choice**.
- [ ] Spec/Map **render-parity** test on the shared shell (same grammar, different projection).
- [ ] Docs describe templates as optional previews, not installed graphs.

### Tasks
- [ ] @qa: extend `tests/test_ontology_profile.py`, `tests/test_knowledge_ontology_api.py` (unit API, publish, override).
- [ ] @qa-automation-engineer: extend `fe/src/__tests__/OntologyPanel.test.tsx`, `EnterpriseMapPanel.test.tsx`; add Playwright cold-start / template-preview / blank-builder / publish / Map-Lens-states.
- [ ] @engineer: extend `/ontology/release-observability` to report unit + fallback health (`routes/knowledge.py:801`).
- [ ] @technical-writer: write `docs/ontology-workbench.md` (lifecycle, two-lens grammar, truth-states); update `docs/ontology-plan-latest.md` cross-refs.
- [ ] @program-manager: acceptance walkthrough vs. the Palantir grammar checklist (G1–G12).

### Data / API / Model impact
- Extend release-observability payload; no new core models.

### Other aspects
- Keep docs aligned with the namespace-keyed API compatibility rule (DM-02).

depends_on: [EPIC-001, EPIC-002, EPIC-003, EPIC-004, EPIC-005]

--
## EPIC-007: Foundation Workstream FW-1

Roles: @principal-engineer, @engineer, @qa-automation-engineer

### Context

`EnterpriseMapPanel.tsx` already implements ~80% of the Palantir grammar (dock tabs, `TimeSelectionMode` at `:150`, `liveMap/shouldUseFallbackMap/effectiveMap` at `:709-712`, `mapSourceKind` at `:793`, styling color-by, faceted histogram, layout, simulation empty-states). FW-1 lifts those into reusable primitives behind a **lens-agnostic model** so the Spec Lens can reuse them verbatim.

### Definition of Done
- [ ] `workbench/` package exists with `WorkbenchShell`, `WorkbenchDock`, `WorkbenchToolbar`, `SelectionInspector`, `LayersStylingPanel`, `HistogramPanel`, `GraphCanvas`, `layout/engine.ts`, `model/workbenchModel.ts`.
- [ ] `EnterpriseMapPanel` renders through `WorkbenchShell` via `mapLensAdapter` with **no visual or behavioral regression** (all existing `EnterpriseMapPanel.test.tsx` assertions pass).
- [ ] Shell consumes a lens-agnostic `WorkbenchModel` (nodes/edges/selection/facets/layers) — no `OntologyProfile`- or instance-specific types leak into shell components.

### Acceptance Criteria
- [ ] The 10-mode layout engine (G7) is a pure function `layout(nodes, edges, mode) → positions`, unit-tested per mode.
- [ ] `GraphCanvas` supports both render modes (G8): compact chip and extended-label card, toggled by prop.
- [ ] `HistogramPanel` faceting/binning/`Filter to`/`Filter out` (G4) is driven by a generic `Facet[]` contract.
- [ ] `LayersStylingPanel` color-by supports `fixed | object_type | property` with `true/false/fallback`-style swatches (G5).
- [ ] Map Lens screenshots (`fe/artifacts/`) are unchanged after re-homing.

### Tasks
- [ ] Define `model/workbenchModel.ts`: `WorkbenchNode`, `WorkbenchEdge`, `WorkbenchSelection`, `WorkbenchFacet`, `WorkbenchLayer`, `RenderMode`, `LayoutMode`, `ColorBy`.
- [ ] Extract dock/toolbar/inspector/histogram/styling/canvas from `EnterpriseMapPanel.tsx` into `workbench/*` with no map-specific logic.
- [ ] Write `mapLensAdapter.ts` mapping `EnterpriseMapProjectionData` → `WorkbenchModel`; mount `EnterpriseMapPanel` on `WorkbenchShell`.
- [ ] Port the layout positioning from `EnterpriseMapPanel` into `layout/engine.ts` as pure functions.
- [ ] Snapshot/interaction tests on the shared primitives.

### Other aspects
- Keep `EnterpriseMapPanel`'s public props stable so `OntologyPanel` wiring (`:1333`) does not change in this phase.
- Do **not** add Spec-Lens behavior here; FW-1 is a pure extraction.

depends_on: [EPIC-001, EPIC-003]

