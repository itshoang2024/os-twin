---
name: ontology-knowledge
description: Use this skill to explore ontology namespaces in the knowledge base.
---

# ontology-knowledge

## Overview

Evaluates the retrieval quality and structural health of knowledge namespaces in the **Knowledge** layer (the project's source of truth). This skill runs probe queries across all three modes (`raw`, `graph`, `summarized`), measures latency, scores each namespace (`healthy`, `degraded`, or `critical`), and saves the findings back to the **Memory** layer as per `brain-ops` doctrine.

## When to Use

- During periodic knowledge quality audits
- After a large import to verify queryability
- When users or evaluators report poor retrieval/missing results in Memory
- When `curate-namespace` reveals suspicious stats (files > 0 but entities = 0)

## Tools Used

All tools are executed via the `mcporter` CLI following `brain-ops` standards:

| Tool | Purpose |
|------|---------|
| `memory.search_memory` | Check for recent retrieval complaints or "promote-to-knowledge" tags |
| `knowledge.list_namespaces` | Get baseline stats per namespace |
| `knowledge.query` | Run probe queries in `raw`, `graph`, `summarized` modes |
| `memory.save_memory` | Record the audit findings and health scores |

## Instructions

### 1. Check Operational Memory (Working Context)

Before probing, check if other agents have reported issues with the Knowledge layer:
```bash
npx mcporter call memory.search_memory query:'missing knowledge OR poor retrieval OR llm_unavailable'
```
Record any specific namespaces or domains that have been flagged by the team.

### 2. Establish Baseline Knowledge Stats

```bash
npx mcporter call knowledge.list_namespaces
```
Record per-namespace: `files_indexed`, `chunks`, `entities`, `relations`. Flag:
- Files > 0 but chunks = 0 → ingestion failure
- Chunks > 0 but entities = 0 → LLM extraction unavailable

### 3. Design Probe Queries

For each namespace, construct 3–5 probes based on the content (and any Memory complaints):
1. **Broad topic** — "What is this project about?"
2. **Specific fact** — "What is the API rate limit?"
3. **Entity name** — "Tell me about AuthService"
4. **Edge-case** — a query about something that shouldn't exist
5. **Cross-document** — "How do X and Y relate?"

### 4. Run Probes in All Modes

Test the resilience of the Knowledge namespace across all retrieval strategies:
```bash
npx mcporter call knowledge.query namespace:'<ns>' query:'<probe>' mode:'raw' top_k:5
npx mcporter call knowledge.query namespace:'<ns>' query:'<probe>' mode:'graph' top_k:5
npx mcporter call knowledge.query namespace:'<ns>' query:'<probe>' mode:'summarized' top_k:5
```
Record: `chunks` count, `entities`, `answer`, `latency_ms`, `warnings`.

### 5. Score Namespace Health

| Score | Criteria |
|-------|----------|
| **Healthy** | All probes return relevant results, latency within bounds, no warnings |
| **Degraded** | Sparse/irrelevant results, high latency, or `llm_unavailable` warning |
| **Critical** | Empty results from most probes, possible index corruption |

### 6. Save Findings to Memory (Brain-Ops Compliance)

As an evaluator, you **MUST** save your audit results to Memory so the rest of the team knows the health of the Knowledge layer.

```bash
npx mcporter call memory.save_memory \
  content:'Ontology Audit for <namespace>. Score: <score>. Findings: <details>. Recommendations: <action items>.' \
  name:'Knowledge Audit: <namespace>' \
  path:'audits/knowledge' \
  tags:'audit,knowledge,ontology,<score>'
```

### 7. Produce Quality Audit Report

Save a detailed `quality-audit.md` artifact with per-namespace probe results, health scores, and recommendations. Flag degraded/critical namespaces for `propose-rebuild`.

## Anti-Patterns

- **Do not** skip checking Memory first — you need to know what the team is struggling to find.
- **Do not** skip saving to Memory at the end — `brain-ops` requires all evaluators to leave a trace.
- **Do not** skip baseline stats — you need context before probing.
- **Do not** use only one query mode — compare all three (`raw`, `graph`, `summarized`).
- **Do not** ignore `warnings` in query responses.
- **Do not** audit mid-import — wait for the import job to complete first.

## Verification

1. `search_memory` called before probing to discover pain points.
2. All namespaces probed with multiple queries across all three modes via `npx mcporter`.
3. Each namespace has a health score assigned.
4. `save_memory` called with the final audit verdict.
5. `quality-audit.md` artifact produced.
