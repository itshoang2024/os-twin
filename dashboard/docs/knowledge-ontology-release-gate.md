# EPIC-010 Ontology Release Gate Evidence

## Engineer self-verification

### Automated backend

```bash
pytest tests/test_knowledge_ontology_lifecycle_e2e.py tests/test_knowledge_ontology_api.py tests/test_ontology_candidates.py tests/test_domain_packs.py tests/test_knowledge_explorer.py -q
# 83 passed, 1 warning in 2.26s

pytest tests/test_knowledge_query.py -q -x
# 33 passed, 1 warning in 59.60s

pytest tests/test_knowledge_e2e_rest.py -q -x
# 17 passed, 1 warning in 4.06s

pytest tests/test_knowledge_query.py tests/test_knowledge_e2e_rest.py tests/test_knowledge_explorer.py tests/test_knowledge_ontology_lifecycle_e2e.py -q
# 105 passed, 2 warnings in 68.97s
```

Coverage includes namespace creation, default profile bootstrap, Financial Services pack install, deterministic fixture ingestion, candidate mapping, raw/graph/summarized query-mode contract, Nexus explorer seed for both profile-enabled and legacy namespaces, and the broader legacy Knowledge query/REST lifecycle regressions.

### Automated frontend

```bash
cd fe && bun run test -- EnterpriseMapPanel use-ontology use-knowledge-explorer
# 3 passed, 45 tests passed in 1.30s
```

Coverage includes Enterprise Map tab rendering, profile-driven edge styles, filters, detail drawer accessibility, ontology hooks, and Knowledge explorer hook behavior.

### Performance baseline

```bash
python scripts/bench_ontology_operations.py --json
```

Latest deterministic measurements:

| Operation | Elapsed |
|---|---:|
| profile_load | 0.424 ms |
| profile_validation | 0.279 ms |
| candidate_listing | 0.238 ms |
| explorer_seed | 166.706 ms |
| enterprise_map_data_prep | 0.010 ms |

### Manual E2E checklist for QA

1. Start frontend from `fe/` with `bun run dev` and open `http://localhost:3000`.
2. Create a Knowledge namespace.
3. Open Ontology tab and reset/bootstrap default profile.
4. Install the Financial Services pack.
5. Import `tests/fixtures/ontology_lifecycle` or run the deterministic test path.
6. Confirm candidate `powers` appears and map it to `enables`.
7. Open Nexus explorer and verify seed/expand behavior.
8. Open Enterprise Map and verify lane mode, filters, relationship styles, detail drawer, candidate state, and citation section.

## Residual risks

- Production ingestion still depends on external parser, embedding, Kuzu, and LLM availability; deterministic regression doubles now cover the release gate when local/CI embedding services are unavailable.
- Ollama local smoke checks passed for `gemma3:1b` and `qwen3-embedding:0.6b`, but the release-gate query/REST suites no longer require those models to be running.
- Final `@qa` signoff remains pending; this document is engineer-provided release-gate evidence, not QA approval.


## Governed knowledge development workflow

EPIC-010 release readiness requires the ontology workflow to be operable without ad hoc LLM calls. The supported lifecycle is:

1. **Author graph instructions** in the Ontology Operations panel. The Graph Instruction editor owns lane dimension, layout hints, default views, relationship rendering defaults, validation surfaces, and small fixture examples as profile JSON.
2. **Preview before mutation** by running profile validation and the side-effect-free profile diff endpoint. The preview displays changed paths plus migration-safety warnings/errors so reviewers can understand schema drift before persistence.
3. **Install governed domain packs** from the Domain Packs section. Audit Risk / Audit Risk Management and Ecommerce Logistics packs contribute versioned concept types, relationship types, aliases, fixtures, Graph Instruction defaults, and migration notes; installs are recorded in namespace pack state and audit operations.
4. **Ingest deterministic or production content**. Release-gate tests use deterministic ingestion fakes so QA can exercise candidate generation without parser, embedding, Kuzu, LLM, or network dependencies. Production imports still use the normal Knowledge import pipeline.
5. **Review candidates** in Candidate Review. Unknown extracted concept or relationship labels can be approved as new canonical enums, mapped to an existing enum/alias, rejected, or bulk rejected. Every review action updates candidate status and appends governance audit metadata.
6. **Inspect lineage** through Enterprise Map / Nexus. Domain pack concepts and relationships carry ontology path, pack id, validation issues, relationship direction, and candidate state so users can follow risk-control-evidence or ecommerce delivery dependencies across the graph.
7. **Require override metadata for dangerous changes**. Error-severity migration issues block save unless the user has previewed the diff and supplies override ticket, approver, and reason metadata; the backend stores that override in profile history.

## Release gate matrix

| Gate | Evidence | Required result |
|---|---|---|
| Performance | `python scripts/bench_ontology_operations.py --json` | Profile load/validation and candidate listing stay sub-second; explorer seed remains bounded for QA fixtures. |
| Accessibility | Frontend ontology and Enterprise Map tests plus manual keyboard/screen-reader pass | Buttons have accessible labels/text, JSON editor has an aria label, candidate selection controls remain keyboard reachable. |
| Schema drift | `POST /ontology/profile/diff`, profile history, migration safety checks | Removed/deprecated relationship types surface changed paths and warnings/errors before save. |
| Legacy compatibility | `test_nexus_explorer_seed_preserves_legacy_namespace_shape` and Knowledge query/REST suites | Namespaces with no ontology profile still return explorer/query shapes with validation fields present. |
| Domain pack governance | `tests/test_domain_packs.py` and lifecycle E2E | Audit Risk and Ecommerce Logistics packs validate, install, expose fixtures, and merge Graph Instructions deterministically. |
| No external LLM release tests | `tests/test_knowledge_ontology_lifecycle_e2e.py` | QA lifecycle path completes using deterministic fakes only. |
