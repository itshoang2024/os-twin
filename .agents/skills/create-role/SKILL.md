---
name: create-role
description: Use this skill to scaffold a new agent role — generates role.json, ROLE.md, and registers the role in registry.json.
tags: [architect, manager, scaffolding]

---

# create-role

## Overview

This skill walks you through creating a new agent role for the Ostwin war-room system. A role defines **who** the agent is, what it can do, and the prompt that shapes its behaviour.

## Install Location

New roles are created under `contributes/roles/` at the project root. This directory is for community and dynamically-created roles. Built-in roles live under `.agents/roles/` and should not be modified directly.

At install time, `install.sh` copies contributed roles into `~/.ostwin/.agents/roles/` and publishes the agent definition (`.md` file) to `~/.config/opencode/agents/<role-name>.md` so the OpenCode CLI can discover and invoke the role.

> **Important:** Always create new roles in `contributes/roles/<role-name>/`. Register them in `.agents/roles/registry.json`. After install, the agent definition will be published to `~/.config/opencode/agents/`.

## Role Anatomy

Every role folder contains:

| File | Required | Purpose |
|------|----------|---------|
| `role.json` | ✅ | Machine-readable definition (capabilities, skills, model, timeout) |
| `ROLE.md` | ✅ | System prompt — the agent reads this to understand its mission |
| `Start-<Role>.ps1` | Optional | PowerShell runner script for orchestration |

The role must also be registered in `.agents/roles/registry.json`.

## Instructions

### 1. Choose a Role Name

Pick a short, lowercase, hyphenated name that describes the specialist:

```
Examples: security-auditor, database-architect, performance-engineer,
          technical-writer, data-pipeline-engineer, devops-engineer
```

### 2. Create `role.json`

Create `contributes/roles/<role-name>/role.json` using this template:

```json
{
  "name": "<role-name>",
  "description": "<one-line description of the role>",
  "capabilities": [
    "<capability-1>",
    "<capability-2>"
  ],
  "prompt_file": "ROLE.md",
  "quality_gates": [
    "<gate-1>",
    "<gate-2>"
  ],
  "skill_refs": [
    "<skill-ref-1>",
    "<skill-ref-2>"
  ],
  "cli": "agent",
  "instance_type": "worker",
  "model": "google-vertex/gemini-3-flash-preview",
  "timeout": 600
}
```

**Field guide:**

| Field | Description |
|-------|-------------|
| `name` | Must match the folder name |
| `description` | One line — shown in logs and the registry |
| `capabilities` | What the agent *can do* (e.g. `code-generation`, `security-review`, `documentation`) |
| `quality_gates` | Checks that must pass before work is accepted (e.g. `unit-tests`, `lint-clean`) |
| `skill_refs` | Skill references this role can use (e.g. `implement-epic`, `write-tests`, `code-review`). Resolved by `Resolve-RoleSkills.ps1` at runtime. |
| `cli` | CLI engine to use (`agent` for OpenCode). |
| `instance_type` | Instance type for war-room assignment (`worker` or `singleton`). Default: `worker`. |
| `model` | LLM model to use. Use `google-vertex/gemini-3-flash-preview` for speed, `google-vertex/gemini-3.1-pro-preview` for complex reasoning. |
| `timeout` | Max seconds the agent can run per invocation (default: 600). |

### 3. Create `ROLE.md`

Create `contributes/roles/<role-name>/ROLE.md` using this template:

```markdown
# <Role Display Name>

You are a <role description> working within a team of AI agents.

## Your Responsibilities

1. **<Responsibility 1>** — <brief explanation>
2. **<Responsibility 2>** — <brief explanation>
3. **<Responsibility 3>** — <brief explanation>

## Guidelines

- <Guideline 1>
- <Guideline 2>
- <Guideline 3>

## Output Format

When delivering work:
1. Summary of changes made
2. Files modified/created
3. How to test the changes

When reviewing:
1. <Review criterion 1>
2. <Review criterion 2>
3. Suggested improvements

## Quality Standards

- Code must compile/parse without errors
- Include inline comments for non-obvious logic
- Follow existing project conventions and patterns
- Handle edge cases mentioned in the task description
```

### 4. Register in `registry.json`

Add an entry to the `roles` array in `.agents/roles/registry.json`:

```json
{
  "name": "<role-name>",
  "description": "<same description as role.json>",
  "runner": "roles/<role-name>/Start-<RolePascalCase>.ps1",
  "definition": "roles/<role-name>/role.json",
  "prompt": "roles/<role-name>/ROLE.md",
  "default_assignment": false,
  "instance_support": false,
  "supported_task_types": ["task", "epic"],
  "capabilities": ["<cap-1>", "<cap-2>"],
  "quality_gates": ["<gate-1>", "<gate-2>"],
  "default_model": "google-vertex/gemini-3-flash-preview"
}
```

> **Note:** Set `instance_support: true` if the role supports multiple concurrent instances (e.g. `engineer:fe`, `engineer:be`). Most roles should use `false`.

### 5. Publish Agent Definition to OpenCode

Copy the `ROLE.md` to `~/.config/opencode/agents/<role-name>.md` so the OpenCode CLI can discover and invoke the role:

```bash
mkdir -p ~/.config/opencode/agents
cp contributes/roles/<role-name>/ROLE.md ~/.config/opencode/agents/<role-name>.md
```

If `sync-opencode-global.sh` is available, you can run it instead to sync all roles at once:

```bash
bash ~/.ostwin/.agents/scripts/sync-opencode-global.sh
```

Alternatively, re-run `install.sh` which copies contributed roles to `~/.ostwin/.agents/roles/` and syncs agent definitions to `~/.config/opencode/agents/` automatically.

> **Note:** `role.json` stays in `contributes/roles/<role-name>/` (project source) and gets copied to `~/.ostwin/.agents/roles/<role-name>/` at install time. Only the `.md` agent definition is published to `~/.config/opencode/agents/`. OpenCode uses the `.md` file to understand the agent's identity and prompt; Ostwin uses `role.json` for capabilities, MCP grants, model binding, and timeout.

### 6. (Optional) Scaffold a Runner Script

If the role needs custom orchestration logic, create `Start-<RolePascalCase>.ps1`. For most roles, the base runner at `.agents/roles/_base/Invoke-Agent.ps1` is sufficient and no custom script is needed.

## Verification

After creating the role, verify:

1. `role.json` is valid JSON — run: `cat contributes/roles/<role-name>/role.json | python3 -m json.tool`
2. `ROLE.md` exists and has a top-level `#` heading
3. `.agents/roles/registry.json` is still valid JSON after your edit
4. The role folder appears under `contributes/roles/`
5. After install, the agent definition exists at `~/.config/opencode/agents/<role-name>.md`
