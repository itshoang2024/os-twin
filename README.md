<p align="center">
  <strong>OSTwin</strong>
</p>

<p align="center">
  A zero-agent operating system for composable AI engineering teams.<br/>
  One universal runner. Config-driven roles. Filesystem coordination.
</p>

<p align="center">
  <a href="https://ostwin.igot.ai">Docs</a> ·
  <a href="https://github.com/igot-ai/os-twin/issues">Issues</a> ·
  <a href="#quick-start">Quick Start</a>
</p>

---

<p align="center">
  <img src="ostwin-flow-animated.svg" alt="OSTwin Architecture Flow" width="100%">
</p>

## The Five Pillars

| Pillar | Concept | Why It Matters |
|--------|---------|----------------|
| **Role Pattern** | Adding a new role requires zero lines of code. Roles are config directories of Skills + MCPs, not compiled agents. | Swap expertise without touching orchestration code |
| **Skills as Expertise** | Portable `SKILL.md` documents teach agents how to perform specific tasks. Declared at design time, fulfilled at runtime. | Same skill works across projects, tools, and environments |
| **MCP Isolation** | Each agent only connects to the MCP servers it actually needs. Unused tools don't waste prompt tokens. | Saves 240K-360K tokens per plan; cuts cost and latency |
| **War-Rooms** | Isolated filesystem directories where agent teams collaborate on a single epic. Channel, artifacts, lifecycle — all local. | No shared database, no message broker, fully inspectable |
| **Layered Memory** | Three-layer architecture (conversation → artifacts → shared ledger) gives agents cross-room context without breaking isolation. | Agents learn from each other without race conditions |

## Quick Start

```bash
# 1. Clone
git clone https://github.com/AnomalyCo/agent-os.git
cd agent-os

# 2. Install
.agents/install.sh           # macOS / Linux
.agents\install.ps1          # Windows (PowerShell 7+)

# 3. Add an API key
echo "GOOGLE_API_KEY=your-key" >> ~/.ostwin/.env

# 4. Create and run a plan
ostwin plan create "Build a REST API with auth"
ostwin run plans/my-feature.md

# 5. Monitor
ostwin status --watch
ostwin logs room-001 --follow
```

## Prerequisites

| Dependency | Min Version | Notes |
|------------|-------------|-------|
| Python | 3.10+ | 3.12 recommended; auto-installed |
| PowerShell | 7+ | `pwsh`; auto-installed |
| Node.js | 18+ | Dashboard UI; auto-installed |
| opencode | latest | Agent execution engine; auto-installed |
| AI Provider Key | — | At least one: Google, OpenAI, Anthropic, etc. |

The installer auto-detects missing dependencies and installs them.

## Installation

### macOS

```bash
.agents/install.sh           # Interactive
.agents/install.sh --yes     # Non-interactive
```

Uses **Homebrew** (auto-installed if missing). Installs everything to `~/.ostwin/`, adds `ostwin` to your PATH.

### Linux

```bash
.agents/install.sh           # Interactive
.agents/install.sh --yes     # Non-interactive
```

Supports Ubuntu/Debian, Fedora/RHEL, Arch, openSUSE. Auto-detects your package manager.

### Windows

```powershell
.agents\install.ps1          # Interactive
.agents\install.ps1 -Yes     # Non-interactive
```

Fully native PowerShell — no WSL or Cygwin needed. Uses winget, Chocolatey, or Scoop.

<details>
<summary>Windows installer options</summary>

```powershell
.agents\install.ps1 -Dir C:\MyOstwin          # Custom install directory
.agents\install.ps1 -Port 8080                 # Custom dashboard port
.agents\install.ps1 -DashboardOnly             # Dashboard only, no agent tooling
.agents\install.ps1 -Channel                   # Include Telegram + Discord + Slack
.agents\install.ps1 -SkipOptional              # Skip Pester etc.
```

</details>

### Post-Install: API Keys

Edit `~/.ostwin/.env` (or `%USERPROFILE%\.ostwin\.env` on Windows):

