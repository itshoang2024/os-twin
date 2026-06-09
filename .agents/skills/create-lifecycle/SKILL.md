---
name: create-lifecycle
description: Use this skill to define and scaffold the lifecycle for an epic — states, quality gates, required artifacts, and escalation rules within a war-room.
tags: [architect, manager, process]

---

# create-lifecycle

## Overview

This skill helps you define and scaffold the **lifecycle** of an epic inside an Ostwin war-room. It aligns with the war-room state machine and ensures every phase has clear entry/exit criteria, required artifacts, and escalation paths.

## War-Room State Machine Reference

```
pending → developing → qa-review ─┬─► passed
              ▲                     │
              │               ┌─────┘ (on fail/escalate)
              │               ▼
              │         manager-triage
              │          ┌────┼────────┐
              │          ▼    ▼        ▼
              │      fixing  architect-review  plan-revision
              │          │        │    │            │
              └──────────┘        │    └────────────┘
                                  ▼
                                fixing
```

Terminal states: `passed`, `failed-final`

## Instructions

### 1. Create the Lifecycle Directory

```bash
mkdir -p <war-room-dir>/lifecycle
```

### 2. Generate the Lifecycle Definition

Create `<war-room>/lifecycle/lifecycle.md`:

```markdown
# Epic Lifecycle — EPIC-XXX

> Epic: <EPIC title>
> Created: <YYYY-MM-DD>
> Max Retries: 3

## Phases

### 1. Pending

**Entry:** Epic is assigned to a war-room.
**Exit criteria:** Engineer reads the brief and acknowledges the assignment.
**Artifacts required:**
- [ ] `brief.md` — Epic description, scope, and acceptance criteria

### 2. Developing

**Entry:** Engineer begins implementation.
**Exit criteria:** Engineer posts a `done` message with all deliverables.
**Artifacts required:**
- [ ] `TASKS.md` — Breakdown of sub-tasks with acceptance criteria
- [ ] Source code changes committed
- [ ] Unit tests written and passing
- [ ] `done-report.md` — Summary of changes, files modified, how to test

### 3. QA Review

**Entry:** Manager routes `done` output to QA.
**Exit criteria:** QA posts `pass`, `fail`, or `escalate`.
**Artifacts required:**
- [ ] `qa-report.md` — Verdict, evidence, specific feedback

### 4a. Passed ✅

**Entry:** QA posts `pass`.
**Artifacts required:**
- [ ] `qa-report.md` with verdict = PASS
- [ ] All acceptance criteria verified

### 4b. Manager Triage (on fail/escalate)

**Entry:** QA posts `fail` or `escalate`.
**Exit criteria:** Manager classifies and routes to the appropriate next state.
**Classification rules:**
| Category | Trigger Keywords | Next State |
|----------|-----------------|------------|
| `implementation-bug` | Default | → fixing |
| `design-issue` | architecture, design, scope, interface | → architect-review |
| `plan-gap` | specification, acceptance criteria, requirements | → plan-revision |
| Repeated failure | retries ≥ 2 AND ≥ 60% word overlap | → design-issue |

**Artifacts required:**
- [ ] `triage-context.md` — Classification, reasoning, QA feedback verbatim

### 5a. Fixing

**Entry:** Manager routes `fix` message to engineer.
**Exit criteria:** Engineer posts a new `done` message → returns to QA Review.
**Retry counter:** Incremented. If retries > 3 → `failed-final`.

### 5b. Architect Review

**Entry:** Manager routes `design-review` to architect.
**Exit criteria:** Architect posts `design-guidance` (FIX / REDESIGN / REPLAN).
**Artifacts required:**
- [ ] `design-guidance.md` — Recommendation, rationale, implementation sketch

### 5c. Plan Revision

**Entry:** Architect recommends REPLAN.
**Exit criteria:** `brief.md` is updated → developing restarts.

### 6. Failed-Final ❌

**Entry:** Max retries exceeded.
**Action:** Escalate to human operator.
**Artifacts required:**
- [ ] `escalation-report.md` — Full history, all triage contexts, recommendation
```

