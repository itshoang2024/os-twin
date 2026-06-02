"""Web research add-on for the knowledge subsystem."""

from dashboard.knowledge.research.config import SEARXNG_URL
from dashboard.knowledge.research.models import (
    FetchResult,
    ResearchResult,
    ResearchSourceResult,
    SearchResult,
)
from dashboard.knowledge.research.page_fetcher import PageFetcher
from dashboard.knowledge.research.researcher import WebResearcher
from dashboard.knowledge.research.searxng_client import SearXNGClient, SearXNGError

__all__ = [
    "SEARXNG_URL",
    "FetchResult",
    "PageFetcher",
    "ResearchResult",
    "ResearchSourceResult",
    "SearchResult",
    "SearXNGClient",
    "SearXNGError",
    "WebResearcher",
]
