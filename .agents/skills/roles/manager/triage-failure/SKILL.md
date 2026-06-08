---
name: triage-failure
description: Use this skill to classify QA failures using the error taxonomy -- route to fixing, architect-review, or plan-revision with documented context."
tags: [manager, triage, routing, failure-handling]

---

# triage-failure

## Overview

This skill guides the manager through classifying and routing QA failures. Every `fail` or `escalate` from QA must pass through triage before the next action is taken. The output is a `triage-context.md` and a routing decision.

## When to Use

- When QA posts a `fail` verdict on a war-room
- When QA posts an `escalate` message
- When a war-room enters the `manager-triage` state

## Artifacts Produced

| Artifact | Format | Location |
|----------|--------|----------|
| Triage context | Markdown | `<war-room>/triage-context.md` |
| Routing message | Channel | `done` / `fix` / `design-review` / `plan-update` / `blocked` / `reject` with compact `TRIAGE_DECISION` block |

## Instructions

### 1. Read the QA Feedback

Gather all context:
- **QA verdict message** -- the `fail` or `escalate` message body
- **`qa-report.md`** -- detailed findings and evidence
- **Previous triage contexts** -- check for repeated failure patterns
- **Retry count** -- how many times has this war-room cycled?

### 2. Classify the Failure

Apply the classification taxonomy in order:

| Priority | Category | Trigger Keywords | Next State |
|----------|----------|-----------------|-----------|
| 1 | `subcommand-bug` | exception, trace, bug in subcommand |  `subcommand-redesign` |
| 2 | `subcommand-missing` | command-not-found, missing-manifest |  `subcommand-redesign` |
| 3 | `environment-error` | module-not-found, file-missing, permission-denied |  `subcommand-redesign` |
| 4 | `design-issue` | architecture, design, scope, interface |  `architect-review` |
| 5 | `plan-gap` | specification, acceptance criteria, requirements |  `plan-revision` |
| 6 | `implementation-bug` | Default (no other match) |  `fixing` |

**Repeated-failure heuristic:** If `retries  2` AND consecutive fail messages share 60% word overlap  upgrade to `design-issue`.

### 3. Check Retry Budget

| Retry Count | Action |
|-------------|--------|
| 0-2 | Route normally per classification |
| 3 | Final attempt -- route to `architect-review` regardless |
| >3 | Mark `failed-final` -- escalate to human |

### 4. Write triage-context.md

```markdown
# Triage Context -- EPIC/TASK-XXX

> Manager: manager
> Date: <YYYY-MM-DD>
> Retry: #<N> of 3

## QA Feedback (verbatim)
<paste the full QA fail/escalate message>

## Classification
- **Category:** <implementation-bug | design-issue | plan-gap | subcommand-bug>
- **Trigger:** <specific keywords or heuristic that matched>
- **Confidence:** <high / medium / low>

## Routing Decision
- **Next state:** <fixing | architect-review | plan-revision | subcommand-redesign | failed-final>
- **Assigned to:** <engineer | architect | human>
- **Instructions:** <specific guidance for the assignee>

## Context for Assignee
<summary of the problem, what was tried before, what should be different this time>

## Previous Attempts
| Retry | Classification | Outcome |
|-------|---------------|---------|
| #1 | <category> | <result> |
| #2 | <category> | <result> |
```

### 5. Route the Work

Post the appropriate channel message:

| Classification | Message Type | Recipient |
|---------------|-------------|-----------|
| `implementation-bug` | `fix` | engineer |
| `design-issue` | `design-review` | architect |
| `plan-gap` | `design-review`  then `plan-update` | architect  engineer |
| `subcommand-bug/missing` | `fix` (with redesign flag) | engineer |
| Max retries exceeded | `escalate` | human/manager |

Always include QA feedback **verbatim** when routing to the engineer.

Every manager triage channel message must end with exactly one compact routing block:

```markdown
## TRIAGE_DECISION
message: <done | fix | design-review | plan-update | blocked | reject>
next: <review | optimize | developing | triage | blocked | failed>
```

Do not add extra keys to the block. If the manager cannot confidently determine a more specific route, or the escalation is stale/already answered by later channel evidence, use the fallback:

```markdown
## TRIAGE_DECISION
message: done
next: review
```

## Verification

After triage:
1. `triage-context.md` exists in the war-room
2. Classification uses the defined taxonomy
3. QA feedback is included verbatim
4. Routing message posted to the correct recipient
5. Retry count is tracked accurately
