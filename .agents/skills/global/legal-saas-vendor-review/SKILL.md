---
name: legal-saas-vendor-review
description: "Use when reviewing SaaS, cloud, software, vendor, subscription, order form, SLA, security, or data-processing contract materials."
tags: [legal, saas, vendor, cloud, security, data-protection]
trust_level: community
category: Legal
enabled: true
applicable_roles: [audit, qa, manager, staff-manager]
---

# Legal SaaS Vendor Review

Use this skill for SaaS and technology vendor agreements where contract, privacy, security, and operational risk intersect.

## Mandatory Legal Gate

Apply `legal-common` first. Outputs are drafts for qualified attorney review, not legal advice or final legal conclusions. Non-legal users receive vendor-risk summaries and escalation guidance.

## Review Inputs

Confirm service type, data handled, customer role, vendor role, term, order form, DPA, security exhibit, SLA, support terms, and procurement owner.

## Review Focus

Check:
- Auto-renewal and cancellation windows.
- Data use, subprocessors, breach notice, and audit rights.
- Security commitments and certifications.
- Availability, credits, support, and disaster recovery.
- IP ownership and feedback rights.
- Liability cap, carveouts, indemnity, warranties, suspension, termination, export controls, and AI/data-training language.

## Output

Return a vendor review memo with business impact, legal risk, security/privacy flags, required approvals, and fallback asks for counsel.
