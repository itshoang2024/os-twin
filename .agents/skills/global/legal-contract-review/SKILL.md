---
name: legal-contract-review
description: "Use when reviewing, summarizing, issue-spotting, or preparing attorney review of a commercial agreement or contract clause."
tags: [legal, contract, commercial, review, attorney-review]
trust_level: community
category: Legal
enabled: true
applicable_roles: [audit, qa, manager, staff-manager]
---

# Legal Contract Review

Use this skill for structured review of commercial agreements and contract clauses.

## Mandatory Legal Gate

Apply `legal-common` first. Outputs are drafts for qualified attorney review, not legal advice or final legal conclusions. Non-legal users receive business-readable issues and escalation guidance.

## Review Inputs

Confirm:
- Party role: buyer, seller, vendor, customer, employer, employee, licensor, licensee, or other.
- Agreement type and document set.
- Governing law and venue.
- Business owner, legal reviewer, and deadline.
- Playbook or fallback positions from `~/.ostwin/legal-profiles/practices/contracts.md`, if available.

## Review Focus

Check scope, payment, term, termination, confidentiality, data protection, IP, warranties, indemnity, liability cap, insurance, assignment, audit rights, dispute resolution, governing law, and operational obligations.

## Output

Produce:
- Reviewer note with sources and assumptions.
- Issue table: clause, risk, business impact, legal review flag, proposed fallback.
- Escalation list.
- Open questions.
- Decision options for counsel.
