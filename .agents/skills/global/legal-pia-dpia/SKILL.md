---
name: legal-pia-dpia
description: "Use when assessing privacy impact, DPIA need, PIA documentation, high-risk processing, new data uses, or product data-flow changes."
tags: [legal, privacy, pia, dpia, data-flow]
trust_level: community
category: Legal
enabled: true
applicable_roles: [audit, qa, manager, staff-manager]
---

# Legal PIA DPIA

Use this skill to structure privacy impact assessments and DPIA triage.

## Mandatory Legal Gate

Apply `legal-common` first. Outputs are drafts for qualified attorney review, not legal advice or final legal conclusions. Non-legal users receive assessment questions and escalation guidance.

## Assessment Inputs

Capture processing purpose, data categories, data subjects, jurisdictions, lawful basis or notice basis, retention, recipients, transfers, security controls, automated decisions, vulnerable populations, and launch timeline.

## Risk Review

Flag sensitive data, large-scale monitoring, profiling, AI decisions, children, employee surveillance, cross-border transfers, vendor processing, incompatible secondary use, and unclear retention.

## Output

Produce:
- PIA/DPIA triage conclusion for attorney review.
- Risk table and mitigations.
- Missing facts.
- Required approvals.
- Draft record of processing assumptions.

Do not state that a DPIA is legally unnecessary unless counsel confirms.
