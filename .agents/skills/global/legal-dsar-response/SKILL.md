---
name: legal-dsar-response
description: "Use when handling access, deletion, correction, portability, opt-out, privacy rights, or data subject request workflows."
tags: [legal, privacy, dsar, data-rights, response]
trust_level: community
category: Legal
enabled: true
applicable_roles: [audit, qa, manager, staff-manager]
---

# Legal DSAR Response

Use this skill to organize data subject requests for supervised legal review.

## Mandatory Legal Gate

Apply `legal-common` first. Outputs are drafts for qualified attorney review, not legal advice or final legal conclusions. Non-legal users receive operational steps and escalation guidance.

## Intake

Capture requester identity, request type, jurisdiction, received date, response deadline source, systems to search, exemptions to evaluate, and reviewer.

If the matter names a current privacy statute, decree, regulator guidance, or official source set, verify that source before stating deadlines, exemptions, or mandatory response content. If verification is unavailable, produce a DSAR operations package and counsel source-request list instead of a final rule summary.

## Workflow

1. Confirm identity and authority.
2. Classify request type and applicable law.
3. Identify deadline and extension rules with source.
4. Map systems and custodians.
5. Flag privileged, confidential, security-sensitive, third-party, or exempt material.
6. Draft response for attorney review.

## Output

Return a DSAR tracker row, search plan, exemption checklist, draft response, and verification gaps. Do not promise compliance or denial without attorney approval.

For non-legal users, separate "safe operational steps now" from "legal determinations for counsel". Deadline, deletion, retention, identity, exemption, third-party, and cross-border conclusions must cite an opened source or be marked as counsel-verification blockers.
