---
name: post-mortem
description: Structured incident and failure analysis using 5-whys root cause analysis, contributing factors taxonomy, timeline reconstruction, and remediation planning with verification criteria.
---

# post-mortem

## Purpose

After a production incident or repeated QA failure cycle, this skill drives a blameless post-mortem that identifies root causes, contributing factors, and actionable prevention measures.

## When to Use

- After a production incident (downtime, data corruption, security breach)
- After 3+ QA failure cycles on the same epic
- After a cross-room integration failure
- When the manager requests a retrospective analysis
- After a P0 bug reaches production

## The Post-Mortem Framework

### Step 1 — Timeline Reconstruction

Build a factual timeline of what happened:

```markdown
| Time | Event | Actor | Evidence |
|------|-------|-------|----------|
| T-2d | Room-001 ships User model without `plan` field | Engineer | Memory: "User model — src/models/user.py" |
| T-1d | Room-003 builds frontend assuming `plan` exists | Engineer | Memory: "Dashboard component" |
| T+0h | QA marks Room-001 done (no frontend to test against) | QA | Channel: done message |
| T+2h | Integration test fails — `plan` is undefined | CI | Build log #247 |
| T+4h | Manager routes fix to Room-001 | Manager | Channel: fix message |
```

### Step 2 — 5-Whys Root Cause Analysis

Drill down from the symptom to the systemic cause:

```
WHY 1: Why did the frontend crash?
→ `user.plan` was undefined — the backend doesn't return it

WHY 2: Why doesn't the backend return `plan`?
→ Room-001's User model was built without that field

WHY 3: Why wasn't the field included?
→ The epic brief didn't specify the full API contract

WHY 4: Why didn't QA catch it?
→ QA reviewed Room-001 in isolation without checking Room-003's expectations

WHY 5: Why was the review done in isolation?
→ No cross-room coherence check exists in the review process

ROOT CAUSE: Missing cross-room interface validation in the QA workflow
```

### Step 3 — Contributing Factors

Classify all contributing factors:

| Factor | Category | Contributed How |
|--------|----------|----------------|
| Incomplete brief | Process | Didn't specify shared API contract |
| Isolated QA review | Process | No cross-room checking protocol |
| No integration tests | Testing | Would have caught the mismatch |
| Memory not checked | Brain-ops | Room-003 didn't search for Room-001's model shape |

Categories: `Process`, `Testing`, `Communication`, `Architecture`, `Tooling`, `Brain-ops`

### Step 4 — Remediation Plan

| Action | Owner | Deadline | Verification |
|--------|-------|----------|-------------|
| Add `plan` field to User model | Room-001 Engineer | T+1d | Unit test passes |
| Add cross-room coherence check to QA workflow | Staff Manager | T+3d | Documented in ROLE.md |
| Create shared interface spec in Knowledge | Architect | T+5d | `knowledge_import_folder` confirmed |
| Add integration test for User contract | Room-003 Engineer | T+3d | CI green |

### Step 5 — Prevention Recommendations

```markdown
## Prevention

### Process Changes
- [ ] Add cross-room coherence check to every QA review
- [ ] Require shared interface specs before rooms start work

### Technical Changes
- [ ] Add contract tests between backend and frontend
- [ ] Create a shared types package imported by both rooms

### Brain-Ops Changes
- [ ] Save shared interfaces to Memory before implementation
- [ ] Promote finalized API contracts to Knowledge
```

## Output Format

```markdown
# Post-Mortem: [Incident Title]

**Date:** YYYY-MM-DD
**Severity:** P0/P1/P2
**Duration:** Xh from detection to resolution
**Impact:** [what was affected]

## Timeline
[Step 1 output]

## Root Cause Analysis (5 Whys)
[Step 2 output]

## Contributing Factors
[Step 3 output]

## Remediation Plan
[Step 4 output]

## Prevention
[Step 5 output]

## Lesson for the Team
[Single paragraph — the generalizable takeaway]
```

## Anti-Patterns

- **Blaming individuals** — post-mortems are about systems, not people
- **Stopping at Why 1** — the surface cause is never the root cause
- **Remediation without verification** — every fix needs a way to confirm it worked
- **Not saving the post-mortem to Memory** — future rooms will hit the same issue
