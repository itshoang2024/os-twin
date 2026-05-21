---
name: legal-nda-triage
description: "Use when triaging, reviewing, summarizing, or escalating an NDA, confidentiality agreement, or confidentiality clause."
tags: [legal, nda, confidentiality, contract, triage]
trust_level: community
category: Legal
enabled: true
applicable_roles: [audit, qa, manager, staff-manager]
---

# Legal NDA Triage

Use this skill to quickly classify confidentiality agreements for attorney review.

## Mandatory Legal Gate

Apply `legal-common` first. Outputs are drafts for qualified attorney review, not legal advice or final legal conclusions. Non-legal users receive plain-language escalation guidance.

## Triage Inputs

Confirm:
- Mutual or one-way NDA.
- Disclosing and receiving parties.
- Purpose of disclosure.
- Information types involved.
- Term and confidentiality survival period.
- Jurisdiction and destination for the summary.

## Review Focus

Check definition of confidential information, exclusions, compelled disclosure, residual knowledge, affiliates and representatives, return/destruction, no-license language, non-solicit or non-compete language, injunctive relief, assignment, governing law, and unusual operational burdens.

## Output

Use a simple status:
- Green: ordinary terms, attorney review still required before signing.
- Yellow: negotiable issues or missing facts.
- Red: likely escalation item.

Include clause references, why it matters, and the question counsel should answer.
