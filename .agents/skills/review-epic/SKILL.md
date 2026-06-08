---
name: review-epic
description: Use this skill to perform a full epic review — verify TASKS.md, cross-check code changes, run the test suite, and post a structured verdict.
tags: [qa, review, epic, verification]

---

# review-epic

## Overview

This skill guides QA through a complete epic review. Unlike a single-task review, an epic review assesses the **holistic feature delivery** — verifying that all sub-tasks were implemented, work together cohesively, and satisfy the original epic brief.

## When to Use

- When assigned to review an **EPIC-XXX** in a war-room
- When a `review` message arrives from the manager referencing an epic
- When re-reviewing after the engineer submits fixes for a previously failed epic

## Artifacts Produced

| Artifact | Format | Location |
|----------|--------|----------|
| QA report | Markdown | `<war-room>/qa-report.md` |
| Verdict message | Channel | `pass` / `fail` / `escalate` |

## Instructions

### 1. Gather Context

Read these artifacts in order:
1. **`brief.md`** — the original epic description, scope, and acceptance criteria
2. **Engineer's `done` message** — summary of what was delivered
3. **`TASKS.md`** — the sub-task breakdown and completion status

### 2. Verify TASKS.md Completeness

- [ ] TASKS.md exists in the war-room
- [ ] All sub-tasks are checked off (`[x]`)
- [ ] Sub-task descriptions match what was actually implemented
- [ ] No obvious gaps between the epic brief and the task list

### 3. Review Code Changes

For each changed file:
1. **Read the diff** — understand what changed
2. **Check correctness** — does the logic match the acceptance criteria?
3. **Check conventions** — does it follow project patterns?
4. **Check edge cases** — are boundary conditions handled?
5. **Check security** — no hardcoded secrets, no injection vectors

### 4. Verify Code is Runnable (CRITICAL)

**Load the `runnable-verify` skill first.** This ensures the codebase can actually run before testing.

```
/runnable-verify
```

This will:
1. Audit dependencies for conflicts
2. Clean install from lockfile
3. Build the application
4. **Attempt to start the application** (runtime verification)
5. Generate fix instructions if anything fails

**If runnable verification FAILS:**
- Stop and post a `fail` message with the fix instructions
- Do NOT proceed to test suite until code is runnable
- The engineer must fix dependency/runtime issues first

**If runnable verification PASSES:**
- Include results in the QA report
- Proceed to test suite

### 5. Run the Test Suite

```bash
# Run the full test suite
<project-specific test command>
```

Verify:
- [ ] All existing tests pass
- [ ] New tests exist for new functionality
- [ ] Tests cover both happy path and error cases
- [ ] Coverage meets the ≥80% threshold for new code

### 6. Validate Acceptance Criteria

For **each** acceptance criterion in `brief.md`:

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | <criterion text> | ✅ / ❌ | <how you verified — command output, test name, manual check> |
| 2 | <criterion text> | ✅ / ❌ | <evidence> |

### 7. Write the QA Report

Create `<war-room>/qa-report.md`:

```markdown
# QA Report — EPIC-XXX

> Reviewer: qa
> Date: <YYYY-MM-DD>
> Verdict: DONE / FAIL / ESCALATE

## TASKS.md Verification
- Total sub-tasks: <N>
- Completed: <N>
- Missing/incomplete: <list or "none">

## Runnable Verification
- Ecosystem: <detected>
- Dependencies: ✅ / ❌ <issue if failed>
- Install: ✅ / ❌
- Build: ✅ / ❌
- Runtime: ✅ / ❌ <error if failed>
- Details: `<war-room>/dependency-audit.md`

## Code Review Summary
- Files reviewed: <N>
- Issues found: <N>
- <summary of findings>

## Test Results
- Tests run: <N>
- Passed: <N>
- Failed: <N>
- Coverage: <X%>

## Acceptance Criteria
| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| ... | ... | ... | ... |

## Issues (if FAIL)
1. **[CRITICAL/MAJOR/MINOR]** <issue description>
   - Expected: <what should happen>
   - Actual: <what happens>
   - Suggested fix: <hint>

## Recommendations (if DONE)
- <non-blocking suggestions for improvement>
```

### 8. Post the Verdict

- **DONE** → `post_message(type="done", body=<qa-report summary>)`
- **FAIL** → `post_message(type="fail", body=<numbered issues list>)`
- **ESCALATE** → `post_message(type="escalate", body=<classification + reasoning>)`

Use ESCALATE when:
- Requirements themselves are wrong or contradictory
- Architectural approach is fundamentally flawed
- Multiple review cycles failed to resolve the same issue

## Verification

After posting verdict:
1. `qa-report.md` exists in the war-room
2. Every acceptance criterion has a verdict and evidence
3. Issues (if any) have severity, expected/actual, and suggested fix
4. Verdict message is posted to the channel
