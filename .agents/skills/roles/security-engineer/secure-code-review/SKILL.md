---
name: secure-code-review
description: Use when reviewing source code for exploitable security flaws, OWASP Top 10 coverage, source-to-sink data flow, risky APIs, authentication/session issues, access control gaps, injection, XSS, CSRF, crypto misuse, secrets, or security-sensitive configuration.
---

# secure-code-review

## Purpose

Security-focused code review catches vulnerabilities that functional reviews and SAST tools miss. Automated tools are useful for breadth; manual review supplies context: trust boundaries, business rules, exploit paths, and whether a finding is reachable.

## Review Workflow

1. **Prioritize by risk** - Review internet-facing, authenticated, privileged, payment, PII, file, parser, and interpreter-facing paths first. Use quantitative scoring where data exists, qualitative judgment where it does not, and Delphi-style consensus for ambiguous high-impact areas.
2. **Decompose the target** - Identify entry points, assets, trust levels, trust boundaries, and a lightweight Data Flow Diagram before inspecting code deeply.
3. **Rank threats** - Use STRIDE for attacker goals and DREAD or local severity rules for ranking.
4. **Code crawl** - Search for risky APIs and patterns before reading linearly.
5. **Trace source to sink** - Follow untrusted input from request/message/file/env source through validation, authorization, transformation, storage, and output.
6. **Verify countermeasures** - Prefer concrete controls in code/config over comments, UI hiding, or assumptions.
7. **Report exploitability** - State the vulnerable path, prerequisites, impact, and a practical fix.

## Metrics and Hotspots

- Use cyclomatic complexity (CC) to find code that is harder to reason about and more likely to hide security defects.
- Track risk density as security defects per KLOC or per changed LOC when comparing modules over time.
- Escalate review depth for high-CC code that also handles auth, authorization, parsing, query building, redirects, file paths, secrets, crypto, or payments.
- Treat generated code, wrappers around native code, reflection, dynamic dispatch, and framework magic as high-context areas requiring manual confirmation.

## Code Crawling Starter Pack

Search first, then inspect call sites in context:

