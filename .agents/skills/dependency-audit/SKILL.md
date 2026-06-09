---
name: dependency-audit
description: Audit module dependencies for circular imports, unnecessary coupling, version conflicts, missing peer dependencies, and implicit global state. Produces a dependency health report with actionable fixes.
---

# dependency-audit

## Purpose

Bad dependencies kill projects slowly. Circular imports create startup crashes. Unnecessary coupling makes changes cascade unpredictably. Version conflicts create "works on my machine" bugs. This skill systematically audits the dependency graph at both the **module level** (import graph) and **package level** (npm/pip dependencies).

## The Audit Checklist

### 1. Circular Import Detection

**What to look for:**
- Module A imports Module B, which imports Module A
- Transitive cycles: A → B → C → A
- Lazy imports used to "fix" circular dependencies (a code smell, not a solution)

**How to check:**
```bash
# Python
python -c "import importlib; importlib.import_module('<module>')"
# If it fails with ImportError mentioning circular import, you found one

# TypeScript/JavaScript
npx madge --circular src/
```

**Severity:** P1 — circular imports cause unpredictable import ordering and runtime errors.

### 2. Unnecessary Coupling

**What to look for:**
- UI components importing database models directly
- Business logic importing HTTP framework types
- Utility modules importing domain-specific types
- "God modules" that everything imports

**Layer boundary rules:**
```
✅ Controller → Service → Repository → Database
❌ Controller → Database (skipping layers)
❌ Repository → Controller (wrong direction)
❌ Utils → Domain (utils should be domain-agnostic)
```

**Severity:** P2 — coupling makes the codebase rigid and changes cascade unpredictably.

### 3. Version Conflicts

**What to look for:**
- Multiple versions of the same package in the lockfile
- Peer dependency warnings
- `resolutions` / `overrides` in package.json (band-aids for conflicts)
- Pinned versions that conflict with ranges in dependencies

**How to check:**
```bash
# npm
npm ls --all 2>&1 | grep -i "ERESOLVE\|peer dep\|invalid"

# pip
pip check
```

**Severity:** P1 for runtime conflicts, P3 for warnings.

### 4. Missing Peer Dependencies

**What to look for:**
- Libraries that expect a peer dependency but it's not installed
- Version ranges that don't overlap between peers
- Framework plugins without the framework installed

**Severity:** P1 — causes "module not found" crashes that only appear in production.

### 5. Implicit Global State

**What to look for:**
- Module-level mutable variables (e.g., `let cache = {}` at file scope)
- Singleton patterns that hold state across requests
- Global event emitters / buses with no cleanup
- Module-level side effects (code that runs on import)

**Severity:** P1 for request-leaking state, P2 for test pollution.

### 6. Unused Dependencies

**What to look for:**
- Packages in `dependencies` that are never imported
- Packages in `dependencies` that should be in `devDependencies`
- Large dependencies used for a single utility function

**How to check:**
```bash
# npm
npx depcheck

# Python
pip-autoremove --list
```

**Severity:** P3 — bloats bundle/install but doesn't break functionality.

## Output Format

```markdown
## Dependency Audit Report

**Scope:** [project/module name]
**Files scanned:** N
**Dependencies:** M direct, K transitive

### Findings

| # | Severity | Category | Finding | Fix |
|---|----------|----------|---------|-----|
| 1 | 🔴 P0 | Circular import | `auth.py ↔ users.py` | Extract shared types to `types.py` |
| 2 | 🟠 P1 | Version conflict | `react@18.2` vs `react@17.0` via `legacy-lib` | Upgrade `legacy-lib` to v3+ |
| 3 | 🟡 P2 | Coupling | `Button.tsx` imports `prisma` directly | Use props/context for data |
| 4 | 🔵 P3 | Unused | `lodash` installed, only `_.get` used | Replace with optional chaining |

### Dependency Graph Health

- Circular imports: 0/1/N found
- Layer violations: 0/1/N found  
- Unused dependencies: 0/1/N found
- Global state risks: 0/1/N found
```

## Anti-Patterns

- Ignoring "peer dependency" warnings during install — they cause production crashes
- Using `// @ts-ignore` or `# type: ignore` to suppress import errors — hiding the problem
- Adding `resolutions` without understanding why the conflict exists
- "It works in dev" — version conflicts often only manifest in production builds
