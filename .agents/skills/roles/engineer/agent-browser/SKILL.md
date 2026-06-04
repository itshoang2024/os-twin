---
name: agent-browser
description: Use Vercel agent-browser CLI for browser automation workflows including search, navigation, snapshots, clicks, form fills, screenshots, and file downloads. CLI-oriented alternative to Playwright MCP or Chrome DevTools MCP.
tags: [engineer, browser, automation, web, cli]
triggers:
  - "use agent-browser"
  - "browser automation"
  - "download from website"
  - "scrape webpage"
  - "take website screenshot"
  - "navigate to url"
  - "fill web form"
  - "click on page"
tools:
  - Bash
mutating: true
---

# agent-browser

## Contract

- Deterministic browser automation using refs like `@e1`, `@e2` from snapshots (not coordinates)
- All screenshots and downloads saved inside project under `artifacts/browser-downloads/`
- Exact artifact paths reported to user
- Graceful fallback to Playwright MCP or Chrome DevTools MCP if CLI unavailable
- No stealth or anti-bot bypass logic enabled by default

## When to Use

- Downloading files from websites
- Taking screenshots
- Filling forms and submitting data
- Navigating multi-step web workflows
- Scraping structured data from pages

## Installation

```bash
# Install CLI
pnpm add -g agent-browser@0.27.0

# Run post-install setup if needed
agent-browser install

# Verify
agent-browser --version
```

## Start Here

Load the installed CLI's version-matched workflow before running a non-trivial browser task:

```bash
agent-browser skills get core
agent-browser skills get core --full
```

## Core Commands

| Command | Purpose |
|---------|---------|
| `agent-browser open <url>` | Navigate to URL |
| `agent-browser snapshot -i` | Get page snapshot with refs |
| `agent-browser snapshot -i --json` | Snapshot as JSON |
| `agent-browser click @eN` | Click element by ref |
| `agent-browser fill @eN "text"` | Fill input by ref |
| `agent-browser wait --load networkidle` | Wait for page load |
| `agent-browser screenshot <path>` | Save screenshot |
| `agent-browser close` | Close browser |

## Workflow

### 1. Navigate and Inspect

```bash
# Create artifact/download directory before launching browser
DOWNLOAD_DIR="$PWD/artifacts/browser-downloads"
mkdir -p "$DOWNLOAD_DIR"
export AGENT_BROWSER_DOWNLOAD_PATH="$DOWNLOAD_DIR"

# Open URL
agent-browser open "https://example.com"

# Wait for page load
agent-browser wait --load networkidle

# Get snapshot to find element refs
agent-browser snapshot -i
```

Snapshot output includes refs like:
```
[@e1] <button>Submit</button>
[@e2] <input type="text" name="search">
```

### 2. Interact Using Refs

Always use refs from snapshots, never coordinates:

```bash
# Fill input
agent-browser fill @e2 "search query"

# Click button
agent-browser click @e1

# Re-snapshot after page changes
agent-browser snapshot -i
```

### 3. Capture Artifacts

```bash
# Screenshot
agent-browser screenshot artifacts/browser-downloads/page.png
```

### 4. Handle Downloads

**Inline files (e.g. PDFs).** `agent-browser download <ref> <path>` clicks the
element and waits for a browser *download event*. Links Chrome renders **inline** —
notably PDFs served with `Content-Disposition: inline` (or no disposition) — open in
the built-in PDF viewer, emit no download event, and time out with no file. Resolve the
browser context **before** clicking, try the native download, validate the result, and
on failure fetch the pre-click URL with browser-derived context (User-Agent + Referer).
Keep it generic — substitute the ref and output name for your case:

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

  # 3) Final validation before claiming success (never trust `-s` alone).
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

For JavaScript-triggered download buttons, use marker-based verification to avoid moving old files:

```bash
# Route browser downloads directly into the project artifact directory
DOWNLOAD_DIR="$PWD/artifacts/browser-downloads"
mkdir -p "$DOWNLOAD_DIR"
export AGENT_BROWSER_DOWNLOAD_PATH="$DOWNLOAD_DIR"

# Create marker timestamp BEFORE clicking download
MARKER=$(date +%s)

# Click download link
agent-browser click @e3

# Wait for download to complete
agent-browser wait --load networkidle
sleep 2

# Find project-local files newer than marker (Linux/macOS)
DOWNLOADED=""
for f in "$DOWNLOAD_DIR"/*; do
    if [ -f "$f" ] && [ -s "$f" ]; then
        # Get file mtime as seconds since epoch
        if [ "$(uname)" = "Darwin" ]; then
            MTIME=$(stat -f %m "$f")
        else
            MTIME=$(stat -c %Y "$f")
        fi
        if [ "$MTIME" -ge "$MARKER" ]; then
            if [ -z "$DOWNLOADED" ] || [ "$MTIME" -gt "$NEWEST_TIME" ]; then
                DOWNLOADED="$f"
                NEWEST_TIME="$MTIME"
            fi
        fi
    fi
done

if [ -n "$DOWNLOADED" ] && [ -s "$DOWNLOADED" ]; then
    FILENAME=$(basename "$DOWNLOADED")
    echo "Downloaded: artifacts/browser-downloads/$FILENAME"
else
    echo "ERROR: No new file downloaded after marker"
fi
```

