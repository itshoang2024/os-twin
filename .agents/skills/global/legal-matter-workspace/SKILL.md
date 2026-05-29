---
name: legal-matter-workspace
description: "Use when legal work should be tied to a matter, client, dispute, transaction, investigation, deadline, or recurring legal workspace."
tags: [legal, matter, workspace, files, confidentiality]
trust_level: community
category: Legal
enabled: true
applicable_roles: [audit, qa, manager, staff-manager]
---

# Legal Matter Workspace

Use this skill to organize matter context, isolate privileged material, and keep legal work attached to the right file.

## Mandatory Legal Gate

Apply `legal-common` first. Outputs are drafts for qualified attorney review, not legal advice or final legal conclusions. Non-legal users get a matter summary and escalation path, not legal conclusions.

## Workspace Rules

- Confirm the active matter before reading or writing matter-specific work.
- Use `~/.ostwin/legal-profiles/matters/<matter-slug>/matter.md` for reusable matter facts.
- Do not mix materials across matters unless the responsible attorney confirms cross-matter use.
- Check confidentiality restrictions before summarizing or moving materials.
- Record deadlines and responsible owners separately from legal analysis.

## Matter Record

Maintain:
- Parties and roles.
- Responsible attorney and business owner.
- Jurisdiction or forum.
- Key facts and documents.
- Open questions.
- Deadlines and source for each deadline.
- Output locations and distribution limits.

## Output

Return the active matter status, missing setup fields, and any safe next step. If conflicts or authorization are unresolved, stop and route to counsel.
