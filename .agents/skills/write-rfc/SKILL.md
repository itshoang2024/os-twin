---
name: write-rfc
description: Author Request for Comments (RFC) documents for major technical decisions that affect multiple teams or have long-term architectural implications. Produces structured, evidence-based proposals with options analysis, migration plans, and stakeholder impact assessment.
---

# write-rfc

## Purpose

RFCs are the decision-making backbone of a principal engineer. Every technical decision with **blast radius > 1 war-room** must be documented as an RFC before implementation begins. This skill produces structured, reviewable technical proposals.

## RFC Template

```markdown
# RFC-XXXX: [Title]

**Author:** principal-engineer  
**Status:** Draft | In Review | Accepted | Rejected | Superseded  
**Created:** [date]  
**Decision deadline:** [date]  
**Affected teams/rooms:** [list]

## Context & Problem Statement

[What is the problem? Why does it need solving now? What is the cost of NOT solving it?]

## Decision Drivers

- [Driver 1: e.g., "Current system cannot handle 10x load growth"]
- [Driver 2: e.g., "Developer experience friction slowing feature delivery"]
- [Driver 3: e.g., "Compliance requirement by Q3"]

## Options Considered

### Option A: [Name]
- **Description:** [How it works]
- **Pros:** [Benefits]
- **Cons:** [Drawbacks]
- **Cost:** [Infrastructure, development, migration effort]
- **Risk:** [What could go wrong]

### Option B: [Name]
[Same structure]

### Option C: Do Nothing
- **Cost of inaction:** [What happens if we don't decide]

## Recommendation

**Chosen option:** [Option X]

**Rationale:** [Why this option wins — must reference evidence, benchmarks, or prior art]

## Migration Plan

1. [Phase 1: Parallel run / feature flag]
2. [Phase 2: Gradual rollout]
3. [Phase 3: Deprecation of old system]
4. [Rollback plan: How to revert if it fails]

## Consequences

### Positive
- [Benefit 1]

### Negative
- [Trade-off 1]

### Neutral
- [Side effect 1]
```

## Process

1. **Draft** — Principal writes RFC using this template
2. **Circulate** — Post to affected war-rooms for async review (3–5 day window)
3. **Address feedback** — Update RFC with responses to concerns
4. **Decide** — Principal makes the call, documents rationale
5. **Archive** — Save to Memory and Knowledge for future reference

## Quality Gates

- [ ] Problem statement is specific and measurable
- [ ] At least 3 options considered (including "do nothing")
- [ ] Each option has cost, risk, and trade-off analysis
- [ ] Recommendation is backed by evidence, not opinion
- [ ] Migration plan includes rollback procedure
- [ ] Affected teams are identified

## Anti-Patterns

- Writing an RFC after the decision is already made → defeats the purpose
- Options that are straw men to justify a predetermined choice → analyze genuinely
- Missing the "do nothing" option → sometimes inaction is correct
- No migration plan → great idea with no path to get there is not actionable
