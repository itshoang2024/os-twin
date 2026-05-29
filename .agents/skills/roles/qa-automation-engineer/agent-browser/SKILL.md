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

Create a marker before clicking the download control and verify a new non-empty file.

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
