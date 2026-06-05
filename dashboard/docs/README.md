# OSTwin Dashboard

OSTwin Dashboard provides the API server, knowledge graph services, ontology management layer, and management UI for the Agent OS dashboard workspace.

## Project Areas

- `knowledge/` contains namespace, ingestion, graph, memory, and ontology services.
- `routes/` exposes the FastAPI route layer used by the dashboard and tooling.
- `fe/` contains the frontend dashboard application.
- `docs/` contains architecture, ontology, operations, QA, and release documentation.
- `tests/` contains regression and contract tests for backend behavior.

## Development

This project is packaged from `pyproject.toml` as `ostwin-dashboard`. The README is intentionally present at `docs/README.md` because the package metadata references that path during editable builds and `uv run` test execution.

Common verification commands:

```bash
uv run pytest tests/test_ontology_profile.py tests/test_ontology_candidates.py tests/test_domain_packs.py -q
uv run pytest tests/test_ontology_profile.py tests/test_ontology_candidates.py tests/test_domain_packs.py tests/test_knowledge_ontology_api.py tests/test_ontology_governance.py tests/test_ontology_normalization.py tests/test_ontology_graph_instruction.py -q
```