| Risk | Patterns and APIs |
|------|-------------------|
| SQL/HQL/LDAP/XPath injection | `SELECT`, `WHERE`, `FromSql`, `createQuery`, `ExecuteQuery`, `SqlCommand`, `Statement`, `ldap`, `xpath`, string interpolation near queries |
| OS command injection | `exec`, `spawn`, `ProcessBuilder`, `Runtime.getRuntime().exec`, `popen`, `system`, `Start-Process` |
| JavaScript/JSON injection | `eval`, `Function`, `setTimeout(string)`, `innerHTML`, `document.write`, unsafe JSONP |
| Session/cookie risk | `Set-Cookie`, `System.Net.Cookie`, `HttpOnly`, `Secure`, `SameSite`, session regeneration |
| XSS sinks | `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `dangerouslySetInnerHTML`, unquoted attributes, template concatenation |
| IDOR/mass assignment | `id` from route/query/body, `findById`, `update(req.body)`, model binding, hidden inputs, `isAdmin`, `role` |
| CSRF | POST/PUT/PATCH/DELETE handlers, forms, cookie-only auth, missing token validation |
| Redirect/forward | `sendRedirect`, `Response.Redirect`, `redirect(`, `header("Location")`, `returnUrl`, `next`, `continue`, `dest` |
| Crypto/secrets | `MD5`, `SHA1`, `DES`, hardcoded keys, static IVs, homegrown crypto, missing KMS/secret store |
| Misconfiguration | `debug=true`, verbose errors, directory listing, permissive CORS, missing request limits |

## OWASP A1-A10 Review Matrix

### A1 Injection

Look for untrusted input sent to SQL, HQL, LDAP, XPath, OS commands, JSON/JavaScript, template engines, or native wrappers.

Required controls:
- Use parameterized queries/prepared statements such as `SqlParameterCollection`, bind variables, or ORM parameter APIs.
- Avoid query construction through string concatenation. If dynamic clauses are required, build them only from server-side allowlists.
- Validate input with exact-match or allowlist rules before it reaches interpreters.
- Do not use `eval()` for JSON/text. Parse with safe parsers.
- Use CSP as defense in depth for client-side injection, not as the primary fix.

### A2 Broken Authentication and Session Management

Look for weak password rules, unsafe password storage, predictable tokens, missing logout invalidation, CAPTCHA bypasses, and weak 2FA flows.

Required controls:
- Enforce password length and complexity requirements appropriate to the risk level; reject weak, common, and reused passwords where policy supports it.
- Hash passwords with modern password hashing and unique random salts; never use MD5/SHA-1 for passwords.
- Review out-of-band authentication such as SMS 2FA for enrollment, reset, replay, rate-limit, and account recovery weaknesses.
- Verify CAPTCHA controls use randomized challenge length, fonts, distortion, replay prevention, and server-side validation where CAPTCHA is required.
- Generate session IDs with cryptographic randomness and at least 128 bits / 16 bytes of entropy.
- Mark session cookies `Secure`, `HttpOnly`, and appropriate `SameSite`.
- Regenerate session ID on authentication and privilege elevation to prevent fixation.
- Enforce absolute session timeouts and server-side invalidation.

### A3 Cross-Site Scripting

Trace untrusted data from source to browser sink. Inspect `innerHTML`, `document.write`, unquoted HTML attributes, template concatenation, and unsafe DOM writes.

Required controls:
- Use contextual output encoding for HTML body, HTML attribute, JavaScript, CSS, and URL contexts.
- Use safe DOM APIs such as `textContent` or `innerText` for text insertion.
- Use vetted sanitizers for intentionally allowed HTML.
- Apply layered encoding for nested contexts.
- Enforce CSP as defense in depth.

### A4 Insecure Direct Object Reference

Look for database records, files, pages, or tenant resources loaded directly from URL parameters, form fields, hidden inputs, or request bodies.

Required controls:
- Enforce server-side authorization before retrieving or mutating every object.
- Scope lookups by current principal or tenant, not only by object ID.
- Use indirect references where practical, such as server-side maps or opaque tokens.
- Prevent over-posting/mass assignment by explicitly allowlisting bindable fields.

### A5 Security Misconfiguration

Review declarative config such as `web.xml`, `web.config`, `server.xml`, framework config, container manifests, reverse proxy rules, and cloud/IaC settings.

Required controls:
- Disable debug modes, directory listing, sample apps, default credentials, and verbose production errors.
- Enforce framework/server request filtering, size limits, URL filtering, and secure defaults, including IIS Request Filtering where applicable.
- Lock down ASP.NET Trust Levels and other framework trust/sandbox settings where the stack supports them.
- Use declarative security such as `@RolesAllowed`, route guards, or equivalent policy annotations where appropriate.
- Encrypt or externalize sensitive config such as connection strings and keys.

### A6 Sensitive Data Exposure

Look for PII, credentials, payment data, tokens, secrets, or regulated data in storage, transit, logs, URLs, client storage, or error responses.

Required controls:
- Enforce TLS for authenticated and sensitive pages/APIs; use HSTS where applicable.
- Use secure cookie flags and avoid sensitive data in URLs.
- Use FIPS 140-2 validated cryptomodules where required, and modern algorithms such as AES and SHA-256-family primitives.
- Reject custom crypto, hardcoded keys, MD5, SHA-1, DES, static IVs, and reversible password storage.
- Use unique random salts of at least 128 bits for password hashing.

### A7 Missing Function Level Access Control

Look for privileged actions hidden only in UI, unprotected routes/controllers, and multi-step workflows that authorize only the first page.

Required controls:
- Enforce authorization in controller, service, or policy layers, not only the view.
- Use centralized RBAC/ABAC or policy checks.
- Default deny every endpoint/function unless explicitly allowed.
- Apply complete mediation at every step in multi-step processes.

### A8 Cross-Site Request Forgery

Identify state-changing POST/PUT/PATCH/DELETE operations that rely only on cookies for authentication.

Required controls:
- Use synchronizer tokens with cryptographically strong unpredictable values.
- Validate CSRF tokens server-side for all state-changing browser requests.
- Use double-submit cookies only when the implementation is carefully bound to the session.
- Check `Origin` or `Referer` as defense in depth.
- Treat XSS as a CSRF bypass and fix XSS first where both exist.

### A9 Using Components With Known Vulnerabilities

Review dependency manifests, lockfiles, container images, framework versions, plugins, and transitive dependencies.

Required controls:
- Maintain an inventory/SBOM of third-party components.
- Compare dependencies against known CVE databases with tools such as OWASP Dependency-Check.
- Upgrade, replace, patch, or formally accept risk with context.
- Remove unused modules/features to reduce attack surface.

### A10 Unvalidated Redirects and Forwards

Look for redirects/forwards built from query string or form fields such as `returnUrl`, `next`, `continue`, `redirect`, or `dest`.

Required controls:
- Avoid user-controlled redirect destinations.
- If needed, validate against a strict server-side allowlist.
- Prefer indirect references such as `?dest=1` mapped to a known safe URL.
- Ensure forwards cannot bypass authorization checks.

## Finding Format

````markdown
## Security Finding: [Title]

**Severity:** P0 🔴 | P1 🟠 | P2 🟡 | P3 🔵
**Category:** [OWASP category]
**File:** `[path]` Lines [X–Y]
**CWE:** [CWE ID if applicable]

### Vulnerability
[What the vulnerability is]

### Exploitation Scenario
[How an attacker could exploit this, step by step]

### Impact
[What happens if exploited: data loss, unauthorized access, account takeover, fraud, etc.]

### Remediation
```[language]
// Before (vulnerable)
[vulnerable code]

// After (fixed)
[fixed code]
```

### References
- [OWASP reference]
- [CWE reference]
````

## Anti-Patterns

- Only reviewing for OWASP Top 10. Business logic vulnerabilities exist outside the list.
- Trusting SAST output without proving reachability and context.
- Flagging everything as critical. Accurate severity matters.
- Treating UI hiding as authorization.
- Ignoring test code and fixtures. Hardcoded credentials can leak.
- Accepting "the framework handles it" without checking the exact framework API and configuration.
