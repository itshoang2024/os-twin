# Plan: Smoke Test Hello Site

> Project: .

## Goal

Verify the Linux installer can create and run a minimal Ostwin plan with one epic,
one engineer role, and one QA role.

## EPIC-001 - Build a static Hello site

Roles: @engineer, @qa
Objective: Create a single frontend HTML page that displays the text "Hello this is OsTwin".
Working_dir: .

### Description

Create `index.html` in this smoke test folder. The page must be a minimal static
HTML document and visibly include the text `Hello this is OsTwin`.

### Definition of Done

- [ ] `index.html` exists in the smoke test folder.
- [ ] `index.html` contains `Hello this is OsTwin`.
- [ ] QA verifies the file content and returns `VERDICT: DONE`.

### Acceptance Criteria

- [ ] Running `grep -q "Hello this is OsTwin" index.html` succeeds.
- [ ] The plan has exactly one epic.
- [ ] The epic uses only the engineer and QA roles.

depends_on: []
