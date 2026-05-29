# Release Pipeline V1

OSTwin uses a small two-environment merge pipeline with a direct hotfix lane:

```text
feature/fix/chore -> release-YYYY.MM.DD.N -> main
hotfix/* -> main -> sync main back into active release branches
```

`release-*` is the QA environment. `main` is production/stable.

## Branch Release Format

Example: `release-2026.05.19.1`

- `2026.05.19`: date the release branch is cut
- `.1`: first release branch for that date
- `.2`, `.3`, and so on are used for additional same-day releases or hotfixes

The release branch name is not SemVer. Semantic versioning lives in the GitHub
tag/release, for example `v1.0.1`.

## Merge Rules

PR into `release-*`:

- Source may be `feature/*`, `fix/*`, `hotfix/*`, `chore/*`, or a team member branch.
- Review remains trust-based. Release notes are not required here.

PR from `release-*` into `main`:

- Source branch must match `release-YYYY.MM.DD.N`.
- `Release Guard` must pass.
- Two tester approvals are required.
- A Lark release note is required.
- A SemVer release version is required, for example `v1.0.1`.
- After merge, the release captain creates the matching GitHub tag/release.

PR from `hotfix/*` into `main`:

- Source branch must start with `hotfix/`.
- `Release Guard` must pass.
- Two approvals are required by the main ruleset.
- Release note and SemVer fields are not required for the hotfix PR.
- After the hotfix is merged, GitHub Actions opens a sync PR from `main` into
  each active `release-*` branch so QA continues from the latest production code.

Use the direct hotfix lane only for urgent production fixes. Normal work still
goes through `release-*`.

## Release Rollover Automation

When a `release-*` PR is merged into `main`, GitHub may move unmerged PRs that
were targeting that release branch back to `main`. The `Roll Release Forward`
workflow handles this automatically:

- It runs only after a merged PR from `release-YYYY.MM.DD.N` into `main`.
- If there are dangling open PRs, it creates a new `release-YYYY.MM.DD.N`
  branch from the latest `main`.
- It retargets PRs that were still based on the old release branch.
- It also retargets non-hotfix PRs that were moved back to `main`.
- It leaves intentional `hotfix/* -> main` PRs alone.

If no dangling PRs exist, it does not create a new release branch.

## Versioning Rule

Use `vMAJOR.MINOR.PATCH`, for example `v1.0.1`, `v1.1.0`, or `v2.0.0`.

## When to use `v2.0.0`

Use a major version when the release has a breaking change or changes a major
contract with users:

- CLI command changes or removals, for example `ostwin run` changes behavior in
  a way that breaks existing scripts.
- Config/schema changes that require manual user migration.
- Installer changes to install path, env, dependency, or setup behavior that are
  not compatible with the old install flow.
- API/dashboard/bot flow changes that require current clients or users to adjust
  their setup or relearn an existing workflow.
- Large architecture upgrades with high risk, difficult rollback, or major
  production behavior changes.

Short rule: if an existing user or client can break by updating, use major.

## When to use `v1.1.0`

Use a minor version when adding capability without breaking the old flow:

- New role.
- New dashboard feature.
- New provider/model setting.
- New integration such as Slack, Lark, or bot behavior.
- Pipeline, QA, or release process improvements that do not break user-facing
  workflows.

Short rule: if it adds a feature and remains backward compatible, use minor.

## When to use `v1.0.1`

Use a patch version for fixes and polish:

- Bug fix.
- Production hotfix.
- Test/CI fix.
- Docs or release-note update.
- Small UX copy/style fix.
- Performance improvement that does not change the behavior contract.

Short rule: if it is not a meaningful new feature and is not breaking, use patch.

## Release Note Template

Lark is the source of truth for release notes. Each release section should
include:

- Release version
- Release branch
- Release PR
- Release date
- Release captain
- QA testers
- Highlights
- Bug fixes
- Breaking changes or big upgrades
- QA evidence
- Known risks
- Rollback plan

## First Release

The first release branch for this pipeline is:

- Branch: `release-2026.05.19.1`
- Version: `v1.0.1`

## GitHub Admin Setup

Rulesets require repository Administration write permission. Configure them after
the `Release Guard` workflow exists on `main`. GitHub `evaluate` mode is only
available with GitHub Enterprise; otherwise use `disabled` during bootstrap and
switch to `active` when ready.

Main ruleset:

- Name: `Main Release Gate`
- Target: `refs/heads/main`
- Enforcement: `active` after bootstrap
- Bypass actors: none
- Block deletion and non-fast-forward updates
- Require pull request before merge
- Require 2 approvals
- Dismiss stale approvals when new commits are pushed
- Require approval from someone other than the last pusher
- Require `Release Guard` once the hotfix-aware guard workflow is on `main`

Release branch ruleset:

- Name: `Release Branch Gate`
- Target: `refs/heads/release-*`
- Enforcement: `active`
- Bypass actors: none
- Block deletion and non-fast-forward updates
- Require pull request before merge
- Require 0 approvals so review stays trust-based
