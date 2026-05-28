# Research: Named Entity Recognition for ostwin

**Date:** 2026-05-25
**Question:** Can named entity recognition (NER) be applied usefully in ostwin?
**Used for:** Architecture and roadmap decision for memory, knowledge graph, plan analysis, and dashboard search.

## Executive Summary

Yes. NER can be applied to ostwin, but the highest-value version is not generic "person/place/org" extraction. The useful version is domain-specific entity extraction for epics, tasks, roles, skills, file paths, APIs, MCP servers, models, environment variables, commands, errors, and project concepts.

The repo already has a graph extraction path using an LLM: `KnowledgeLLM.extract_entities()` feeds `GraphRAGExtractor`, which writes entities and relationships into the knowledge graph. NER should therefore be introduced as a cheaper, more deterministic layer around this existing system: rules first for structured engineering entities, optional local model extraction for fuzzy/domain concepts, and LLM relation extraction only where relationships are actually needed.

## Findings

### What NER Does

NER finds spans of text and assigns labels to them. Traditional NER is usually token classification: each token receives an entity label such as person, organization, location, product, etc. Hugging Face documents NER as a token-classification task and supports fine-tuned transformer models through the `pipeline("ner")` interface.

For ostwin, the entity labels should be project-specific:

- `EPIC_REF`: `EPIC-001`
- `TASK_REF`: `TASK-004`
- `ROLE`: `architect`, `engineer`, `qa`
- `SKILL`: `write-tests`, `github:gh-fix-ci`
- `FILE_PATH`: `dashboard/routes/amem.py`
- `API_ROUTE`: `/api/amem/{plan_id}/graph`
- `MCP_SERVER`: `memory`, `channel`, `warroom`
- `MODEL_NAME`: `google-vertex/gemini-3.1-pro-preview`
- `ENV_VAR`: `GOOGLE_VERTEX_LOCATION`
- `COMMAND`: `ostwin init`
- `ERROR_SIGNATURE`: `Request had insufficient authentication scopes`
- `COMPONENT`: `GraphRAGExtractor`, `MemoryTab`, `PlanSidebar`

### Existing Repo Fit

The memory note schema already stores semantic metadata: `keywords`, `links`, `context`, `category`, and `tags` in `dashboard/agentic_memory/memory_note.py`. The dashboard memory API exposes those fields and builds the current note graph from `links` in `dashboard/routes/amem.py`.

The knowledge graph path already extracts entities and relations:

- `dashboard/knowledge/llm.py` defines strict JSON extraction for entities and relationships.
- `dashboard/knowledge/graph/core/graph_rag_extractor.py` wraps that call and converts extracted entities into LlamaIndex `EntityNode`s and relations into `Relation`s.
- `dashboard/knowledge/ingestion.py` routes chunks through `PropertyGraphIndex.insert_nodes()`, which triggers extraction and persistence.

That means ostwin does not need an isolated NER product. It needs an entity extraction layer that can enrich both memory notes and knowledge ingestion consistently.

### Candidate Approaches

| Approach | Fit for ostwin | Pros | Cons |
|---|---:|---|---|
| Regex/rule NER | Very high | Fast, local, deterministic, ideal for EPIC IDs, paths, env vars, routes, commands | Cannot infer fuzzy concepts or aliases |
| spaCy EntityRuler | High | Mature pattern matching, can mix rules with statistical NER | Adds spaCy dependency/model if not already installed |
| Hugging Face token classification | Medium | Already have `transformers` and `torch`; good if fine-tuned labels are available | Generic models will miss ostwin-specific labels |
| GLiNER | High | Promptable/open-label NER, local, good for custom labels without full fine-tuning | Adds new dependency/model, still needs evaluation and threshold tuning |
| Existing LLM extraction | Already present | Extracts entities plus relationships, flexible schema | Slower, costlier, more variable than NER |
| Presidio | Targeted high | Strong choice for PII/security redaction in bot/log/memory flows | PII-focused, not a general project ontology extractor |

### Best Architecture

Add a small shared extraction abstraction:

```python
class EntityMention(TypedDict):
    text: str
    label: str
    start: int
    end: int
    canonical: str | None
    confidence: float
    source: str  # rule, gliner, llm
```

Recommended module: `dashboard/knowledge/entity_extraction.py`.

Recommended execution order:

