---
name: review-the-review
description: Meta-analysis of QA verdicts to ensure review quality. Catches lenient passes, shallow testing, missed integration points, and systematic QA blind spots.
---

# review-the-review

## Purpose

QA's verdict is not the final word. The staff-manager reviews QA's own work to ensure review quality is high. A rubber-stamped DONE is worse than a thorough FAIL.

## The Meta-Review Checklist

### 1. Evidence of Execution

Did QA actually run the code?

| Signal | Pass | Fail |
|--------|------|------|
| Test output logs cited | ✅ | ❌ "all tests pass" with no evidence |
| Specific test names mentioned | ✅ | ❌ Generic "tested successfully" |
| Error reproduction steps | ✅ | ❌ "verified manually" |
| Screenshots or output | ✅ | ❌ None |

### 2. Integration Point Coverage

Did QA check the boundaries?

| Check | Should have done | Evidence in verdict |
|-------|-----------------|-------------------|
| Cross-room data shapes | `memory_search()` for other rooms' interfaces | Yes / No |
| Database migration compatibility | Checked migration files | Yes / No |
| API contract match | Compared backend output to frontend interface | Yes / No |
| Error path testing | Tested with invalid input, missing data, timeouts | Yes / No |

### 3. Depth of Analysis

Is the verdict substantive?

| Red flag | Example |
|----------|---------|
| Single-sentence verdict | "All looks good, passing." |
| No specific file references | "Code is clean and well-structured." |
| No edge cases mentioned | Only happy path tested |
| Copy-paste of engineer's done message | QA just echoed what the engineer said |
| No Memory search performed | QA didn't check what other rooms built |

### 4. Verdict Calibration

Is the severity assessment correct?

| Miscalibration | Example |
|----------------|---------|
| P0 classified as P3 | Data corruption bug marked as "minor style issue" |
| P3 classified as P0 | Naming convention violation marked as "blocker" |
| DONE with open P1s | "Passing with notes" but notes contain critical issues |
| FAIL without specifics | "Failing" but no actionable feedback for the engineer |

## Output Format

```markdown
## Review of QA Verdict: [Epic/Task ID]

**QA Verdict:** DONE / FAIL
**Staff Assessment:** ✅ Upheld / 🔴 Overruled

### Execution Evidence
- [✅/❌] Tests actually run with output cited
- [✅/❌] Manual testing with reproduction steps

### Integration Coverage
- [✅/❌] Cross-room data shape check
- [✅/❌] API contract verification
- [✅/❌] Error path coverage

### Depth Score: N/5
[1=rubber stamp, 5=thorough]

### Verdict
[If overruling, explain what QA missed and why it matters]

### Recommendation
- [ ] QA should re-review with [specific focus area]
- [ ] Add [check] to QA's standard checklist
```

## When to Use

- After every QA DONE on critical epics (auth, payments, data pipeline)
- After QA DONE on epics that touch shared interfaces
- When a previously-passed epic later causes integration failures
- Periodically as a calibration exercise (every 5th QA verdict)

## Anti-Patterns

- Overruling QA without evidence — your override needs to cite specific issues QA missed
- Reviewing only FAILs — lenient PASSes are more dangerous than overzealous FAILs
- Not communicating findings to QA — the goal is to improve QA's process, not undermine them
