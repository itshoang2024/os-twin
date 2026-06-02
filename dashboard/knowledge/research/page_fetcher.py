"""URL content fetcher with safety guards.

Fetches web pages via ``httpx``, respects timeout, max content size,
URL blocklist, and MIME type filtering. Returns raw bytes + metadata
for downstream MarkItDown conversion.

For video page URLs (YouTube, Vimeo, etc.), only the HTML page metadata
(title, description) is fetched — NOT the video file itself.
"""

from __future__ import annotations

import fnmatch
import ipaddress
import logging
import socket
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional
from urllib.parse import urlparse

from dashboard.knowledge.research.config import (
    RESEARCH_FETCH_TIMEOUT,
    RESEARCH_MAX_FETCH_SIZE,
    RESEARCH_SKIP_MIME_TYPES,
    RESEARCH_URL_BLOCKLIST,
    RESEARCH_USER_AGENT,
)
from dashboard.knowledge.research.models import FetchResult

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = frozenset({"http", "https"})

# Maximum number of redirects to follow (validated at each hop).
_MAX_REDIRECTS = 5
_DNS_PIN_LOCK = threading.Lock()


@dataclass(frozen=True)
class _ResolvedTarget:
    hostname: str
    port: int
    addrinfos: tuple


def _is_private_ip(ip_str: str) -> bool:
    """Return True if the IP address is private, loopback, link-local, or reserved."""
    try:
        addr = ipaddress.ip_address(ip_str)
        return (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        )
    except ValueError:
        return True  # Unparseable → reject


def _normalize_hostname(hostname: object) -> str:
    if isinstance(hostname, bytes):
        hostname = hostname.decode("ascii", errors="ignore")
    return str(hostname).lower().rstrip(".")


def _resolve_url_target(url: str) -> tuple[Optional[_ResolvedTarget], Optional[str]]:
    """Validate URL scheme and resolved IP addresses.

    Returns a resolved target plus an error string. The resolved target is used
    to pin the later HTTP connection to the addresses that passed validation.
    """
    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        return None, f"Blocked scheme: {parsed.scheme!r}"

    hostname = parsed.hostname
    if not hostname:
        return None, "No hostname in URL"

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addrinfos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        return None, f"DNS resolution failed for {hostname}: {exc}"

    if not addrinfos:
        return None, f"DNS resolution returned no addresses for {hostname}"

    for _family, _type, _proto, _canonname, sockaddr in addrinfos:
        ip = sockaddr[0]
        if _is_private_ip(ip):
            return None, f"URL resolves to non-public address ({hostname} → {ip})"

    return _ResolvedTarget(
        hostname=_normalize_hostname(hostname),
        port=port,
        addrinfos=tuple(addrinfos),
    ), None


def _validate_url_target(url: str) -> Optional[str]:
    """Validate URL scheme and resolved IP addresses.

    Returns an error string if the URL is unsafe, or None if safe.
    """
    _target, error = _resolve_url_target(url)
    return error


@contextmanager
def _pin_dns_resolution(target: _ResolvedTarget) -> Iterator[None]:
    """Pin httpx's DNS lookup to the addresses already SSRF-validated.

    httpx does not expose a sync resolver hook, so the fetcher temporarily
    overrides ``socket.getaddrinfo`` while opening the connection. A lock keeps
    concurrent research fetches from observing the wrong pinned target.
    """
    original_getaddrinfo = socket.getaddrinfo
    hostnames = {_normalize_hostname(target.hostname)}
    try:
        hostnames.add(_normalize_hostname(target.hostname.encode("idna").decode("ascii")))
    except UnicodeError:
        pass

    def pinned_getaddrinfo(host, port, *args, **kwargs):
        try:
            requested_port = int(port)
        except (TypeError, ValueError):
            requested_port = target.port

        if _normalize_hostname(host) in hostnames and requested_port == target.port:
            return list(target.addrinfos)
        return original_getaddrinfo(host, port, *args, **kwargs)

    with _DNS_PIN_LOCK:
        socket.getaddrinfo = pinned_getaddrinfo
        try:
            yield
        finally:
            socket.getaddrinfo = original_getaddrinfo