```bash
GOOGLE_API_KEY=your-key-here
OPENAI_API_KEY=your-key-here
ANTHROPIC_API_KEY=your-key-here
```

## CLI Reference

```bash
ostwin run <plan>                 # Execute a plan
ostwin run <plan> --resume        # Resume a stopped plan
ostwin run <plan> --dry-run       # Parse only, no execution

ostwin plan create "Title"        # AI-assisted plan creation
ostwin plan create --file brief   # From a file
ostwin plan list                  # List tracked plans

ostwin status                     # War-room dashboard
ostwin status --watch             # Live refresh
ostwin logs room-001 --follow    # Stream channel logs
ostwin stop                       # Graceful shutdown

ostwin skills search "web"        # Search ClawHub catalog
ostwin skills install my-skill    # Install a skill
ostwin skills list                # Show installed skills

ostwin mcp catalog                # Browse MCP extensions
ostwin mcp install <git-url> --name custom-server
ostwin mcp list                   # Show installed extensions

ostwin dashboard start            # Launch web dashboard
ostwin health                     # System health check
```

## Architecture

OSTwin is four subsystems communicating through the filesystem:

| Subsystem | Language | Purpose |
|-----------|----------|---------|
| **Engine** | PowerShell | Plan execution, agent invocation, lifecycle enforcement |
| **Dashboard** | Python (FastAPI) + TypeScript (Next.js) | Real-time monitoring, SSE streaming, memory search |
| **MCP Servers** | Python + native MCP CLIs | Tool interfaces for agents (channel, warroom, memory, knowledge, browser automation) |
| **Bot** | TypeScript | Chat platform integrations (Discord, Telegram, Slack) |

All state lives in `.agents/` — plans, war-rooms, roles, skills, and the shared memory ledger. No database, no message broker, no shared process.

### Built-in MCP Servers

| Server | Type | Tools |
|--------|------|-------|
| `channel` | local | `post_message`, `read_messages`, `get_latest` |
| `warroom` | local | `update_status`, `report_progress`, `list_artifacts` |
| `memory` | remote | `publish`, `query`, `search`, `get_context` |
| `knowledge` | remote | `list_namespaces`, `query`, `search_all`, `find_relevant` |
| `chrome-devtools` | local | Browser automation through Obscura's native MCP server |
| `playwright` | local | Browser automation |

## Data Layout

**Project-local** (tracked per plan):

| Location | What |
|----------|------|
| `.agents/war-rooms/room-*/` | Channel, config, artifacts, status |
| `.agents/memory/` | Shared memory ledger |
| `.agents/roles/` | Role definitions (`role.json` + `ROLE.md`) |
| `.agents/skills/` | Skill documents (`SKILL.md`) |

**Global** (at `~/.ostwin/`):

| Location | What |
|----------|------|
| `~/.ostwin/plans/` | Plan files and metadata |
| `~/.ostwin/.env` | API keys and secrets |
| `~/.ostwin/.agents/skills/` | Globally installed skills |
| `~/.ostwin/.zvec/` | Vector embeddings cache |

## Contributing

We welcome contributions — new roles, skills, MCP extensions, and docs improvements.

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Commit your changes (`git commit -m 'feat: add my feature'`)
4. Push to the branch (`git push origin feat/my-feature`)
5. Open a Pull Request

See [CONTRIBUTE.md](CONTRIBUTE.md) for detailed guidelines and the [contribution guide](https://ostwin.igot.ai/contributing/guide/) for creating custom roles and publishing skills.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ostwin: command not found` | Open a new terminal or `source ~/.zshrc` |
| `opencode not found` | `brew install anomalyco/tap/opencode` |
| Python version too old | `uv python install 3.12` or `brew install python@3.12` |
| Dashboard not starting | Check port is free: `lsof -i :3366` |
| `pwsh` not found (Windows) | `winget install Microsoft.PowerShell` |
| Execution policy error (Windows) | `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy Bypass` |

## License

[MIT](.agents/memory/LICENSE) © 2025 AGI Research
