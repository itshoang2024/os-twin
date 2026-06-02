---
title: CLI Commands
description: Complete reference for the ostwin CLI.
sidebar:
  order: 1
---

The `ostwin` CLI is the unified entry point for all OSTwin operations — plan creation, execution, monitoring, skill management, and more. It lives at `.agents/bin/ostwin` and is a pure PowerShell script (requires `pwsh` 7+).

## Global Options

| Flag | Description |
|------|-------------|
| `-h`, `--help` | Show help text and exit |
| `-v`, `--version` | Show version and build hash |

## ostwin run

Execute a plan. This is the primary entry point for running work.

```bash
ostwin run <plan_id>
ostwin run <plan_id> --dry-run
ostwin run <plan_id> --resume --expand
ostwin run plans/my-feature.md
```

The first positional argument is resolved in this order:

1. **Plan ID** — a hex string (8–64 characters) resolved via the dashboard API to a plan file and working directory
2. **File path** — an existing `.md` file used directly
3. **Fallback** — passed through as-is (will error if invalid)

When a plan ID is provided and the dashboard is reachable, `ostwin run` automatically resolves the plan file location and extracts the `working_dir` from the plan metadata.

| Flag | Description |
|------|-------------|
| `--dry-run` | Parse plan, build DAG, but do not execute |
| `--resume` | Resume a previously stopped plan execution |
| `--expand` | Expand the plan using AI before execution |
| `--review` | Run in review-only mode |
| `--max-rooms N` | Limit concurrent war-rooms |
| `--working-dir PATH` | Override the working directory for the plan |
| `--non-interactive`, `-n` | Skip all interactive prompts |

### Auto Role Scaffolding

If the plan references roles that are not installed, `ostwin run` will prompt (or auto-create in non-interactive mode) to scaffold the missing roles using `Auto-CreateRole.ps1`.

### Project Initialization

Before execution, `ostwin run` ensures the project directory is initialized (runs `init.ps1` idempotently). This creates `.agents/` and `.opencode/opencode.json` if they don't exist.

## ostwin plan

Plan management with AI-assisted creation.

```bash
ostwin plan create "Implement user auth"
ostwin plan create --file brief.txt
ostwin plan create brief.md
ostwin plan start <plan_id>
ostwin plan list
ostwin plan clear --force
```

| Subcommand | Description |
|------------|-------------|
| `create` | Generate a plan via the dashboard API from a title or file |
| `start` | Execute a plan (same resolution as `ostwin run`) |
| `list` | List all plans tracked in the project |
| `clear` | Delete all plan files and zvec indexes |

### plan create

```bash
ostwin plan create "My Feature"
ostwin plan create --file brief.txt
ostwin plan create brief.md          # smart-detect: .md file treated as --file
```

| Argument | Description |
|----------|-------------|
| `[Title]` | Plan title (positional) |
| `--file`, `-f` | Read initial content from a file |
| _bare .md path_ | If the positional arg is an existing `.md` file, it's used as the init file automatically |

Creates the plan via the dashboard API and opens the plan editor in your browser.

Requires the dashboard to be running (`ostwin dashboard start`).

### plan start

```bash
ostwin plan start <plan_id>
ostwin plan start <plan_id> --dry-run
```

Accepts the same `plan_id` or file path resolution as `ostwin run`, plus the same flags (`--dry-run`, `--resume`, `--expand`, `--working-dir`).

### plan clear

```bash
ostwin plan clear
ostwin plan clear --force
```

Removes all plan files from `~/.ostwin/.agents/plans/` (preserving `PLAN.template.md`) and clears the zvec index. Stops and restarts the dashboard if it was running.

| Flag | Description |
|------|-------------|
| `--force`, `-f`, `-y` | Skip confirmation prompt |

## ostwin init

Scaffold Agent OS into a project directory.

```bash
ostwin init                    # Initialize current directory
ostwin init /path/to/project   # Initialize a specific directory
ostwin init --yes              # Non-interactive mode
```

| Flag | Description |
|------|-------------|
| `--yes`, `-y` | Accept all defaults without prompts |
| `--help`, `-h` | Show help |

Creates `.agents/`, `config.json`, role directories, and the opencode configuration. Lighter than a full install — does not install Python dependencies.

## ostwin sync

Sync framework updates from the global OSTwin installation to an initialized project.

```bash
ostwin sync
ostwin sync /path/to/project
```

Updates `.agents/` scripts and configuration to match the installed version.

## ostwin status

Show the current state of all war-rooms.

```bash
ostwin status
ostwin status --watch
ostwin status --json
```

| Flag | Description |
|------|-------------|
| `--json` | Machine-readable JSON output |
| `--watch` | Continuously refresh the status display |

Reads `status`, `state_changed_at`, and `retries` from each room directory.

## ostwin logs

View war-room channel logs.

```bash
ostwin logs
ostwin logs room-001
ostwin logs room-001 --follow
ostwin logs --type done --last 20
```

