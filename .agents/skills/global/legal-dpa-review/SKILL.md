---
name: legal-dpa-review
description: "Use when reviewing a DPA, data processing addendum, subprocessors, cross-border transfer terms, security exhibit, or controller-processor clauses."
tags: [legal, privacy, dpa, data-processing, vendor]
trust_level: community
category: Legal
enabled: true
applicable_roles: [audit, qa, manager, staff-manager]
---

# Legal DPA Review

Use this skill for data processing terms attached to contracts or vendor reviews.

## Mandatory Legal Gate

Apply `legal-common` first. Outputs are drafts for qualified attorney review, not legal advice or final legal conclusions. Non-legal users receive a plain-language summary and escalation guidance.

## Review Inputs

Confirm data roles, jurisdictions, data categories, processing purposes, subprocessors, transfers, security controls, breach notice timing, deletion/return requirements, and audit commitments.

## Review Focus

Check:
- Controller, processor, service provider, or business role alignment.
- Instructions, confidentiality, assistance, audits, and deletion.
- Subprocessor approval and notice.
- Transfer mechanism and local-law risk.
- Security exhibit specificity.
- Breach notice obligations and timing.
- Liability alignment with the main agreement.

## Output

Return a clause-by-clause issue table with source references, business impact, missing facts, fallback language to discuss with counsel, and escalation items.
