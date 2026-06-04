---
name: compliance-mapping
description: Use when mapping implementation details, security controls, OWASP findings, privacy/data-protection behavior, access control, encryption, logging, vulnerability management, or configuration evidence to SOC2, GDPR, HIPAA, PCI-DSS, ISO 27001, or similar compliance frameworks.
---

# compliance-mapping

## Purpose

Compliance frameworks define what security controls must exist. This skill connects the gap between "what the framework requires" and "what we've actually implemented," producing actionable mapping documents and evidence.

## Supported Frameworks

| Framework | Focus | When Required |
|-----------|-------|---------------|
| **SOC 2** | Trust service criteria (security, availability, confidentiality) | SaaS companies, enterprise customers |
| **GDPR** | EU data protection and privacy | Processing EU citizen data |
| **HIPAA** | Protected health information | Healthcare data processing |
| **PCI-DSS** | Payment card data security | Payment processing |
| **ISO 27001** | Information security management | Enterprise compliance |

## Compliance Mapping Template

```markdown
# Compliance Mapping: [Framework] — [System/Service]

**Framework version:** [version]
**Mapped by:** security-engineer
**Date:** [date]
**Overall compliance:** [X]% of controls satisfied

## Control Mapping

### [Category: e.g., Access Control]

| Control ID | Requirement | Implementation | Status | Evidence |
|-----------|-------------|---------------|--------|----------|
| [AC-1] | [what the control requires] | [how we implement it] | ✅🟡🔴 | [where evidence is] |
| [AC-2] | [what the control requires] | [how we implement it] | ✅🟡🔴 | [where evidence is] |

### Status Legend
- ✅ **Compliant** — control is fully implemented with evidence
- 🟡 **Partial** — control is partially implemented, gaps identified
- 🔴 **Non-compliant** — control is not implemented

## Gap Analysis

| Control | Gap | Risk | Remediation | Priority | Owner |
|---------|-----|------|------------|----------|-------|
| [ID] | [what's missing] | [impact] | [how to fix] | P[X] | [who] |

## Evidence Inventory

| Control | Evidence Type | Location | Last Updated |
|---------|-------------|----------|-------------|
| [ID] | [policy doc, config, screenshot, log] | [where] | [date] |

## Remediation Timeline

| Phase | Controls | Deadline | Status |
|-------|---------|----------|--------|
| 1 | [P0 controls] | [date] | In progress |
| 2 | [P1 controls] | [date] | Not started |
| 3 | [P2 controls] | [date] | Not started |
```

## Compliance Review Process

1. **Scope** — identify which framework requirements apply to this system
2. **Map** — connect each requirement to current implementation
3. **Assess** — evaluate compliance status for each control
4. **Gap** — document gaps with remediation plans
5. **Evidence** — collect and organize compliance evidence
6. **Track** — monitor remediation progress
7. **Review** — reassess quarterly or when significant changes occur

## Security Evidence to Capture

For security-engineer reviews, collect evidence that maps naturally to compliance controls:

- Access control: server-side authorization, RBAC/ABAC policy, default-deny endpoint behavior, IDOR prevention.
- Authentication/session: password hashing, session entropy, cookie flags, session regeneration, timeout/invalidation.
- Data protection: TLS/HSTS, encryption at rest, key management, password salting, sensitive-data logging rules.
- Configuration: disabled debug mode, safe error handling, request filtering, encrypted/externalized secrets.
- Vulnerability management: dependency inventory/SBOM, CVE scan output, remediation/acceptance records, unused component removal.
- Application security testing: manual secure code review findings, SAST/DAST outputs, threat model, risk acceptance.

## Anti-Patterns

- Compliance as a project → compliance is continuous, not a one-time effort
- Paper compliance → documentation without implementation is fraud
- Over-scoping → not every control applies to every system; scope accurately
- Ignoring evidence management → auditors need evidence; collect it continuously, not before the audit
- Treating compliance as security → compliance is a minimum bar; it doesn't mean you're secure
