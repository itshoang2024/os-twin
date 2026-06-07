---
name: org-health-check
description: Assess engineering organizational health across velocity trends, burnout indicators, skill distribution, attrition risk, and team morale. Produces a structured health report with leading indicators and intervention recommendations.
---

# org-health-check

## Purpose

Healthy teams build great products. Unhealthy teams burn out, lose talent, and ship bugs. This skill provides a structured assessment of organizational health so problems are caught early — before they become crises.

## Health Dimensions

### 1. Velocity & Throughput
- Sprint completion rate (committed vs. delivered)
- Cycle time trends (time from start to done)
- Lead time trends (time from request to delivery)
- WIP limits adherence

**Red flags:** Declining velocity over 3+ sprints, cycle time increasing, WIP consistently over limit.

### 2. Quality Indicators
- Bug escape rate (bugs found in production vs. pre-release)
- Test coverage trends
- Code review turnaround time
- Post-release hotfix frequency

**Red flags:** Bug escape rate increasing, coverage dropping, reviews taking > 2 days.

### 3. Team Health
- Oncall burden distribution (is it equitable?)
- Unplanned work ratio (< 20% is healthy)
- Meeting load (> 30% of time in meetings is a problem)
- Knowledge concentration (bus factor per critical system)

**Red flags:** Single point of failure on knowledge, oncall burnout, meeting overload.

### 4. Skill Distribution
- Skills matrix coverage (critical skills covered by 2+ people)
- Training and growth investment
- Cross-training progress
- New hire ramp-up time

**Red flags:** Critical skills held by 1 person, no cross-training, slow ramp-up.

### 5. Morale & Engagement
- Voluntary attrition rate
- Internal mobility requests
- Escalation frequency and tone
- Feedback survey trends

**Red flags:** Rising attrition, frequent escalations, negative feedback trends.

## Health Report Template

```markdown
# Org Health Report — [Month Year]

## Executive Summary
[2-3 sentence overall health assessment with the single most important action needed]

## Scorecard

| Dimension | Score (1-5) | Trend | Status |
|-----------|-------------|-------|--------|
| Velocity | X | ↑↓→ | 🟢🟡🔴 |
| Quality | X | ↑↓→ | 🟢🟡🔴 |
| Team Health | X | ↑↓→ | 🟢🟡🔴 |
| Skill Distribution | X | ↑↓→ | 🟢🟡🔴 |
| Morale | X | ↑↓→ | 🟢🟡🔴 |

## Detailed Findings
[Per-dimension analysis with evidence]

## Interventions Recommended
| Priority | Intervention | Owner | Timeline |
|----------|-------------|-------|----------|
| P0 | [action] | [who] | [when] |
| P1 | [action] | [who] | [when] |

## Comparison to Last Month
[What improved, what degraded, what's new]
```

## Anti-Patterns

- Only measuring velocity → fast teams shipping the wrong thing aren't healthy
- Measuring health once per quarter → monthly is minimum; some indicators need weekly
- Ignoring leading indicators → attrition is a lagging indicator; by the time people leave, it's too late
- Using health metrics punitively → teams will manipulate metrics if they're punished for honest reporting
