"""WebResearcher — orchestrates search → fetch → ingest → summarize.

The main entry point is :meth:`WebResearcher.run`. It:
1. Queries SearXNG with engine/category targeting
2. Concurrently fetches top-N result pages
3. Batch-ingests the converted markdown into the target namespace
4. Optionally produces an LLM-generated summary of the findings

Construction is cheap — heavy deps are lazy-loaded on first ``run()``.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from dashboard.knowledge.research.config import (
    RESEARCH_MAX_CONCURRENT_FETCHES,
    RESEARCH_MAX_RESULTS,
    RESEARCH_TOTAL_TIMEOUT,
)
from dashboard.knowledge.research.models import (
    FetchResult,
    ResearchResult,
    ResearchSourceResult,
    SearchResult,
)
from dashboard.knowledge.research.page_fetcher import PageFetcher
from dashboard.knowledge.research.searxng_client import SearXNGClient

logger = logging.getLogger(__name__)


def _slugify(text: str, max_len: int = 30) -> str:
    """Convert text to a URL/namespace-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower().strip())
    slug = slug.strip("-")[:max_len].rstrip("-")
    return slug or "research"


def _sha256_str(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class WebResearcher:
    """Orchestrates web research: search → fetch → ingest → summarize.

    Parameters
    ----------
    searxng_client:
        Pre-configured SearXNG client. When None, a default is constructed.
    page_fetcher:
        Pre-configured page fetcher. When None, a default is constructed.
    ingestor:
        The knowledge Ingestor instance (injected by KnowledgeService).
    embedder:
        The KnowledgeEmbedder instance (injected by KnowledgeService).
    llm:
        The KnowledgeLLM instance (injected by KnowledgeService), used for
        summarization. When None, summaries are skipped.
    namespace_manager:
        The NamespaceManager instance (injected by KnowledgeService).
    vector_store_factory:
        Factory to get/create vector stores (injected by KnowledgeService).
    kuzu_factory:
        Factory to get/create Kuzu graphs (injected by KnowledgeService).
    """

    def __init__(
        self,
        searxng_client: Optional[SearXNGClient] = None,
        page_fetcher: Optional[PageFetcher] = None,
        ingestor: Any = None,
        embedder: Any = None,
        llm: Any = None,
        namespace_manager: Any = None,
        vector_store_factory: Optional[Callable] = None,
        kuzu_factory: Optional[Callable] = None,
    ) -> None:
        self._client = searxng_client or SearXNGClient()
        self._fetcher = page_fetcher or PageFetcher()
        self._ingestor = ingestor
        self._embedder = embedder
        self._llm = llm
        self._nm = namespace_manager
        self._vs_factory = vector_store_factory
        self._kg_factory = kuzu_factory

    def run(
        self,
        query: str,
        namespace: str,
        *,
        engines: Optional[list[str]] = None,
        categories: Optional[list[str]] = None,
        max_results: int = 0,
        summarize: bool = True,
        language: str = "en",
        emit: Optional[Callable] = None,
    ) -> ResearchResult:
        """Execute a full research cycle.

        Parameters
        ----------
        query:
            The research query string.
        namespace:
            Target knowledge namespace. Must already exist or be auto-created
            by the caller (KnowledgeService handles this).
        engines:
            SearXNG engines to target (e.g. ``["youtube", "github"]``).
        categories:
            SearXNG categories (e.g. ``["videos", "it"]``).
        max_results:
            Override max results for this run.
        summarize:
            When True and an LLM is available, generate a summary.
        language:
            Search language code.
        emit:
            Optional progress callback (for job manager integration).

        Returns
        -------
        ResearchResult
            Aggregate result with per-source outcomes and optional summary.
        """
        t0 = time.perf_counter()
        effective_max = max_results or RESEARCH_MAX_RESULTS
        total_timeout = RESEARCH_TOTAL_TIMEOUT

        result = ResearchResult(
            query=query,
            namespace=namespace,
            engines_used=engines or [],
            categories_used=categories or [],
        )

        # --- Step 1: Search SearXNG ---
        try:
            search_results = self._client.search(
                query,
                engines=engines,
                categories=categories,
                language=language,
                max_results=effective_max,
            )
        except Exception as exc:
            logger.error("SearXNG search failed for %r: %s", query, exc)
            result.warnings.append(f"search_failed: {exc}")
            result.elapsed_seconds = time.perf_counter() - t0
            return result

        if not search_results:
            result.warnings.append("no_results: SearXNG returned 0 results")
            result.elapsed_seconds = time.perf_counter() - t0
            return result

        logger.info(
            "SearXNG returned %d results for %r (engines=%s)",
            len(search_results), query, engines,
        )

        # --- Step 2: Fetch pages concurrently ---
        fetch_results = self._fetch_pages(search_results, total_timeout - (time.perf_counter() - t0))

        # --- Step 3: Ingest fetched content ---
        sources, ingest_totals = self._ingest_batch(
            query=query,
            namespace=namespace,
            search_results=search_results,
            fetch_results=fetch_results,
            engines=engines,
        )

        result.sources = sources
        result.total_chunks_added = ingest_totals.get("chunks_added", 0)
        result.total_entities_added = ingest_totals.get("entities_added", 0)
        result.total_relations_added = ingest_totals.get("relations_added", 0)

        # --- Step 4: Optional LLM summary ---
        if summarize and self._llm and hasattr(self._llm, "is_available") and self._llm.is_available():
            try:
                result.summary = self._generate_summary(query, namespace, sources)
            except Exception as exc:
                logger.warning("Summary generation failed: %s", exc)
                result.warnings.append(f"summary_failed: {exc}")

        result.elapsed_seconds = time.perf_counter() - t0
        return result

    def _fetch_pages(
        self,
        search_results: list[SearchResult],
        remaining_timeout: float,
    ) -> dict[str, FetchResult]:
        """Fetch pages concurrently with a total timeout budget."""
        fetch_results: dict[str, FetchResult] = {}
        if not search_results:
            return fetch_results

        max_workers = max(1, min(RESEARCH_MAX_CONCURRENT_FETCHES, len(search_results)))

        pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="research-fetch")
        try:
            future_to_url = {
                pool.submit(self._fetcher.fetch, sr.url): sr.url
                for sr in search_results
            }

            deadline = time.perf_counter() + remaining_timeout
            try:
                for future in as_completed(future_to_url, timeout=max(0.1, remaining_timeout)):
                    url = future_to_url[future]
                    try:
                        fetch_results[url] = future.result()
                    except Exception as exc:
                        fetch_results[url] = FetchResult(url=url, error=str(exc))

                    if time.perf_counter() > deadline:
                        logger.warning("Research fetch timeout reached, stopping remaining fetches")
                        break
            except FuturesTimeoutError:
                logger.warning("Research fetch timeout reached before all pages completed")

            for future, url in future_to_url.items():
                if url in fetch_results:
                    continue
                if future.done():
                    try:
                        fetch_results[url] = future.result()
                    except Exception as exc:
                        fetch_results[url] = FetchResult(url=url, error=str(exc))
                else:
                    future.cancel()
                    fetch_results[url] = FetchResult(url=url, error="fetch timeout")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        return fetch_results

    def _ingest_batch(
        self,
        query: str,
        namespace: str,
        search_results: list[SearchResult],
        fetch_results: dict[str, FetchResult],
        engines: Optional[list[str]] = None,
    ) -> tuple[list[ResearchSourceResult], dict[str, int]]:
        """Ingest fetched pages into the namespace via the Ingestor."""
        sources: list[ResearchSourceResult] = []
        totals = {"chunks_added": 0, "entities_added": 0, "relations_added": 0}

        if self._ingestor is None:
            logger.warning("No ingestor available — skipping ingestion")
            for sr in search_results:
                sources.append(ResearchSourceResult(
                    url=sr.url, title=sr.title, engine=sr.engine, status="skipped",
                    error="no ingestor",
                ))
            return sources, totals

        # Build batch items for ingest_research_batch
        batch_items: list[dict[str, Any]] = []
        source_map: dict[str, ResearchSourceResult] = {}

        for sr in search_results:
            fr = fetch_results.get(sr.url)
            source = ResearchSourceResult(url=sr.url, title=sr.title, engine=sr.engine)

            if fr is None:
                source.status = "error"
                source.error = "fetch not attempted (timeout)"
            elif not fr.ok:
                source.status = "error"
                source.error = fr.error
            elif not fr.markdown.strip():
                source.status = "skipped"
                source.error = "empty content after conversion"
            else:
                source.status = "fetched"
                batch_items.append({
                    "text": fr.markdown,
                    "source_url": sr.url,
                    "source_title": sr.title,
                    "metadata": {
                        "source_url": sr.url,
                        "source_title": sr.title,
                        "source_engine": sr.engine,
                        "source_query": query,
                        "source_snippet": sr.snippet[:500],
                        "research_timestamp": datetime.now(timezone.utc).isoformat(),
                        "engines_used": ",".join(engines or []),
                    },
                })

            sources.append(source)
            source_map[sr.url] = source

        # Call ingest_research_batch
        if batch_items:
            try:
                ingest_result = self._ingestor.ingest_research_batch(
                    namespace=namespace,
                    items=batch_items,
                )
                totals["chunks_added"] = ingest_result.get("chunks_added", 0)
                totals["entities_added"] = ingest_result.get("entities_added", 0)
                totals["relations_added"] = ingest_result.get("relations_added", 0)

                # Update per-source status from ingest results
                per_source = ingest_result.get("per_source", {})
                for url, count in per_source.items():
                    if url in source_map:
                        source_map[url].status = "ingested"
                        source_map[url].chunks_added = count

            except Exception as exc:
                logger.error("Batch ingestion failed: %s", exc)
                for item in batch_items:
                    url = item["source_url"]
                    if url in source_map:
                        source_map[url].status = "error"
                        source_map[url].error = f"ingestion failed: {exc}"

        return sources, totals

    def _generate_summary(
        self,
        query: str,
        namespace: str,
        sources: list[ResearchSourceResult],
    ) -> str:
        """Generate an LLM summary of the research findings."""
        # Build context from successfully ingested sources
        ingested = [s for s in sources if s.status == "ingested"]
        if not ingested:
            return "No content was successfully ingested to summarize."

        source_list = "\n".join(
            f"- [{s.title}]({s.url}) ({s.chunks_added} chunks, engine: {s.engine})"
            for s in ingested
        )

        system_prompt = (
            "You are a research assistant. Summarize the findings from a web research session. "
            "Be concise but comprehensive. Include key findings, sources, and actionable insights."
        )
        user_prompt = (
            f"Research query: {query}\n\n"
            f"Sources successfully ingested ({len(ingested)} total):\n{source_list}\n\n"
            f"Provide a structured summary with:\n"
            f"1. Key findings (bullet points)\n"
            f"2. Source quality assessment\n"
            f"3. Gaps or areas needing further research\n"
            f"4. Recommended next steps"
        )

        return self._llm._complete(system_prompt, user_prompt, max_tokens=1024)
