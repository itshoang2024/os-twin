---
name: legal-escalation-summary
description: "Use when a legal issue, contract position, policy gap, deadline, dispute, or compliance risk must be escalated to counsel or an approver."
tags: [legal, escalation, summary, approvals, risk]
trust_level: community
category: Legal
enabled: true
applicable_roles: [audit, qa, manager, staff-manager]
---

# Legal Escalation Summary

Use this skill to convert a legal finding into a concise escalation that an approver can act on.

## Mandatory Legal Gate

Apply `legal-common` first. Outputs are drafts for qualified attorney review, not legal advice or final legal conclusions. Non-legal users receive a message to send to counsel, not instructions to decide.

## Escalation Content

Include:
- Decision needed.
- Business context.
- Legal or compliance issue.
- Source documents and clauses.
- Deadline or urgency.
- Options and tradeoffs.
- Recommended reviewer or approver.
- What happens if no action is taken.

## Output

Draft:
- One-paragraph executive summary.
- Issue table.
- Exact questions for the approver.
- Attachments or source list.

Keep tone neutral. Do not bury uncertainty or missing facts.
