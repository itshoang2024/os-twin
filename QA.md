# QA - Current Project Review Strategy

> Reviewer: qa  
> Date: 2026-06-08 03:30  
> Verdict: PENDING / STRATEGY WITH INITIAL SMOKE FINDING

## Scope

Review scope is the current project at `/Users/paulaan/PycharmProjects/os-twin`, with emphasis on whether the dashboard and agent platform express the intended product direction: a Harnessing Platform / super OS for agents with roles, skills, plans, war-room channels, master-agent orchestration, manager-mediated delegation, channel pairing, and cross-bot/company-specific AI-agent platform concepts.

Primary areas under review:

- Backend availability via `python dashboard/api.py` on default port `3366`.
- Frontend under `dashboard/fe`, including API-base configuration and frontend-to-backend connectivity.
- Navigation and information architecture for Home, Plans, Knowledge, Roles, Skills, MCP, Settings, and Settings → Channels.
- Role, skill, plan, war-room, channel, and master-agent workflows.
- Telegram/Slack/Discord channel setup and pairing concepts where implemented.
- QA automation handoff requirements for screenshots and browser evidence.

## Inputs Reviewed

- User brief: current chat assignment.
- Repo structure: CodeGraph and file listing.
- Recent Memory:
  - `verification/dashboard/dashboard-fe-tests-green.md`: frontend Vitest suite was recently fixed and verified green, 713 tests.
  - `code/agents/roles/manager-rolemd-mediation-update.md`: manager is lifecycle authority and mediation judge.
  - `code/agents/manager/managerloop-helpers-triage-prompt-compilation.md`: manager triage prompt compilation and member-role context were added.
  - `code/bot/connectors/botsrcconnectorstelegramts-persisted-pairing.md` / Slack pairing memories: persisted pairing and explicit `/pair` ownership are important channel-contract concepts.
- Knowledge query: `b8b7a1769154` returned limited dashboard-specific guidance; relevant guidance is regression-first testing, no TypeScript build errors, screenshot parity, and performance budgets for interactive UI.
- Git baseline:
  - HEAD: `f9833755 (main, origin/main) release-2026-06-05 (#193)`
  - Working tree: only untracked `edd/EPIC-006-verification-migration-operational-readiness.md`.
  - No unstaged or staged tracked diffs.
- Code reviewed:
  - `dashboard/api.py`
  - `dashboard/routes/channels.py`
  - `dashboard/master_agent.py`
  - `dashboard/fe/package.json`
  - `dashboard/fe/src/lib/api-client.ts`
  - `dashboard/fe/src/lib/runtime-config.ts`
  - `dashboard/fe/src/app/page.tsx`
  - `dashboard/fe/src/app/channels/page.tsx`
  - `dashboard/fe/src/components/layout/Sidebar.tsx`
  - `dashboard/fe/src/components/settings/ChannelsPanel.tsx`
  - `dashboard/fe/playwright.config.ts`
  - Existing Cypress and Playwright e2e specs.

## Assumptions

- Backend default API port is `3366` unless started with `--port`.
- Frontend dev server should run from `dashboard/fe` and target the backend API using `NEXT_PUBLIC_API_BASE_URL=http://localhost:3366/api` when not using a same-origin proxy.
- Screenshots have **not** been captured in this review. QA automation must verify and store screenshot evidence before any visual pass claim.
- Cross-bot communication is partly conceptual/product-directional unless backed by routes/UI/tests; QA should mark missing/ambiguous product behavior as conceptual gaps, not implementation failures, until manager confirms requirements.

## Test Environment / Run Commands

Recommended local commands:

```bash
# Backend
python dashboard/api.py --port 3366
curl -i http://localhost:3366/api/health
curl -i http://localhost:3366/api/plans
curl -i http://localhost:3366/api/roles
curl -i http://localhost:3366/api/skills
curl -i http://localhost:3366/api/channels

# Frontend
cd dashboard/fe
NEXT_PUBLIC_API_BASE_URL=http://localhost:3366/api PORT=3001 pnpm dev
pnpm test
pnpm lint
pnpm build
pnpm exec playwright test
```

Commands actually executed during this initial QA pass:

