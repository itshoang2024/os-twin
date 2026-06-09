---
name: review-task
description: Use this skill to review a single task — read the done message, check code changes, validate acceptance criteria, and post a verdict.
tags: [qa, review, task, verification]

---

# review-task

## Overview

This skill guides QA through a single-task review. It is lighter-weight than an epic review — focused on verifying one atomic unit of work against its acceptance criteria.

## When to Use

- When assigned to review a **TASK-XXX** in a war-room
- When a `review` message arrives from the manager referencing a single task
- When re-reviewing a task after engineer submits a fix

## Artifacts Produced

| Artifact | Format | Location |
|----------|--------|----------|
| QA report | Markdown | `<war-room>/qa-report.md` |
| Verdict message | Channel | `pass` / `fail` / `escalate` |

## Instructions

### 1. Read the Done Message

From the channel, read the engineer's `done` message. Extract:
- **Summary** — what was implemented
- **Files modified/created** — scope of changes
- **Testing instructions** — how to verify

### 2. Review Code Changes

For each modified file:
1. Read the changes and understand the intent
2. Verify correctness against the task requirements
3. Check for code quality issues:
   - [ ] No compilation/parse errors
   - [ ] Follows project conventions
   - [ ] Edge cases handled
   - [ ] No hardcoded secrets

### 3. Run Tests

Execute the project's test suite:
- [ ] All existing tests pass
- [ ] New tests exist for new functionality
- [ ] No regressions introduced

### 4. Validate Acceptance Criteria

Check each acceptance criterion from the original task:

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | <criterion> | ✅ / ❌ | <evidence> |

### 5. Post Verdict

**On DONE:**
```markdown
## QA Verdict — TASK-XXX: DONE ✅
- All acceptance criteria met
- Tests: <N> run, <N> passed
- Suggestions: <non-blocking improvements, if any>
```

**On FAIL:**
```markdown
## QA Verdict — TASK-XXX: FAIL ❌
1. **[SEVERITY]** <issue>
   - Expected: <what should happen>
   - Actual: <what happens>
   - Suggested fix: <hint>
```

**On ESCALATE:**
```markdown
## QA Verdict — TASK-XXX: ESCALATE ⚠️
- Classification: DESIGN | SCOPE | REQUIREMENTS
- Reason: <why the engineer cannot fix this alone>
- Suggested path: <recommendation>
```

## Verification

After posting verdict:
1. Every acceptance criterion has a verdict with evidence
2. Issues (if any) are numbered with severity and suggested fix
3. Verdict message posted to the channel
