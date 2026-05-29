---
name: security-architecture
description: Use when reviewing architecture, configuration, authentication/session design, access control, sensitive data handling, transport security, framework/server security settings, zero trust, least privilege, defense in depth, and audit logging.
---

# security-architecture

## Purpose

Security architecture review ensures that the system is designed with security as a foundational property, not an afterthought. This review happens at the design level, before implementation begins.

## Security Architecture Principles

### 1. Zero Trust
- Never trust, always verify
- Authenticate and authorize every request
- No implicit trust based on network location
- Verify explicitly, use least privileged access, assume breach

### 2. Defense in Depth
- Multiple layers of security controls
- No single point of security failure
- If one layer fails, others still protect

### 3. Least Privilege
- Grant minimum permissions needed
- Time-bound access where possible
- Regular access reviews

### 4. Secure by Default
- Default configurations are secure
- Security features are opt-out, not opt-in
- Fail securely (deny by default)

## Architecture Review Focus Areas

### Authentication and Session Integrity

- Session identifiers must be cryptographically random with at least 128 bits / 16 bytes of entropy.
- Session IDs must be regenerated after login, privilege elevation, and other identity context changes.
- Cookies carrying sessions must use `Secure`, `HttpOnly`, and appropriate `SameSite`.
- Absolute session timeout and server-side invalidation must be enforced.
- Password length and complexity policy must match the system risk level; out-of-band flows such as SMS 2FA and CAPTCHA must be rate-limited, replay-resistant, and server-validated.
- Password storage must use strong password hashing with unique random salts; never store reversible passwords.

### Object and Function Authorization

- Server-side authorization must happen before object retrieval or mutation.
- Every endpoint/function defaults to deny unless explicitly allowed.
- Authorization must live in controller/service/policy layers, not only in presentation logic.
- Multi-step workflows require complete mediation at every step.
- Tenant and owner scoping must be part of data access patterns.

### Security Configuration

- Review `web.xml`, `web.config`, `server.xml`, framework config, reverse proxy rules, deployment descriptors, annotations, container manifests, and cloud/IaC policy.
- Disable debug mode, directory listing, sample apps, default accounts, verbose errors, and admin interfaces not required in production.
- Enforce request filtering, upload size limits, URL limits, safe error handling, and framework-native security controls such as IIS Request Filtering.
- Lock down ASP.NET Trust Levels and equivalent runtime trust/sandbox settings where applicable.
- Encrypt or externalize sensitive configuration such as connection strings and keys.

### Sensitive Data Protection

- Enforce TLS for authenticated and sensitive traffic.
- Use HSTS where browser clients are in scope.
- Encrypt sensitive data at rest using FIPS 140-2 validated cryptomodules where required, plus modern algorithms and key management.
- Keep secrets in a secret manager/KMS, not in source, images, config files, or logs.
- Keep PII, credentials, tokens, and payment data out of URLs, analytics events, and exception traces.

### Browser-Side Request Integrity

- State-changing browser requests require CSRF protection when cookie-authenticated.
- CSP, secure headers, and output encoding strategy should be defined at architecture level, then verified in code.
- Redirect destinations must be allowlisted or indirect references.

## Security Architecture Review Template

```markdown
# Security Architecture Review: [System Name]

**Reviewer:** security-engineer
**Date:** [date]
**Verdict:** Approved | Conditional | Redesign Required

## System Overview
[Architecture diagram reference, data flows, trust boundaries]

## Review Dimensions

### Identity & Access Management
- [ ] Authentication mechanism is appropriate for risk level
- [ ] Authorization is enforced at service boundary, not just UI
- [ ] Default-deny access control is implemented for functions/endpoints
- [ ] Object authorization prevents IDOR and tenant breakout
- [ ] Service-to-service authentication is implemented
- [ ] API keys/tokens have appropriate scopes and expiration
- [ ] Access is logged and auditable
**Score:** [1-5] | **Finding:** [summary]

### Session Management
- [ ] Session IDs have at least 128 bits of entropy
- [ ] Session IDs regenerate after login and privilege elevation
- [ ] Session cookies use Secure, HttpOnly, and appropriate SameSite
- [ ] Absolute timeout and server-side invalidation are implemented
**Score:** [1-5] | **Finding:** [summary]

### Data Protection
- [ ] Data classification is defined (public, internal, confidential, restricted)
- [ ] Encryption at rest for confidential and restricted data
- [ ] Encryption in transit (TLS 1.2+) for all data
- [ ] Key management follows best practices (not hardcoded)
- [ ] Data retention and deletion policies defined
**Score:** [1-5] | **Finding:** [summary]

### Network Security
- [ ] Network segmentation between environments
- [ ] Firewall rules follow least-privilege
- [ ] Public endpoints are minimized
- [ ] Internal services are not directly internet-accessible
- [ ] DDoS protection for public endpoints
**Score:** [1-5] | **Finding:** [summary]

### Logging & Monitoring
- [ ] Security events are logged (auth, access, changes)
- [ ] Logs are tamper-resistant and centralized
- [ ] Alerting on suspicious patterns
- [ ] Audit trail for compliance requirements
- [ ] Log retention meets compliance requirements
**Score:** [1-5] | **Finding:** [summary]

### Configuration Hardening
- [ ] Debug mode and verbose production errors are disabled
- [ ] Directory listing, sample apps, and default credentials are removed
- [ ] Request filtering, upload limits, URL limits, and IIS Request Filtering are configured where applicable
- [ ] ASP.NET Trust Levels or equivalent runtime trust settings are locked down where applicable
- [ ] Sensitive config sections are encrypted or externalized
- [ ] Security headers and framework declarative security are configured
**Score:** [1-5] | **Finding:** [summary]

### Resilience & Recovery
- [ ] Secrets rotation is automated
- [ ] Backup and recovery procedures include security
- [ ] Incident response plan covers security incidents
- [ ] Business continuity plan exists
**Score:** [1-5] | **Finding:** [summary]

## Gap Analysis
| Gap | Severity | Remediation | Priority |
|-----|----------|------------|----------|
| [gap] | P[X] | [fix] | [timeline] |

## Verdict
[Final assessment with conditions if applicable]
```

## Anti-Patterns

- Security review only at the end: architecture changes are expensive late in development
- Treating internal networks as trusted: assume breach; internal is not automatically secure
- Security through obscurity: hiding implementation details is not a security control
- Compliance-driven security: compliance is a minimum bar, not a security strategy
- UI-only authorization: hiding buttons does not protect functions or objects
- Cookie-only state changes without CSRF design
- Config treated as deployment detail instead of security-critical system behavior
