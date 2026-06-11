---
title: "Pillar 2: Skills as Atomic Expertise"
description: "Skills are self-contained markdown documents that give any role instant expertise. No code wiring required."
sidebar:
  order: 2
  icon: rocket
---

OSTwin's second pillar treats expertise as **portable, composable documents** rather than hard-coded tool integrations. A skill is a single `SKILL.md` file that teaches any agent how to perform a specific task.

The defining characteristic of OSTwin skills is **adaptive mode**: skills are *declared* at design time but *fulfilled* at runtime. An agent states what expertise it needs — the system finds, adapts, and loads the best available implementation when the session starts. This means a skill defined once can run across projects, platforms, tools, and even different vibe-coding environments without modification.

## SKILL.md Format

Every skill is a markdown file with YAML frontmatter followed by instructional content:

```markdown
---
name: implement-epic
description: >
  Break an epic into sub-tasks, implement them sequentially,
  write tests, and deliver a structured done report.
triggers:
  - "implement epic"
  - "build feature"
  - "start development"
requires_mcp: false
---

# Implement Epic

When assigned an epic, follow this workflow:

1. Read the brief.md and TASKS.md in the war-room
2. Break the epic into ordered sub-tasks
3. Implement each task, running tests after each
4. Post a structured done report to the channel
...
```

### Frontmatter Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string` | Yes | Unique skill identifier |
| `description` | `string` | Yes | What this skill teaches the agent |
| `triggers` | `string[]` | No | Phrases that activate this skill |
| `requires_mcp` | `bool` | No | Whether the skill needs MCP servers |
| `tags` | `string[]` | No | Discovery tags for marketplace search |
| `version` | `string` | No | Semver version for compatibility |
| `author` | `string` | No | Creator attribution |
| `dependencies` | `string[]` | No | Other skills this one requires |
| `platform` | `string[]` | No | OS constraint: `macos`, `linux`, `windows`. Missing = cross-platform. |
| `trust_level` | `string` | No | `"core"`, `"community"`, or `"experimental"`. Experimental skills are gated by default. |
| `enabled` | `bool` | No | Set `false` to disable without removing. Defaults to `true`. |
| `applicable_roles` | `string[]` | No | Roles this skill is designed for. Drives discovery matching. |

## Directory Layout

Skills are organized into two top-level categories:

```
.agents/skills/
  global/                        # Available to ALL roles
    auto-memory/SKILL.md
    war-room-communication/SKILL.md
    create-architecture/SKILL.md
    create-lifecycle/SKILL.md
    lang/SKILL.md
  roles/                         # Scoped to specific roles
    engineer/
      implement-epic/SKILL.md
      fix-from-qa/SKILL.md
      write-tests/SKILL.md
      refactor-code/SKILL.md
    qa/
      review-epic/SKILL.md
      review-task/SKILL.md
      build-verify/SKILL.md
    architect/
      create-role/SKILL.md
      design-review/SKILL.md
      write-adr/SKILL.md
    manager/
      assign-epic/SKILL.md
      triage-failure/SKILL.md
      discover-skills/SKILL.md
```

**Global skills** are injected into every agent session regardless of role. **Role-scoped skills** are only available when that specific role is invoked.

## How Skills Reach the Agent

Skills travel from disk to prompt through a 5-step pipeline. This pipeline is the delivery mechanism for adaptive mode — it ensures that skills declared as needs are fulfilled and available when the agent actually requires them:

### Step 1: Resolve

The runner collects skill references from three sources (union-merged). This is Phase 1 of the adaptive pipeline — the config-driven baseline:

- Role-level `skill_refs` in `role.json`
- Room-level `skill_refs` in the war-room's `config.json`
- Plan-level `skill_refs` in the plan metadata

### Step 2: Copy

Resolved skills are staged into the war-room's working directory so the agent has local access during execution.

### Step 3: Environment Variable

The skill manifest is written to an environment variable that the LLM client reads at session start, providing a table of available skills with descriptions.

### Step 4: Discover

The agent receives a **lean skill index** -- just names and one-line descriptions. This keeps base prompt size small while letting the agent know what expertise is available.

### Step 5: Load on Demand

When the agent recognizes it needs a skill, it calls the `skill` tool with the skill name. The full `SKILL.md` content is injected into the conversation at that point.

