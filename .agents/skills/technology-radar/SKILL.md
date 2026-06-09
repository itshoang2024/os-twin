---
name: technology-radar
description: Evaluate emerging technologies, frameworks, and tools using a structured Adopt/Trial/Assess/Hold classification. Produces evidence-based recommendations with total cost of ownership analysis, team readiness assessment, and migration risk evaluation.
---

# technology-radar

## Purpose

Prevents both "resume-driven development" (adopting trendy tech without justification) and "legacy lock-in" (refusing to evolve). Provides a structured framework for evaluating whether to adopt, trial, assess, or hold on any technology.

## Classification Ring

| Ring | Meaning | Action |
|------|---------|--------|
| **Adopt** | Proven in production, team proficient, recommended as default | Use in new projects |
| **Trial** | Promising, limited production use, actively experimenting | Use in non-critical paths |
| **Assess** | Interesting, needs investigation, no production use yet | Spike / proof of concept only |
| **Hold** | Not recommended — too risky, deprecated, or superseded | Do not use in new code |

## Evaluation Framework

For every technology under consideration, assess:

### 1. Problem Fit (Weight: 30%)
- Does it solve a specific, documented problem?
- Is the problem significant enough to justify adoption cost?
- Are there simpler alternatives?

### 2. Maturity (Weight: 20%)
- Community size and activity
- Release cadence and stability
- Documentation quality
- Enterprise adoption

### 3. Team Readiness (Weight: 20%)
- Current team skills overlap
- Training cost and time
- Hiring market availability
- Knowledge concentration risk (bus factor)

### 4. Total Cost of Ownership (Weight: 20%)
- Licensing costs
- Infrastructure costs
- Maintenance burden
- Migration cost from current solution

### 5. Risk (Weight: 10%)
- Vendor lock-in
- Security track record
- Compatibility with existing stack
- Exit strategy if it doesn't work out

## Output Format

```markdown
## Technology Radar Entry: [Technology Name]

**Classification:** Adopt | Trial | Assess | Hold
**Evaluated:** [date]
**Evaluator:** principal-engineer

### Score

| Dimension | Score (1-5) | Weight | Weighted |
|-----------|-------------|--------|----------|
| Problem Fit | X | 30% | X.X |
| Maturity | X | 20% | X.X |
| Team Readiness | X | 20% | X.X |
| TCO | X | 20% | X.X |
| Risk | X | 10% | X.X |
| **Total** | | | **X.X / 5.0** |

### Recommendation
[What to do and why]

### Conditions for Promotion
[What would need to be true to move this to the next ring]

### Exit Criteria
[How to know if we should move this to Hold]
```

## Anti-Patterns

- Evaluating technology without a specific problem to solve → solution looking for a problem
- Ignoring TCO and only looking at features → hidden costs kill ROI
- Skipping team readiness → great tech the team can't use is worthless
- Not defining exit criteria → technologies should earn their place continuously
