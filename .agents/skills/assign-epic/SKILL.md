---
name: assign-epic
description: Use this skill to assign epics from PLAN.md to war-rooms -- create rooms, assign creative specialist roles, and write briefs."
tags: [manager, orchestration, assignment, war-room]

---

# assign-epic

## Overview

This skill guides the manager through reading a plan, creating war-rooms for each epic/task, and assigning the most appropriate specialist role. The manager should be **creative** with role assignment -- inventing the ideal specialist for each piece of work.

## When to Use

- When starting execution of a new plan (PLAN.md)
- When a new epic or task is added to an existing plan
- When reassigning work after a `plan-revision`

## Artifacts Produced

| Artifact | Format | Location |
|----------|--------|----------|
| War-room directories | Directory | `<plan-dir>/.war-rooms/<room-id>/` |
| Briefs | Markdown | `<war-room>/brief.md` |
| Room config | JSON | `<war-room>/config.json` |

## Instructions

### 1. Read the Plan

Parse `PLAN.md` to extract all epics and tasks:

```markdown
## Epic: EPIC-001 -- <title>
Objective: <what to deliver>
Skills: <required capabilities>
Acceptance Criteria:
- <criterion 1>
- <criterion 2>
```

For each item, note:
- **Identifier** -- EPIC-XXX or TASK-XXX
- **Objective** -- what it delivers
- **Skills** -- technologies and domains needed
- **Dependencies** -- which items must complete first

### 2. Design the Role Assignment

For each epic/task, choose the **most specific** role:

| Epic | Objective | Best Role | Rationale |
|------|-----------|-----------|-----------|
| EPIC-001 | Build REST API | `api-engineer` | Needs HTTP, auth, validation expertise |
| EPIC-002 | Design database schema | `database-architect` | Schema design, migration planning |
| EPIC-003 | Security audit | `security-engineer` | OWASP, vulnerability scanning |

**Rules:**
- Don't default to `engineer` -- invent the ideal specialist
- The role name should describe the expert (e.g., `performance-engineer`, `data-pipeline-engineer`)
- Define clear `Objective:` and `Skills:` per epic
- Check if the role exists in `registry.json`; if not, use the `create-role` skill first

### 3. Create War-Rooms

For each epic/task:

```bash
# Create the war-room using the ostwin CLI
ostwin war-room create \
  --plan <plan-id> \
  --epic <EPIC-XXX> \
  --role <role-name> \
  --title "<epic title>"
```

Or create the directory structure manually:

```
.war-rooms/<room-id>/
 brief.md          # What to do
 config.json       # Room configuration
 status.json       # Current state
 artifacts/        # Work artifacts
```

### 4. Write the Brief

Create `<war-room>/brief.md`:

```markdown
# Brief -- <EPIC/TASK-XXX>

## Objective
<clear, actionable description of what to deliver>

## Scope
### In Scope
- <deliverable 1>
- <deliverable 2>

### Out of Scope
- <exclusion 1>

## Acceptance Criteria
- [ ] <measurable criterion 1>
- [ ] <measurable criterion 2>
- [ ] <measurable criterion 3>

## Skills Required
<technologies, frameworks, domains>

## Context
<any background information, related work, or constraints>

## References
- <link to relevant docs, APIs, or existing code>
```

### 5. Configure the Room

Create `<war-room>/config.json`:

```json
{
  "epic": "<EPIC-XXX>",
  "role": "<role-name>",
  "model": "<model-name>",
  "skill_refs": [],
  "max_retries": 3,
  "timeout": 600,
  "dependencies": ["<room-id-of-dependency>"]
}
```

Run `discover-skills` to populate `skill_refs`.

### 6. Post Assignment

Post a `task` message to the war-room channel:

```
Assigning EPIC-XXX to <role-name>.
Brief: <war-room>/brief.md
Config: <war-room>/config.json
```

Respect the `max_concurrent_rooms` limit -- queue excess rooms.

## Verification

After assigning epics:
1. Every epic/task in PLAN.md has a corresponding war-room
2. Each war-room has `brief.md` and `config.json`
3. Roles are creative and specific (not all defaulting to `engineer`)
4. Dependencies between rooms are correctly specified
5. Concurrent room count does not exceed the limit
