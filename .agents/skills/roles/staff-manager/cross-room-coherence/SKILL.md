---
name: cross-room-coherence
description: Validate that code produced by multiple war-rooms will integrate correctly. Check shared interfaces, database migration ordering, event contracts, and hidden coupling between independently developed epics.
---

# cross-room-coherence

## Purpose

Each war-room works independently, but their code must work **together**. This skill validates that independently developed modules will integrate without breaking.

## The Coherence Checks

### 1. Shared Interface Consistency

When multiple rooms consume or produce the same data type, compare field names, types, and optionality across rooms. Flag any divergence.

**How to check:**
1. `memory_search(query="User model interface schema")` — find all rooms' implementations
2. Build a comparison table of fields across rooms
3. Flag mismatches in types, naming, or optionality

### 2. Database Migration Ordering

When multiple rooms add migrations:
- Are foreign key dependencies explicit?
- Can migrations run in any order without failing?
- Are there conflicting column additions to the same table?

### 3. Event/Message Contract Alignment

When rooms communicate via events or messages:
- Do event names match exactly? (watch for `user.created` vs `user_created`)
- Do payload shapes match between producer and all consumers?
- Are required fields present in the producer's output?

### 4. API Endpoint Conflicts

Check for route collisions — two rooms defining the same HTTP endpoint with different handlers.

### 5. Shared Resource Contention

Watch for rooms competing for: database tables, cache keys, file paths, environment variables.

### 6. Timing Dependencies

Check if Room B's code only works after Room A's code has run — hidden deployment ordering requirements.

## The Coherence Protocol

1. **Load all room context** from Memory
2. **Build the integration map** — list every shared artifact
3. **Check each integration point** against the checks above
4. **Report coherence score** with critical mismatches and recommended integration order

## Output Format

```markdown
## Cross-Room Coherence Report

**Rooms reviewed:** Room-001, Room-003, Room-005
**Integration points:** 12 identified
**Coherent:** 9 (75%) | **Mismatched:** 3 (25%)

### Critical Mismatches
1. 🔴 P0: `User.id` type mismatch — Room-005 uses `number`, others use `string`
2. 🟠 P1: Room-003 expects `plan` field not yet in Room-001's API

### Recommended Integration Order
1. Room-001 → 2. Room-003 → 3. Room-005
```

## Anti-Patterns

- Reviewing rooms in isolation — the bugs live at the boundaries
- Assuming Memory is complete — verify against actual code
- Ignoring migration ordering — "we'll fix it in deployment" fails
- Not checking event contracts — async communication hides type mismatches until runtime
