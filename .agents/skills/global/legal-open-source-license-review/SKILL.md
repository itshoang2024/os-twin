---
name: legal-open-source-license-review
description: "Use when reviewing open source licenses, dependency obligations, notices, copyleft risk, attribution, SaaS distribution, or OSS policy compliance."
tags: [legal, ip, open-source, licenses, compliance]
trust_level: community
category: Legal
enabled: true
applicable_roles: [audit, qa, manager, staff-manager]
---

# Legal Open Source License Review

Use this skill to classify OSS obligations for counsel and engineering review.

## Mandatory Legal Gate

Apply `legal-common` first. Outputs are drafts for qualified attorney review, not legal advice or final legal conclusions. Non-legal users receive compliance tasks and escalation guidance.

## Inputs

Capture package, version, license text, use mode, linking or modification, distribution model, SaaS exposure, repository, notices, and product owner.

## Review Focus

Classify permissive, weak copyleft, strong copyleft, network copyleft, unknown, custom, dual-license, or no-license items. Flag missing license files, license conflicts, attribution, source offer, patent clauses, and policy exceptions.

## Output

Return an OSS review table with license, source, use mode, obligations, risk flag, action owner, and attorney-review status. Do not approve a license exception without counsel.
