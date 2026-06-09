---
name: mentorship-feedback
description: Transform review findings into teaching moments. Generate "Lesson for the Team" sections, build pattern libraries of common mistakes, and create targeted advice per engineer based on their error patterns.
---

# mentorship-feedback

## Purpose

Every review finding is a teaching opportunity. This skill transforms technical corrections into reusable team knowledge that prevents the same class of bug from recurring.

## The Teaching Framework

### 1. Lesson Extraction

Every staff-manager review MUST end with a "Lesson for the Team" section:

```markdown
## Lesson for the Team

**Trace data contracts across boundaries before marking code as reviewed.**
The most dangerous bugs live at the seam between backend response shapes and
frontend TypeScript interfaces. When you add a fallback path that synthesizes
data, you're essentially building a second data source — and it must conform
to the exact same contract as the primary one.

A quick way to catch this class of bug: copy the TypeScript interface, paste
it next to your Python `return {}`, and check every key.
```

**Rules for good lessons:**
- State the principle, not just the fix
- Explain WHY, not just WHAT
- Give a concrete technique the team can use immediately
- Make it generalizable beyond this specific code review

### 2. Pattern Library

Track recurring mistakes to build a team pattern library:

```markdown
## Recurring Pattern: Shape Mismatch in Fallback Paths

**Frequency:** Seen in EPIC-003, EPIC-007, EPIC-012
**Root Cause:** Engineers build fallback data without referencing the primary contract
**Impact:** P0 — frontend crashes on fallback data

### Prevention Checklist
- [ ] For every `return {}` or `return []`, verify against the TypeScript interface
- [ ] Add a comment linking to the interface file: `# Must match UserResponse in types.ts`
- [ ] Write a test that validates the fallback shape against the primary shape

### Example
[Link to the most illustrative review]
```

Save pattern libraries to Memory with tag `promote-to-knowledge` for eventual promotion.

### 3. Engineer Growth Tracking

Track per-engineer patterns (saved to Memory, not shared publicly):

```markdown
## Engineer Pattern: [Engineer-ID / Room-ID]

### Strengths
- Excellent test coverage
- Clear code organization

### Growth Areas
| Pattern | Seen In | Frequency | Status |
|---------|---------|-----------|--------|
| Missing null guards | EPIC-003, EPIC-005 | 2x | Active |
| Hardcoded config values | EPIC-003 | 1x | Monitoring |
| Missing error logging | EPIC-005, EPIC-007 | 2x | Active |

### Recommended Focus
Next review, specifically check error logging — this is becoming a pattern.
```

### 4. Review Checklist Generation

When a pattern recurs 3+ times, generate a permanent checklist item:

```markdown
## Generated Checklist Item

**Trigger:** Pattern "Shape Mismatch in Fallback Paths" seen 3x
**Add to:** QA Review Checklist + Engineer Pre-Submit Checklist

### New Checklist Item
- [ ] For any code that returns data (API endpoints, fallback generators, 
  cache hydration): verify the return shape matches the consumer's expected 
  interface field-by-field. Pay special attention to field names, types, 
  optionality, and nested object shapes.
```

## Memory Integration

After every mentorship extraction:

```bash
# Save the lesson
memory_save(
  content="Lesson: Trace data contracts across boundaries...",
  name="Lesson — data contract tracing",
  path="mentorship/lessons",
  tags=["mentorship", "lesson", "data-contracts"]
)

# Save recurring pattern (if 2+ occurrences)
memory_save(
  content="Pattern: Shape mismatch in fallback paths. Seen in EPIC-003, EPIC-007...",
  name="Pattern — fallback shape mismatch",
  path="mentorship/patterns",
  tags=["mentorship", "pattern", "recurring", "promote-to-knowledge"]
)
```

## Anti-Patterns

- **Lecturing without a concrete technique** — "be more careful" is not a lesson
- **Making it personal** — lessons are about patterns, not people
- **Not saving to Memory** — lessons that aren't saved are lessons that aren't learned
- **One-liners** — a good lesson is a paragraph with a principle, explanation, and technique