| Flag | Description |
|------|-------------|
| `--follow`, `-f` | Stream new log entries in real time |
| `--type TYPE` | Filter by message type (`task`, `done`, `review`, `pass`, `fail`, `fix`, `error`, `signoff`) |
| `--from ROLE` | Filter by sender role |
| `--last N` | Show only the last N messages |

## ostwin stop

Graceful shutdown of running processes.

```bash
ostwin stop
ostwin stop --force
```

| Flag | Description |
|------|-------------|
| `--force` | Force-kill the entire process tree immediately |

Stops the dashboard and any running channel processes. Without `--force`, sends a graceful termination signal and waits up to 5 seconds before force-killing.

## ostwin dashboard

Manage the web dashboard server.

```bash
ostwin dashboard start
ostwin dashboard stop
ostwin dashboard restart
ostwin dashboard status
ostwin dashboard logs
ostwin dashboard logs --follow
```

| Subcommand | Description |
|------------|-------------|
| `start` | Start the dashboard in the background |
| `stop` | Stop the running dashboard |
| `restart` | Stop and start the dashboard |
| `status` | Show running state, URL, and memory pool health |
| `logs` | Show the last 50 log lines (use `-f` to follow) |

The dashboard runs on port 3366 by default (overridable via `DASHBOARD_PORT` env var).

## ostwin channel

Manage communication channel integrations (Telegram, Discord, Slack).

```bash
ostwin channel start
ostwin channel stop
ostwin channel status
ostwin channel logs
ostwin channel list
ostwin channel connect
ostwin channel disconnect
ostwin channel test
ostwin channel pair
ostwin channel deploy
```

| Subcommand | Description |
|------------|-------------|
| `start` | Start the channel service |
| `stop` | Stop the channel service |
| `status` | Show channel connection status |
| `logs` | View channel service logs |
| `list` | List configured channels |
| `connect` | Connect a channel integration |
| `disconnect` | Disconnect a channel integration |
| `test` | Test channel connectivity |
| `pair` | Pair a channel with a war-room |
| `deploy` | Deploy channel configuration |

## ostwin skills

Manage skill discovery, installation, and updates.

```bash
ostwin skills search "web"
ostwin skills install my-skill
ostwin skills install https://github.com/user/repo
ostwin skills install --from /path/to/skill
ostwin skills install my-skill --agent engineer
ostwin skills list
ostwin skills update --all
ostwin skills remove my-skill
ostwin skills sync
```

| Subcommand | Description |
|------------|-------------|
| `install` | Install a skill from ClawHub catalog, GitHub URL, or local directory |
| `list` | Show installed skills (via dashboard API) |
| `search` | Search the ClawHub catalog |
| `update` | Update a specific skill or all skills |
| `remove` | Uninstall a skill |
| `sync` | Synchronize skills across the project |

### install sources

The `install` subcommand supports three sources:

| Source | Example |
|--------|---------|
| **ClawHub slug** | `ostwin skills install my-skill` |
| **GitHub URL** | `ostwin skills install https://github.com/user/skill-repo` |
| **Local directory** | `ostwin skills install --from /path/to/skill-dir` |

When installing from a GitHub URL, `ostwin` clones the repository, scans for `SKILL.md` files, and installs each skill found. Nested skills (skills inside other skill directories) are skipped.

| Flag | Description |
|------|-------------|
| `--from DIR` | Install from a local directory |
| `--agent ROLE` | Install to a specific role's skill directory instead of global |

## ostwin mcp

Manage MCP extensions and permissions.

```bash
ostwin mcp sync
ostwin mcp install <git-url> --name custom-server
ostwin mcp install --http https://stitch.googleapis.com/mcp
ostwin mcp list
ostwin mcp catalog
ostwin mcp remove chrome-devtools
ostwin mcp credentials set API_KEY
ostwin mcp test chrome-devtools
```

| Subcommand | Description |
|------------|-------------|
| `sync` | Resolve MCP servers from role definitions and generate agent permissions |
| `install` | Install an MCP extension from catalog, git, or HTTP |
| `list` | Show installed extensions |
| `catalog` | Show available packages in the central catalog |
| `remove` | Uninstall an extension |
| `credentials` | Manage credentials in the vault (`set`, `list`, `delete`) |
| `test` | Test MCP server connectivity |

### mcp sync

```bash
ostwin mcp sync
```

Resolves MCP server references from `role.json` `mcp_refs` and generates the agent permission configuration in `~/.ostwin/.opencode/opencode.json`. Run this after installing new MCP extensions or updating role configurations.

## ostwin memory

Manage agent memory namespaces.

```bash
ostwin memory list
ostwin memory stats <plan_id>
ostwin memory tree <plan_id>
ostwin memory clear <plan_id> --force
ostwin memory delete <plan_id> <note_id>
ostwin memory archive <plan_id>
ostwin memory export <plan_id>
```

