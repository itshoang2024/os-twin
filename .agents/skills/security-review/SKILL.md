---
name: security-review
description: Use this skill to perform a security-focused code review — check for secrets, injection vectors, auth issues, and dependency vulnerabilities.
tags: [qa, security, review, compliance]

---

# security-review

## Overview

This skill guides a focused security review of code changes. It covers the most common vulnerability categories and integrates with the `no-hardcoded-secrets` quality gate.

## When to Use

- As part of any QA review (security checklist)
- When the task involves authentication, authorization, or user input handling
- When QA escalates with a `security` classification
- When reviewing code that handles sensitive data (PII, credentials, tokens)

## Artifacts Produced

| Artifact | Format | Location |
|----------|--------|----------|
| Security findings | Markdown | Section in `qa-report.md` |

## Instructions

### 1. Secrets and Credentials Scan

Search all changed files for potential hardcoded secrets:

```bash
# Search for common secret patterns
grep -rn -E "(password|secret|token|api_key|apikey|private_key|access_key)\s*[=:]\s*['\"]" <changed-files>

# Search for base64-encoded strings (potential encoded secrets)
grep -rn -E "[A-Za-z0-9+/]{40,}={0,2}" <changed-files>

# Check for private keys
grep -rn "BEGIN.*PRIVATE KEY" <changed-files>
```

| Finding | Severity | Location |
|---------|----------|----------|
| Hardcoded API key | 🔴 CRITICAL | `file.py:42` |
| Password in config | 🔴 CRITICAL | `config.json:15` |

### 2. Injection Vulnerability Check

Review all user input paths:

| Vector | What to Check |
|--------|--------------|
| **SQL Injection** | Parameterized queries used? No string concatenation in SQL? |
| **Command Injection** | Shell commands use safe APIs? No `eval()` or `exec()` with user input? |
| **Path Traversal** | File paths validated? No `../` allowed in user input? |
| **XSS** | HTML output escaped? Template engine auto-escaping enabled? |
| **SSRF** | URL inputs validated? Allowlist for external requests? |

### 3. Authentication and Authorization

If the code touches auth:
- [ ] Authentication is required for protected endpoints
- [ ] Authorization checks use role/permission model (not just auth check)
- [ ] Session tokens have appropriate expiry
- [ ] Password hashing uses bcrypt/argon2 (not MD5/SHA1)
- [ ] Failed auth attempts are rate-limited or logged

### 4. Data Handling

- [ ] Sensitive data is not logged (passwords, tokens, PII)
- [ ] Sensitive data is encrypted at rest and in transit
- [ ] Data validation happens at the boundary (input validation)
- [ ] Error messages don't leak internal details

### 5. Dependency Review

```bash
# Check for known vulnerabilities
# Python
pip-audit

# JavaScript
pnpm audit

# Go
govulncheck ./...
```

- [ ] No dependencies with known critical CVEs
- [ ] Dependencies are pinned to specific versions
- [ ] No unnecessary dependencies added

### 6. Report Security Findings

Add a security section to `qa-report.md`:

```markdown
## Security Review

### Secrets Scan
- Status: ✅ CLEAN / ❌ FINDINGS
- <details if findings>

### Injection Vectors
- Status: ✅ CLEAN / ❌ FINDINGS
- <details if findings>

### Auth/Authz
- Status: ✅ N/A / ✅ CLEAN / ❌ FINDINGS
- <details if findings>

### Dependencies
- Status: ✅ CLEAN / ❌ FINDINGS
- <details if findings>

### Overall Security Verdict: DONE / FAIL
```

Any **CRITICAL** security finding automatically makes the overall verdict **FAIL**.

## Verification

After completing security review:
1. Secrets scan was run on all changed files
2. Input handling paths were reviewed for injection vectors
3. Security section exists in `qa-report.md`
4. Critical findings (if any) are flagged as blocking
