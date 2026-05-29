---
name: legal-policy-gap-analysis
description: "Use when comparing policies, procedures, playbooks, controls, or public notices against legal, regulatory, or contractual requirements."
tags: [legal, policy, gap-analysis, compliance, controls]
trust_level: community
category: Legal
enabled: true
applicable_roles: [audit, qa, manager, staff-manager]
---

# Legal Policy Gap Analysis

Use this skill to compare a policy baseline against requirements and produce attorney-reviewable gaps.

## Mandatory Legal Gate

Apply `legal-common` first. Outputs are drafts for qualified attorney review, not legal advice or final legal conclusions. Non-legal users receive plain-language gaps and escalation guidance.

## Inputs

Capture current policy, target requirement source, jurisdiction, control owner, effective date, and enforcement risk.

## Analysis

Separate:
- Text gaps: policy does not say the required thing.
- Practice gaps: policy says it, but process evidence is missing.
- Ownership gaps: nobody owns the requirement.
- Evidence gaps: compliance may exist but proof is absent.

## Output

Return a gap table with requirement, current state, evidence, severity, owner, due date, and attorney-review flag. Draft replacement text only as a proposal.