| Command | Result | Evidence |
| --- | --- | --- |
| `git status --short` | PASS with untracked file only | `?? edd/EPIC-006-verification-migration-operational-readiness.md` |
| `git log --oneline --decorate -n 5` | PASS | HEAD `f9833755` |
| `git diff --stat`, `git diff --name-status`, `git diff --cached --name-status` | PASS / no tracked changes | Empty output |
| `python -m pytest dashboard/tests/test_channels_api.py dashboard/tests/test_master_agent.py dashboard/tests/test_frontend_fallback.py -q` | FAIL | 59 passed, 1 failed: `TestResolveModelProvider.test_google_vertex_is_preserved` expected `google-vertex`, actual `google` |
| `pnpm test -- src/__tests__/api-client.test.ts src/__tests__/SettingsSidebar.test.tsx` from `dashboard/fe` | PASS | Vitest ran full suite: 58 files, 714 tests passed |

## Initial Finding From Smoke Verification

| Severity | Area | Issue | Expected | Actual | Suggested next action |
| --- | --- | --- | --- | --- | --- |
| MAJOR | Master-agent model routing | `google-vertex` provider preservation test fails. | `dashboard.master_agent.get_model_and_provider()` preserves provider `google-vertex` for Vertex AI. | Provider is normalized to `google`, contradicting the test and nearby code comment. | @engineer should reconcile `_LEGACY_PROVIDER_IDS` and provider normalization; either preserve `google-vertex` or update tests/spec if product intentionally moved to `google`. |

## Change / Feature Inventory

| Area | Implementation evidence | Risk | Planned verification |
| --- | --- | --- | --- |
| Backend API | `dashboard/api.py` includes routers for auth, plans, rooms, system, mcp, skills, roles, memory, channels, command, files, settings, knowledge, ai, chat. | Backend startup can be blocked by env/model/MCP lifecycle issues. | Start backend, verify health and core endpoints, inspect logs. |
| Frontend API config | `runtime-config.ts` defaults to `/api`; env override via `NEXT_PUBLIC_API_BASE_URL`; WebSocket URL uses browser origin or env. | If frontend is on `localhost:3001` and backend is on `3366`, `/api` hits Next unless proxy exists; user explicitly said frontend should target backend port. | Run frontend with explicit env; verify network requests go to `3366`; test websocket URL. |
| Navigation | Sidebar links Home, Plans, Knowledge, Roles, Skills, MCP, Settings. Channels route redirects to Settings → Channels. | No visible top-level War Rooms route; channel concepts hidden under Settings; super-OS narrative may be unclear. | Browser nav sweep across all routes and deep links. |
| Home/master agent | Home prompt creates `/plans/threads`; recent ideas link to `/ideas/{id}`. | `/ideas` route was not found in page glob; possible broken navigation after prompt submit. | Verify prompt submit route, thread creation, and resulting page. |
| Plans/war rooms | Routes and tests exist for plan rooms and DAG/epics. | Legacy root Cypress tests may target old static dashboard selectors, not current Next UI. | Verify plan list/detail, room cards, channel feed, epics, DAG, status transitions. |
| Roles/skills | Roles and skills pages/hooks/routes exist; role editor references model, skills, MCP. | Need contract checks between role fields, role config files, and skills taxonomy. | CRUD/edit tests with validation and persistence checks. |
| Channels | `channels.py` exposes Telegram/Discord/Slack setup, connect/disconnect, pairing, settings; `ChannelsPanel.tsx` shows setup/settings/notifications. | Credentials are persisted in `~/.ostwin/channels.json`; UI may expose pairing code and lacks explicit cross-bot/CEO↔CFO pairing mental model. | API+UI tests for setup, pairing regeneration, secrets masking, per-target events. |
| Telegram/cross-bot concepts | Bot memories indicate Telegram/Slack persisted pairing and owner detection. | Frontend may not show company-agent-to-company-agent channel pairing, only platform connectors. | Manager should clarify expected product narrative and required UI affordances. |

## Test Matrix / Critique Items

