---
name: data-contract-tracing
description: Trace data shapes across boundaries (backend→frontend, service→service). Verify that fallback paths, synthesized data, and proxy responses conform to the exact same contract as the primary data source.
---

# data-contract-tracing

## Purpose

The most dangerous bugs live at the **seam between data producers and consumers**. This skill provides a systematic method for tracing data contracts across boundaries and catching shape mismatches before they reach production.

## When Data Contracts Break

Data contract bugs happen when:
1. **Backend returns a different shape** than frontend expects
2. **Fallback/synthetic data** doesn't match the primary source's contract
3. **Database schema evolves** but the ORM model doesn't update
4. **API versioning** introduces subtle field differences
5. **Serialization/deserialization** changes types silently (e.g., `Date` → `string`)
6. **Optional fields** treated as required, or vice versa

## The Tracing Method

### Step 1 — Identify the Contract

Find the **canonical type definition** — the single source of truth for the data shape:

```
TypeScript interface → for frontend-consumed APIs
Python dataclass / Pydantic model → for backend APIs
JSON Schema → for service-to-service contracts
Protobuf / gRPC definition → for RPC contracts
Database migration → for persistence layer
```

### Step 2 — Find All Producers

List every code path that produces data conforming to this contract:
- Primary API endpoint
- Fallback/default data generators
- Cache hydration logic
- Mock data in tests
- Seed data scripts
- WebSocket push payloads

### Step 3 — Trace Field-by-Field

For each producer, verify every field:

```markdown
| Field | Contract Type | Producer 1 (API) | Producer 2 (Fallback) | Match? |
|-------|--------------|-------------------|----------------------|--------|
| id | string (UUID) | ✅ UUID from DB | ❌ incremental int | 🔴 MISMATCH |
| name | string | ✅ | ✅ | ✅ |
| items | Item[] | ✅ Item objects | ❌ raw JSON strings | 🔴 MISMATCH |
| meta | object? (optional) | ✅ null when absent | ❌ missing entirely | 🟡 RISK |
```

### Step 4 — Check Consumers

Verify that every consumer handles the contract correctly:
- Does the frontend destructure the correct field names?
- Does the consumer handle `null` vs `undefined` vs `missing` correctly?
- Are optional fields guarded with defaults?
- Does the rendering code crash on empty arrays? Missing nested objects?

### Step 5 — Document the Findings

```markdown
## Data Contract Trace: [Contract Name]

**Contract:** `UserResponse` (file: `src/types/user.ts:L12-28`)
**Producers:** 3 identified
**Consumers:** 2 identified

### Mismatches Found

#### 🔴 P0: Fallback `nodes` shape mismatch
- **Contract expects:** `{ id: string, label: string, data: object }[]`
- **Primary API returns:** ✅ correct shape
- **Fallback (L42) returns:** `{ id: number, name: string }[]` — wrong field names, wrong `id` type
- **Consumer (React component L88):** accesses `node.label` → will render `undefined` from fallback data

#### Fix
```python
# Before (wrong shape)
return {"nodes": [{"id": i, "name": n} for i, n in enumerate(names)]}

# After (matches contract)
return {"nodes": [{"id": str(uuid4()), "label": n, "data": {}} for n in names]}
```
```

## Quick Check Pattern

When you see code that produces data (especially fallback paths):

1. Copy the TypeScript interface
2. Paste it next to the return statement
3. Check every key
4. Check every type
5. Check optionality (`?` markers)
6. Check nested object shapes recursively

This takes 60 seconds and catches the most dangerous class of frontend bugs.

## Common Traps

| Trap | Example | Why it's dangerous |
|------|---------|-------------------|
| Field name mismatch | `name` vs `label` vs `title` | Silent `undefined` rendering |
| Type mismatch | `id: number` vs `id: string` | `===` comparisons fail silently |
| Nesting mismatch | `data.user.name` vs `data.name` | TypeError in production |
| Array vs single | `item` vs `items[]` | Map/filter crashes |
| Optional vs required | `meta?: object` vs `meta: object` | Null pointer on missing field |
| Enum mismatch | `"active"` vs `"ACTIVE"` vs `1` | Switch/case falls through |

## Anti-Patterns

- Trusting that "the types will catch it" — TypeScript types are erased at runtime; backend can return anything
- Only checking the primary data path — fallback and cache paths are where mismatches hide
- Assuming test mocks match production shapes — mocks are often outdated
- Skipping nested object tracing — the mismatch is always one level deeper than you checked
