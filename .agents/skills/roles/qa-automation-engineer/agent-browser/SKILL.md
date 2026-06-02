---
name: agent-browser
description: Use when the QA automation engineer needs browser automation, screenshots, downloads, exploratory testing, or evidence capture through agent-browser.
tags: [qa-automation-engineer, browser, automation, web, cli, screenshot, download]
triggers:
  - "use agent-browser"
  - "browser automation"
  - "qa automation"
  - "capture screenshot evidence"
  - "download evidence"
  - "test web app"
tools:
  - Bash
mutating: true
---

# agent-browser

## Contract

- Prefer `agent-browser` when available for browser automation and evidence artifacts.
- Use refs from `agent-browser snapshot -i`; do not use coordinate clicks.
- Save screenshots and downloads under `artifacts/browser-downloads/`.
- Record exact relative artifact paths in the QA report.
- Keep Chrome DevTools MCP and Playwright MCP as fallbacks or companion inspection tools.
- If blocked by auth, bot checks, missing runtime, or network failure, report `BLOCKED` with evidence instead of bypassing controls.

## Installation

Use the repository package manager:

```bash
pnpm add -g agent-browser@0.27.0
agent-browser install
agent-browser --version
```

## Start Here

Load version-matched CLI guidance before running a full browser scenario:

```bash
agent-browser skills get core
agent-browser skills get core --full
agent-browser skills get dogfood
```

## Core Commands

| Command | Purpose |
| --- | --- |
| `agent-browser open <url>` | Navigate to runtime target |
| `agent-browser wait --load networkidle` | Wait for stable page state |
| `agent-browser snapshot -i` | Get accessible tree with refs |
| `agent-browser click @eN` | Click a page element |
| `agent-browser fill @eN "text"` | Fill form input |
| `agent-browser screenshot <path>` | Save screenshot evidence |
| `agent-browser close` | Close session |

## Automation Flow

```bash
DOWNLOAD_DIR="$PWD/artifacts/browser-downloads"
mkdir -p "$DOWNLOAD_DIR"
export AGENT_BROWSER_DOWNLOAD_PATH="$DOWNLOAD_DIR"

agent-browser open "http://localhost:3000"
agent-browser wait --load networkidle
agent-browser snapshot -i
```

Execute actions only from current refs, then resnapshot after state changes:

```bash
agent-browser click @e1
agent-browser wait --load networkidle
agent-browser snapshot -i
agent-browser screenshot artifacts/browser-downloads/scenario-after-click.png
```

Always close the browser session:

```bash
agent-browser close
```

## Screenshot Evidence

- Capture every user-facing state needed to support the verdict.
- Name files by scenario and state, for example `login-before.png`, `login-after.png`, `error-state.png`.
- Keep files project-local under `artifacts/browser-downloads/`.

## Download Evidence

**Inline files (e.g. PDFs).** `agent-browser download <ref> <path>` waits for a
browser *download event*. Links Chrome renders inline — notably PDFs sent with
`Content-Disposition: inline` (or no disposition) — open in the built-in PDF viewer,
emit no event, and time out with no file. Resolve the browser context **before**
clicking, try the native download, validate the result, and on failure fetch the
pre-click URL with browser-derived context (User-Agent + Referer). Keep it generic —
substitute the ref and output name for your case:

```bash
DOWNLOAD_DIR="$PWD/artifacts/browser-downloads"
mkdir -p "$DOWNLOAD_DIR"
export AGENT_BROWSER_DOWNLOAD_PATH="$DOWNLOAD_DIR"

REF="@eN"                         # ref from `agent-browser snapshot -i`
OUT="$DOWNLOAD_DIR/source.pdf"    # pick a descriptive output name

# Resolve browser context BEFORE clicking: the native download can navigate Chrome into
# the PDF viewer (a chrome-extension:// page), after which get attr/get url read the
# wrong page.
HREF="$(agent-browser get attr "$REF" href 2>/dev/null || true)"
PAGE_URL="$(agent-browser get url 2>/dev/null || true)"
UA="$(agent-browser eval 'navigator.userAgent' 2>/dev/null || true)"

# Validate the artifact: exists, non-empty, and (for .pdf targets) starts with %PDF-.
validate_file() {
  python3 - "$OUT" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
if not p.exists() or p.stat().st_size == 0:
    raise SystemExit(1)
if p.suffix.lower() == ".pdf" and p.read_bytes()[:5] != b"%PDF-":
    raise SystemExit(1)
PY
}

# 1) Try the native download first (works for normal download buttons/links).
agent-browser download "$REF" "$OUT" || true

if validate_file; then
  echo "Downloaded: artifacts/browser-downloads/$(basename "$OUT")"
else
  rm -f "$OUT"            # drop any invalid native artifact (e.g. HTML/error page)

  # 2) Fallback for inline files / no download event, using the PRE-CLICK context.
  python3 - "$HREF" "$PAGE_URL" "$UA" "$OUT" <<'PY'
import sys, urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlsplit
href, page_url, ua, out = (a.strip().strip('"').strip("'") for a in sys.argv[1:5])
url = urljoin(page_url, href)                       # absolutize relative hrefs
if not href or not page_url or not url:
    sys.exit("FAIL: could not resolve target URL before click")
req = urllib.request.Request(url, headers={
    "User-Agent": ua or "agent-browser",
    "Referer": page_url,
    "Accept": "application/pdf,application/octet-stream,*/*",
})
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        data, ctype = r.read(), (r.headers.get("Content-Type") or "").lower()
except Exception as e:
    sys.exit(f"FAIL: fetch failed: {e}")
if not data:
    sys.exit("FAIL: empty body")
expect_pdf = out.lower().endswith(".pdf") or urlsplit(url).path.lower().endswith(".pdf")
head = data[:1024].lstrip().lower()
looks_html = head.startswith((b"<!doctype html", b"<html", b"<head", b"<?xml")) or "html" in ctype
if expect_pdf and data[:5] != b"%PDF-":
    sys.exit("FAIL: expected a PDF but got "
             + ("an HTML/login/CAPTCHA page (do not bypass)" if looks_html
                else f"non-PDF bytes {data[:8]!r}"))
p = Path(out); p.parent.mkdir(parents=True, exist_ok=True)
p.write_bytes(data)                                  # save to the requested path
print(f"OK: wrote {out} ({len(data)} bytes)")
PY

  # 3) Final validation before recording the evidence path (never trust `-s` alone).
  if validate_file; then
    echo "Downloaded: artifacts/browser-downloads/$(basename "$OUT")"
  else
    rm -f "$OUT"
    echo "ERROR: no valid file produced"
  fi
fi
```

If the fetch needs session cookies, save them to a **temp** state file under a cleanup
trap so cookies/localStorage never linger on disk:

```bash
STATE="$(mktemp)"
trap 'rm -f "$STATE"' EXIT
agent-browser state save "$STATE"
# ...read cookies for the target host from "$STATE" and add them as a Cookie header...
rm -f "$STATE"
trap - EXIT
```

6. If the page or response is a CAPTCHA / login / block wall, do **not** bypass it —
   capture evidence and report `BLOCKED_CAPTCHA`:

```bash
agent-browser screenshot artifacts/browser-downloads/blocked.png
echo "BLOCKED_CAPTCHA: artifacts/browser-downloads/blocked.png"
```

Prefer the browser-derived fetch above (User-Agent + Referer; cookies only when
required) over a naked `curl`, and never accept a print-to-PDF artifact in place of the
real file.

For JavaScript-triggered download buttons, create a marker before clicking the download control and verify a new non-empty file.

```bash
DOWNLOAD_DIR="$PWD/artifacts/browser-downloads"
mkdir -p "$DOWNLOAD_DIR"
export AGENT_BROWSER_DOWNLOAD_PATH="$DOWNLOAD_DIR"
MARKER=$(date +%s)

agent-browser click @e3
agent-browser wait --load networkidle
sleep 2

DOWNLOADED=""
NEWEST_TIME=0
for f in "$DOWNLOAD_DIR"/*; do
    if [ -f "$f" ] && [ -s "$f" ]; then
        if [ "$(uname)" = "Darwin" ]; then
            MTIME=$(stat -f %m "$f")
        else
            MTIME=$(stat -c %Y "$f")
        fi
        if [ "$MTIME" -ge "$MARKER" ] && [ "$MTIME" -gt "$NEWEST_TIME" ]; then
            DOWNLOADED="$f"
            NEWEST_TIME="$MTIME"
        fi
    fi
done

if [ -n "$DOWNLOADED" ]; then
    echo "Downloaded: artifacts/browser-downloads/$(basename "$DOWNLOADED")"
else
    echo "ERROR: No new non-empty download found"
fi
```

## Report Output

- Verdict: `PASS`, `FAIL`, or `BLOCKED`.
- Runtime URL and platform.
- Actions performed and actual result.
- Screenshot/download artifact paths.
- Fallback used, if `agent-browser` was unavailable.