| # | Category | Area | Test / critique item | Expected result | Evidence target | Owner |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | Functional | Backend | Start `python dashboard/api.py --port 3366`. | Server starts without tracebacks; logs show dashboard path and routers available. | Terminal log, `/api/health` response. | @engineer |
| 2 | Functional | Backend | GET `/api/health` or closest health endpoint. | 200 response with stable health payload. | curl output. | @engineer |
| 3 | Functional | Backend | GET `/api/plans`, `/api/roles`, `/api/skills`, `/api/channels`. | All return expected JSON contracts; unauthorized behavior matches auth mode. | curl/API test output. | @engineer |
| 4 | Functional | Frontend config | Run frontend with `NEXT_PUBLIC_API_BASE_URL=http://localhost:3366/api`. | Browser network requests target backend port, not Next dev server `/api`. | DevTools/network screenshot. | @frontend-engineer + @qa-automation-engineer |
| 5 | Functional | Frontend config | Run frontend without env override. | Either documented proxy works or UI clearly fails with actionable backend-port guidance. | Screenshot + console/network logs. | @frontend-engineer |
| 6 | Functional | WebSocket | Verify `getWebSocketUrl()` and live connection to `/api/ws`. | Connected event received; reconnect/error state visible. | Browser console/network WS screenshot. | @frontend-engineer |
| 7 | Navigation | Sidebar | Visit each Sidebar route: `/`, `/plans`, `/knowledge`, `/roles`, `/skills`, `/mcp`, `/settings`. | No 404/hydration crash; active state is correct. | Per-page screenshot. | @qa-automation-engineer |
| 8 | Navigation | Channels | Visit `/channels`. | Redirects to `/settings?tab=channels`; messaging is transient and accessible. | Screenshot before/after redirect. | @frontend-engineer |
| 9 | UX clarity | Product narrative | Home should communicate “agent OS / harnessing platform” beyond “What do you want to build?” | User understands roles, skills, plans, channels, and delegation from first screen or onboarding. | Home screenshot + UX notes. | @frontend-engineer + @manager |
| 10 | Functional | Home prompt | Submit a prompt with no template. | Thread is created and navigates to a valid page. | Request payload, resulting page screenshot. | @frontend-engineer |
| 11 | Functional | Home prompt | Submit with attached template. | Template metadata and content are sent correctly; no raw template leaks into textarea. | Network payload, UI screenshot. | @frontend-engineer |
| 12 | Error handling | Home prompt | Backend unavailable during submit. | Non-alert, styled error state with retry guidance; no silent failure. | Screenshot + console log. | @frontend-engineer |
| 13 | Functional | Plans list | Plans list loads from backend. | Recent plans on Home and Plans page match API data. | API response + UI screenshot. | @frontend-engineer |
| 14 | Functional | Plan detail | Open a plan detail page. | Plan title/content/epics/rooms render; no missing fields. | Screenshot + network logs. | @frontend-engineer |
| 15 | Functional | War rooms | For a plan with rooms, room cards show room id, task ref, status, progress. | UI matches `/api/plans/{id}/rooms`. | API response + screenshot. | @frontend-engineer |
| 16 | Functional | Channel feed | Open room/channel feed if present. | Messages show from/to/type/ref/body and update on new message. | Screenshot + posted test message. | @engineer + @frontend-engineer |
| 17 | Data consistency | War-room status | Change room status via backend/tool. | UI updates status and progress consistently. | Before/after screenshots. | @engineer |
| 18 | Functional | Manager delegation | Verify manager-mediated task delegation flow from plan/epic to rooms. | Manager role is visibly lifecycle authority; tasks route to correct role/evaluator. | Channel log + UI screenshot. | @manager + @engineer |
| 19 | Functional | Master agent | Verify master model setting persists and is used for chat/delegation. | Chosen provider/model survives reload and backend uses same provider. | Settings screenshot + API/log evidence. | @engineer |
| 20 | Regression | Master agent | `google-vertex` provider preservation. | Test passes or spec is updated. | Pytest output. | @engineer |
| 21 | Functional | Roles | Roles page lists role definitions with tags/skills/trust level if available. | Role cards/table match backend role contract. | API response + screenshot. | @frontend-engineer |
| 22 | Functional | Role editor | Create/edit role with model, skills, MCP server selections. | Saved role persists and reloads with selected fields. | Before/after screenshot + API payload. | @frontend-engineer |
| 23 | Validation | Role editor | Missing required role fields. | Inline validation; no malformed role file/API write. | Screenshot. | @frontend-engineer |
| 24 | Functional | Skills | Skills page/library lists skills with categories/role fit. | Search/filter/detail/edit behavior works. | Screenshot. | @frontend-engineer |
| 25 | Data consistency | Skills↔roles | Skill selections in role editor use same skill IDs as skills API. | No display-name/id mismatch. | API payload + UI screenshot. | @frontend-engineer |
| 26 | Functional | MCP | MCP page lists server configs and status. | Add/test/remove flows work or show clear not-configured state. | Screenshot + API response. | @frontend-engineer |
| 27 | Functional | Knowledge | Knowledge list/detail/import/query states work. | Namespace data matches backend; empty and error states are clear. | Screenshots across states. | @frontend-engineer |
| 28 | Functional | Channels setup | Telegram setup card loads steps and validates token input. | Finish disabled until required fields; connect creates config and pairing code. | Screenshot + API response. | @frontend-engineer |
| 29 | Functional | Channels setup | Slack setup requires bot token and app token. | Finish disabled until both; optional signing secret handled. | Screenshot. | @frontend-engineer |
| 30 | Functional | Channels setup | Discord setup requires token/client/server ID. | Finish disabled until all required fields. | Screenshot. | @frontend-engineer |
| 31 | Security | Channels | Secrets are masked in UI and not logged to console/network beyond request body. | Password inputs; no visible token after save. | Screenshot + console inspection. | @engineer + @frontend-engineer |
| 32 | Security | Channels | Channel credentials stored and read safely. | Manager confirms acceptable storage or engineer moves secrets to vault. | Code review + config evidence. | @manager + @engineer |
| 33 | Functional | Pairing | Regenerate pairing code. | New code displayed; old code invalidated where bot connector enforces pairing. | API response + UI screenshot. | @engineer |
| 34 | Conceptual completeness | Cross-bot | CEO Bot ↔ CFO Bot via Telegram paired channel concept. | UI/API either supports agent-to-agent pairing explicitly or product marks it future scope. | Requirements decision + UI concept screenshot if present. | @manager |
| 35 | UX clarity | Channels | “Users” metric on connected channel should explain users vs paired channel targets. | Labels disambiguate authorized users, channel items, and conversation IDs. | Screenshot + UX notes. | @frontend-engineer |
| 36 | Accessibility | Global nav | Keyboard navigation through sidebar and cards. | Focus visible, logical order, links/buttons named. | Keyboard recording/screenshots. | @frontend-engineer |
| 37 | Accessibility | Forms | Inputs in settings/channels have programmatic labels. | Labels use `htmlFor`/`id` or equivalent accessible name. | axe/Playwright accessibility report. | @frontend-engineer |
| 38 | Accessibility | Color/contrast | Status badges, muted text, primary buttons meet contrast. | WCAG AA for normal text and UI controls. | axe/lighthouse report. | @frontend-engineer |
| 39 | Responsiveness | Dashboard | Test 390px, 768px, 1024px, 1440px widths. | No horizontal overflow; sidebar auto-collapse works; cards remain usable. | Screenshot set. | @qa-automation-engineer |
| 40 | Responsiveness | Channels | Three-column channel cards collapse cleanly. | Setup forms fit mobile without clipping. | Screenshot set. | @qa-automation-engineer |
| 41 | Error handling | API errors | Simulate 500/404 on list endpoints. | Page displays recoverable empty/error state, not raw exception. | Mocked route screenshot. | @frontend-engineer |
| 42 | Data consistency | API client unwrap | Verify wrapped backend arrays unwrap only when intended. | Detail endpoints keep `{plan, epics}`; list endpoints return arrays to hooks. | Unit tests. | @frontend-engineer |
| 43 | E2E health | Playwright | Run `pnpm exec playwright test`. | E2E suite passes against backend-targeted frontend. | Playwright report/screenshots. | @qa-automation-engineer |
| 44 | E2E health | Legacy Cypress | Assess root `cypress/e2e` selector drift. | Either update old AgentOS selectors or retire as legacy. | Cypress report + manager decision. | @manager + @frontend-engineer |
| 45 | Conceptual completeness | Company-specific AI platform | UI should show how a company’s roles/skills/channels combine into an operating platform. | Clear IA or onboarding path from role definitions → skills → plans → channels → agent delegation. | UX walkthrough screenshots. | @manager + @frontend-engineer |

