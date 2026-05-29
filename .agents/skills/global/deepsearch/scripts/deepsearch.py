#!/usr/bin/env python3
"""Deep search via the SearXNG Search API plus local artifact search."""

from __future__ import annotations

import argparse
import datetime as dt
import html.parser
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_SEARXNG_BASE_URL = "http://localhost:6633"

TYPE_EXTENSIONS = {
    "archive": {".7z", ".bz2", ".gz", ".rar", ".tar", ".tgz", ".zip"},
    "csv": {".csv"},
    "data": {".csv", ".json", ".jsonl", ".tsv", ".xml", ".yaml", ".yml"},
    "doc": {".doc", ".docx"},
    "excel": {".xls", ".xlsx"},
    "html": {"", ".htm", ".html"},
    "image": {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tiff", ".webp"},
    "json": {".json", ".jsonl"},
    "pdf": {".pdf"},
    "ppt": {".ppt", ".pptx"},
    "spreadsheet": {".csv", ".ods", ".tsv", ".xls", ".xlsx"},
    "text": {".csv", ".htm", ".html", ".json", ".jsonl", ".log", ".md", ".rst", ".tsv", ".txt", ".xml", ".yaml", ".yml"},
}
TEXT_EXTENSIONS = TYPE_EXTENSIONS["text"] | {".css", ".js", ".jsx", ".py", ".scss", ".sql", ".ts", ".tsx"}
HTML_EXTENSIONS = {".htm", ".html"}
SKIP_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}
SEARCH_OPTION_PARAMS = {
    "autocomplete": "autocomplete",
    "categories": "categories",
    "disabled_engines": "disabled_engines",
    "disabled_plugins": "disabled_plugins",
    "enabled_engines": "enabled_engines",
    "enabled_plugins": "enabled_plugins",
    "engines": "engines",
    "image_proxy": "image_proxy",
    "language": "language",
    "results_on_new_tab": "results_on_new_tab",
    "safe_search": "safesearch",
    "theme": "theme",
    "time_range": "time_range",
}
ACCEPT_BY_FORMAT = {
    "json": "application/json",
    "csv": "text/csv,*/*;q=0.8",
    "rss": "application/rss+xml,application/xml,text/xml,*/*;q=0.8",
}


class TextExtractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001 - html.parser API
        if tag in {"script", "style", "noscript"}:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.skip_depth:
            self.skip_depth -= 1
        if tag in {"article", "br", "h1", "h2", "h3", "li", "p", "section", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = " ".join(data.split())
        if text:
            self.parts.append(text)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", " ".join(self.parts)).strip() + "\n"


def parse_items(value: str) -> set[str]:
    items = {item.strip().lower() for item in value.split(",") if item.strip()}
    return items or {"all"}


def slug(value: str, max_len: int = 90) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return (value or "item")[:max_len]


def content_type_extension(content_type: str) -> str:
    return mimetypes.guess_extension(content_type.split(";")[0].strip().lower()) or ""


def build_search_url(base_url: str, endpoint: str) -> str:
    if endpoint == "/":
        return base_url.rstrip("/") + "/"
    return urllib.parse.urljoin(base_url.rstrip("/") + "/", endpoint.lstrip("/"))


def request_bytes(
    url: str,
    timeout: float,
    *,
    method: str = "GET",
    form: dict[str, str] | None = None,
    accept: str = "text/html,application/xhtml+xml,application/json,application/pdf,*/*",
) -> tuple[bytes, dict[str, str], str]:
    method = method.upper()
    headers = {
        "Accept": accept,
        "User-Agent": "ostwin-deepsearch/1.1",
    }
    data = None

    if form:
        encoded = urllib.parse.urlencode(form)
        if method == "POST":
            data = encoded.encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            separator = "&" if urllib.parse.urlparse(url).query else "?"
            url = f"{url}{separator}{encoded}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read()
        response_headers = {key.lower(): value for key, value in response.headers.items()}
        return body, response_headers, response.geturl()


def build_search_params(args: argparse.Namespace) -> dict[str, str]:
    params = {
        "q": args.query,
        "format": args.search_format,
        "pageno": str(args.page),
    }
    for attr, param in SEARCH_OPTION_PARAMS.items():
        value = getattr(args, attr)
        if value not in (None, ""):
            params[param] = str(value)
    return params


def request_search_response(args: argparse.Namespace, params: dict[str, str]) -> tuple[bytes, dict[str, str], str]:
    url = build_search_url(args.base_url, args.endpoint)
    try:
        return request_bytes(
            url,
            args.timeout,
            method=args.method,
            form=params,
            accept=ACCEPT_BY_FORMAT.get(args.search_format, "*/*"),
        )
    except urllib.error.HTTPError as exc:
        hint = " Enable the requested format in search.formats." if exc.code == 403 else ""
        raise SystemExit(f"Search failed: HTTP {exc.code}.{hint}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Search failed: {exc.reason}") from exc


def request_search_json(args: argparse.Namespace, params: dict[str, str]) -> tuple[dict, str]:
    body, _, final_url = request_search_response(args, params)
    try:
        return json.loads(body.decode("utf-8", errors="replace")), final_url
    except json.JSONDecodeError as exc:
        raise SystemExit("Search failed: response was not valid JSON. Check that format=json is enabled in SearXNG.") from exc


def compact_result(result: dict) -> dict:
    keys = (
        "title",
        "url",
        "content",
        "engine",
        "category",
        "score",
        "publishedDate",
        "img_src",
        "thumbnail",
        "metadata",
    )
    return {key: result.get(key) for key in keys if result.get(key) not in (None, "", [])}


def search_web(args: argparse.Namespace) -> tuple[dict, dict]:
    params = build_search_params(args)
    raw, final_url = request_search_json(args, params)
    raw["results"] = raw.get("results", [])[: args.limit]
    payload = {
        "mode": "web",
        "query": args.query,
        "base_url": args.base_url.rstrip("/"),
        "search_api": {
            "endpoint": args.endpoint,
            "method": args.method,
            "format": args.search_format,
            "final_url": final_url,
            "params": params,
        },
        "number_of_results": raw.get("number_of_results"),
        "answers": raw.get("answers", []),
        "suggestions": raw.get("suggestions", []),
        "results": [compact_result(item) for item in raw.get("results", [])],
    }
    return raw, payload


def extension_from_url(url: str) -> str:
    return Path(urllib.parse.urlparse(url).path).suffix.lower()


def type_matches(path_or_url: str, content_type: str, wanted: set[str]) -> bool:
    if "all" in wanted:
        return True

    ext = Path(urllib.parse.urlparse(path_or_url).path).suffix.lower()
    header_ext = content_type_extension(content_type)
    content_type = content_type.lower()

    for item in wanted:
        extension_item = item if item.startswith(".") else f".{item}"
        if ext == extension_item or header_ext == extension_item:
            return True
        if ext in TYPE_EXTENSIONS.get(item, set()) or header_ext in TYPE_EXTENSIONS.get(item, set()):
            return True
        if item and item in content_type:
            return True
    return False


def write_html_text_sidecar(path: Path, body: bytes) -> str:
    extractor = TextExtractor()
    extractor.feed(body.decode("utf-8", errors="replace"))
    text_path = path.with_suffix(".txt")
    text_path.write_text(extractor.text(), encoding="utf-8")
    return str(text_path)


def fetch_result(index: int, result: dict, out_dir: Path, wanted: set[str], timeout: float) -> dict:
    url = result.get("url")
    record = {"index": index, "title": result.get("title"), "url": url, "engine": result.get("engine")}
    if not url:
        record["error"] = "missing url"
        return record

    try:
        body, headers, final_url = request_bytes(url, timeout)
    except urllib.error.HTTPError as exc:
        record["error"] = f"HTTP {exc.code}"
        return record
    except urllib.error.URLError as exc:
        record["error"] = str(exc.reason)
        return record
    except TimeoutError:
        record["error"] = "timeout"
        return record

    content_type = headers.get("content-type", "")
    record.update({"final_url": final_url, "content_type": content_type})
    if not type_matches(final_url, content_type, wanted):
        record["skipped"] = "content type not requested"
        return record

    ext = extension_from_url(final_url) or content_type_extension(content_type) or ".bin"
    if ext == ".jpe":
        ext = ".jpg"
    base = slug(result.get("title") or Path(urllib.parse.urlparse(final_url).path).name or f"result-{index}")
    path = out_dir / f"{index:02d}-{base}{ext}"
    path.write_bytes(body)
    record["path"] = str(path)

    if "text/html" in content_type.lower() or ext in HTML_EXTENSIONS:
        record["text_path"] = write_html_text_sidecar(path, body)
    return record


def is_text_like(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS


def iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        yield path


def grep_files(root: Path, pattern: str, limit: int = 500) -> list[dict[str, object]]:
    regex = re.compile(pattern, re.IGNORECASE)
    matches: list[dict[str, object]] = []
    for path in iter_files(root):
        if not is_text_like(path):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            if regex.search(line):
                matches.append({"path": str(path), "line": number, "text": line[:500]})
                if len(matches) >= limit:
                    return matches
    return matches


def local_files(root: Path, query: str, wanted: set[str], limit: int) -> list[dict[str, object]]:
    terms = [term.lower() for term in re.findall(r"[A-Za-z0-9._-]+", query)]
    files: list[dict[str, object]] = []
    for path in iter_files(root):
        if not type_matches(str(path), "", wanted):
            continue
        rel = str(path.relative_to(root))
        haystack = rel.lower()
        if terms and not all(term in haystack for term in terms):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = None
        files.append({"path": str(path), "relative_path": rel, "size": size})
        if len(files) >= limit:
            break
    return files


def render_markdown(payload: dict) -> str:
    lines = [f"# Deepsearch {payload['mode']} results", ""]
    if payload.get("query"):
        lines.extend([f"Query: {payload['query']}", ""])

    answers = payload.get("answers") or []
    if answers:
        lines.append("## Answers")
        lines.extend(f"- {answer}" for answer in answers[:3])
        lines.append("")

    if payload["mode"] == "local":
        lines.append("## Files")
        for index, item in enumerate(payload.get("files", []), 1):
            lines.append(f"{index}. `{item['path']}`")
        lines.append("")
    else:
        lines.append("## Results")
        for index, result in enumerate(payload.get("results", []), 1):
            title = result.get("title") or result.get("url") or "Untitled"
            url = result.get("url") or ""
            content = (result.get("content") or "").strip()
            source = result.get("engine") or result.get("category") or "unknown"
            lines.append(f"{index}. [{title}]({url})")
            if content:
                lines.append(f"   {content}")
            lines.append(f"   Source: {source}")
        lines.append("")

    if payload.get("out_dir"):
        lines.extend(["## Artifacts", f"- Output directory: `{payload['out_dir']}`", f"- Manifest: `{payload.get('manifest')}`"])
        if "saved_count" in payload:
            lines.append(f"- Saved files: {payload['saved_count']}")
        lines.append("")

    if payload.get("grep_results"):
        lines.extend(["## Grep", f"- Matches: {payload.get('grep_matches', 0)}", f"- Results: `{payload['grep_results']}`", ""])
    elif payload.get("grep_matches") is not None:
        lines.extend(["## Grep", f"- Matches: {payload.get('grep_matches', 0)}", ""])

    return "\n".join(lines).rstrip() + "\n"


def emit(payload: dict, output: str) -> None:
    if output == "json":
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return
    if output == "urls":
        items = payload.get("files") if payload.get("mode") == "local" else payload.get("results")
        key = "path" if payload.get("mode") == "local" else "url"
        for item in items or []:
            if item.get(key):
                print(item[key])
        return
    sys.stdout.write(render_markdown(payload))


def emit_raw_search_response(args: argparse.Namespace) -> int:
    if args.fetch or args.out or args.grep:
        raise SystemExit("--output raw cannot be combined with --fetch, --out, or --grep.")
    body, _, _ = request_search_response(args, build_search_params(args))
    sys.stdout.buffer.write(body)
    if not body.endswith(b"\n"):
        sys.stdout.buffer.write(b"\n")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", default="", help="SearXNG query, or local filename query with --local")
    parser.add_argument("--base-url", default=os.getenv("SEARXNG_BASE_URL", DEFAULT_SEARXNG_BASE_URL))
    parser.add_argument("--endpoint", choices=["/search", "/"], default="/search", help="SearXNG Search API endpoint")
    parser.add_argument("--method", choices=["GET", "POST"], default="GET", help="SearXNG Search API HTTP method")
    parser.add_argument("--search-format", "--format", dest="search_format", choices=["json", "csv", "rss"], default="json", help="SearXNG format parameter")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--page", "--pageno", dest="page", type=int, default=1)
    parser.add_argument("--language", default="")
    parser.add_argument("--categories", default="")
    parser.add_argument("--engines", default="")
    parser.add_argument("--enabled-engines", default="")
    parser.add_argument("--disabled-engines", default="")
    parser.add_argument("--enabled-plugins", default="")
    parser.add_argument("--disabled-plugins", default="")
    parser.add_argument("--time-range", choices=["day", "month", "year"], default="")
    parser.add_argument("--safe-search", "--safesearch", dest="safe_search", choices=["0", "1", "2"], default="")
    parser.add_argument("--results-on-new-tab", choices=["0", "1"], default="")
    parser.add_argument("--image-proxy", choices=["0", "1", "true", "false", "True", "False"], default="")
    parser.add_argument("--autocomplete", default="")
    parser.add_argument("--theme", default="")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", choices=["json", "markdown", "urls", "raw"], default="markdown")
    parser.add_argument("--fetch", action="store_true", help="Download web search results and write a manifest")
    parser.add_argument("--out", default="", help="Output directory. Implies --fetch for web searches")
    parser.add_argument("--types", default="all", help="Comma-separated types, extensions, or MIME fragments")
    parser.add_argument("--grep", default="", help="Regex to scan fetched or local text-like files")
    parser.add_argument("--local", default="", help="Search an existing local artifact/data directory")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between fetch requests")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    wanted = parse_items(args.types)

    if args.local:
        if args.output == "raw":
            raise SystemExit("--output raw is only for direct SearXNG Search API responses, not local search.")
        root = Path(args.local).expanduser().resolve()
        if not root.is_dir():
            raise SystemExit(f"Local search failed: not a directory: {root}")
        payload = {
            "mode": "local",
            "query": args.query,
            "root": str(root),
            "files": local_files(root, args.query, wanted, args.limit),
        }
        if args.grep:
            matches = grep_files(root, args.grep)
            payload.update({"grep_matches": len(matches), "matches": matches})
        emit(payload, args.output)
        return 0

    if not args.query:
        raise SystemExit("A query is required unless --local is set.")

    if args.output == "raw":
        return emit_raw_search_response(args)
    if args.search_format != "json":
        raise SystemExit("Deepsearch formatting, URL output, fetch, and grep require --search-format json. Use --output raw for csv/rss.")

    raw, payload = search_web(args)
    should_fetch = args.fetch or bool(args.out or args.grep)
    if should_fetch:
        timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = Path(args.out or f"deepsearch-{slug(args.query, 40)}-{timestamp}").expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "search-results.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

        manifest = []
        for index, result in enumerate(raw.get("results", []), 1):
            manifest.append(fetch_result(index, result, out_dir, wanted, args.timeout))
            time.sleep(args.delay)
        manifest_path = out_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        payload.update(
            {
                "out_dir": str(out_dir),
                "saved_count": sum(1 for item in manifest if item.get("path")),
                "manifest": str(manifest_path),
            }
        )
        if args.grep:
            matches = grep_files(out_dir, args.grep)
            grep_path = out_dir / "grep-results.json"
            grep_path.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
            payload.update({"grep_matches": len(matches), "grep_results": str(grep_path), "matches": matches})

    emit(payload, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
