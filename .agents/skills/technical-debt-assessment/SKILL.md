---
name: technical-debt-assessment
description: Assess and quantify technical debt with classification (deliberate vs accidental), impact scoring (blast radius, remediation cost, interest rate), and prioritized paydown planning.
---

# technical-debt-assessment

## Purpose

Technical debt is not inherently bad — but **untracked** debt is. This skill provides a framework for classifying, quantifying, and prioritizing technical debt so the team can make informed decisions about when to pay it down.

## Debt Classification Matrix

| | Reckless | Prudent |
|---|---------|---------|
| **Deliberate** | "We don't have time for tests" | "We know this is a shortcut — we'll refactor in Sprint 3" |
| **Accidental** | "What's a connection pool?" | "Now we understand the domain better — the original model was wrong" |

- **Deliberate + Prudent** = Acceptable with a paydown plan
- **Deliberate + Reckless** = P1 — must schedule remediation
- **Accidental + Prudent** = Normal — refactor when understanding improves
- **Accidental + Reckless** = P0 — immediate training + fix needed

## Impact Scoring

Every debt item gets three scores (1–5):

### Blast Radius (1–5)
How many modules/teams are affected if this debt causes a problem?
- 1 = Single function, isolated module
- 3 = Multiple modules in one service
- 5 = Cross-service, affects entire platform

### Remediation Cost (1–5)
How much effort to fix it properly?
- 1 = < 1 hour, one file change
- 3 = 1–3 days, multiple files, tests needed
- 5 = > 1 week, architectural change, migration required

### Interest Rate (1–5)
How fast is this debt getting worse over time?
- 1 = Static — it's ugly but stable
- 3 = Growing — each new feature adds to it
- 5 = Compounding — it's actively causing bugs and slowing velocity

**Priority Score = Blast Radius × Interest Rate ÷ Remediation Cost**

High priority = high blast radius, high interest rate, low remediation cost (easy wins with big impact).

## Assessment Process

### Step 1 — Identify Debt

Scan the codebase for indicators:
- `TODO`, `HACK`, `FIXME`, `WORKAROUND` comments
- Duplicated code across modules
- Missing tests for critical paths
- Inconsistent patterns (some services use Repository, others use raw queries)
- Configuration in code (hardcoded URLs, magic numbers)
- Outdated dependencies

### Step 2 — Classify Each Item

For each debt item, determine: deliberate/accidental, reckless/prudent.

### Step 3 — Score Impact

Apply Blast Radius, Remediation Cost, and Interest Rate scores.

### Step 4 — Prioritize

Sort by Priority Score (descending). Group into:
- **Pay Now** — P-score > 3.0 or any Reckless+Deliberate items
- **Pay Next Sprint** — P-score 1.5–3.0
- **Track** — P-score < 1.5

## Output Format

```markdown
## Technical Debt Assessment

**Scope:** [project/module]
**Date:** YYYY-MM-DD
**Total items:** N
**Debt load:** Low / Medium / High / Critical

### Summary

| Priority | Count | Estimated Effort |
|----------|-------|-----------------|
| Pay Now | N | X days |
| Pay Next Sprint | N | X days |
| Track | N | — |

### Pay Now Items

| # | Description | Classification | BR | RC | IR | P-Score |
|---|-------------|---------------|----|----|-----|---------|
| 1 | No connection pooling on DB | Accidental/Reckless | 5 | 2 | 5 | 12.5 |
| 2 | Hardcoded API keys in config | Deliberate/Reckless | 5 | 1 | 3 | 15.0 |

### Velocity Impact Estimate
Current debt is costing approximately N hours/sprint in:
- Workarounds: X hours
- Bug fixes from debt: X hours  
- Onboarding friction: X hours
```

## Anti-Patterns

- Calling everything "tech debt" — poor naming is not debt, it's a 5-minute fix
- Tracking debt without paydown dates — debt without a plan is just a list
- Only counting code debt — process debt and documentation debt are equally costly
- Ignoring interest rate — static debt is less urgent than compounding debt