## Evidence Plan / Screenshots Required

No screenshots are currently verified. @qa-automation-engineer should capture and save artifacts under a stable folder such as `artifacts/browser-evidence/current-review/`.

Required screenshots/states:

1. Backend terminal start and successful `/api/health` response.
2. Home page initial load with recent plans and activity feed.
3. Home prompt before submit, loading state, success destination, and backend-down error state.
4. Sidebar expanded and auto-collapsed states.
5. Plans list empty, loading, and populated states.
6. Plan detail page with epics/rooms/DAG where available.
7. War-room/channel feed global state and room-filtered state.
8. Roles list and role editor create/edit/validation states.
9. Skills list/library and skill detail/editor states.
10. MCP page list/config/status state.
11. Knowledge list and namespace detail/import/query states.
12. Settings providers/runtime/memory/knowledge/channels tabs.
13. Channels page redirect to Settings → Channels.
14. Telegram setup wizard empty/valid/connected/settings states.
15. Slack setup wizard empty/valid/connected/settings states.
16. Discord setup wizard empty/valid/connected/settings states.
17. Pairing code visible/regenerated state, with confirmation of masking for credentials.
18. Responsive screenshots at 390px, 768px, 1024px, 1440px for Home, Plans, Roles, Skills, Settings → Channels.
19. Accessibility evidence: keyboard focus screenshots and axe/Lighthouse output.
20. Browser console/network evidence showing frontend requests target `localhost:3366/api`.

