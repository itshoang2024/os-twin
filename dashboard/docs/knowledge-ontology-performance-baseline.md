# Ontology Operations Performance Baseline

Baseline captured for EPIC-010 on 2026-06-02 using deterministic release-gate fixtures. The deterministic benchmark avoids parser/model/network variance and measures service/API orchestration overhead for the profile-aware workflow.

## Baseline command

```bash
python scripts/bench_ontology_operations.py --json
```

## Recorded baseline

| Operation | Baseline target | Recorded on deterministic fixture | Notes |
|---|---:|---:|---|
| Profile load | < 25 ms | ~1-5 ms | `KnowledgeService.get_ontology_profile_with_default` after namespace bootstrap. |
| Profile validation | < 50 ms | ~1-10 ms | `validate_ontology_payload(subject=profile)`. |
| Candidate listing | < 25 ms | ~1-5 ms | Pending candidate list after deterministic fixture ingestion. |
| Explorer seed | < 200 ms | 166.706 ms | `explorer_seed(top_k=3)` with ontology-aware fake graph and NetworkX community detection. |
| Enterprise map render/data prep | < 250 ms | 0.010 ms backend data prep; 45 frontend tests in 1.30s | Covered by `fe/src/__tests__/EnterpriseMapPanel.test.tsx`; manual browser QA should verify at `http://localhost:3000`. |

## Scaling expectation

Enterprise-scale namespaces should keep backend profile, validation, candidate listing, and seed orchestration sub-second. Actual import, embedding, graph extraction, and browser rendering costs scale with file count, vector backend, graph size, and client hardware; measure separately with production data before increasing candidate or explorer seed limits.

## Release gate interpretation

A release fails performance gate if deterministic profile load, validation, candidate list, explorer seed, or Enterprise Map render regresses by more than 3x from this baseline without a documented reason, or if any operation becomes unbounded with namespace size.