### 3. Generate a Phase Checklist

Create `<war-room>/lifecycle/phase-checklist.md` — a lightweight tracker agents update as they progress:

```markdown
# Phase Checklist — EPIC-XXX

| # | Phase | Status | Agent | Entered | Exited | Artifacts |
|---|-------|--------|-------|---------|--------|-----------|
| 1 | Pending | ⬜ | — | — | — | brief.md |
| 2 | Developing | ⬜ | engineer | — | — | TASKS.md, code, tests |
| 3 | QA Review | ⬜ | qa | — | — | qa-report.md |
| 4 | Passed / Triage | ⬜ | manager | — | — | triage-context.md |
| 5 | Fixing / Architect | ⬜ | — | — | — | varies |
| 6 | Release | ⬜ | manager | — | — | RELEASE.md |

**Status legend:** ⬜ not started · 🔄 in progress · ✅ done · ❌ failed
```

### 4. Generate Quality Gates

Create `<war-room>/lifecycle/quality-gates.md`:

```markdown
# Quality Gates — EPIC-XXX

## Gate Definitions

| Gate | Phase Transition | Criteria |
|------|-----------------|----------|
| **Brief Approved** | pending → developing | Brief has clear scope, acceptance criteria, and role assignment |
| **Code Complete** | developing → qa-review | All TASKS.md items checked, tests pass, done message posted |
| **QA Passed** | qa-review → passed | All acceptance criteria verified, no blocking issues |
| **Triage Complete** | qa-review → fixing/architect | Failure classified, context documented, next action clear |
| **Fix Verified** | fixing → qa-review | Fix addresses all QA feedback points, no new regressions |
| **Design Approved** | architect-review → fixing | Design guidance provided with actionable implementation steps |
| **Release Ready** | passed → released | All epics passed, RELEASE.md drafted, signoffs collected |

## Mandatory Checks Per Phase

### Before Leaving Developing
- [ ] All sub-tasks in TASKS.md are checked off
- [ ] No compilation/parse errors
- [ ] Unit test coverage ≥ 80% (if applicable)
- [ ] No hardcoded secrets or credentials

### Before Leaving QA Review
- [ ] Every acceptance criterion has a pass/fail verdict
- [ ] Evidence provided for each verdict (command output, screenshots, etc.)
- [ ] Feedback is specific and actionable (if failing)

### Before Release
- [ ] All war-rooms in `passed` state
- [ ] RELEASE.md lists all changes
- [ ] Required signoffs collected (engineer, qa, manager)
```

### 5. Generate an Escalation Runbook

Create `<war-room>/lifecycle/escalation-runbook.md`:

```markdown
# Escalation Runbook — EPIC-XXX

## When to Escalate

| Condition | Action |
|-----------|--------|
| Retries exhausted (> 3) | Auto-escalate to `failed-final` |
| Architect recommends REPLAN but scope change is major | Escalate to human for approval |
| Agent timeout exceeded | Retry once, then escalate |
| Conflicting QA verdicts across retries | Escalate for human triage |

## Escalation Process

1. Manager writes `escalation-report.md` with full history
2. Manager posts `escalate` message to the orchestration channel
3. Human reviews and decides: retry with new guidance, reassign, or close

## Recovery from Escalation

1. Human provides new guidance in `brief.md`
2. Manager resets war-room state to `pending`
3. Normal lifecycle resumes
```

## Verification

After scaffolding the lifecycle:

1. `lifecycle.md` covers all states from the war-room state machine
2. `phase-checklist.md` has a row for every phase
3. `quality-gates.md` criteria are measurable and actionable
4. `escalation-runbook.md` covers all edge cases (timeout, repeated failures, scope changes)
5. All artifacts reference the correct EPIC-XXX identifier
