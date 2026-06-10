---
title: Command Support Inventory
description: Tested command surfaces for the OSTwin CLI, channel bot, MCP tools, and macOS role shortcuts.
sidebar:
  order: 2
---

This page inventories the command surfaces discovered during the 2026-06-10 command review. It complements the [CLI Commands](cli-commands.md) reference by showing where each command is implemented, how it was smoke-tested, and which commands require a live dashboard or external services.

## Review scope

| Surface | Source of truth | Notes |
|---------|-----------------|-------|
| `ostwin` CLI | `.agents/bin/ostwin` and `.agents/bin/ostwin.ps1` | Unified PowerShell entrypoint. The Unix executable uses a `pwsh` shebang; Windows uses `ostwin.cmd` to invoke `ostwin.ps1`. |
| MCP extension manager | `.agents/mcp/mcp-extension.sh` | Reached through `ostwin mcp ...` except `ostwin mcp sync`, which calls `resolve_opencode.py` directly. |
| Channel CLI | `.agents/bin/channel_cmd.py` | Reached through `ostwin channel ...`; all operational subcommands call the dashboard REST API. |
| Search engine manager | `.agents/search-engine.sh` | Manages a user-owned SearXNG runtime under `OSTWIN_HOME/search-engine`. |
| Role subcommands | `.agents/roles/*/subcommands.json` | Currently `manager` and `macos-automation-engineer` expose role subcommands. |
| Bot slash commands | `bot/src/commands.ts` | Registry used by Discord, Telegram, and Slack connectors. |
| `ostwin` MCP tools | `.agents/mcp/ostwin-server.py` | Tools exposed to OpenCode as deterministic MCP calls that proxy dashboard REST APIs. |

## Safe smoke-test matrix

These commands were exercised in a non-destructive shell with a temporary `OSTWIN_HOME` and unused dashboard port where possible.

| Command | Result | Classification | Notes |
|---------|--------|----------------|-------|
| `ostwin --help` | Pass | Safe | Main help renders all top-level commands. |
| `ostwin version` | Pass | Safe | Prints `ostwin v<version>` from `.agents/config.json`. |
| `ostwin plan help` | Pass | Safe | Shows `create`, `start`, `list`, `clear`. |
| `ostwin skills help` | Pass | Safe | Shows `sync`, `install`, `search`, `update`, `remove`, `list`. |
| `ostwin mcp help` | Pass | Safe | Shows extension, credentials, test, compile, migrate, and init-project commands. |
| `ostwin search-engine --help` | Pass | Safe | Shows install/configure/start/stop/status/settings. |
| `ostwin channel --help` | Pass | Safe | Argparse help shows list/connect/disconnect/test/pair. |
| `ostwin memory help` | Pass | Safe | Shows namespace list/stats/tree/clear/delete/archive/export. |
| `ostwin dashboard help` | Pass | Safe | Shows server lifecycle and autostart commands. |
| `ostwin test --help` | Pass | Safe | Lists available Pester suites and flags. |
| `ostwin role` | Pass | Safe | Lists roles that have `subcommands.json`. |
| `ostwin role macos-automation-engineer` | Pass | Safe | Lists the nine macOS script shortcuts. |
| `ostwin mac app help` | Pass | Safe | Confirms app lifecycle usage. |
| `ostwin mac window help` | Pass | Safe | Confirms Accessibility-gated window commands. |
| `ostwin mac capture help` | Pass | Safe | Confirms Screen Recording-gated capture commands. |
| `ostwin config --help` | Pass | Safe | Shows get/set syntax. |
| `ostwin status --json` | Pass | Safe/read-only | Reads local `.war-rooms` state. |
| `ostwin logs --last 1` | Pass | Safe/read-only | Reads latest local channel message. |
| `ostwin dashboard status` | Pass | Safe/read-only | Reports whether a dashboard process listens on the configured port. |
| `ostwin search-engine status` | Pass | Safe/read-only | Reports runtime state and managed paths without starting SearXNG. |
| `ostwin mcp catalog` | Pass | Safe/read-only | Catalog command returns successfully even when no packages are present. |
| `ostwin mcp list` | Pass | Safe/read-only | Lists built-in MCP servers and installed extensions. |
| `ostwin mcp definitely-not-a-command` | Fixed | Negative test | Unknown MCP subcommands now exit non-zero instead of reporting failure with exit `0`. |

## Dashboard-dependent commands

These commands are valid but need the dashboard API to be running and reachable at `DASHBOARD_URL`/`DASHBOARD_PORT`.

| Command family | Requires dashboard? | Why |
|----------------|---------------------|-----|
| `ostwin plan create`, `ostwin plan list` | Yes | Uses `/api/plans/create`, `/api/plans`, and related plan editor endpoints. |
| `ostwin channel list/connect/disconnect/test/pair` | Yes | Uses `/api/channels/...`. |
| `ostwin skills list` | Yes | Uses `/api/skills`. |
| `ostwin memory list/stats/tree/clear/delete/archive/export` | Yes | Uses `/api/amem/...`. |
| `ostwin health` | Partially | Checks local components plus dashboard endpoints when available. |

## Top-level CLI commands

