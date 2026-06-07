---
name: runnable-verify
description: Ensure each epic's code is runnable with valid dependencies. Detects conflicts, validates versions, runs the application, and provides fix instructions for dependency issues.
tags: [qa, dependencies, runtime, verification, runnable]

---

# runnable-verify

## Overview

This skill ensures that **code is actually runnable** — not just that it compiles. It validates dependencies, checks for version conflicts, attempts to start the application, and provides actionable fix instructions when issues are found.

**Critical for Ostwin:** This is the gatekeeper that prevents epics from being marked "done" when the codebase cannot actually run.

## When to Use

- **After every epic implementation** — before QA passes the epic
- When engineer's `done` message mentions new dependencies
- When reviewing code that touches `package.json`, `requirements.txt`, `Cargo.toml`, etc.
- Before running integration tests
- When the codebase hasn't been verified runnable in a while

## Artifacts Produced

| Artifact | Format | Location |
|----------|--------|----------|
| Dependency audit | Markdown | `<war-room>/dependency-audit.md` |
| Runtime verification log | Terminal output | Inline |
| Fix instructions | Markdown | In fail message |

## Prerequisites

Before running this skill:
1. Ensure you're in the project's working directory (check `config.json` → `assignment.working_dir`)
2. Have access to run shell commands

---

## Instructions

### Phase 1: Dependency Audit

#### 1.1 Detect Ecosystem

Check for these marker files in priority order:

| Marker | Ecosystem | Package File |
|--------|-----------|--------------|
| `bun.lockb` / `bun.lock` | Bun/Node | `package.json` |
| `pnpm-lock.yaml` | pnpm/Node | `package.json` |
| `yarn.lock` | Yarn/Node | `package.json` |
| `package-lock.json` | npm/Node | `package.json` |
| `package.json` (no lock) | npm/Node | `package.json` |
| `pyproject.toml` | Python | `pyproject.toml` |
| `requirements.txt` | Python | `requirements.txt` |
| `Cargo.toml` | Rust | `Cargo.toml` |
| `go.mod` | Go | `go.mod` |
| `Gemfile` | Ruby | `Gemfile` |
| `composer.json` | PHP | `composer.json` |
| `*.csproj` / `*.sln` | .NET | `*.csproj` |

If none exist, report: **"No package manager detected — cannot verify dependencies"** and skip to Phase 3.

#### 1.2 Check for New/Modified Dependencies

```bash
# Compare with last known good state
git diff HEAD~1 -- <package-file> 2>/dev/null || git diff main -- <package-file> 2>/dev/null
```

List any new or changed dependencies in the audit.

#### 1.3 Detect Dependency Conflicts

**Node.js (npm/yarn/pnpm/bun):**

```bash
# Check for peer dependency conflicts
npm ls 2>&1 | grep -E "(UNMET|invalid|missing|peer dep)" || echo "No conflicts detected"

# For yarn
yarn why <package> 2>&1 | grep -E "(doesn't satisfy)" || true

# For pnpm
pnpm why <package> 2>&1 || true
```

**Python:**

```bash
# Check for version conflicts
pip check 2>&1 || echo "Conflicts detected"

# If using pip-tools
pip-compile --dry-run requirements.in 2>&1 | grep -E "(ERROR|Could not)" || true
```

**Rust:**

```bash
# Check for duplicate versions and conflicts
cargo tree --duplicates 2>&1 || true
cargo check 2>&1 | grep -E "(error\[E|multiple versions)" || true
```

**Go:**

```bash
# Check for version mismatches
go mod verify 2>&1 || true
go mod graph | grep -E "^[^ ]+$" | sort | uniq -d || echo "No duplicates"
```

**.NET:**

```bash
# Check for binding redirects needed
dotnet list package --outdated 2>&1 || true
dotnet nuget why <package> 2>&1 || true
```

#### 1.4 Record Findings

Create `<war-room>/dependency-audit.md`:

```markdown
# Dependency Audit — EPIC-XXX

> Timestamp: <ISO-8601>
> Ecosystem: <detected ecosystem>

## New/Modified Dependencies

| Package | Old Version | New Version | Change Type |
|---------|-------------|-------------|-------------|
| <name> | <old> | <new> | added/changed/removed |

## Conflicts Detected

| Package | Issue | Severity |
|---------|-------|----------|
| <name> | <conflict description> | critical/warning |

## Version Analysis

- Runtime required: <node/python/etc version>
- Lockfile present: yes/no
- Frozen install possible: yes/no
```

---

### Phase 2: Install & Build

#### 2.1 Clean Install (Recommended)

**Why clean install?** Ensures reproducibility — verifies the lockfile actually works.

```bash
# Node.js
rm -rf node_modules
npm ci                    # or: pnpm install --frozen-lockfile, yarn install --frozen-lockfile

# Python
rm -rf .venv
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows
pip install -r requirements.txt

# Rust
cargo clean
cargo build

# Go
go clean -modcache
go mod download

# .NET
dotnet clean
dotnet restore
```

#### 2.2 Build

Run the ecosystem-specific build command. If build fails, go directly to **Phase 5: Generate Fix Instructions**.

---

### Phase 3: Runtime Verification

This is the critical step that `build-verify` doesn't cover — **actually running the application**.

#### 3.1 Identify Entry Point

Find the application entry point:

