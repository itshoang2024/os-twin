---
name: system-design-review
description: Review system architecture proposals at macro scale for scalability, reliability, cost, and complexity. Evaluates designs across multiple dimensions including failure modes, data flow integrity, operational burden, and evolutionary fitness.
---

# system-design-review

## Purpose

Where the architect designs systems for a single epic, and the staff-manager reviews code quality, the principal engineer reviews system designs at the **organizational scale** — asking whether the proposed architecture will serve the business for the next 2–4 quarters.

## Review Dimensions

### 1. Scalability Assessment
- What is the expected load profile? (read-heavy, write-heavy, bursty)
- What is the scaling strategy? (horizontal, vertical, sharding)
- Where are the bottlenecks? (database, network, compute)
- What happens at 10x current load? 100x?

### 2. Reliability Analysis
- What are the failure modes? (single points of failure, cascading failures)
- What is the blast radius of each failure?
- What is the recovery strategy for each failure mode?
- What are the SLO implications?

### 3. Cost Modeling
- What are the infrastructure costs at current and projected load?
- What is the development cost (person-quarters)?
- What is the ongoing maintenance burden?
- Are there cheaper alternatives that meet requirements?

### 4. Complexity Budget
- How many new concepts does this introduce?
- How many services/components are added?
- What is the operational complexity? (monitoring, debugging, deployment)
- Can a new team member understand this in < 1 week?

### 5. Evolutionary Fitness
- How easy is it to change this design later?
- What decisions are reversible? Which are one-way doors?
- Does this design accommodate known future requirements?
- Does it avoid premature abstraction?

## Output Format

```markdown
# System Design Review: [Title]

**Reviewer:** principal-engineer
**Design author:** [architect / team]
**Verdict:** ✅ Approved | ⚠️ Approved with conditions | 🔴 Redesign required

## Dimension Scores

| Dimension | Score (1-5) | Notes |
|-----------|-------------|-------|
| Scalability | X | [key concern] |
| Reliability | X | [key concern] |
| Cost | X | [key concern] |
| Complexity | X | [key concern] |
| Evolutionary Fitness | X | [key concern] |

## Critical Findings
[P0/P1 issues that must be addressed]

## Recommendations
[Specific changes to the design]

## Questions for the Author
[Open questions that need answers before approval]

## Decision
[Final verdict with conditions if applicable]
```

## Anti-Patterns

- Reviewing designs without understanding the business context → designs serve requirements, not elegance
- Optimizing for problems you don't have → YAGNI applies to architecture too
- Ignoring operational complexity → a design that's hard to operate will fail in production
- Not considering migration → a perfect target architecture without a migration path is a fantasy