| Command | Supported subcommands/options | Implementation | Status |
|---------|-------------------------------|----------------|--------|
| `run` | `--dry-run`, `--resume`, `--expand`, `--review`, `--max-rooms`, `--working-dir`, `--workspace-isolation`, `--non-interactive` | `.agents/bin/ostwin` + `.agents/plan/Start-Plan.ps1` | Supported; execution command, not safe-smoked end-to-end in docs review. |
| `plan` | `create`, `start`, `list`, `clear` | CLI + dashboard API + `Start-Plan.ps1` | Supported; `help` smoke-tested. |
| `init` | `[directory]`, `--yes`, `--help` | `.agents/init.ps1` | Supported. |
| `sync` | `[directory]` | `.agents/sync.ps1` | Supported for directories already initialized with `.agents/`; exits non-zero for uninitialized targets. |
| `status` | `--json`, `--watch` | `.agents/war-rooms/Get-WarRoomStatus.ps1` | Supported; `--json` smoke-tested. |
| `logs` | `[room-id]`, `--follow`, `--type`, `--from`, `--last` | `.agents/logs.ps1` | Supported; read-only smoke-tested. |
| `stop` | `--force` | Inline CLI process shutdown | Supported; destructive, not smoke-tested. |
| `dashboard` | `start`, `stop`, `restart`, `status`, `logs`, `autostart`, `--port`, `--project-dir` | `.agents/dashboard.sh` / `.agents/dashboard.ps1` | Supported; `status` and `help` smoke-tested. |
| `channel` | `list`, `connect`, `disconnect`, `test`, `pair` | `.agents/bin/channel_cmd.py` | Supported; help smoke-tested. |
| `config` | `--get`, `--set`, `--help` | `.agents/config.ps1` | Supported; help smoke-tested. |
| `role` | list roles, list role subcommands, dispatch role subcommand | Role `subcommands.json` manifests | Supported; list paths smoke-tested. |
| `mac` | `app`, `window`, `click`, `type`, `capture`, `system`, `finder`, `axbridge`, `devtools` | Shortcut to `role macos-automation-engineer` | Supported; help smoke-tested for representative scripts. |
| `health` | `--json` | `.agents/health.ps1` | Supported; may report unhealthy without dashboard. |
| `skills` | `sync`, `install`, `search`, `update`, `remove`, `list` | `.agents/sync-skills.ps1`, `.agents/clawhub-install.ps1` | Supported; help smoke-tested. |
| `mcp` | `install`, `list`, `catalog`, `remove`, `sync`, `test`, `compile`, `credentials`, `migrate`, `init-project` | `.agents/mcp/mcp-extension.sh`, `resolve_opencode.py` | Supported; help/list/catalog smoke-tested. |
| `search-engine` | `install`, `configure`, `start`, `stop`, `status`, `settings` | `.agents/search-engine.sh` | Supported; status/help/settings smoke-tested. `settings` is safe before configure and prints guidance. |
| `reload-env` | no subcommands | Inline CLI MCP config updater | Supported; writes MCP configs. |
| `memory` | `list`, `stats`, `tree`, `clear`, `delete`, `archive`, `export` | Inline dashboard API wrapper | Supported; help smoke-tested. |
| `test` | `--suite`, `--path`, `--verbose` | Inline Pester runner | Supported; help smoke-tested. |
| `version` | `-v`, `--version` | Inline version printer | Supported; smoke-tested. |

## Bot slash command registry

Bot commands are configured once in `COMMAND_REGISTRY` and then exposed by each connector. Discord includes the voice-only commands; Telegram and Slack omit commands marked `discordOnly`.

| Category | Commands |
|----------|----------|
| Plans and AI | `menu`, `help`, `draft <idea>`, `edit`, `viewplan`, `startplan`, `resume`, `assets`, `setdir <path>`, `cancel`, `clear`, `feedback <text>` |
| Monitoring | `dashboard`, `status`, `errors`, `logs <room_id>`, `health`, `progress`, `plans` |
| Skills and roles | `skills`, `skillsearch <query>`, `skillinstall <slug>`, `skillremove <name>`, `skillsync`, `roles` |
| System | `triage <room_id>`, `clearplans`, `new`, `restart`, `launchdashboard`, `preferences`, `subscriptions` |
| Discord voice only | `join`, `leave`, `ping` |

## `ostwin` MCP server tools

The `ostwin` MCP server exposes dashboard actions as typed tools for OpenCode. These tools are dashboard-dependent and return JSON strings.

| Tool | Purpose |
|------|---------|
| `list_plans` | List every plan with ID, title, and status. |
| `get_plan_status(plan_id)` | Return one plan plus its epic statuses. |
| `create_plan(idea, working_dir?)` | Create and AI-draft a new plan, then save it. |
| `refine_plan(plan_id, instruction)` | Ask the dashboard to refine and save an existing plan. |
| `launch_plan(plan_id)` | Launch a saved plan into war-rooms. |
| `resume_plan(plan_id)` | Mark a plan as running again. |
| `get_war_room_status` | Return aggregate dashboard stats. |
| `get_logs(plan_id, room_id, limit?)` | Read recent war-room channel messages. |
| `get_health` | Check dashboard health. |
| `search_skills(query)` | Search ClawHub through the dashboard API. |
| `get_plan_assets(plan_id)` | List plan-attached assets. |
| `get_memories(plan_id)` | Stub currently returning an empty memories array. |

## Removal guidance

The broken `clone-role` shortcut was removed from public help/docs because it delegated to a missing `manager clone` role subcommand. The invalid `ostwin mac click 100 200` example was replaced with `ostwin mac click help`; real click actions must include a click subcommand such as `ostwin mac click click 100 200` and require Accessibility permission. The unknown MCP subcommand path was fixed to return exit `1`, and command wrappers now propagate child-process failures for sync and role/mac dispatch. Commands that require credentials, dashboard availability, Git worktrees, Accessibility permission, Screen Recording permission, or destructive state changes remain documented but should be tested in an environment prepared for those side effects.
