"""Configuration constants for the web research add-on.

All values are env-overridable. No heavy deps imported at module load.
"""

from __future__ import annotations

import os

# --- SearXNG connection ---------------------------------------------------

SEARXNG_URL: str = os.environ.get("OSTWIN_SEARXNG_URL", "http://localhost:8080")

# --- Research tunables ----------------------------------------------------

# Maximum number of search results to fetch per query.
RESEARCH_MAX_RESULTS: int = int(
    os.environ.get("OSTWIN_RESEARCH_MAX_RESULTS", "10")
)

# Per-page fetch timeout in seconds.
RESEARCH_FETCH_TIMEOUT: float = float(
    os.environ.get("OSTWIN_RESEARCH_FETCH_TIMEOUT", "30.0")
)

# Total timeout for the entire research operation (search + all fetches + ingest).
RESEARCH_TOTAL_TIMEOUT: float = float(
    os.environ.get("OSTWIN_RESEARCH_TOTAL_TIMEOUT", "300.0")
)

# Maximum content size per fetched page (bytes). Default 10 MB.
RESEARCH_MAX_FETCH_SIZE: int = int(
    os.environ.get("OSTWIN_RESEARCH_MAX_FETCH_SIZE", str(10 * 1024 * 1024))
)

# User-Agent string for outbound HTTP requests.
RESEARCH_USER_AGENT: str = os.environ.get(
    "OSTWIN_RESEARCH_USER_AGENT",
    "OSTwin-Research/1.0 (+https://github.com/nicepkg/os-twin)",
)

# Rate limit: minimum seconds between SearXNG requests (per process).
RESEARCH_RATE_LIMIT_SECONDS: float = float(
    os.environ.get("OSTWIN_RESEARCH_RATE_LIMIT", "1.0")
)

# TTL for search result cache (seconds). 0 = disabled.
RESEARCH_CACHE_TTL: float = float(
    os.environ.get("OSTWIN_RESEARCH_CACHE_TTL", "300.0")
)

# Maximum concurrent page fetches.
RESEARCH_MAX_CONCURRENT_FETCHES: int = int(
    os.environ.get("OSTWIN_RESEARCH_MAX_CONCURRENT_FETCHES", "5")
)

# URL blocklist — comma-separated patterns. URLs matching any pattern are skipped.
RESEARCH_URL_BLOCKLIST: list[str] = [
    p.strip()
    for p in os.environ.get("OSTWIN_RESEARCH_URL_BLOCKLIST", "").split(",")
    if p.strip()
]

# MIME types to skip when fetching (binary content MarkItDown can't handle).
RESEARCH_SKIP_MIME_TYPES: set[str] = {
    "video/mp4",
    "video/webm",
    "video/mpeg",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "application/octet-stream",
    "application/zip",
    "application/x-tar",
    "application/gzip",
    "application/x-7z-compressed",
    "application/x-rar-compressed",
    "application/vnd.android.package-archive",
    "application/x-executable",
    "application/x-mach-binary",
}