| Subcommand | Description |
|------------|-------------|
| `list` | List all namespaces with note counts and sizes |
| `stats` | Show stats for a namespace (notes, tags, keywords, paths) |
| `tree` | Show the note directory tree for a namespace |
| `clear` | Delete all notes in a namespace |
| `delete` | Delete a single note by ID |
| `archive` | Archive notes and start fresh |
| `export` | Export a namespace as `.tar.gz` |

Requires the dashboard to be running.

| Flag | Description |
|------|-------------|
| `--force` | Skip confirmation prompt (for `clear`) |

## ostwin role

Run a role's subcommand or list available roles.

```bash
ostwin role                       # List all roles with subcommands
ostwin role <name>                # List subcommands for a role
ostwin role <name> <sub> [args]   # Run a role subcommand
```

Roles define their subcommands in `subcommands.json`. Each subcommand has an `invoke` template that is resolved and executed in the role's module root directory.

## ostwin clone-role

Clone a global role to a project-local directory for customization.

```bash
ostwin clone-role engineer
ostwin clone-role engineer --project-dir /path/to/project
```

| Flag | Description |
|------|-------------|
| `--project-dir PATH` | Target project directory (default: current directory) |

This is a shortcut for `ostwin role manager clone -RoleName <role> -ProjectDir <path>`.

## ostwin config

View or update configuration.

```bash
ostwin config --get manager.poll_interval_seconds
ostwin config --set manager.default_model "google-vertex/gemini-3.1-pro"
```

| Flag | Description |
|------|-------------|
| `--get KEY` | Read a configuration value |
| `--set KEY VALUE` | Write a configuration value |

## ostwin health

Check system health.

```bash
ostwin health
ostwin health --json
```

| Flag | Description |
|------|-------------|
| `--json` | Machine-readable JSON output |

Validates the PowerShell engine, dashboard API, dashboard frontend, memory daemon, and active war-room states.

## ostwin test

Run test suites.

```bash
ostwin test
ostwin test --suite NAME --verbose
```

| Flag | Description |
|------|-------------|
| `--suite NAME` | Run a specific test suite |
| `--verbose` | Verbose output |

Executes Pester tests across `lib/`, `channel/`, `war-rooms/`, `roles/`, and `plan/` modules.

## ostwin reload-env

Reload environment variables from `~/.ostwin/.env` into MCP configuration files.

```bash
ostwin reload-env
```

Parses the `.env` file and injects all variables into the `environment` (or `env`) blocks of every configured MCP server. Useful after adding new API keys or changing environment configuration.

## ostwin mac

macOS desktop automation shorthand. Delegates to the `macos-automation-engineer` role.

```bash
ostwin mac app help
ostwin mac window list
ostwin mac capture screen
ostwin mac type "Hello World"
ostwin mac click 100 200
```

Available scripts: `app`, `window`, `click`, `type`, `capture`, `system`, `finder`, `axbridge`, `devtools`. Run `ostwin mac <script> help` for per-script usage.

This is a shortcut for `ostwin role macos-automation-engineer <script> <command>`.

## ostwin version

Show the current version.

```bash
ostwin version
```

Displays the version from `config.json` and the build hash (if available).

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ENGINEER_CMD` | Override the CLI tool spawned for the engineer role |
| `QA_CMD` | Override the CLI tool spawned for the QA role |
| `MOCK_SIGNOFF` | Set to `"true"` for automatic signoff (testing) |
| `AGENT_OS_LOG_LEVEL` | Log level: `DEBUG`, `INFO`, `WARN`, `ERROR` (default: `INFO`) |
| `WARROOMS_DIR` | Override the war-rooms data directory (default: `<project>/.war-rooms`) |
| `DASHBOARD_PORT` | Override the dashboard port (default: `3366`) |
| `DASHBOARD_URL` | Override the dashboard URL (default: `http://localhost:3366`) |
| `OSTWIN_HOME` | Override the OSTwin home directory (default: `~/.ostwin`) |
| `OSTWIN_API_KEY` | API key for dashboard authentication |

Environment files are loaded in this order (later values do not override already-set variables):

1. `~/.ostwin/.env` — global
2. `<project-root>/.env` — project root
3. `.agents/.env` — agents directory

## Plan ID Resolution

When a command accepts a `<plan_id>` argument, the following resolution logic applies:

1. **Existing file** — If the argument is a path to an existing file, use it directly and extract `working_dir` from the file content
2. **Hex ID** — If the argument matches `^[0-9a-fA-F]{8,64}$` (no slashes or dots), query the dashboard API at `/api/plans/<id>` to resolve the plan file location and working directory
3. **Fallback** — Pass through as-is

This means you can use either short hex IDs (e.g., `a1b2c3d4e5f6`) or full file paths interchangeably.

:::tip
Use `ostwin run <plan_id>` with the hex ID returned by `ostwin plan create` — this is the recommended workflow. The dashboard resolves the file path automatically.
:::

:::tip
Run `ostwin status --json` to get machine-readable output suitable for CI pipelines.
:::

:::note
The `ostwin` CLI requires PowerShell 7+ (`pwsh`) to be on the PATH. All subcommands are implemented as `.ps1` scripts invoked by the CLI.
:::