## Proposed Acceptance Criteria for @frontend-engineer

1. Frontend dev mode can be run with `NEXT_PUBLIC_API_BASE_URL=http://localhost:3366/api` and all dashboard API calls use that backend target.
2. All sidebar routes load without 404, hydration errors, or console exceptions.
3. Home prompt creation navigates to an implemented, valid route and displays styled error feedback when backend/thread creation fails.
4. Pages for Plans, Knowledge, Roles, Skills, MCP, and Settings have loading, empty, success, and error states.
5. Settings → Channels supports Telegram, Slack, and Discord setup forms with validation, masked secrets, pairing-code display/regeneration, and notification preferences.
6. Role editor preserves model, skills, and MCP selections after save/reload.
7. UI labels explain the platform model: roles + skills + plans + war rooms + channels + manager/master agent orchestration.
8. All interactive controls are keyboard reachable with visible focus and accessible names.
9. Responsive layouts are usable at mobile/tablet/desktop widths with no horizontal overflow.
10. Frontend passes `pnpm test`, `pnpm lint`, `pnpm build`, and Playwright e2e tests.

## Proposed Acceptance Criteria for @engineer

1. `python dashboard/api.py --port 3366` starts cleanly and exposes health, plans, roles, skills, channels, rooms, settings, MCP, AI/chat endpoints as documented.
2. Backend API contracts match frontend hooks, including wrapped-vs-unwrapped response shapes.
3. Master-agent provider/model selection is deterministic, persisted, and test-aligned; `google-vertex` behavior is resolved.
4. Manager-mediated delegation creates plan-scoped war rooms with correct lifecycle/channel artifacts.
5. Channel API persists connector config safely, regenerates pairing codes, and notifies/restarts bot manager when needed.
6. Telegram/Slack/Discord connectors enforce explicit pairing/authorization and use the same owner model.
7. Cross-bot communication requirements are either implemented as API contracts or documented as future scope.
8. Backend tests for channels, master agent, rooms, roles, skills, and plan delegation pass in CI.
9. Secrets are not exposed in logs, GET responses, or frontend state beyond intentional masked status.
10. Legacy Cypress tests are reconciled with the current Next.js dashboard or retired with manager approval.

## Blockers / Questions for @manager

1. The user’s product goal includes “CEO Bot ↔ CFO Bot via Telegram when channels are paired.” Is this required now, or a future conceptual target?
2. Should “Channels” remain under Settings, or should it be top-level for the super-OS narrative?
3. What exact user journey should demonstrate “company-specific AI Agent platforms that can do all jobs”? Example: create company roles → attach skills → launch plan → delegate war rooms → cross-bot notification.
4. Is root Cypress legacy dashboard (`Agent OS — Command Center`) still expected, or should QA treat it as obsolete after the Next.js dashboard migration?
5. What is the source of truth for screenshots: Playwright artifacts, agent-browser, or both?
6. Should channel credentials remain in `~/.ostwin/channels.json`, or must they move to vault-backed storage?
7. Which auth mode should QA use for browser testing: dev anonymous mode or real first-run auth?
8. Should `google-vertex` be preserved as an OpenCode provider, or normalized to `google`?