:::tip[Token Efficiency]
The lean-prompt pattern means an agent with access to 50 skills only pays ~2K tokens for the index, not 50K+ tokens for all skill content upfront. Skills are loaded only when actually needed.
:::

## 3-Tier Runtime Resolution

When the agent requests a skill by name, resolution follows three tiers. This is the final stage of adaptive fulfillment — where a declared skill need finds its concrete implementation:

| Priority | Source | Example Path |
|----------|--------|-------------|
| 1 | War-room local | `.agents/war-rooms/room-042/skills/{name}/SKILL.md` |
| 2 | Project-level | `.agents/skills/roles/{role}/{name}/SKILL.md` |
| 3 | User-global | `~/.agents/skills/{name}/SKILL.md` |

The first match wins. This allows room-specific skill overrides without modifying project-level defaults.

## Linking via skill_refs

Skills are linked to agents through `skill_refs` arrays at three levels:

```json
// role.json -- role-level defaults
{ "skill_refs": ["implement-epic", "write-tests"] }

// config.json -- war-room override
{ "skill_refs": ["fix-from-qa", "security-review"] }

// plan metadata -- plan-wide additions
{ "skill_refs": ["create-architecture"] }
```

At invocation time, all three arrays are **union-merged** -- duplicates are removed, and the agent receives the combined set. This means a plan can grant temporary skills to all rooms without modifying role configs.

## Adaptive Mode

The core innovation of OSTwin skills is **adaptive mode**: the separation of *declaring what expertise an agent needs* from *fulfilling that expertise at runtime*. This is what makes skills portable across tools, projects, and environments without re-wiring.

### The Problem with Static Skills

Traditional agent systems bind capabilities at design time. An agent configured with "Run Jest tests" knows exactly one test runner, one way. If the project uses pytest instead, the agent breaks — you must edit its configuration or rewrite its prompts.

This static binding creates three problems:

1. **Fragility** — Changing the tool, platform, or project structure breaks the agent's capabilities
2. **Duplication** — You need separate agent configs for each environment variant
3. **Inflexibility** — The agent cannot adapt when it encounters an unfamiliar context at runtime

### Declare Needs, Fulfill at Runtime

Adaptive mode inverts the static model. Instead of wiring specific implementations at design time, you declare **what the agent needs to know** and let the runtime fulfill it:

```
Design time:  role.json declares skill_refs: ["build-verify"]
                          ↓
Runtime:       Resolve-RoleSkills.ps1 finds build-verify/SKILL.md
                          ↓
               Platform gate checks: does this skill match the current OS?
                          ↓
               Skill content is staged into the war-room
                          ↓
               Agent discovers "build-verify" in the lean index
                          ↓
               Agent calls skill tool → full SKILL.md injected on demand
```

The role never says *how* to verify a build — only that it *needs* build-verification expertise. The skill document itself adapts to the environment it finds at runtime.

### Skill Contracts

Every `SKILL.md` implicitly defines a **skill contract** — a declaration of what the skill provides and what it expects. This contract is expressed through frontmatter fields, not code:

```yaml
---
name: build-verify
description: "Install project dependencies and build the application."
platform: []               # Empty = works everywhere
requires_mcp: false         # No MCP servers needed
dependencies: []            # No prerequisite skills
applicable_roles: [engineer, qa]
---
```

The contract says: *"Given any project, I can detect its type, install dependencies, and run the build. I don't need MCP. I work on any platform."*

The skill body then implements this contract with adaptive logic:

```markdown
# Build Verify

Detect the project type and run the appropriate build:

1. If `package.json` exists → `npm ci && npm run build`
2. If `pom.xml` exists → `mvn verify`
3. If `Cargo.toml` exists → `cargo build --release`
4. If `*.sln` exists → `dotnet build`
5. Otherwise → scan for Makefile, build.gradle, pyproject.toml...
```

The contract is the *what*; the body is the *how*. The same `build-verify` skill works across Node.js, Java, Rust, .NET, and Python projects without any configuration change. The agent doesn't need to know which build system it will encounter — the skill adapts.

### The Adaptive Resolution Pipeline

When an agent session starts, skills are resolved through a **3-phase adaptive pipeline** that goes beyond simple file lookup:

#### Phase 1: Config-Driven Resolution

