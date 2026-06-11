---
title: Skill Schema
description: Reference for SKILL.md files, frontmatter, resolution, and skill_refs merging.
sidebar:
  order: 5
---

Skills are reusable instruction sets that augment role behavior. Each skill is a directory containing a `SKILL.md` file with YAML frontmatter and markdown instructions.

## Directory Structure

Skills are organized by scope:

```
.agents/skills/
├── global/                    # Available to all roles
│   ├── war-room-communication/
│   │   └── SKILL.md
│   ├── create-lifecycle/
│   │   └── SKILL.md
│   └── lang/
│       └── SKILL.md
└── roles/                     # Role-specific skills
    ├── engineer/
    │   ├── implement-epic/
    │   │   └── SKILL.md
    │   └── fix-from-qa/
    │       └── SKILL.md
    ├── qa/
    │   └── review-epic/
    │       └── SKILL.md
    └── manager/
        └── assign-epic/
            └── SKILL.md
```

## SKILL.md Schema

### Frontmatter

```yaml
---
name: implement-epic
description: "Break an epic into sub-tasks, implement them sequentially, write tests, and deliver a done report."
tags: [engineer, implementation, epic]
trust_level: core
---
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string` | Yes | Unique skill identifier |
| `description` | `string` | Yes | One-line description shown in discovery |
| `tags` | `string[]` | Yes | Discovery tags for search and matching |
| `trust_level` | `string` | No | `"core"`, `"community"`, or `"experimental"` |

### Body Content

The body after frontmatter is standard markdown containing:

- **Overview** — When and why to use this skill
- **When to Use** — Trigger conditions
- **Workflow** — Step-by-step instructions
- **Examples** — Concrete usage patterns
- **References** — Links to related skills or docs

## Skill Resolution

When an agent session starts, skills are resolved from multiple sources and merged in order:

1. **Global skills** — `.agents/skills/global/` (available to all roles)
2. **Role skills** — `.agents/skills/roles/{role-name}/` (role-specific)
3. **Config skill_refs** — Listed in `.agents/config.json` under the role
4. **Room skill_refs** — Listed in the war-room `config.json`
5. **Role definition skill_refs** — Listed in `role.json`

## skill_refs Merge

The `skill_refs` array can appear in three places. They merge additively:

```json
// .agents/config.json (role-level)
{
  "engineer": {
    "skill_refs": ["web-research"]
  }
}

// role.json (definition-level)
{
  "skill_refs": ["war-room-communication"]
}

// war-room config.json (room-level)
{
  "skill_refs": ["detect-ui", "unity-dev-principles"]
}
```

Final merged set for the agent: `["web-research", "war-room-communication", "detect-ui", "unity-dev-principles"]`.

Duplicates are de-duplicated. Order does not matter.

## Registry Integration

The `registry.json` contains an `available` array under `skills`:

```json
{
  "skills": {
    "skills_dir": "skills/",
    "auto_discover": true,
    "required_files": ["SKILL.md"],
    "available": [
      {
        "name": "lang",
        "description": "Fetch LangGraph documentation",
        "path": "skills/global/lang/SKILL.md",
        "tags": ["engineer", "python"],
        "trust_level": "core"
      }
    ]
  }
}
```

When `auto_discover` is `true`, the system scans `skills_dir` for any directory containing a `SKILL.md` file, regardless of whether it appears in `available`.

## ClawHub Skills

Skills installed from ClawHub are placed in the standard directory structure. The `clawhub-install.sh` script handles downloading and placing them:

```bash
.agents/clawhub-install.sh <skill-name>
```

Installed skills include a `.clawhub-meta.json` sidecar:

```json
{
  "source": "clawhub",
  "version": "1.2.0",
  "installed_at": "2026-04-01T12:00:00Z",
  "checksum": "sha256:abc123..."
}
```

## Skill Sub-Resources

Skills can bundle additional files alongside `SKILL.md`:

```
skills/roles/engineer/implement-epic/
├── SKILL.md
├── references/
│   ├── template.md
│   └── checklist.md
└── scripts/
    └── validate.py
```

These are referenced from within the SKILL.md body using relative paths.

## Writing Skills

A well-structured skill has:

1. Clear trigger conditions ("Use when...")
2. Step-by-step workflow
3. Input/output expectations
4. Error handling guidance
5. Examples with realistic data

:::tip
Tag skills with the roles that should discover them. The `tags` array drives both search and capability matching.
:::

:::caution
Skills with `trust_level: experimental` are not loaded by default. Set `preflight_skill_check: "skip"` in config to allow them.
:::

:::note
Skill content is injected into the agent's system prompt. Keep skills focused and under 4KB to avoid prompt bloat.
:::
