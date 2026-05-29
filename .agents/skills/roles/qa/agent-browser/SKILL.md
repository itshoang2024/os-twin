---
name: agent-browser
description: Use when QA verification needs browser navigation, snapshots, clicks, forms, screenshots, downloads, exploratory testing, or web app evidence through agent-browser.
tags: [qa, browser, automation, web, cli, evidence]
triggers:
  - "use agent-browser"
  - "browser automation"
  - "take website screenshot"
  - "download from website"
  - "verify web app"
  - "exploratory testing"
tools:
  - Bash
mutating: true
---

# agent-browser

## Contract

- Use `agent-browser` for QA flows that need browser interaction or evidence files.
- Use element refs from snapshots, such as `@e1` and `@e2`; avoid coordinate clicks.
- Save screenshots and downloaded files under `artifacts/browser-downloads/`.
- Report exact relative artifact paths in the QA result.
- Use Chrome DevTools MCP or Playwright MCP only when `agent-browser` is unavailable or the task needs their specific inspection surface.
- Do not add stealth, anti-bot bypass, or logged-in profile attachment by default.

## Installation

Use the repository package manager:

```bash
pnpm add -g agent-browser@0.27.0
agent-browser install
agent-browser --version
```

## Start Here

Load the installed CLI's version-matched workflow before running a non-trivial browser task:

```bash
agent-browser skills get core
agent-browser skills get core --full
```

For exploratory QA or bug hunts:

```bash
agent-browser skills get dogfood
```

## Core Commands

| Command | Purpose |
| --- | --- |
| `agent-browser open <url>` | Navigate to a URL |
| `agent-browser wait --load networkidle` | Wait for page/network idle |
| `agent-browser snapshot -i` | Inspect page with element refs |
| `agent-browser click @eN` | Click by ref |
| `agent-browser fill @eN "text"` | Fill input by ref |
| `agent-browser screenshot <path>` | Save screenshot evidence |
| `agent-browser close` | Close the browser session |

## QA Flow

```bash
DOWNLOAD_DIR="$PWD/artifacts/browser-downloads"
mkdir -p "$DOWNLOAD_DIR"
export AGENT_BROWSER_DOWNLOAD_PATH="$DOWNLOAD_DIR"

agent-browser open "https://example.com"
agent-browser wait --load networkidle
agent-browser snapshot -i
```

Use the snapshot refs for each action:

```bash
agent-browser fill @e2 "search query"
agent-browser click @e1
agent-browser wait --load networkidle
agent-browser snapshot -i
agent-browser screenshot artifacts/browser-downloads/after-action.png
```

Close the session when finished:

```bash
agent-browser close
```

## Download Evidence

Use a marker before clicking a download link, then accept only a new non-empty file.

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

## QA Report Requirements

- Include URL, scenario, action sequence, and observed result.
- Include screenshot/download paths.
- Mark the result `PASS`, `FAIL`, or `BLOCKED`.
- If the CLI is unavailable, say which fallback was used.