The runner collects skill references from a priority cascade (first non-empty source wins):

| Priority | Source | Scope |
|----------|--------|-------|
| 1 | Plan-roles config (`{plan_id}.roles.json`) | Plan-wide overrides |
| 2 | Home role.json (`~/.ostwin/roles/{role}/role.json`) | User-level defaults |
| 3 | Local role.json (`.agents/roles/{role}/role.json`) | Project-level defaults |

This means a plan can temporarily swap out a role's entire skill set without modifying any config files — the original role definition stays untouched.

#### Phase 2: Task-Aware Discovery (Adaptive)

This is where adaptive mode truly shines. After Phase 1 establishes the baseline, the system **reads the actual task** the agent will work on and discovers additional skills it may need:

**Phase 2a — Local keyword matching:**

1. Extracts keywords from the war-room's `brief.md` + `TASKS.md`
2. Scans all local `SKILL.md` frontmatter (name, description, tags) for matches
3. Scores by word overlap + bigram matching (bigrams get a +10 bonus)
4. Injects up to 5 additional skill refs not already in Phase 1

This means if your task mentions "security review" and a `security-review` skill exists locally, it gets discovered and added automatically — even if no one explicitly listed it in `skill_refs`.

**Phase 2b — Remote API search:**

When a dashboard API key is available, the system sends task context to the skill search endpoint and merges up to 5 more skill refs from the remote index. This allows a running agent to discover and load skills that weren't installed locally when the session started.

#### Phase 3: Multi-Strategy Resolution

For each skill ref, resolution tries multiple strategies until one succeeds:

| Strategy | Search Path | What It Does |
|----------|-------------|-------------|
| 1: Registry | `registry.json` → `skills.available[].path` | Explicit path lookup |
| 2a: Own-role | `skills/roles/{current_role}/{ref}/SKILL.md` | Role-scoped search |
| 2b: Flat | `skills/{ref}/SKILL.md` | Top-level search |
| 2c: Global | `skills/global/{ref}/SKILL.md` | Cross-role search |
| 2d: Cross-role | `skills/roles/*/{ref}/SKILL.md` | Wildcard search across all roles |
| 3: Backend | Dashboard API → download to local disk | Runtime fetch from remote |

Strategy 3 is the **runtime fulfillment** mechanism: when a skill isn't found anywhere on disk, the system downloads it from the dashboard API, writes it to the local skill directory, and stages it for the agent. The skill materializes on demand — no pre-installation required.

### Platform and Trust Gating

Before any skill reaches the agent, two gate functions filter the resolved set:

- **Platform gate** (`Test-SkillPlatform`) — Checks the `platform` frontmatter field against the current OS. A skill declaring `platform: [macos]` is silently skipped on Linux. Missing `platform` means cross-platform — it loads everywhere.
- **Trust gate** (`Test-SkillEnabled`) — Checks `enabled: false` and `trust_level: experimental`. Experimental skills are blocked unless the config explicitly opts in with `preflight_skill_check: "skip"`.

These gates ensure that even if a skill is discovered and resolved, it only reaches the agent if it's compatible with the runtime environment.

### Cross-Tool Compatibility

The `SKILL.md` format is deliberately tool-agnostic. It's a markdown file with YAML frontmatter — readable by any system that can parse those formats. This makes OSTwin skills compatible with any vibe-coding tool that adopts the convention:

```
OSTwin agent  ──┐
                ├──→  .agents/skills/build-verify/SKILL.md
Cursor rule   ──┤     (same file, consumed differently)
Windsurf      ──┤
ClawHub      ──┘
```

Each tool consumes the skill differently:

| Tool | How It Consumes SKILL.md |
|------|--------------------------|
| **OSTwin** | Full pipeline: resolve → stage → lean index → load on demand via `skill` tool |
| **Cursor** | Reads SKILL.md as a project rule; frontmatter maps to rule metadata |
| **Windsurf** | Imports SKILL.md as a workflow definition; triggers map to activation events |
| **ClawHub** | Hosts SKILL.md as a publishable artifact; version and trust_level drive discovery |
| **Any vibe-code tool** | Parses YAML frontmatter for metadata, markdown body for instructions |

The key insight: **the skill document is the contract, not the integration**. No tool-specific adapters, no plugin APIs, no SDK dependencies. A skill written for OSTwin works in any environment that can read markdown and YAML.

