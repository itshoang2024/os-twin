---
name: legal-source-citation-hygiene
description: "Use when legal work cites cases, statutes, regulations, contracts, filings, policies, or document evidence that must be verified."
tags: [legal, citations, sources, verification, research]
trust_level: community
category: Legal
enabled: true
applicable_roles: [audit, qa, manager, staff-manager]
---

# Legal Source Citation Hygiene

Use this skill to keep legal assertions tied to real sources and to prevent fabricated citations or overconfident legal claims.

## Mandatory Legal Gate

Apply `legal-common` first. Outputs are drafts for qualified attorney review, not legal advice or final legal conclusions. Non-legal users receive plain-language verification notes and escalation guidance.

## Provenance Tags

Use:
- `[user provided]` for documents or facts supplied by the user.
- `[retrieved source]` for sources fetched in this session.
- `[model knowledge - verify]` for remembered law or uncited propositions.
- `[needs source]` for claims that cannot be relied on without verification.

Do not upgrade a tag because the proposition seems right. Tags describe provenance, not confidence.

## Verification Rules

- Every pin cite must point to a source actually available.
- Every deadline must identify the rule, contract clause, order, or statute used.
- Every quoted passage must be quoted from a source, not reconstructed.
- If the matter depends on current law and the source set is only named but not opened, classify legal-rule output as blocked or provisional; do not rely on remembered law as the primary authority.
- If the user provides newer authority names, do not substitute an older law, decree, policy, or regulator rule from memory except as a clearly labeled historical/background note.
- If a source conflicts with memory, surface the conflict and require verification.
- If a source cannot be opened, say so and explain the impact.

## Output

Add a reviewer note listing:
- Sources used.
- Sources not available.
- Items needing verification.
- Any verified facts suitable for `~/.ostwin/legal-profiles/verification-log.md`.

For high-stakes current-law work, include a "Source Sufficiency" line: `sufficient`, `limited`, or `blocked`. Use `blocked` when no current authoritative text, excerpts, or retrieved source is available for the rule being applied.
