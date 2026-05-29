"""SearXNG JSON API client.

Thin wrapper around SearXNG's ``/search`` endpoint with engine/category
targeting, rate limiting, and response caching.

No heavy deps — only ``httpx`` (lazy-imported on first call).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from dashboard.knowledge.research.config import (
    RESEARCH_CACHE_TTL,
    RESEARCH_MAX_RESULTS,
    RESEARCH_RATE_LIMIT_SECONDS,
    RESEARCH_USER_AGENT,
    SEARXNG_URL,
)
from dashboard.knowledge.research.models import SearchResult

logger = logging.getLogger(__name__)


class SearXNGError(Exception):
    """Raised when SearXNG returns a non-2xx response."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"SearXNG error {status_code}: {message}")


class SearXNGClient:
    """HTTP client for SearXNG's JSON search API.

    Parameters
    ----------
    base_url:
        SearXNG instance URL (default from ``OSTWIN_SEARXNG_URL``).
    max_results:
        Default maximum results per query.
    rate_limit:
        Minimum seconds between consecutive requests (per-instance).
    cache_ttl:
        Cache lifetime in seconds. 0 disables caching.
    """

    def __init__(
        self,
        base_url: str = "",
        max_results: int = 0,
        rate_limit: float = 0.0,
        cache_ttl: float = 0.0,
    ) -> None:
        self._base_url = (base_url or SEARXNG_URL).rstrip("/")
        self._max_results = max_results or RESEARCH_MAX_RESULTS
        self._rate_limit = rate_limit or RESEARCH_RATE_LIMIT_SECONDS
        self._cache_ttl = cache_ttl if cache_ttl > 0 else RESEARCH_CACHE_TTL
        self._last_request_time: float = 0.0
        self._lock = threading.Lock()
        # Simple TTL cache: key = (query, engines_tuple, categories_tuple) → (timestamp, results)
        self._cache: dict[tuple, tuple[float, list[SearchResult]]] = {}

    def search(
        self,
        query: str,
        *,
        engines: Optional[list[str]] = None,
        categories: Optional[list[str]] = None,
        language: str = "en",
        max_results: Optional[int] = None,
    ) -> list[SearchResult]:
        """Search SearXNG and return parsed results.

        Parameters
        ----------
        query:
            The search query string.
        engines:
            Specific SearXNG engines to target (e.g. ``["youtube", "github"]``).
            When None, SearXNG uses its default engine set.
        categories:
            SearXNG categories (e.g. ``["videos", "it", "general"]``).
            When None, SearXNG uses its default category.
        language:
            Search language code (default ``"en"``).
        max_results:
            Override the instance default for this query.

        Returns
        -------
        list[SearchResult]
            Parsed search results, ordered by SearXNG score.

        Raises
        ------
        SearXNGError
            When SearXNG returns a non-2xx status.
        """
        if not query.strip():
            return []

        effective_max = max_results or self._max_results
        engines_tuple = tuple(sorted(engines)) if engines else ()
        categories_tuple = tuple(sorted(categories)) if categories else ()

        # Check cache
        cache_key = (query, engines_tuple, categories_tuple, language)
        cached = self._get_cached(cache_key)
        if cached is not None:
            logger.debug("SearXNG cache hit for %r", query)
            return cached[:effective_max]

        # Rate limiting
        self._wait_rate_limit()

        # Build request params
        params: dict[str, Any] = {
            "q": query,
            "format": "json",
            "language": language,
        }
        if engines:
            params["engines"] = ",".join(engines)
        if categories:
            params["categories"] = ",".join(categories)

        # Execute request
        import httpx  # noqa: WPS433 — lazy import

        try:
            with httpx.Client(
                timeout=30.0,
                headers={"User-Agent": RESEARCH_USER_AGENT},
                follow_redirects=True,
            ) as client:
                response = client.get(f"{self._base_url}/search", params=params)

            if response.status_code != 200:
                raise SearXNGError(response.status_code, response.text[:500])

            data = response.json()
        except httpx.HTTPError as exc:
            raise SearXNGError(0, f"HTTP error: {exc}") from exc

        # Parse results
        raw_results = data.get("results", [])
        results = self._parse_results(raw_results)

        # Cache the full result set
        self._set_cached(cache_key, results)

        return results[:effective_max]

    def health_check(self) -> bool:
        """Return True if SearXNG is reachable."""
        import httpx  # noqa: WPS433 — lazy import

        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self._base_url}/healthz")
                return resp.status_code == 200
        except Exception:
            return False

    # ---- Internals -------------------------------------------------------

    def _parse_results(self, raw: list[dict]) -> list[SearchResult]:
        """Convert raw SearXNG JSON results to SearchResult models."""
        results: list[SearchResult] = []
        for item in raw:
            url = item.get("url", "")
            if not url:
                continue

            metadata: dict[str, Any] = {}
            # Capture engine-specific fields
            for key in ("duration", "views", "author", "publishedDate", "img_src", "stars"):
                if key in item:
                    metadata[key] = item[key]

            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=url,
                    snippet=item.get("content", ""),
                    engine=item.get("engine", ""),
                    score=float(item.get("score", 0.0)),
                    thumbnail_url=item.get("thumbnail", "") or item.get("img_src", ""),
                    metadata=metadata,
                )
            )
        return results

    def _wait_rate_limit(self) -> None:
        """Block until rate limit window has passed."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._rate_limit:
                time.sleep(self._rate_limit - elapsed)
            self._last_request_time = time.monotonic()

    def _get_cached(self, key: tuple) -> Optional[list[SearchResult]]:
        """Return cached results if still fresh, else None."""
        if self._cache_ttl <= 0:
            return None
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, results = entry
        if time.monotonic() - ts > self._cache_ttl:
            del self._cache[key]
            return None
        return results

    def _set_cached(self, key: tuple, results: list[SearchResult]) -> None:
        """Store results in the TTL cache."""
        if self._cache_ttl <= 0:
            return
        self._cache[key] = (time.monotonic(), results)
