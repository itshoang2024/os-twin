---
name: deep-code-review
description: Multi-layer code analysis reviewing at Contract, Logic, Integration, and Production layers. Goes beyond syntax correctness to catch systems-level bugs at component boundaries.
---

# deep-code-review

## Purpose

Standard code review checks if code works. Deep code review checks if code will **survive production**. This skill enforces a 4-layer review methodology that catches bugs at seams between components.

## The 4 Layers

### Layer 1 — Contract Layer

**Question:** Do the data shapes match across boundaries?

| Check | What to look for |
|-------|-----------------|
| API request/response | Does the backend return shape match the frontend TypeScript interface? |
| Database ↔ Model | Do ORM model fields match the actual DB schema and migrations? |
| Service ↔ Service | Do message/event schemas match between producer and consumer? |
| Config ↔ Code | Do environment variables used in code match the deployment config? |
| Fallback data | When code synthesizes fallback data, does it conform to the same contract as the primary source? |

**How to check:**
1. Find the TypeScript interface (or Python dataclass / JSON schema)
2. Find the code that produces the data
3. Compare every key, type, and optionality marker
4. Pay special attention to: `null` vs `undefined`, `[]` vs `null`, `string` vs `number`

### Layer 2 — Logic Layer

**Question:** Is the logic correct beyond the happy path?

| Check | What to look for |
|-------|-----------------|
| Edge cases | Empty arrays, null values, zero-length strings, boundary values |
| Race conditions | Concurrent writes, read-after-write consistency, async ordering |
| Null propagation | Chained `?.` access that silently swallows errors |
| Off-by-one | Loop boundaries, pagination offsets, slice indices |
| Type coercion | Implicit string-to-number, truthy/falsy surprises |
| Idempotency | Can this operation be safely retried? |
| State mutations | Are shared state modifications thread-safe? |

### Layer 3 — Integration Layer

**Question:** Will this work with the rest of the system?

| Check | What to look for |
|-------|-----------------|
| Cross-room compatibility | Does this code match what other rooms have built? (Check Memory) |
| Shared interfaces | Are shared types/interfaces consistent across modules? |
| Database migrations | Will this migration conflict with or depend on another room's migration? |
| Event contracts | Are published events consumed correctly by subscribers? |
| Import cycles | Does this introduce circular dependencies? |
| Version compatibility | Are dependency versions compatible with the rest of the monorepo? |

### Layer 4 — Production Layer

**Question:** Will this survive real-world traffic?

| Check | What to look for |
|-------|-----------------|
| Error handling | Are errors caught, logged, and returned with appropriate HTTP status codes? |
| Logging | Is there enough logging to debug production issues? Too much? (PII?) |
| Graceful degradation | What happens when a dependency is down? Timeout? Circuit breaker? |
| Retry logic | Are retries safe (idempotent)? Is there exponential backoff? Max retries? |
| Resource cleanup | Are connections, file handles, and locks properly released? |
| Rate limiting | Are new endpoints protected against abuse? |
| Observability | Are metrics, traces, and health checks in place? |

## Output Format

```markdown
## Deep Code Review

### Contract Layer
- ✅ API response shape matches `UserResponse` interface
- 🔴 P0: Fallback path returns `{nodes: [...]}` but interface expects `{nodes: {id, label, ...}[]}` — shape mismatch at L42

### Logic Layer
- ✅ Pagination handles empty results correctly
- 🟡 P2: `filter()` on L78 doesn't handle `null` items in array

### Integration Layer
- ✅ Shared `User` model consistent with Room-001's implementation
- 🟠 P1: Migration `002_add_status` depends on Room-003's `001_create_users` but no explicit dependency declared

### Production Layer
- ✅ Error handler returns proper 4xx/5xx codes
- 🔵 P3: Consider adding structured logging for the retry loop at L112
```

## When to Use

- Every code review by the staff-manager
- After the `critical-thinking` preamble is complete
- Focus the layers based on what `critical-thinking` Q1-Q3 revealed

## Anti-Patterns

- Reviewing only Layer 2 (Logic) — most production bugs live in Layer 1 (Contract) and Layer 3 (Integration)
- Marking all findings as P3 — if you're not finding P0/P1 issues, you're reviewing too shallowly
- Ignoring Layer 4 in "internal tools" — internal tools become external tools; review as if they're public
