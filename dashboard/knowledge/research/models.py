"""Pydantic models for the web research add-on."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    """A single result from a SearXNG search."""

    title: str
    url: str
    snippet: str = ""
    engine: str = ""
    score: float = 0.0
    thumbnail_url: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class FetchResult(BaseModel):
    """Result of fetching a single URL."""

    url: str
    final_url: str = ""
    content_type: str = ""
    content_length: int = 0
    status_code: int = 0
    error: str = ""
    markdown: str = ""

    @property
    def ok(self) -> bool:
        return self.status_code >= 200 and self.status_code < 400 and not self.error


class ResearchSourceResult(BaseModel):
    """Per-URL outcome within a research run."""

    url: str
    title: str = ""
    engine: str = ""
    status: str = "pending"  # pending | fetched | ingested | skipped | error
    chunks_added: int = 0
    error: str = ""


class ResearchResult(BaseModel):
    """Aggregate result of a complete research run."""

    query: str
    namespace: str
    engines_used: list[str] = Field(default_factory=list)
    categories_used: list[str] = Field(default_factory=list)
    sources: list[ResearchSourceResult] = Field(default_factory=list)
    total_chunks_added: int = 0
    total_entities_added: int = 0
    total_relations_added: int = 0
    summary: Optional[str] = None
    elapsed_seconds: float = 0.0
    warnings: list[str] = Field(default_factory=list)

    @property
    def urls_fetched(self) -> int:
        return sum(1 for s in self.sources if s.status in ("fetched", "ingested"))

    @property
    def urls_failed(self) -> int:
        return sum(1 for s in self.sources if s.status == "error")
