---
name: architecture-conformance
description: Verify implementation matches architectural intent — ADR compliance, layer boundary enforcement, naming convention consistency, and pattern uniformity across the codebase.
---

# architecture-conformance

## Purpose

Good architecture means nothing if the implementation ignores it. This skill verifies that code actually follows the architectural decisions, layer boundaries, naming conventions, and patterns documented in Knowledge.

## The Conformance Checks

### 1. ADR Compliance

For every Architecture Decision Record in Knowledge:

```markdown
## ADR Conformance: ADR-003 — Use PostgreSQL with JSONB

| Requirement | Code | Status |
|-------------|------|--------|
| Use PostgreSQL (not MongoDB) | ✅ `sqlalchemy` + `psycopg2` in requirements | ✅ |
| JSONB for product attributes | ✅ `attributes = Column(JSONB)` | ✅ |
| GIN index on attributes | ❌ No index in migration | 🔴 P1 |
| No raw SQL for JSONB queries | ❌ `db.execute("SELECT * FROM...")` at L42 | 🟡 P2 |
```

**How to check:**
1. `knowledge_list_namespaces()` to identify the relevant project namespace, then `knowledge_query(namespace="<project-namespace>", query="architecture decisions ADR")` 
2. For each ADR, find the relevant code and verify compliance
3. Report deviations with severity

### 2. Layer Boundary Enforcement

Define the allowed import graph and check for violations:

```
Allowed:
  Controller → Service → Repository → Database
  Controller → DTO/Schema
  Service → Domain Model
  Any → Utils (domain-agnostic only)

Forbidden:
  Controller → Database (skipping service layer)
  Repository → Controller (wrong direction)
  Utils → Domain Model (utils must be generic)
  Frontend → Database (direct DB access from UI)
  Model → Controller (domain depending on transport)
```

**How to check:**
1. Scan import statements in each module
2. Classify each module by layer
3. Check that imports only flow in allowed directions
4. Flag violations with the specific import path

### 3. Naming Convention Enforcement

Check consistency across the codebase:

| Convention | Rule | Example |
|-----------|------|---------|
| Files | `snake_case.py`, `kebab-case.ts` | ✅ `user_service.py` ❌ `UserService.py` |
| Classes | `PascalCase` | ✅ `UserService` ❌ `user_service` |
| Functions | `snake_case` (Python), `camelCase` (TS) | per language |
| Constants | `UPPER_SNAKE_CASE` | ✅ `MAX_RETRIES` |
| Database tables | `snake_case`, plural | ✅ `users` ❌ `User` |
| API endpoints | `kebab-case`, plural nouns | ✅ `/api/v1/user-profiles` |
| Environment vars | `UPPER_SNAKE_CASE` with prefix | ✅ `APP_DATABASE_URL` |

### 4. Pattern Consistency

If the codebase uses a pattern, ALL modules should use it:

| Pattern | Check |
|---------|-------|
| Repository pattern | If service A uses a repository, service B shouldn't use raw queries |
| Error handling | If module A uses `Result<T, Error>`, module B shouldn't throw exceptions |
| Config loading | If module A reads env vars via a config class, module B shouldn't use `os.getenv` directly |
| Logging | If module A uses structured logging, module B shouldn't use `print()` |
| Testing | If module A uses fixtures, module B shouldn't use inline setup |

### 5. Security Architecture

Check that security decisions are implemented correctly:

| Security ADR | Verification |
|-------------|--------------|
| "All endpoints require auth" | Check for unprotected routes |
| "Use parameterized queries" | Scan for string concatenation in SQL |
| "No secrets in code" | Grep for API keys, passwords, tokens |
| "CORS restricted to known origins" | Check CORS config |
| "Rate limiting on public endpoints" | Check middleware configuration |

## Output Format

```markdown
## Architecture Conformance Report

**ADRs checked:** N
**Compliant:** M (X%)
**Violations:** K

### ADR Violations
| ADR | Violation | Severity | File | Line |
|-----|-----------|----------|------|------|
| ADR-003 | Missing GIN index | P1 | migrations/002.py | — |
| ADR-005 | Raw SQL in service | P2 | services/product.py | L42 |

### Layer Violations
| From | To | Direction | File | Import |
|------|----|-----------|------|--------|
| Controller | Database | ❌ Skips service | routes/users.py | `from db import Session` |

### Pattern Inconsistencies
| Pattern | Expected | Actual | File |
|---------|----------|--------|------|
| Error handling | Result type | try/except | services/payment.py |

### Conformance Score: X/100
```

## Anti-Patterns

- Checking conformance without reading the ADRs first — you need to know what was decided
- Only checking new code — existing non-conforming code should also be flagged
- Enforcing conventions that aren't documented — if it's not in Knowledge, it's not a rule
- Ignoring "minor" naming issues — inconsistent naming compounds into confusing codebases
