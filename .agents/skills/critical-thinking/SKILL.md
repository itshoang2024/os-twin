---
name: critical-thinking
description: Structured 3-question critical thinking framework applied before every code review. Forces the reviewer to identify assumptions, trace fragile dependencies, and predict blind spots before reading code.
---

# critical-thinking

## Purpose

This is the **first skill** invoked in every staff-manager review. It prevents rubber-stamping by forcing structured pre-review thinking before any code is read.

## The 3-Question Framework

Before opening any file, answer these three questions in writing:

### Question 1 — What assumption am I making about this code?

Common assumptions to challenge:
- "The data shapes match between backend and frontend"
- "The existing tests cover the critical paths"
- "The engineer followed the conventions documented in Knowledge"
- "The error handling is sufficient for production"
- "The previous review caught the important issues"

**Action:** Write down your assumption. Then actively look for evidence that contradicts it.

### Question 2 — What would break if the upstream data shape changed?

Trace the data flow:
- Where does input data come from? (API, DB, another room's module, user input)
- What transformations happen? (parsing, mapping, filtering, aggregation)
- Where does output data go? (UI rendering, another service, DB write, API response)
- Are there hardcoded field names, magic strings, or implicit type coercions?

**Action:** Identify the fragile coupling points. These are where P0 bugs hide.

### Question 3 — What did the previous reviewer likely miss?

Common blind spots:
- **Happy-path bias** — QA tested the success case but not the error/fallback path
- **Diff tunnel vision** — reviewing only changed lines without understanding the system context
- **Trust escalation** — "the architect approved the design, so the implementation must be fine"
- **Test coverage illusion** — tests exist but don't test the actual edge cases
- **Cross-room ignorance** — the code works in isolation but conflicts with another room's work

**Action:** Explicitly target the blind spot in your review.

## Output Format

Every review begins with this block:

```markdown
## Critical Thinking Process

Before reviewing the code, I asked myself three questions:

1. **Assumption:** [your assumption]
   → I will verify this by [specific action]

2. **Fragile dependency:** [the upstream data shape or contract]
   → If this changed, [what would break]

3. **Previous blind spot:** [what the last reviewer likely missed]
   → I will specifically check [targeted area]
```

## When to Use

- **Always** — this is not optional. Every review starts here.
- Even for "small" changes — small changes at seam boundaries cause the worst production incidents.

## Anti-Patterns

- Writing the 3 questions as boilerplate without actually thinking → your findings will be shallow
- Skipping Q2 because "it's a frontend-only change" → frontend changes often depend on backend shapes
- Answering Q3 with "nothing" → if you think the previous reviewer caught everything, you're the one with a blind spot