1. Rule extractor for structured engineering spans.
2. Optional GLiNER/local model extractor for softer concepts.
3. Existing LLM extractor only for relation extraction or low-confidence/high-value chunks.
4. Canonicalization pass to merge aliases: `gemini-3.1-pro-preview` and `google-vertex/gemini-3.1-pro-preview`, `MemoryTab.tsx` and `dashboard/fe/src/components/plan/MemoryTab.tsx`, etc.

### Application Points

1. Memory enrichment

Add an optional `entities` field to `MemoryNote` frontmatter, or map high-confidence mentions into `keywords`/`tags` while preserving a richer internal entity list. This would make the memory tab filter by roles, files, API routes, MCP servers, errors, and epics instead of only free-text tags.

2. Entity-aware memory graph

Current memory graph links note-to-note only when a `links` ID matches another note. Add entity nodes or entity facets so multiple notes mentioning the same file, role, error, or MCP server cluster automatically.

3. Knowledge graph cost control

Use rules/NER before the current LLM extraction. If a chunk contains no useful ostwin entities, skip relation extraction or run a cheaper path. If it contains high-value entities, pass the entity hints into `KnowledgeLLM.extract_entities()` so relationship extraction is more stable.

4. Plan dependency analysis

Extract files, API routes, components, and services from EPIC sections. This can supplement dependency review: two epics touching the same file or route, or one epic producing a component another consumes, are dependency candidates.

5. Bot and safety

The repo has Slack/Discord/Telegram bot code. Presidio-style PII detection could redact emails, API keys, phone numbers, and secrets before saving messages to memory or logs.

## Recommendation

Implement NER in phases.

### Phase 1: Rule-based ostwin entity extraction

No new model dependency. Build regex/pattern extractors for:

- EPIC/TASK refs
- file paths
- API routes
- env vars
- model names
- MCP server names
- role/skill names
- commands
- common error signatures

Wire this into memory note creation and the dashboard memory API. This gives immediate value with low risk.

### Phase 2: Entity facets in MemoryTab

Expose extracted entities from `/api/amem/{plan_id}/notes` and `/api/amem/{plan_id}/graph`. Add filters/grouping for file, role, component, error, API route, and MCP server. This turns memory into a navigable engineering map.

### Phase 3: NER-assisted knowledge graph ingestion

Use the shared extractor inside `GraphRAGExtractor` or before `KnowledgeLLM.extract_entities()`. Pass candidate entities to the LLM prompt, or skip LLM extraction for chunks that only contain low-value text.

### Phase 4: Optional GLiNER backend

Add a feature-flagged local GLiNER backend for custom labels like `component`, `service`, `design decision`, `risk`, and `requirement`. Measure against a small labeled corpus before enabling by default.

## Risks

- Generic NER is the wrong target. The value comes from ostwin-specific labels.
- Entity extraction without canonicalization creates duplicate graph nodes.
- LLM-based extraction is already present, so adding a model blindly could duplicate complexity.
- spaCy/GLiNER add dependency and install weight; rules should come first.
- NER finds spans, not dependency truth. Plan dependency detection still needs heuristics or LLM reasoning.

## Evaluation Plan

Create a labeled fixture set from existing plan files, memory notes, and war-room logs.

Measure:

- Span precision/recall/F1 for each entity type.
- Entity canonicalization accuracy.
- Memory search/filter usefulness.
- Knowledge ingestion latency and LLM call reduction.
- False positive rate on noisy agent logs.

Initial success bar:

- 95%+ precision for structured entities like EPIC refs, paths, env vars, and routes.
- 80%+ recall for file paths and API routes in plan text.
- 25%+ reduction in LLM entity extraction calls for knowledge ingestion, without reducing graph query answer quality.

## Sources

- spaCy EntityRecognizer API: https://spacy.io/api/entityrecognizer
- spaCy EntityRuler API: https://spacy.io/api/entityruler
- Hugging Face Transformers token classification docs: https://huggingface.co/docs/transformers/main/tasks/token_classification
- GLiNER paper: https://arxiv.org/abs/2311.08526
- GLiNER repository: https://github.com/urchade/GLiNER
- LlamaIndex Property Graph Index guide: https://developers.llamaindex.ai/python/framework/module_guides/indexing/lpg_index_guide/
- Microsoft Presidio NLP model customization docs: https://microsoft.github.io/presidio/analyzer/customizing_nlp_models/
- CoNLL-2003 shared task paper: https://arxiv.org/abs/cs/0306050
- CoNLL-2003 temporal generalization paper: https://arxiv.org/abs/2212.09747
