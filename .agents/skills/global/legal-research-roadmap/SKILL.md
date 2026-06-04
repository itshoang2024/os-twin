---
name: legal-research-roadmap
description: "Use when a legal question needs research planning, issue spotting, authority hierarchy, source selection, or verification steps."
tags: [legal, research, roadmap, authority, issue-spotting]
trust_level: community
category: Legal
enabled: true
applicable_roles: [audit, qa, manager, staff-manager]
---

# Legal Research Roadmap

Use this skill to turn a legal question into a research plan before drafting analysis.

## Mandatory Legal Gate

Apply `legal-common` first. Outputs are drafts for qualified attorney review, not legal advice or final legal conclusions. Non-legal users receive research leads and escalation guidance.

## Roadmap

1. State the question, posture, jurisdiction, and decision deadline.
2. Identify controlling authority hierarchy: constitution, statute, regulation, rule, case law, agency guidance, contract, policy.
3. Separate legal questions from factual questions.
4. Define search terms and primary sources to check.
5. Identify stale or fast-changing law that needs current verification.
6. Mark what can be answered now and what must wait for research.

## Guardrails

- Do not present a remembered case or rule as verified.
- Do not answer under the wrong jurisdiction without saying so.
- Do not turn research leads into legal conclusions.
- For non-legal users, phrase output as questions to ask counsel.

## Output

Return a research plan with issue list, source plan, verification checklist, and likely deliverable format.