class PageFetcher:
    """Fetches URL content with safety guards.

    Parameters
    ----------
    timeout:
        Per-page fetch timeout in seconds.
    max_size:
        Maximum response body size in bytes.
    user_agent:
        User-Agent header for requests.
    url_blocklist:
        URL patterns to skip (fnmatch glob patterns).
    skip_mime_types:
        MIME types to skip (binary content MarkItDown can't handle).
    """

    def __init__(
        self,
        timeout: float = 0.0,
        max_size: int = 0,
        user_agent: str = "",
        url_blocklist: Optional[list[str]] = None,
        skip_mime_types: Optional[set[str]] = None,
    ) -> None:
        self._timeout = timeout or RESEARCH_FETCH_TIMEOUT
        self._max_size = max_size or RESEARCH_MAX_FETCH_SIZE
        self._user_agent = user_agent or RESEARCH_USER_AGENT
        self._url_blocklist = url_blocklist if url_blocklist is not None else RESEARCH_URL_BLOCKLIST
        self._skip_mime_types = skip_mime_types if skip_mime_types is not None else RESEARCH_SKIP_MIME_TYPES

    def fetch(self, url: str) -> FetchResult:
        """Fetch a URL and return the content as a FetchResult.

        The method:
        1. Checks the URL against the blocklist
        2. Validates scheme and resolved IP (SSRF protection)
        3. Sends a GET request, following redirects with per-hop validation
        4. Skips binary MIME types
        5. Reads up to max_size bytes
        6. Returns content bytes for MarkItDown conversion

        Returns a FetchResult with error set on failure (never raises).
        """
        # Check blocklist
        if self._is_blocked(url):
            return FetchResult(url=url, error="URL matched blocklist", status_code=0)

        # SSRF guard: validate scheme and resolved destination IP
        current_target, ssrf_err = _resolve_url_target(url)
        if ssrf_err:
            return FetchResult(url=url, error=ssrf_err, status_code=0)

        import httpx  # noqa: WPS433 — lazy import

        try:
            with httpx.Client(
                timeout=self._timeout,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                follow_redirects=False,
                trust_env=False,
            ) as client:
                # Manually follow redirects to validate each hop
                current_url = url
                redirects_followed = 0

                while True:
                    if current_target is None:
                        return FetchResult(url=url, error="No resolved target", status_code=0)
                    with _pin_dns_resolution(current_target), client.stream("GET", current_url) as response:
                        status_code = response.status_code

                        # Handle redirects with SSRF validation on each hop
                        if status_code in (301, 302, 303, 307, 308):
                            redirects_followed += 1
                            if redirects_followed > _MAX_REDIRECTS:
                                return FetchResult(
                                    url=url,
                                    final_url=current_url,
                                    status_code=status_code,
                                    error=f"Too many redirects (>{_MAX_REDIRECTS})",
                                )
                            location = response.headers.get("location")
                            if not location:
                                return FetchResult(
                                    url=url,
                                    final_url=current_url,
                                    status_code=status_code,
                                    error="Redirect with no Location header",
                                )
                            # Resolve relative redirects
                            next_url = str(response.url.join(location))
                            # Validate the redirect target
                            next_target, hop_err = _resolve_url_target(next_url)
                            if hop_err:
                                return FetchResult(
                                    url=url,
                                    final_url=next_url,
                                    status_code=status_code,
                                    error=f"Redirect blocked: {hop_err}",
                                )
                            current_url = next_url
                            current_target = next_target
                            continue  # Follow the redirect

                        final_url = str(response.url)

                        if status_code >= 400:
                            return FetchResult(
                                url=url,
                                final_url=final_url,
                                status_code=status_code,
                                error=f"HTTP {status_code}",
                            )

                        # Check Content-Type
                        content_type = response.headers.get("content-type", "")
                        mime_type = content_type.split(";")[0].strip().lower()

                        if mime_type in self._skip_mime_types:
                            return FetchResult(
                                url=url,
                                final_url=final_url,
                                status_code=status_code,
                                content_type=mime_type,
                                error=f"Skipped MIME type: {mime_type}",
                            )

                        # Check Content-Length header if available
                        content_length = response.headers.get("content-length")
                        try:
                            content_length_value = int(content_length) if content_length else 0
                        except ValueError:
                            content_length_value = 0
                        if content_length_value > self._max_size:
                            return FetchResult(
                                url=url,
                                final_url=final_url,
                                status_code=status_code,
                                content_type=mime_type,
                                content_length=content_length_value,
                                error=f"Content too large: {content_length_value} bytes (max {self._max_size})",
                            )

                        # Read body with size limit
                        chunks: list[bytes] = []
                        total_read = 0
                        too_large = False
                        for chunk in response.iter_bytes(chunk_size=65536):
                            total_read += len(chunk)
                            if total_read > self._max_size:
                                too_large = True
                                break
                            chunks.append(chunk)

                        if too_large:
                            return FetchResult(
                                url=url,
                                final_url=final_url,
                                status_code=status_code,
                                content_type=mime_type,
                                content_length=total_read,
                                error=f"Content too large: streamed more than {self._max_size} bytes",
                            )

                        body = b"".join(chunks)

                    # Exited the redirect loop — we have a response body
                    break

            # Convert to markdown via MarkItDown
            markdown = self._convert_to_markdown(body, mime_type, final_url)

            return FetchResult(
                url=url,
                final_url=final_url,
                status_code=status_code,
                content_type=mime_type,
                content_length=len(body),
                markdown=markdown,
            )

        except Exception as exc:
            logger.debug("Fetch failed for %s: %s", url, exc)
            return FetchResult(url=url, error=str(exc), status_code=0)

    def _convert_to_markdown(self, content: bytes, mime_type: str, url: str) -> str:
        """Convert fetched content to markdown using MarkItDown.

        Falls back to raw text decode if MarkItDown fails.
        """
        try:
            from markitdown import MarkItDown  # noqa: WPS433 — lazy import
            import tempfile
            import os

            # MarkItDown works with files — write to a temp file
            suffix = self._guess_suffix(mime_type, url)
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            try:
                md = MarkItDown()
                result = md.convert(tmp_path)
                text = result.text_content if result and result.text_content else ""
            finally:
                os.unlink(tmp_path)

            if text:
                return text

        except Exception as exc:
            logger.debug("MarkItDown conversion failed for %s: %s", url, exc)

        # Fallback: decode as text
        try:
            return content.decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _guess_suffix(self, mime_type: str, url: str) -> str:
        """Guess file extension from MIME type or URL for MarkItDown."""
        mime_to_ext = {
            "text/html": ".html",
            "application/xhtml+xml": ".html",
            "application/pdf": ".pdf",
            "text/plain": ".txt",
            "text/markdown": ".md",
            "application/json": ".json",
            "text/csv": ".csv",
            "application/xml": ".xml",
            "text/xml": ".xml",
        }
        ext = mime_to_ext.get(mime_type, "")
        if ext:
            return ext

        # Try URL path
        path = urlparse(url).path
        if "." in path.split("/")[-1]:
            return "." + path.split(".")[-1][:10]

        return ".html"  # default assumption for web pages

    def _is_blocked(self, url: str) -> bool:
        """Check if URL matches any blocklist pattern."""
        for pattern in self._url_blocklist:
            if fnmatch.fnmatch(url, pattern):
                return True
            # Also check if pattern appears as substring (common use case)
            if pattern in url:
                return True
        return False