**Rules:**
- Create marker timestamp before clicking download
- Only accept files newer than marker
- Verify file exists and has non-zero size
- Select exactly one newest matching file
- Report exact relative path
- Report explicit failure if no new file appears

### 5. Clean Up

```bash
agent-browser close
```

## Example: Download Vietnamese Legal Decree

```bash
# Setup
DOWNLOAD_DIR="$PWD/artifacts/browser-downloads"
mkdir -p "$DOWNLOAD_DIR"
export AGENT_BROWSER_DOWNLOAD_PATH="$DOWNLOAD_DIR"

# Navigate to law library
agent-browser open "https://thuvienphapluat.vn"
agent-browser wait --load networkidle
agent-browser snapshot -i

# Search (refs from snapshot)
agent-browser fill @e1 "Nghi dinh 123/2024"
agent-browser click @e2
agent-browser wait --load networkidle
agent-browser snapshot -i

# Open result
agent-browser click @e3
agent-browser wait --load networkidle
agent-browser snapshot -i

# Click download with marker verification
MARKER=$(date +%s)
agent-browser click @e4
sleep 3

DOWNLOADED=""
for f in "$DOWNLOAD_DIR"/*; do
    if [ -f "$f" ] && [ -s "$f" ]; then
        if [ "$(uname)" = "Darwin" ]; then
            MTIME=$(stat -f %m "$f")
        else
            MTIME=$(stat -c %Y "$f")
        fi
        if [ "$MTIME" -ge "$MARKER" ]; then
            if [ -z "$DOWNLOADED" ] || [ "$MTIME" -gt "$NEWEST_TIME" ]; then
                DOWNLOADED="$f"
                NEWEST_TIME="$MTIME"
            fi
        fi
    fi
done

if [ -n "$DOWNLOADED" ]; then
    FILENAME=$(basename "$DOWNLOADED")
    echo "Downloaded: artifacts/browser-downloads/$FILENAME"
else
    echo "ERROR: No new file downloaded"
fi

# Cleanup
agent-browser close
```

## Fallback

If `agent-browser` CLI is unavailable:

### Chrome DevTools MCP

Use the currently available `chrome-devtools` MCP tools for browser navigation, snapshots, interaction, and browser state. This server is backed by native Obscura MCP, so tool names come from the active MCP runtime. Prefer `agent-browser` or Playwright MCP when screenshot files or download artifacts are required.

### Playwright MCP

Use the currently available Playwright MCP browser tools for navigation, snapshots, interaction, and capture.

## Platform Notes

### Windows (PowerShell)

```powershell
# Route browser downloads directly into the project artifact directory
$downloadDir = Join-Path (Get-Location) "artifacts\browser-downloads"
New-Item -ItemType Directory -Path $downloadDir -Force
$env:AGENT_BROWSER_DOWNLOAD_PATH = $downloadDir

# Create marker BEFORE clicking download
$marker = Get-Date

# ... click download link ...

# Find project-local files newer than marker with non-zero size
$downloaded = Get-ChildItem $downloadDir -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -gt $marker -and $_.Length -gt 0 } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if ($downloaded) {
    $relative = Join-Path "artifacts\browser-downloads" $downloaded.Name
    Write-Host "Downloaded: $relative"
}
else {
    Write-Host "ERROR: No new file downloaded after marker"
}
```

### Linux / macOS (Bash)

```bash
# Route browser downloads directly into the project artifact directory
DOWNLOAD_DIR="$PWD/artifacts/browser-downloads"
mkdir -p "$DOWNLOAD_DIR"
export AGENT_BROWSER_DOWNLOAD_PATH="$DOWNLOAD_DIR"

# Create marker BEFORE clicking download
MARKER=$(date +%s)

# ... click download link ...

# Find files newer than marker with non-zero size
DOWNLOADED=""
for f in "$DOWNLOAD_DIR"/*; do
    if [ -f "$f" ] && [ -s "$f" ]; then
        if [ "$(uname)" = "Darwin" ]; then
            MTIME=$(stat -f %m "$f")
        else
            MTIME=$(stat -c %Y "$f")
        fi
        if [ "$MTIME" -ge "$MARKER" ]; then
            if [ -z "$DOWNLOADED" ] || [ "$MTIME" -gt "$NEWEST_TIME" ]; then
                DOWNLOADED="$f"
                NEWEST_TIME="$MTIME"
            fi
        fi
    fi
done

if [ -n "$DOWNLOADED" ]; then
    FILENAME=$(basename "$DOWNLOADED")
    echo "Downloaded: artifacts/browser-downloads/$FILENAME"
else
    echo "ERROR: No new file downloaded after marker"
fi
```

## Anti-Patterns

- **Coordinate clicks** - Use refs from snapshots
- **Assuming download succeeded** - Always verify file exists and has content
- **Saving outside project** - Keep artifacts under `artifacts/browser-downloads/`
- **Not reporting paths** - User needs exact file locations
- **Stealth/bypass logic** - If blocked, report the blocker; do not add anti-detection
- **Hardcoded absolute paths** - Use relative paths from project root
- **Wildcards with `|| true`** - Hides failures; verify each download explicitly

## Verification Checklist

- [ ] Browser session closed after use
- [ ] All interactions use refs from snapshots (not coordinates)
- [ ] Downloads verified to exist with non-zero size
- [ ] Files saved under `artifacts/browser-downloads/`
- [ ] Exact relative paths reported to user
- [ ] No stealth/anti-bot logic added
