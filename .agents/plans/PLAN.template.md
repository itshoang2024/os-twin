# Plan: Example Feature

> Created: {{date_now}}
> Status: draft

## Config

working_dir: /path/to/your/project/...

---

Per-epic format:
```
Roles: @<role1>, @<role2>, ...    (dynamically chosen agents for this epic's workflow)
Objective: <mission>            (what this war-room must achieve — be specific)
working_dir: <path>              (scope agents to a specific subdirectory)
```

{{AVAILABLE_ROLES}}

### EPIC Lifecycle (Closed Loop)

Every Epic runs a dynamically designed closed lifecycle where the specific agents assigned to that epic iterate and correct each other's work until all quality gates pass.

For example, an Engineering Epic might use:

```text
pending → engineer → qa ─┬─► passed → signoff
             ▲            │
             └─ engineer ◄┘ (on fail → fixing)
```

While a Research Epic might use:
```text
pending → researcher → analyst ─┬─► passed → signoff
              ▲                 │
              └── researcher ◄──┘ (on fail → fixing)
```

- Each loop repeats until the review passes or retries are exhausted.
- Complex loops can include escalations (e.g. failing a design review routes back to an architect).

#### Pipeline Directive (Optional)

Override the default lifecycle to add specialized review stages.
Each review stage becomes an additional quality gate with its own correction loop:

```
Pipeline: architect -> engineer -> security-review -> qa
Pipeline: engineer -> schema-review -> qa
Pipeline: researcher -> engineer -> architect-review -> qa
```

Stages containing "review", "qa", "audit", "check", or "verify" get
pass/fail/escalate transitions with correction loops back through fixing.

#### Capabilities Directive

Declare required capabilities. The system auto-inserts review stages:

```
Capabilities: security, database        (adds security-review + schema-review stages)
Capabilities: accessibility, security   (adds a11y-review + security-review stages)
```

Capability-to-stage mapping:
- `security` -> `security-review` (by `security-specialist`)
- `database` -> `schema-review` (by `database-architect`)
- `architecture` -> `architect-review` (by `architect`)
- `infrastructure` -> `infra-review` (by `devops`)
- `accessibility` -> `a11y-review` (by `accessibility-specialist`)

---

## Goal
...

## EPIC-001: ...
...

Goals: ...

### Definition of Done
- [ ] ...

### Acceptance Criteria
- [ ] ...

### Tasks
- [ ] ...

depends_on: [EPIC-..., EPIC-...]

## EPIC-002: ...
...
