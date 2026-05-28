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

For download links, use marker-based verification to avoid moving old files:

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