| Ecosystem | Common Entry Points |
|-----------|---------------------|
| Node.js | `npm start`, `npm run dev`, `node src/index.js`, `node dist/index.js` |
| Python | `python main.py`, `python -m <module>`, `flask run`, `django runserver` |
| Rust | `cargo run`, `./target/debug/<binary>` |
| Go | `go run .`, `go run main.go` |
| .NET | `dotnet run`, `dotnet <project>.dll` |

#### 3.2 Attempt Startup (with timeout)

```bash
# Run with a timeout — we just want to verify it STARTS, not runs forever
timeout 10s npm start 2>&1 || EXIT_CODE=$?

# Check if startup succeeded (exit code 124 = timeout, which is OK for servers)
if [ "${EXIT_CODE:-0}" -eq 124 ]; then
  echo "STARTUP_OK: Application started and remained running"
elif [ "${EXIT_CODE:-0}" -eq 0 ]; then
  echo "STARTUP_OK: Application ran to completion"
else
  echo "STARTUP_FAILED: Exit code $EXIT_CODE"
fi
```

For GUI applications (desktop apps):
- Attempt to launch
- Check for crash within 5 seconds
- Capture any error dialogs

#### 3.3 Verify No Import/Runtime Errors

Even if startup succeeds, check for:

```bash
# Look for import errors in logs
grep -E "(ImportError|ModuleNotFoundError|Cannot find module|No such file)" logs/* 2>/dev/null || true

# Check for missing native modules
grep -E "(gyp ERR|node-gyp|native module|binding)" logs/* 2>/dev/null || true

# Check for missing environment variables
grep -E "(env|ENV|environment variable)" logs/* 2>/dev/null || true
```

---

### Phase 4: Integration Verification

Verify the new code integrates with existing codebase.

#### 4.1 Check Imports Work

```bash
# Node.js - verify all imports resolve
node -e "
  const fs = require('fs');
  const path = require('path');
  
  function checkImports(dir) {
    fs.readdirSync(dir).forEach(file => {
      const fullPath = path.join(dir, file);
      if (fs.statSync(fullPath).isDirectory()) {
        checkImports(fullPath);
      } else if (file.endsWith('.js') || file.endsWith('.ts')) {
        try {
          require.resolve(fullPath);
        } catch (e) {
          console.error('UNRESOLVED:', fullPath, e.message);
        }
      }
    });
  }
  checkImports('./src');
" 2>&1 || true
```

#### 4.2 Run Smoke Tests

If the project has smoke tests or health checks:

```bash
npm run test:smoke 2>&1 || npm test -- --grep "smoke" 2>&1 || echo "No smoke tests found"
```

---

### Phase 5: Generate Fix Instructions

When dependencies or runtime fails, generate actionable fix instructions.

#### 5.1 Common Issues & Fixes

| Issue | Fix Command | Notes |
|-------|-------------|-------|
| **Peer dependency conflict** | `npm install --legacy-peer-deps` | Temporary; report to engineer |
| **Version mismatch** | `nvm use <version>` or update `engines` | Check `.nvmrc` |
| **Missing native module** | `npm rebuild` or reinstall build tools | May need `python3`, `make`, `gcc` |
| **Lockfile out of sync** | Delete `node_modules`, `rm package-lock.json`, `npm install` | Generate new lockfile |
| **Cached bad package** | `npm cache clean --force` | Clear npm cache |
| **Python version wrong** | Use `pyenv` or update `requires-python` | Check `pyproject.toml` |
| **Missing system lib** | Install via apt/brew/choco | Project-specific |

#### 5.2 Create Fix Instructions

Format for the engineer:

```markdown
## Dependency Fix Required

### Problem
<clear description of what failed>

### Root Cause
<technical explanation>

### Immediate Fix
```bash
<command to fix>
```

### Recommended Changes
1. Update `<package-file>`:
   ```diff
   - "dependency": "^1.0.0"
   + "dependency": "^2.0.0"
   ```
2. Run: `<install command>`

### Verification
After fix, run:
```bash
<verification command>
```

### If Still Failing
<escalation path or alternative approach>
```

---

### Phase 6: Report to Channel

#### 6.1 Success Format

```
## Runnable Verification — PASS

- Ecosystem: <ecosystem>
- Dependencies: ✅ Valid (no conflicts)
- Install: ✅ Clean install succeeded
- Build: ✅ Build succeeded
- Runtime: ✅ Application starts without errors
- Entry point: `<command>`

### Runtime Verification
- Started: <timestamp>
- No import errors
- No missing modules
- No environment errors

### Dependency Audit
See: `<war-room>/dependency-audit.md`
```

#### 6.2 Failure Format

```
## Runnable Verification — FAIL

- Ecosystem: <ecosystem>
- Failed at: <phase> — <step>
- Exit code: <N>

### Error
```
<error output>
```

### Fix Instructions

1. **<fix summary>**
   ```bash
   <command>
   ```

2. **<additional step if needed>**

### Dependency Audit
See: `<war-room>/dependency-audit.md`

---

**Engineer: Please apply fixes and resubmit for review.**
```

---

## Integration with Epic Review

This skill should be invoked **before** the test suite in `review-epic`:

1. Run `runnable-verify` first
2. If runnable verification FAILS → post `fail` message with fix instructions
3. If runnable verification PASSES → proceed to test suite
4. Include runnable verification results in final QA report

---

## Verification Checklist

After completing this skill:

- [ ] Dependency audit file created
- [ ] Dependencies installed from clean state
- [ ] Build completed successfully
- [ ] Application starts (or runs) without errors
- [ ] No import/module resolution errors
- [ ] Fix instructions provided for any failures
- [ ] Results posted to war-room channel
