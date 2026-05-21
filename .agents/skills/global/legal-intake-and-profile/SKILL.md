---
name: legal-intake-and-profile
description: "Use when legal work needs initial setup, user role identification, jurisdiction capture, playbook context, or reusable OSTwin legal profile data."
tags: [legal, intake, profile, playbook, matter]
trust_level: community
category: Legal
enabled: true
applicable_roles: [audit, qa, manager, staff-manager]
---

# Legal Intake And Profile

Use this skill to collect the minimum context needed for reliable legal workflows and to create reusable OSTwin legal profile files.

## Mandatory Legal Gate

Apply `legal-common` first. Outputs are drafts for qualified attorney review, not legal advice or final legal conclusions. For non-legal users, produce plain-language intake and escalation guidance.

## Intake Fields

Capture:
- User role and attorney contact.
- Organization or client context.
- Jurisdiction, forum, governing law, and affected locations.
- Practice area and objective.
- Documents or source materials available.
- Deadline, business urgency, and decision owner.
- Confidentiality, privilege, or disclosure restrictions.

## Profile Workflow

If reusable context is missing, draft profile files using the templates in `legal-common/references/`:
- Company profile at `~/.ostwin/legal-profiles/company.md`.
- Practice profile at `~/.ostwin/legal-profiles/practices/<practice>.md`.
- Matter profile at `~/.ostwin/legal-profiles/matters/<matter-slug>/matter.md`.

Do not invent legal positions. Mark unknown fields and ask for them only when they change the work product.

## Output

Return a concise intake summary with:
- Known facts.
- Missing high-impact facts.
- Assumptions safe to use for this run.
- Suggested profile updates.
- Whether the work can proceed or should be escalated.
