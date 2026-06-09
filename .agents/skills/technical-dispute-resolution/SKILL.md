---
name: technical-dispute-resolution
description: Mediate cross-team technical disagreements with evidence-based verdicts. Uses a structured framework to separate opinions from facts, evaluate trade-offs objectively, and produce binding technical decisions with documented rationale.
---

# technical-dispute-resolution

## Purpose

When two or more teams disagree on a technical approach, the principal engineer arbitrates. This skill provides a structured mediation process that produces fair, evidence-based decisions — not consensus by exhaustion.

## Dispute Resolution Process

### Step 1 — Frame the Disagreement

Document precisely what is being disputed:

```markdown
## Dispute: [Title]

**Teams involved:** [Room A, Room B]
**Position A:** [What Team A wants to do and why]
**Position B:** [What Team B wants to do and why]
**Stakes:** [What happens if we choose wrong]
**Deadline:** [When this must be resolved]
```

### Step 2 — Separate Facts from Opinions

For each position, classify claims:

| Claim | Type | Evidence |
|-------|------|----------|
| "This approach is faster" | Fact — needs benchmark | [benchmark or none] |
| "This is cleaner code" | Opinion — subjective | N/A |
| "This won't scale past 10k users" | Fact — needs load test | [data or none] |

### Step 3 — Evaluate Against Shared Criteria

Both positions are scored against the same criteria:

| Criterion | Weight | Position A | Position B |
|-----------|--------|-----------|-----------|
| Correctness | 25% | ? | ? |
| Maintainability | 20% | ? | ? |
| Performance | 20% | ? | ? |
| Migration cost | 15% | ? | ? |
| Reversibility | 10% | ? | ? |
| Team familiarity | 10% | ? | ? |

### Step 4 — Decide and Document

```markdown
## Decision

**Chosen approach:** [Position A / B / Hybrid]

**Rationale:** [Why — must reference scores and evidence]

**Concessions:** [What the losing side gets — perhaps their approach is noted for future consideration]

**Review date:** [When to re-evaluate if the decision was correct]
```

### Step 5 — Commitment Protocol

After the decision:
1. Both teams commit to the chosen approach (disagree and commit)
2. No relitigating unless new evidence emerges
3. The decision is saved to Memory for precedent

## Escalation

If the dispute cannot be resolved at principal level:
- Escalate to `director-of-engineering` with full documentation
- Include scores, evidence gaps, and your preliminary recommendation

## Anti-Patterns

- Splitting the baby — compromising on technical decisions often produces the worst of both approaches
- Authority without evidence — "because I said so" is not a valid rationale
- Consensus-seeking — not all voices carry equal weight on technical matters; expertise matters
- Relitigating — once decided, don't revisit unless genuinely new data emerges