This is why adaptive mode matters at the ecosystem level. When you publish a skill to ClawHub, it isn't published *for OSTwin* — it's published as a portable expertise document that any compatible tool can consume. The skill adapts to the tool, not the other way around.

### Adaptive vs. Static: A Comparison

| Dimension | Static Skills | Adaptive Mode |
|-----------|--------------|---------------|
| **Binding time** | Design time (hardcoded in config) | Runtime (resolved per session) |
| **Discovery** | Only listed in `skill_refs` | Keyword matching + remote search + explicit refs |
| **Platform** | One config per OS | `platform` gate auto-filters |
| **Missing skills** | Agent breaks or silently lacks capability | Backend fetch materializes skills on demand |
| **Tool coupling** | Tied to one agent framework | SKILL.md format works across tools |
| **Override** | Edit the source config | Layer a higher-priority file (room > project > user) |
| **Token cost** | All skill content loaded upfront | Lean index + load on demand |

### How Adaptive Mode Enables Runtime Compatibility

Consider a concrete scenario: an engineer role is assigned to a war-room working on a Unity game project.

1. **Phase 1** resolves `skill_refs: ["implement-epic", "write-tests"]` from the role definition
2. **Phase 2a** scans the task brief, finds keywords like "Unity", "scene", "animation", and discovers `add-feature`, `add-ui`, and `Create Animation Clip` skills — even though they weren't in `skill_refs`
3. **Phase 2b** queries the remote API and finds a `unity-shader-patterns` skill published on ClawHub
4. **Phase 3** resolves all refs: `implement-epic` from the local role directory, `unity-shader-patterns` from the backend (downloaded and staged), `add-ui` from the cross-role directory
5. **Platform gate** filters out any skills that declare `platform: [linux]` since this session runs on macOS
6. **Trust gate** blocks an `experimental` skill unless the war-room config opts in

The agent now has expertise perfectly tailored to the task — discovered, resolved, and loaded entirely at runtime. No one edited the role definition. No one pre-installed the Unity skills. The system adapted.

## Skill Marketplace: ClawHub

ClawHub is the runtime fulfillment source for adaptive mode — when a skill can't be found locally, the marketplace can supply it on demand:

```powershell
# Search for skills
Invoke-SkillSearch -Query "testing" -Tags "qa,automation"

# Install from marketplace
Install-Skill -Name "performance-testing" -Source "clawhub"
```

:::note[Community Skills]
ClawHub hosts 50+ community-contributed skills spanning game development, web engineering, DevOps, documentation, and more. Skills are versioned and reviewed before publication.
:::

## Search Directories

The skill discovery system searches these directories in order (highest priority first for overrides, broadest first for discovery):

1. `.agents/war-rooms/{room}/skills/` -- Room-local overrides (highest priority for runtime adaptation)
2. `.agents/skills/global/` -- Global skills for all roles
3. `.agents/skills/roles/{current_role}/` -- Role-specific skills
4. `~/.agents/skills/` -- User-installed global skills
5. `~/.ostwin/.agents/skills/` -- ClawHub-installed skills
6. ClawHub remote index -- Online marketplace (runtime fetch, lowest priority)

## Key Source Files

| File | Purpose |
|------|---------|
| `.agents/skills/*/SKILL.md` | Skill definitions and contracts |
| `.agents/roles/_base/Resolve-RoleSkills.ps1` | 3-phase adaptive skill resolution |
| `.agents/roles/_base/Invoke-Agent.ps1` | Agent launcher + skill staging |
| `.agents/roles/_base/Build-SystemPrompt.ps1` | System prompt (skills NOT inlined) |
| `.agents/plan/Test-SkillCoverage.ps1` | Pre-flight skill coverage check |
| `.agents/bin/skills/` | ClawHub installation + CLI skill loader |
| `dashboard/routes/skills.py` | Skills API + ClawHub integration |
| `.agents/skills/global/` | Skills available to all roles |
| `.agents/skills/roles/` | Role-scoped skill directories |

:::caution[Skill Size]
Keep individual SKILL.md files under 8K tokens. If a skill exceeds this, split it into a primary skill and reference sub-documents in a `references/` subdirectory. The build-ui skill demonstrates this pattern with 64 sub-skills.
:::
