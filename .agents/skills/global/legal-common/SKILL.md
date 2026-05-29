---
name: legal-common
description: "Use when any legal, compliance, policy, contract, litigation, privacy, IP, employment, corporate, clinic, or law-student task needs shared guardrails."
tags: [legal, guardrails, attorney-review, citation-hygiene, profile]
trust_level: community
category: Legal
enabled: true
applicable_roles: [audit, qa, manager, staff-manager]
---

# Legal Common

Shared baseline for OSTwin legal skills. Use this skill to establish role, jurisdiction, profile context, source provenance, privilege posture, output destination, and review requirements before any legal workflow.

## Mandatory Legal Gate

Before substantive work, identify:
- User role: legal professional, supervised non-legal user, or unsupervised non-legal user.
- Jurisdiction or forum. If unknown and material, ask.
- Source set: user-provided documents, retrieved sources, model knowledge, or mixed.
- Privilege/confidentiality posture and intended destination.
- Whether a qualified attorney or authorized legal professional will review the output.

All legal outputs are drafts for qualified attorney review. They are not legal advice, final legal conclusions, filings, or substitutes for counsel.

## Activation Contract

For high-stakes work, externally shared work, or any output that could guide a legal decision:
1. Check the OSTwin profile paths below and state whether company, practice, and matter context was loaded, absent, or assumed.
2. **When the task depends on user-provided documents, contracts, PDFs, DOCX, exhibits, filings, policies, or other source files: apply `source-document-intake` before legal analysis.** Record extraction method and read coverage per that skill's provenance output requirements.
3. State document/source read coverage: complete, partial, sampled, excerpt-only, OCR-needed, conversion-needed, or not provided.
4. Confirm the intended audience and output destination before writing privileged analysis or external-facing text.
5. If any gate item is unknown, either ask a focused question or proceed only with an explicit gap marker.
6. Run `references/legal-output-checklist.md` before the final output.

Do not treat generic legal positions as the user's house playbook. If profile data is absent, label the work as unconfigured and avoid "standard position" claims.

## Mixed User Handling

- Legal professionals: use precise legal framing, work-product markings when appropriate, and a concise reviewer note.
- Non-legal users: use plain language, state what to escalate, and avoid telling them what legal position to take.
- If the destination is outside the privilege circle or unclear, stop and clarify before preparing privileged analysis.

## OSTwin Role Routing

These legal skills provide domain context. They do not replace OSTwin role gates.

- `manager`: use `discover-skills` to attach relevant `legal-*` global skills to a war-room.
- `qa`: use `review-task` or `review-epic` for acceptance-criteria review; attach legal skills only for legal-domain checks.
- `audit`: use audit skills for compliance, privacy, regulatory, investigation, and risk-decision workflows.
- `staff-manager`: use `review-the-review` or deep review skills for critical legal/compliance QA passes.
- Design or principal review roles: use only when legal requirements change system architecture, public APIs, or technical standards.

If a task asks for "legal review" in an OSTwin war-room, route the review through the appropriate OSTwin role and treat the legal skill as the domain checklist attached to that role.

## Source Discipline

Use provenance tags consistently:
- `[user provided]` for material supplied in the session.
- `[retrieved source]` only for sources actually fetched or opened in the session.
- `[model knowledge - verify]` for uncited or remembered legal statements.
- `[needs source]` where a legal assertion requires verification before reliance.

Never invent pin cites, deadlines, statute text, case holdings, registration numbers, or filing requirements. If a source is missing, say what is missing and mark the item for verification.

Current-law, filing, deadline, citation, regulator, and venue-specific assertions require a checked source. Without one, mark the assertion `[model knowledge - verify]` or `[needs source]`.

When the user or plan names a current-law source set, treat those sources as the controlling research target. Do not default to older remembered regimes or generic model knowledge if a newer named source appears applicable. If the sources are not available to open or quote, state that limitation at the top, produce only an intake/source-request or operational scaffold, and keep legal rule statements out of the decision layer.

## OSTwin Profile Paths

Preferred reusable context:
- `~/.ostwin/legal-profiles/company.md`
- `~/.ostwin/legal-profiles/practices/<practice>.md`
- `~/.ostwin/legal-profiles/matters/<matter-slug>/matter.md`
- `~/.ostwin/legal-profiles/verification-log.md`

Use profile data when available. If profile data is absent, proceed with explicit assumptions and mark the output as unconfigured.

## Output Frame

Start high-stakes outputs with:
- Reviewer note: sources used, read coverage (per `source-document-intake` provenance output when source documents were opened), verification gaps, jurisdiction assumptions, and attorney-review requirement.
- Draft marking: legal professional work product or non-legal research notes, depending on user role.
- Decision options: practical next steps without choosing the legal decision for the user.

When an output cites authority or legal facts, append or update `references/citation-verification-log-template.md` style entries if a verification log is requested or available.
