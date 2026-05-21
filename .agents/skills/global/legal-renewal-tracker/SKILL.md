---
name: legal-renewal-tracker
description: "Use when extracting, checking, tracking, or reporting contract renewal, termination, notice, auto-renewal, or deadline information."
tags: [legal, contracts, renewals, deadlines, tracker]
trust_level: community
category: Legal
enabled: true
applicable_roles: [audit, qa, manager, staff-manager]
---

# Legal Renewal Tracker

Use this skill to turn contract terms into a reliable renewal and notice register.

## Mandatory Legal Gate

Apply `legal-common` first. Outputs are drafts for qualified attorney review, not legal advice or final legal conclusions. Non-legal users receive deadline summaries and escalation guidance.

## Extraction Rules

For each contract, capture:
- Agreement name and counterparty.
- Effective date, initial term, renewal term.
- Auto-renewal language.
- Notice deadline and method.
- Termination rights.
- Source clause and page or section.
- Owner and next action.

Do not calculate deadlines without showing the source language and calculation assumption.

## Output

Produce a register with status, due date, confidence, source cite, owner, and recommended escalation. Mark ambiguous clauses for attorney review.
