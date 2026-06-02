# Knowledge Ontology Operations Guide

This guide is the maintenance reference for the profile-aware Knowledge workflow: namespace creation, ontology profile bootstrap, domain-pack installation, ingestion candidate review, Nexus explorer use, and Enterprise Map visualization.

## Core lifecycle

1. **Create a namespace** with `POST /api/knowledge/namespaces` or `KnowledgeService.create_namespace`.
2. **Bootstrap a profile** with `POST /api/knowledge/namespaces/{namespace}/ontology/reset-default`. The default profile is `enterprise_feature_map` and is deterministic per namespace.
3. **Install a domain pack** with `POST /api/knowledge/namespaces/{namespace}/ontology/packs/install`. Built-in packs live under `knowledge/ontology/packs/defaults/` and are merged into the namespace profile and pack state.
4. **Ingest source material** with folder or text ingestion. With an active profile, extraction normalizes known labels and creates reviewable ontology candidates for unknown concept or relationship labels.
5. **Review candidates** with `/ontology/candidates` list plus approve/map/reject/bulk routes. Approved candidates add new profile definitions; mapped candidates point unknown labels to existing canonical definitions; rejected candidates stay suppressed for the same source hash.
6. **Explore the graph** through legacy graph/query routes and Nexus explorer routes under `/explorer/*`.
7. **Render Enterprise Map** using the frontend Enterprise Map tab, which consumes explorer seed data, ontology profile metadata, installed pack state, and candidate state.

## Profile schema extension points

Ontology profiles are namespace-scoped. Different projects can define different profiles without changing global storage because profile JSON is stored under `{knowledge_dir}/{namespace}/ontology/profile.json` and the namespace manifest only records the active profile version.

Key profile sections:

| Section | Purpose | Extension rule |
|---|---|---|
| `concept_types` | Node taxonomy such as `feature`, `service`, `data_object`, `financial_product` | Add project-specific types with stable IDs, labels, abstraction levels, colors, shapes, lifecycle state, and optional metadata schema. |
| `relationship_types` | Canonical edge vocabulary | Add only labels with clear semantics, source/target constraints, family, direction, weight, style, and inverse when applicable. |
| `aliases` | Relationship label normalization | Map source/extraction vocabulary to canonical relationship IDs; never shadow an existing canonical relationship ID. |
| `concept_aliases` | Concept type normalization | Map project/user labels to canonical concept types. |
| `layers` | Enterprise map lanes such as strategy/product/platform/data/governance | Use for visualization grouping, not as a substitute for concept type. |
| `abstraction_levels` | Semantic altitude such as capability/feature/implementation/evidence | Use for cross-layer reasoning and validation. |
| `metadata_fields` | Project-specific node metadata | Define stable field IDs and descriptions; domain packs can add fields. |
| `validation_rules` | Governance checks | Prefer warning rules for adoption and error rules only for invariants that must block save/validation. |

### Multiple project profiles

Projects should start with the default `enterprise_feature_map` profile, then add only domain-specific types and metadata fields. For example, a banking project installs the Financial Services pack to add `financial_product`, `regulatory_obligation`, and `regulated_by`; a SaaS project may instead install Technology SaaS concepts. Because profiles are per namespace, both projects can use the same Knowledge backend, import pipeline, Nexus explorer, and frontend hooks while preserving separate metadata vocabularies.

## Relation taxonomy: when to use each core relation

| Relation | Use when | Do not use when |
|---|---|---|
| `depends_on` | The source cannot be delivered, reasoned about, or considered complete without the target. Example: `Loan Origination depends_on KYC Screening Service`. | The relationship is only data movement or an output; use `consumes` or `produces`. |
| `consumes` | The source reads, calls, imports, or uses data/service/artifact at runtime. Example: `Risk Scoring consumes Customer Profile Data`. | The target is a prerequisite rather than an operational input; use `depends_on`. |
| `produces` | The source creates an artifact, event, data object, evidence item, or output. Example: `KYC Screening produces Customer Risk Assessment`. | The source merely unlocks another capability; use `enables`. |
| `enables` | The source unlocks or supports the target. It is commonly the inverse view of `depends_on`, but may also be authored when the product planning perspective starts from the enabler. | The target directly consumes the source at runtime; use `consumes`/`feeds`. |
| `regulated_by` | A Financial Services source is governed by a regulatory obligation or evidence object. | General dependency or flow semantics; keep governance relationships explicit. |
| `related_to` | Weak semantic association when no stronger relation is defensible. | As a fallback for unknown extraction labels; unknowns should become candidates. |

## Domain pack authoring

Pack manifests live in `knowledge/ontology/packs/defaults/*.json` and are validated by `DomainPackStore` before merge. A pack should include:

- `pack_id`, `name`, `version`, and `compatible_profile_versions`.
- Additive `concept_types`, `relationship_types`, `metadata_fields`, `aliases`, and `validation_rules`.
- `fixtures` that demonstrate valid node/edge combinations.
- `migration_notes` explaining governance impact.

Authoring rules:

1. Use stable lowercase IDs with underscores or dashes.
2. Keep pack additions additive and reversible; uninstall removes pack-owned definitions when safe.
3. Define validation rules as warnings first unless migration safety requires an error.
4. Include at least one fixture edge that validates all new relationship constraints.
5. Run `service.validate_domain_pack_install(namespace, pack_id)` or `POST /ontology/packs/validate` before install.

## Candidate review operations

Unknown extraction output is persisted in `{namespace}/ontology/candidates.json` and exposed through REST and frontend hooks.

- **Approve** when the label should become a new canonical concept or relationship type.
- **Map** when the label is a synonym for an existing canonical ID, such as mapping `powers` to `enables`.
- **Reject** when the source label is noise or should not reappear for the same source hash.
- **Bulk update** only after confirming candidate source samples and confidence.

## QA operations checklist

Run these checks before release:

- Create namespace and verify manifest records `ontology_profile_version` only after profile save/reset.
- Bootstrap default profile and validate no blocking profile issues.
- Install Financial Services pack and verify `financial-services` is present in installed pack state.
- Ingest `tests/fixtures/ontology_lifecycle` through the deterministic test path and verify candidate `powers` appears.
- Map `powers -> enables` and verify pending candidate count returns to zero.
- Query raw, graph, and summarized modes and verify all return the stable `QueryResult` shape.
- Run Nexus explorer seed on both legacy and profile-enabled namespaces.
- Render Enterprise Map and verify lanes, filters, relation style metadata, inverse labels, candidate state, and detail drawer.

## Regression commands

```bash
pytest tests/test_knowledge_ontology_lifecycle_e2e.py tests/test_knowledge_ontology_api.py tests/test_ontology_candidates.py tests/test_domain_packs.py -q
pytest tests/test_knowledge_e2e_rest.py tests/test_knowledge_explorer.py -q
cd fe && bun run test -- EnterpriseMapPanel use-ontology use-knowledge-explorer
python scripts/bench_ontology_operations.py --json
```
