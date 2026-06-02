---
name: legal-privacy-triage
description: "Use when triaging privacy, personal data, data sharing, cookies, tracking, vendor processing, transfer, retention, or privacy-policy questions."
tags: [legal, privacy, data-protection, triage, compliance]
trust_level: community
category: Legal
enabled: true
applicable_roles: [audit, qa, manager, staff-manager]
---

# Legal Privacy Triage

Use this skill to classify privacy questions and route them to the right level of review.

## Mandatory Legal Gate

Apply `legal-common` first. Outputs are drafts for qualified attorney review, not legal advice or final legal conclusions. Non-legal users receive plain-language privacy risk and escalation guidance.

## Triage Inputs

Confirm:
- Data categories and data subjects.
- Jurisdictions affected.
- Controller, processor, service provider, or business role.
- Purpose, retention, sharing, transfer, and security posture.
- Existing privacy notice, DPA, consent, or policy basis.

## Triage Focus

Flag sensitive data, children, health, financial, biometrics, employee data, international transfers, onward sharing, automated decisions, training data, cookies, dark patterns, breach risk, and unclear retention.

## Output

Return risk level, why it matters, missing facts, required documents, and whether a PIA, DPIA, DPA review, DSAR workflow, or attorney escalation is needed.
