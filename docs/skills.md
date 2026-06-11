# Pillar 2: Skills as the Atomic Unit of Expertise

## Core Concept

A skill is a `SKILL.md` file with YAML frontmatter. It is the atomic unit of
expertise in OSTwin -- a self-contained instruction set that gives an agent
knowledge about a specific domain or workflow.

Skills are **decoupled from roles**. The same skill can be used by multiple
roles, and a role's expertise can be changed by editing a JSON file -- no code
changes required.

Critically, skills are **not baked into the system prompt**. They are discovered
at runtime and copied into each war-room's `skills/` directory, keeping the
system prompt lean.

## SKILL.md Format

```markdown
---
name: implement-epic
description: "Break an epic into sub-tasks, implement them, write tests"
tags: [engineering, implementation]
trust_level: core
version: 1.0.0
category: Engineering
applicable_roles: [engineer]
enabled: true
platform: [macos, linux, windows]
---

# Implement Epic

## Workflow

1. Read the brief.md and TASKS.md
2. Break the epic into sub-tasks
3. Implement each task sequentially
4. Write tests for each component
5. Post a structured done report

## Rules

- Always run tests before marking done
- Never commit secrets
...
```

## Skill Directory Layout

```
.agents/skills/
  global/                          # Available to ALL roles
    create-architecture/SKILL.md
    create-lifecycle/SKILL.md
    shared-memory/SKILL.md
    war-room-communication/SKILL.md
  roles/                           # Scoped to specific roles
    engineer/
      implement-epic/SKILL.md
      refactor-code/SKILL.md
      write-tests/SKILL.md
      shopify-apps/SKILL.md
    architect/
      create-role/SKILL.md
      design-review/SKILL.md
      write-adr/SKILL.md
    qa/
      review-epic/SKILL.md
      review-task/SKILL.md
      security-review/SKILL.md
    manager/
      assign-epic/SKILL.md
      triage-failure/SKILL.md
    game-engineer/
      develop-unity-ui/SKILL.md    # Has 64 sub-skills in references/
      build-ui/SKILL.md
      build-anim/SKILL.md
    ...
```

## Runtime Skill Resolution

`Resolve-RoleSkills.ps1` resolves skills through a 3-tier chain:

| Tier | Source | Description |
|------|--------|-------------|
| 1 | Registry lookup | `~/.ostwin/roles/registry.json` -> `skills.available[].path` |
| 2 | Local fallback | `skills/{ref}/SKILL.md` relative to `.agents/skills/` |
| 3 | Dashboard API | `GET /api/skills/search?q={ref}&role={roleName}` -- fetched skills are cached to disk for offline use |

Two gates filter at resolution time:
- **Platform gate**: Skips skills with `platform: [windows]` when running on macOS, etc.
- **Enabled gate**: Skips skills with `enabled: false`

## How Skills Reach the Agent

This is the critical design decision. Skills are NOT injected into the system
prompt. Instead:

1. `Resolve-RoleSkills.ps1` resolves all `skill_refs` for the role
2. Each skill directory is **copied** into `{room_dir}/skills/{skill_name}/`
3. The env var `AGENT_OS_SKILLS_DIR={room_dir}/skills/` is set
4. The agent CLI discovers available skills from that directory at runtime
5. The system prompt stays lean -- only identity, capabilities, quality gates,
   and the task brief

This means:
- The same engineer role becomes a "frontend engineer" or a "Unity game engineer"
  by swapping `skill_refs` in the plan's `roles.json`
- Skills are isolated per war-room -- two rooms running the same role can have
  different skill sets
- The system prompt token budget is not wasted on skill content the agent may
  never need

## Linking Skills to Roles

Skills are linked via the `skill_refs` array at multiple levels:

| Level | File | Priority |
|-------|------|----------|
| Role default | `role.json` | Lowest |
| Engine override | `.agents/config.json` | Medium |
| Per-plan override | `{plan_id}.roles.json` | Highest |

The `skill_refs` and `disabled_skills` arrays are **merged as unions** across
all layers, not replaced.

Example from the audit role:
```json
{
  "skill_refs": [
    "scope-investigation",
    "analytical-lenses",
    "question-library",
    "structure-data-request",
    "validate-output",
    "risk-decision"
  ]
}
```

## Skill Marketplace (ClawHub)

The dashboard provides a skill marketplace:
- `GET /api/skills/clawhub-search` -- search for skills
- `POST /api/skills/clawhub-install` -- install to `~/.ostwin/.agents/skills/`
- `POST /api/skills/{name}/fork` -- fork an existing skill for customization
- Skills support versioning via `.versions/v{version}.md` snapshots

## Skill Search Directories

The system searches for skills across multiple locations (from `api_utils.py`):

```
~/.ostwin/.agents/skills/     # Global user-level
~/.ostwin/skills/global/
~/.ostwin/skills/roles/
.agents/skills/                # Project-level
.agents/skills/
.deepagents/skills/            # Legacy
~/.deepagents/agent/skills/    # Legacy
```

## Key Source Files

| File | Purpose |
|------|---------|
| `.agents/roles/_base/Resolve-RoleSkills.ps1` | 3-tier skill resolution with platform/enabled gating |
| `.agents/roles/_base/Invoke-Agent.ps1` | Copies skills to room, sets `AGENT_OS_SKILLS_DIR` |
| `.agents/skills/` | Skill pack directory |
| `.agents/bin/skills/load.py` | Python skill loader/resolver |
| `.agents/bin/skills/commands.py` | Skill CLI commands |
| `dashboard/routes/skills.py` | REST API for skill CRUD, search, marketplace |
| `dashboard/api_utils.py` | Skill discovery helpers, `SKILLS_DIRS` |