## Subagent Prompt Plan

The requested Task tool is not available in this environment, so these are the prompts QA would send to the named subagents.

### Prompt for subagent: qa

Perform a full QA review loop for `/Users/paulaan/PycharmProjects/os-twin`. Use `QA.md` as the plan/report artifact. Verify backend startup with `python dashboard/api.py --port 3366`, frontend API targeting via `NEXT_PUBLIC_API_BASE_URL=http://localhost:3366/api`, navigation across Home/Plans/Knowledge/Roles/Skills/MCP/Settings, and workflows for roles, skills, plans, war rooms, channels, master-agent delegation, manager-mediated routing, pairing, and cross-bot concepts. Do not claim screenshots unless QA automation provides artifacts. Record all command results and verdict evidence.

### Prompt for subagent: frontend-engineer

Review and update the Next.js frontend under `dashboard/fe` so it clearly supports the Harnessing Platform / super OS product narrative. Ensure frontend dev mode targets backend port 3366 via `NEXT_PUBLIC_API_BASE_URL`, all sidebar routes work, Home prompt navigates to an implemented route, pages have loading/empty/error states, Channels under Settings supports Telegram/Slack/Discord setup/pairing/preferences with masked secrets, and responsive/accessibility standards are met. Run `pnpm test`, `pnpm lint`, `pnpm build`, and Playwright. Address QA matrix items assigned to @frontend-engineer in `QA.md`.

### Prompt for subagent: engineer

Review and update backend/API workflows for `/Users/paulaan/PycharmProjects/os-twin`. Ensure `python dashboard/api.py --port 3366` starts cleanly and exposes stable contracts for plans, roles, skills, rooms, channels, settings, MCP, master-agent, and chat/delegation flows. Fix or resolve the failing `dashboard/tests/test_master_agent.py::TestResolveModelProvider::test_google_vertex_is_preserved` provider behavior. Verify manager-mediated delegation, plan-scoped war-room artifacts, channel pairing/authorization, bot restart signaling, and safe credential persistence. Run targeted and full backend tests relevant to channels/master-agent/plans/rooms.

### Prompt for subagent: manager

Resolve product and scope questions for the os-twin Harnessing Platform review. Confirm required user journeys for roles + skills + plans + war rooms + master-agent + manager delegation + channels. Decide whether cross-bot communication such as CEO Bot ↔ CFO Bot via Telegram pairing is in current acceptance scope. Decide whether Channels should be top-level or Settings-only. Decide whether legacy Cypress AgentOS tests remain valid. Clarify auth mode, screenshot evidence standard, and whether channel credentials must be vault-backed. Resolve expected `google-vertex` provider behavior.

### Prompt for subagent: qa-automation-engineer

Use browser automation to capture evidence for the current os-twin dashboard. Start backend on port 3366 and frontend from `dashboard/fe` with `NEXT_PUBLIC_API_BASE_URL=http://localhost:3366/api PORT=3001 pnpm dev`. Capture screenshots and network evidence for all pages/states listed in `QA.md` Evidence Plan, including responsive widths 390/768/1024/1440 and Settings → Channels setup/pairing flows. Use refs/selectors rather than coordinate clicks. Save artifacts under `artifacts/browser-evidence/current-review/` and report exact paths. Do not bypass auth/CAPTCHA; report blockers.

## Recommended Next Actions

1. @engineer fixes or adjudicates the `google-vertex` master-agent provider test failure.
2. @manager answers the eight scope questions above, especially cross-bot current-vs-future scope and legacy Cypress validity.
3. @frontend-engineer validates API-base behavior against backend port 3366 and fixes any broken navigation such as `/ideas/{id}` if not implemented.
4. @qa-automation-engineer captures the screenshot/evidence plan before any visual or UX pass is claimed.
5. QA reruns backend targeted tests, full frontend tests, build/lint, and browser e2e after fixes.

## Current QA Verdict

PENDING. Initial smoke verification found one backend regression/failing test in master-agent provider routing. No screenshot evidence has been captured yet, so visual/UX/browser claims remain unverified.
