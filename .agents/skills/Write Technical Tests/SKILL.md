---
name: Write Technical Tests
description: Write unit and integration tests across multiple frameworks (pytest, jest, pester) with coverage targets.
version: 1.0.0
category: Quality Assurance
applicable_roles: [engineer, qa]
tags: [engineer, implementation, testing, qa, coverage]

source: project
author: Agent OS Core
---

# write-tests

## Overview

This skill guides you through writing effective unit and integration tests. It covers test discovery, framework conventions, coverage targets, and alignment with the `unit-tests` quality gate.

## When to Use

- When implementing a new feature that needs test coverage
- When a QA `fail` cites missing tests
- When refactoring code that lacks existing tests
- When a sub-task in TASKS.md specifically requires tests

## Artifacts Produced

| Artifact | Format | Location |
|----------|--------|----------|
| Test files | Language-specific | Project test directory |
| Coverage report | Text / HTML | stdout or `coverage/` |

## Instructions

### 1. Identify Test Framework

Detect the project's test framework by inspecting existing tests and config:

| Language | Common Framework | Config File |
|----------|-----------------|-------------|
| Python | pytest | `pytest.ini`, `pyproject.toml` |
| JavaScript/TS | Jest / Vitest | `jest.config.*`, `vitest.config.*` |
| PowerShell | Pester | `*.Tests.ps1` |
| Go | testing (stdlib) | `*_test.go` |

Follow whichever framework and conventions the project already uses.

### 2. Write Unit Tests

For each function/module under test:

```
test_<function_name>_<scenario>
  ├── Arrange — set up inputs, mocks, fixtures
  ├── Act    — call the function
  └── Assert — verify output, side effects, exceptions
```

**Coverage targets:**
- Happy path — normal input → expected output
- Edge cases — empty inputs, boundary values, nulls
- Error cases — invalid inputs → expected errors/exceptions
- Integration points — mock external dependencies

### 3. Write Integration Tests (When Needed)

Create integration tests for workflows that span multiple components:

1. Set up realistic test data/fixtures
2. Execute the full workflow end-to-end
3. Assert on final state, not intermediate steps
4. Clean up test artifacts after each test

### 4. Run and Validate

```bash
# Python
python -m pytest --cov=<module> --cov-report=term-missing

# JavaScript
pnpm test -- --coverage

# PowerShell
Invoke-Pester -Path ./tests -CodeCoverage <source-files>

# Go
go test -cover ./...
```

**Quality gate: `unit-tests`** — All tests must pass. Target ≥80% line coverage for new code.

### 5. Review Test Quality

Self-check before reporting:
- [ ] Tests are deterministic (no flaky timing dependencies)
- [ ] Tests are independent (order doesn't matter)
- [ ] Test names clearly describe what is being tested
- [ ] Mocks are minimal — don't mock what you don't have to
- [ ] No hardcoded file paths or environment-specific values

## Verification

After writing tests:
1. Full test suite passes: `0 failures`
2. New code has ≥80% coverage
3. Tests follow project naming conventions
4. No existing tests were broken
