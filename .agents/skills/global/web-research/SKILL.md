---
name: web-research
description: Research a topic on the web and ingest findings into a knowledge namespace.
applyTo: "**"
---

# Web Research Skill

Use the `knowledge_web_research` MCP tool to search the web via SearXNG, fetch and parse
top results, and ingest them into a knowledge namespace for later retrieval.

## Usage

```
knowledge_web_research(
    query="your search query",
    namespace="target-namespace",
    max_results=10,        # 1-50, default 10
    engines=["google"],    # optional: specific SearXNG engines
    categories=["it"],     # optional: SearXNG categories
    summarize=True,        # generate LLM summary of findings
    language="en"          # search language
)
```

## When to Use

- User asks to "research", "look up", or "find out about" a topic
- Gathering external context before planning or implementation
- Building a knowledge base on a new domain

## Prerequisites

- SearXNG must be running: `docker compose -f docker-compose.searxng.yml up -d`
- The knowledge service must be available on the dashboard server

## Examples

Research pixel art techniques:
```
knowledge_web_research(query="pixel art animation techniques 2024", namespace="gamedev")
```

Research with specific engines:
```
knowledge_web_research(query="rust async patterns", namespace="rust-learning", engines=["google", "github"])
```
