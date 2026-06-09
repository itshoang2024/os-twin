---
name: implement-epic
description: Use this skill to break an epic into sub-tasks, implement them sequentially, write tests, and deliver a structured done report.
tags: [engineer, implementation, epic, planning]

---

# implement-epic

## Overview

This skill guides you through the full epic implementation lifecycle — from reading a brief to delivering a tested, documented result. It covers task decomposition, sequential implementation, testing, and reporting.

## When to Use

- When assigned an **EPIC-XXX** in a war-room
- When a `task` message arrives with an epic-level brief
- When restarting an epic after a `plan-revision` by the architect

## Artifacts Produced

| Artifact | Format | Location |
|----------|--------|----------|
| Task breakdown | Markdown | `<war-room>/TASKS.md` |
| Source code | Various | Project working directory |
| Tests | Various | Project test directory |
| Done report | Markdown | Channel `done` message |

## Instructions

### 1. Read the Brief

Read `brief.md` from the war-room directory. Extract:
- **Objective** — What the epic delivers
- **Scope** — In-scope vs out-of-scope
- **Acceptance criteria** — How QA will verify the result
- **Skills / tools** — Any specific technologies required

### 2. Decompose into TASKS.md

Create `TASKS.md` in the war-room directory:

```markdown
# Tasks for EPIC-XXX

- [ ] TASK-001 — <short title>
  - AC: <measurable acceptance criterion>
- [ ] TASK-002 — <short title>
  - AC: <measurable acceptance criterion>
- [ ] TASK-003 — Write unit tests
  - AC: ≥80% coverage, tests both happy path and error cases
- [ ] TASK-004 — Integration testing
  - AC: End-to-end workflow completes without errors
```

**Rules:**
- Each sub-task must be independently testable
- Always include at least one testing sub-task
- Order tasks by dependency (foundations first)
- Keep sub-task count between 3–8

### 3. Implement Sequentially

For each sub-task:
1. Implement the change in the project working directory
2. Write or update tests for the change
3. Run the test suite — ensure no regressions
4. Check off in TASKS.md: `- [x] TASK-001 — ...`
5. Report progress: `report_progress(percent, message)`

### 4. Self-Verify Before Reporting

Before posting `done`, run through this checklist:

- [ ] All TASKS.md items are checked off
- [ ] All tests pass (`unit-tests` quality gate)
- [ ] Code lints cleanly (`lint-clean` quality gate)
- [ ] No hardcoded secrets or credentials (`no-hardcoded-secrets` gate)
- [ ] Code follows existing project conventions

### 5. Post the Done Report

Post a `done` message to the channel with:

```markdown
## Epic Summary — EPIC-XXX

### What Was Delivered
<high-level summary of the complete feature>

### Completed Tasks
- [x] TASK-001 — <title>
- [x] TASK-002 — <title>
...

### Files Modified/Created
- `path/to/file1.py` — <what changed>
- `path/to/file2.py` — <what changed>

### How to Test
1. <step-by-step testing instructions>
2. <expected results>
```

## Verification

After completing the epic:
1. Every TASKS.md item has a corresponding code change
2. Test suite passes with no regressions
3. Done message includes files list and testing instructions
4. No TASKS.md items are left unchecked
