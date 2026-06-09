---
name: engineering-standards
description: Define and enforce organization-wide engineering standards including API conventions, coding patterns, testing requirements, error handling, and documentation mandates. Produces living standards documents that are actionable and enforceable.
---

# engineering-standards

## Purpose

Standards exist to make the right thing easy and the wrong thing hard. This skill produces org-wide engineering conventions that reduce decision fatigue, improve code consistency, and make cross-team collaboration frictionless.

## Standards Categories

### 1. API Design Standards
- Naming conventions (RESTful resource names, gRPC service names)
- Versioning strategy (URL path, header, query param)
- Error response format (standard error envelope)
- Pagination patterns
- Authentication/authorization patterns
- Rate limiting conventions

### 2. Code Standards
- Language-specific style guides (linter configs)
- File organization patterns
- Naming conventions (variables, functions, classes, modules)
- Comment and documentation requirements
- Maximum function/file length guidelines

### 3. Testing Standards
- Required test types by component type (unit, integration, e2e)
- Minimum coverage thresholds
- Test naming conventions
- Fixture and mock patterns
- Performance test requirements

### 4. Error Handling Standards
- Error classification (transient, permanent, user, system)
- Retry policies by error type
- Logging levels and what belongs at each level
- Alert severity definitions
- Graceful degradation patterns

### 5. Documentation Standards
- README requirements per service/module
- ADR requirements for architectural decisions
- API documentation format (OpenAPI, GraphQL schema)
- Runbook requirements for production services
- Onboarding documentation per team

## Standards Document Template

```markdown
# Standard: [Name]

**ID:** STD-XXXX
**Author:** principal-engineer
**Status:** Draft | Active | Deprecated
**Enforced by:** [linter rule, CI check, code review, honor system]

## Purpose
[Why this standard exists — the problem it prevents]

## Standard
[The actual requirement — specific, unambiguous, testable]

## Examples

### ✅ Correct
[Code/configuration example that follows the standard]

### ❌ Incorrect
[Code/configuration example that violates the standard]

## Exceptions
[When it's acceptable to deviate and the process for doing so]

## Enforcement
[How compliance is checked — automated tool, review checklist, CI pipeline]
```

## Process for New Standards

1. **Identify the pattern** — observe a recurring issue across 3+ teams
2. **Draft the standard** — write it using the template above
3. **Circulate for feedback** — give teams 1 week to comment
4. **Finalize** — address feedback, publish to Knowledge
5. **Enforce** — add automated checks where possible
6. **Review annually** — standards that nobody follows should be fixed or removed

## Anti-Patterns

- Standards without enforcement → just suggestions people ignore
- Too many standards → decision fatigue returns; prioritize high-impact ones
- Standards that are too vague → "write clean code" is not a standard
- Not grandfathering existing code → applying new standards retroactively without a migration plan creates chaos
- Standards by fiat without feedback → teams won't follow rules they didn't help shape
