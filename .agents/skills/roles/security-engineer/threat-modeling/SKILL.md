---
name: threat-modeling
description: Use when decomposing a feature, API, service, data flow, or architecture change to identify entry points, assets, trust boundaries, STRIDE threats, DREAD risk, and countermeasures before or during implementation.
---

# threat-modeling

## Purpose

Threat modeling answers: "What can go wrong?" before it goes wrong. By identifying threats during design, we prevent security vulnerabilities from being coded in.

## Three-Step Process

### 1. Decompose the Application

Capture enough structure to reason about abuse:

- Entry points: routes, APIs, queues, webhooks, file uploads, admin tools, CLI jobs, scheduled jobs.
- Assets: credentials, sessions, PII, payment data, secrets, tenant data, audit logs, business-critical state.
- Trust levels: anonymous user, authenticated user, privileged user, service account, external partner, internal operator.
- Trust boundaries: browser to server, service to service, app to database, app to third party, public to private network.
- Data Flow Diagram: show sources, processes, stores, sinks, and boundaries. Keep it lightweight but concrete.

### 2. Determine and Rank Threats

Use STRIDE to classify attacker goals, then rank with DREAD or the project's severity scale. Include context: attacker prerequisite, reachable path, affected asset, mitigating controls, and likely impact.

### 3. Define Countermeasures

For every meaningful threat, specify preventive, detective, or responsive controls. Prefer controls that can be verified in code, tests, configuration, or operational evidence.

## STRIDE Threat Categories

| Category | Threat | Example |
|----------|--------|---------|
| **S**poofing | Pretending to be someone else | Stolen credentials, session hijacking |
| **T**ampering | Modifying data or code | SQL injection, man-in-the-middle |
| **R**epudiation | Denying an action | Missing audit logs |
| **I**nformation Disclosure | Exposing private data | API leaking PII, verbose errors |
| **D**enial of Service | Making service unavailable | Resource exhaustion, DDoS |
| **E**levation of Privilege | Gaining unauthorized access | Privilege escalation, IDOR |

## DREAD Risk Rating

| Factor | 1 (Low) | 5 (Medium) | 10 (High) |
|--------|---------|-----------|-----------|
| **D**amage | Minor data exposure | Significant data loss | Complete system compromise |
| **R**eproducibility | Hard to reproduce | Requires specific conditions | Always reproducible |
| **E**xploitability | Requires expertise | Moderate skill | Script kiddie can do it |
| **A**ffected users | Single user | Subset of users | All users |
| **D**iscoverability | Requires insider knowledge | Discoverable with effort | Publicly known |

**Risk score = (D + R + E + A + D) / 5**

Recommended mapping:

| Average | Risk | Expected action |
|---------|------|-----------------|
| 8.0-10.0 | Critical | Block until mitigated or explicitly accepted |
| 6.0-7.9 | High | Require mitigation before release |
| 3.0-5.9 | Medium | Track with owner and deadline |
| 1.0-2.9 | Low | Accept or harden opportunistically |

## Threat Model Template

```markdown
# Threat Model: [Feature/System Name]

**Author:** security-engineer
**Date:** [date]
**Status:** Draft | In Review | Accepted

## System Description
[What the system does, data flows, trust boundaries]

## Entry Points
| Entry Point | Caller | Trust Level | Notes |
|-------------|--------|-------------|-------|
| POST /api/orders | Authenticated user | External authenticated | Creates payment-bearing state |

## Assets
| Asset | Classification | Owner |
|-------|---------------|-------|
| User credentials | Confidential | Auth team |
| Payment data | Restricted | Payments team |

## Trust Boundaries
[Where do trust levels change? e.g., client→server, service→database]

## Data Flow Diagram
[Link to DFD or concise text diagram]

## Threat Analysis

### T-001: [Threat Name]
- **Category:** [STRIDE]
- **Description:** [How the attack works]
- **DREAD Score:** [D:? R:? E:? A:? D:? = Avg:?]
- **Risk Level:** Critical | High | Medium | Low
- **Mitigation:** [How to prevent or detect]
- **Status:** Mitigated | Accepted | Open

## Security Requirements
[Derived from the threat analysis — what the implementation MUST include]

## Residual Risks
[Threats that are accepted with documented rationale]
```

## When to Threat Model

- New features that handle user data
- Changes to authentication or authorization
- New API endpoints
- Changes to data storage or processing
- Integration with external services
- Infrastructure changes
- Any path that parses untrusted input, performs redirects, changes state, or crosses tenant/security boundaries

## Anti-Patterns

- Threat modeling only after code is complete. It is primarily a design activity.
- Modeling every tiny change equally. Focus on changes with security implications.
- Generic threats without context. "SQL injection is possible" is unhelpful; specify where, how, and what interpreter is involved.
- No mitigations. Identifying threats without countermeasures is incomplete.
- No trust boundary. A threat model without trust levels usually misses the attacker path.
