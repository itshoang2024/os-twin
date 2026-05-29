import { expect } from 'chai';
import sinon from 'sinon';
import api from '../src/api';
import { registry } from '../src/connectors/registry';
import * as sessions from '../src/sessions';
import {
  routeCommand,
  routeCallback,
  cmdHelp,
  cmdUnknown,
  COMMAND_REGISTRY,
  COMMANDS_NO_ARGS,
  COMMANDS_WITH_ARGS,
  ALL_PLATFORM_COMMANDS,
  DEFERRED_COMMANDS,
  buildDiscordSlashCommands,
  getCommandDef,
  getCommandsForPlatform,
  getCommandsWithArgsForPlatform,
  getCommandsWithoutArgsForPlatform,
} from '../src/commands';

describe('commands', () => {
  let sandbox: sinon.SinonSandbox;

  beforeEach(() => {
    sandbox = sinon.createSandbox();
    sessions.clearSession('u1', 'telegram');
    sessions.clearSession('u1', 'discord');
    sandbox.stub(api, 'getPlanAssets').resolves({ assets: [], count: 0 });
    sandbox.stub(api, 'getPlanEpics').resolves({ epics: [], count: 0 });
  });

  afterEach(() => {
    sandbox.restore();
  });

  // ── Fixtures ────────────────────────────────────────────────────

  const MOCK_ROOMS = {
    rooms: [
      { room_id: 'room-1', status: 'passed', message_count: 10, epic_ref: 'E-1' },
      { room_id: 'room-2', status: 'engineering', message_count: 5, epic_ref: 'E-2' },
      { room_id: 'room-3', status: 'failed-final', message_count: 3, epic_ref: 'E-3' },
    ],
    summary: { total: 3, passed: 1, engineering: 1, failed_final: 1, pending: 0, qa_review: 0, fixing: 0 },
  };

  const MOCK_PLANS = {
    plans: [
      { plan_id: 'p1', title: 'Auth System', status: 'launched', epic_count: 3 },
      { plan_id: 'p2', title: 'Dashboard UI', status: 'draft', epic_count: 2 },
    ],
    count: 2,
  };

  // ── Menu commands (pure, no API) ─────────────────────────────

  describe('routeCommand — menu', () => {
    it('returns menu with 4 category buttons', async () => {
      const [resp] = await routeCommand('u1', 'telegram', 'menu');
      expect(resp.buttons).to.have.lengthOf(4);
      const data = resp.buttons!.flat().map(b => b.callbackData);
      expect(data).to.include('menu:cat:monitoring');
      expect(data).to.include('menu:cat:plans');
      expect(data).to.include('menu:cat:skills');
      expect(data).to.include('menu:cat:system');
    });
  });

  describe('routeCommand — help', () => {
    it('returns help text with all commands listed', async () => {
      const [resp] = await routeCommand('u1', 'telegram', 'help');
      expect(resp.text).to.include('/menu');
      expect(resp.text).to.include('/draft');
      expect(resp.text).to.include('/dashboard');
      expect(resp.text).to.include('/status');
    });
  });

  describe('routeCommand — unknown', () => {
    it('returns unknown command message', async () => {
      const [resp] = await routeCommand('u1', 'telegram', 'nonexistent');
      expect(resp.text).to.include('Unknown command');
    });
  });

  describe('routeCommand — draft', () => {
    it('sets awaiting_idea mode when /draft has no args', async () => {
      sessions.setPlan('u1', 'telegram', 'old-plan');
      sessions.setMode('u1', 'telegram', 'editing');

      const [resp] = await routeCommand('u1', 'telegram', 'draft');
      const session = sessions.getSession('u1', 'telegram');

      expect(resp.text).to.include('Send me the idea');
      expect(session.mode).to.equal('awaiting_idea');
      expect(session.activePlanId).to.equal(null);
    });

    it('uses a fresh OpenCode conversation for each explicit /draft idea', async () => {
      const askCommandStub = sandbox.stub(api, 'askOpenCodeCommand').resolves({
        text: 'Plan created: new-plan',
        conversation_id: 'ignored',
        actions: [{ type: 'plan_created', plan_id: 'new-plan' }],
      });
      sessions.setPlan('u1', 'telegram', 'old-plan');
      sessions.setMode('u1', 'telegram', 'editing');

      const [resp] = await routeCommand('u1', 'telegram', 'draft', 'build a note app');
      const request = askCommandStub.firstCall.args[0];
      const session = sessions.getSession('u1', 'telegram');

      expect(resp.text).to.include('Plan created');
      expect(request.command).to.equal('draft');
      expect(request.arguments).to.equal('build a note app');
      expect(request.conversation_id).to.match(/^connector:telegram:u1:draft:/);
      expect(request.conversation_id).to.not.equal('connector:telegram:u1');
      expect(session.activePlanId).to.equal('new-plan');
      expect(session.mode).to.equal('idle');
    });
  });

  describe('cmdUnknown — typo fallback', () => {
    it('suggests the closest registered command for a 1-char typo', () => {
      // /drafft → /draft (edit distance 1)
      const resp = cmdUnknown('/drafft hello world', 'telegram');
      expect(resp.text).to.include('Unknown command');
      expect(resp.text).to.include('/drafft');
      expect(resp.text).to.include('Did you mean');
      expect(resp.text).to.include('/draft');
    });

    it('strips arguments and the leading slash when echoing the typo', () => {
      const resp = cmdUnknown('/healt now please', 'telegram');
      expect(resp.text).to.include('`/healt`');
      // The whole command-with-args should NOT appear inside the backticks.
      expect(resp.text).to.not.include('healt now please');
    });

    it('omits "Did you mean" when no command is within edit distance 2', () => {
      // 7 chars different from every command — no suggestions.
      const resp = cmdUnknown('/zzzzzzzzzz', 'telegram');
      expect(resp.text).to.include('Unknown command');
      expect(resp.text).to.not.include('Did you mean');
      expect(resp.text).to.include('/help');
    });

    it('always renders the 4-category menu buttons', () => {
      const resp = cmdUnknown('/whatever', 'telegram');
      const labels = (resp.buttons || []).flat().map(b => b.label);
      expect(labels).to.include('📊 Monitoring');
      expect(labels).to.include('📝 Plans & AI');
      expect(labels).to.include('🧠 Skills & Roles');
      expect(labels).to.include('⚙️ System');
      const callbacks = (resp.buttons || []).flat().map(b => b.callbackData);
      expect(callbacks).to.deep.equal([
        'menu:cat:monitoring',
        'menu:cat:plans',
        'menu:cat:skills',
        'menu:cat:system',
      ]);
    });

    it('matches case-insensitively (/MENU → /menu)', () => {
      const resp = cmdUnknown('/MENU', 'telegram');
      expect(resp.text).to.include('Did you mean');
      expect(resp.text).to.include('/menu');
    });

    it('respects the platform filter when suggesting (discord-only commands not offered to telegram)', () => {
      // /pingg is one char off /ping, which is discordOnly — telegram should
      // not surface it as a suggestion. Inspect the "Did you mean" line only
      // since `/pingg` itself contains the substring `/ping`.
      const suggestionLine = (text: string) =>
        text.split('\n').find(l => l.includes('Did you mean')) || '';

      const tg = cmdUnknown('/pingg', 'telegram');
      expect(suggestionLine(tg.text)).to.not.include('`/ping`');

      const dc = cmdUnknown('/pingg', 'discord');
      expect(suggestionLine(dc.text)).to.include('`/ping`');
    });

    it('limits suggestions to at most 5 commands', () => {
      const resp = cmdUnknown('/sk', 'telegram');
      // Each suggestion appears as `/<name>` — count those occurrences in the
      // "Did you mean" line only.
      const line = resp.text.split('\n').find(l => l.includes('Did you mean')) || '';
      const matches = line.match(/`\/[a-zA-Z0-9_]+`/g) || [];
      expect(matches.length).to.be.at.most(5);
    });
  });

  // ── Monitoring commands (require API stubs) ───────────────────

  describe('routeCommand — dashboard', () => {
    it('renders dashboard with room counts', async () => {
      sandbox.stub(api, 'getRooms').resolves(MOCK_ROOMS);

      const [resp] = await routeCommand('u1', 'telegram', 'dashboard');
      expect(resp.text).to.include('COMMAND CENTER');
      expect(resp.text).to.include('ONLINE');
    });

    it('shows zeros when no rooms exist', async () => {
      sandbox.stub(api, 'getRooms').resolves({ rooms: [], summary: {} });

      const [resp] = await routeCommand('u1', 'telegram', 'dashboard');
      expect(resp.text).to.include('0');
    });

    it('counts active rooms via new keys (developing/review)', async () => {
      // New-shape summary: dashboard 3366 reports developing/review.
      sandbox.stub(api, 'getRooms').resolves({
        rooms: [],
        summary: { total: 5, passed: 1, failed_final: 0, pending: 1, developing: 2, review: 1, fixing: 0 },
      });
      const [resp] = await routeCommand('u1', 'telegram', 'dashboard');
      // pending(1) + developing(2) + review(1) = 4 active
      expect(resp.text).to.match(/Active:\*\s+`4\s/);
    });

    it('sums both new and legacy keys without double-counting', async () => {
      // Mixed shape — older callers may still publish engineering/qa_review.
      sandbox.stub(api, 'getRooms').resolves({
        rooms: [],
        summary: { total: 4, passed: 0, failed_final: 0, pending: 0, developing: 1, review: 1, engineering: 1, qa_review: 1, fixing: 0 },
      });
      const [resp] = await routeCommand('u1', 'telegram', 'dashboard');
      // developing(1) + engineering(1) + review(1) + qa_review(1) = 4
      expect(resp.text).to.match(/Active:\*\s+`4\s/);
    });
  });

  describe('routeCommand — feedback', () => {
    it('requires arguments', async () => {
      const [resp] = await routeCommand('u1', 'telegram', 'feedback', '');
      expect(resp.text).to.include('Please include your feedback message');
    });

    it('posts feedback to the dashboard', async () => {
      sandbox.stub(api, 'getRooms').resolves(MOCK_ROOMS);
      const postStub = sandbox.stub(api, 'postComment').resolves({ ok: true });

      const [resp] = await routeCommand('u1', 'telegram', 'feedback', 'Looks good!');
      expect(resp.text).to.include('Feedback received');
      expect(postStub.calledOnce).to.be.true;
      expect(postStub.firstCall.args[0]).to.equal('room-1');
      expect(postStub.firstCall.args[1]).to.equal('telegram:u1');
      expect(postStub.firstCall.args[2]).to.equal('Looks good!');
    });
  });

  describe('routeCommand — progress', () => {
    it('shows progress for active plans', async () => {
      sandbox.stub(api, 'getPlans').resolves({
        plans: [
          { plan_id: 'p1', title: 'Plan 1', status: 'launched', pct_complete: 50 },
        ]
      });

      const [resp] = await routeCommand('u1', 'telegram', 'progress');
      expect(resp.text).to.include('Plan 1');
      expect(resp.text).to.include('50%');
      expect(resp.text).to.include('█████░░░░░');
    });

    it('shows message when no active plans', async () => {
      sandbox.stub(api, 'getPlans').resolves({ plans: [] });
      const [resp] = await routeCommand('u1', 'telegram', 'progress');
      expect(resp.text).to.include('No active plans');
    });
  });

  describe('routeCallback — preferences', () => {
    it('handles prefs:toggle_global', async () => {
      const updateStub = sandbox.stub(registry, 'updateConfig').resolves();
      const getConfigStub = sandbox.stub(registry, 'getConfig');

      getConfigStub.onFirstCall().returns({
        platform: 'telegram', enabled: true, notification_preferences: { events: [], enabled: true }
      } as any);

      getConfigStub.onSecondCall().returns({
        platform: 'telegram', enabled: true, notification_preferences: { events: [], enabled: false }
      } as any);

      const [resp] = await routeCallback('u1', 'telegram', 'prefs:toggle_global:false');
      expect(updateStub.calledOnce).to.be.true;
      expect(resp.text).to.include('Disabled');
    });

    it('handles prefs:toggle_event', async () => {
      const updateStub = sandbox.stub(registry, 'updateConfig').resolves();
      const getConfigStub = sandbox.stub(registry, 'getConfig');

      getConfigStub.onFirstCall().returns({
        platform: 'telegram', enabled: true, notification_preferences: { events: ['plan_started'], enabled: true }
      } as any);

      getConfigStub.onSecondCall().returns({
        platform: 'telegram', enabled: true, notification_preferences: { events: ['plan_started', 'epic_passed'], enabled: true }
      } as any);

      const [resp] = await routeCallback('u1', 'telegram', 'prefs:toggle_event:epic_passed');
      expect(updateStub.calledOnce).to.be.true;
      expect(resp.text).to.include('Subscriptions');
    });
  });

  describe('routeCommand — status', () => {
    it('lists all rooms with status', async () => {
      sandbox.stub(api, 'getRooms').resolves(MOCK_ROOMS);

      const [resp] = await routeCommand('u1', 'telegram', 'status');
      expect(resp.text).to.include('room-1');
      expect(resp.text).to.include('room-2');
      expect(resp.text).to.include('PASSED');
    });

    it('returns "No War-Rooms" when empty', async () => {
      sandbox.stub(api, 'getRooms').resolves({ rooms: [], summary: {} });

      const [resp] = await routeCommand('u1', 'telegram', 'status');
      expect(resp.text).to.include('No War-Rooms');
    });

    it('shows error on API failure', async () => {
      sandbox.stub(api, 'getRooms').resolves({ error: 'connection refused', rooms: [], summary: {} });

      const [resp] = await routeCommand('u1', 'telegram', 'status');
      expect(resp.text).to.include('connection refused');
    });

    it('renders proper emojis for both legacy and new status keys', async () => {
      // Mix old and new — slash-command output must look sane in both
      // deployments without the unknown ❓ fallback.
      sandbox.stub(api, 'getRooms').resolves({
        rooms: [
          { room_id: 'r-dev', status: 'developing', message_count: 1, epic_ref: 'E-D' },
          { room_id: 'r-eng', status: 'engineering', message_count: 1, epic_ref: 'E-E' },
          { room_id: 'r-rev', status: 'review', message_count: 1, epic_ref: 'E-R' },
          { room_id: 'r-qa',  status: 'qa_review', message_count: 1, epic_ref: 'E-Q' },
        ],
        summary: {},
      });
      const [resp] = await routeCommand('u1', 'telegram', 'status');
      expect(resp.text).to.not.include('❓');
      expect(resp.text).to.include('🏃‍♂️');  // developing + engineering
      expect(resp.text).to.include('👀');     // review + qa_review
    });
  });

  describe('routeCommand — errors', () => {
    it('lists failed rooms', async () => {
      sandbox.stub(api, 'getRooms').resolves(MOCK_ROOMS);
      sandbox.stub(api, 'getRoomChannel').resolves([
        { type: 'error', body: 'Something went wrong in deployment' },
      ]);

      const [resp] = await routeCommand('u1', 'telegram', 'errors');
      expect(resp.text).to.include('room-3');
      expect(resp.text).to.include('FAILED-FINAL');
    });

    it('returns stable message when no errors', async () => {
      sandbox.stub(api, 'getRooms').resolves({ rooms: [{ room_id: 'r1', status: 'passed' }], summary: {} } as any);

      const [resp] = await routeCommand('u1', 'telegram', 'errors');
      expect(resp.text).to.include('stable');
    });
  });

  // ── Plan commands ─────────────────────────────────────────────

  describe('routeCommand — plans', () => {
    it('lists all plans', async () => {
      sandbox.stub(api, 'getPlans').resolves(MOCK_PLANS);

      const [resp] = await routeCommand('u1', 'telegram', 'plans');
      expect(resp.text).to.include('Auth System');
      expect(resp.text).to.include('Dashboard UI');
      expect(resp.text).to.include('p1');
    });

    it('returns "No plans" when empty', async () => {
      sandbox.stub(api, 'getPlans').resolves({ plans: [], count: 0 });

      const [resp] = await routeCommand('u1', 'telegram', 'plans');
      expect(resp.text).to.include('No plans');
    });
  });

  describe('routeCommand — skills', () => {
    it('lists skills with tags', async () => {
      sandbox.stub(api, 'getSkills').resolves([
        { name: 'code-review', tags: ['qa', 'review'] },
        { name: 'deploy', tags: [] },
      ]);

      const [resp] = await routeCommand('u1', 'telegram', 'skills');
      expect(resp.text).to.include('code-review');
      expect(resp.text).to.include('qa, review');
      expect(resp.text).to.include('General');
    });
  });

  // ── System commands ────────────────────────────────────────────

  describe('routeCommand — new', () => {
    it('wipes war-rooms and returns confirmation', async () => {
      sandbox.stub(api, 'shellCommand').resolves({ stdout: '', returncode: 0 });

      const [resp] = await routeCommand('u1', 'telegram', 'new');
      expect(resp.text).to.include('Cleaned up');
    });

    it('handles error during wipe', async () => {
      sandbox.stub(api, 'shellCommand').resolves({ _error: 'permission denied' });

      const [resp] = await routeCommand('u1', 'telegram', 'new');
      expect(resp.text).to.include('Failed');
    });
  });

  describe('routeCommand — restart', () => {
    it('calls stop endpoint and returns confirmation', async () => {
      sandbox.stub(api, 'stopDashboard').resolves({ status: 'stopped' });

      const [resp] = await routeCommand('u1', 'telegram', 'restart');
      expect(resp.text).to.include('Restarting');
    });
  });

  // ── Plan selection menus ──────────────────────────────────────

  describe('routeCommand — edit', () => {
    it('returns plan selection buttons', async () => {
      sandbox.stub(api, 'getPlans').resolves(MOCK_PLANS);

      const [resp] = await routeCommand('u1', 'telegram', 'edit');
      expect(resp.buttons).to.be.an('array');
      expect(resp.buttons!.length).to.be.greaterThan(0);
      const data = resp.buttons!.flat().map(b => b.callbackData);
      expect(data[0]).to.match(/^menu:edit:/);
    });

    it('returns text when no plans', async () => {
      sandbox.stub(api, 'getPlans').resolves({ plans: [], count: 0 });

      const [resp] = await routeCommand('u1', 'telegram', 'edit');
      expect(resp.text).to.include('No plans');
      expect(resp.buttons).to.be.undefined;
    });
  });

  describe('routeCommand — viewplan', () => {
    it('returns plan selection buttons', async () => {
      sandbox.stub(api, 'getPlans').resolves(MOCK_PLANS);

      const [resp] = await routeCommand('u1', 'telegram', 'viewplan');
      expect(resp.buttons).to.be.an('array');
      const data = resp.buttons!.flat().map(b => b.callbackData);
      expect(data[0]).to.match(/^menu:view:/);
    });
  });

  describe('cmdViewPlan (via menu:view callback)', () => {
    // /api/plans/{id} returns { plan: { content }, epics }. cmdViewPlan
    // must read from data.plan.content; the legacy data.content path is
    // kept only for older dashboards.

    it('renders content from the nested plan.content field (new shape)', async () => {
      sandbox.stub(api, 'getPlan').resolves({
        plan: { plan_id: 'p1', content: '# Nested Plan Body' },
        epics: [],
      });
      const [resp] = await routeCallback('u1', 'telegram', 'menu:view:p1');
      expect(resp.text).to.include('Nested Plan Body');
    });

    it('falls back to top-level data.content (legacy shape)', async () => {
      sandbox.stub(api, 'getPlan').resolves({ plan_id: 'p1', content: '# Legacy Body' });
      const [resp] = await routeCallback('u1', 'telegram', 'menu:view:p1');
      expect(resp.text).to.include('Legacy Body');
    });

    it('shows a no-content message when both fields are empty', async () => {
      sandbox.stub(api, 'getPlan').resolves({ plan: { plan_id: 'p1', content: '' } });
      const [resp] = await routeCallback('u1', 'telegram', 'menu:view:p1');
      expect(resp.text).to.include('no markdown content found');
    });

    it('returns not-found message when API errors', async () => {
      sandbox.stub(api, 'getPlan').resolves({ _error: 'missing' });
      const [resp] = await routeCallback('u1', 'telegram', 'menu:view:p1');
      expect(resp.text).to.include('not found');
    });
  });

  describe('routeCommand — startplan', () => {
    it('returns plan selection buttons with launch prefix', async () => {
      sandbox.stub(api, 'getPlans').resolves(MOCK_PLANS);

      const [resp] = await routeCommand('u1', 'telegram', 'startplan');
      expect(resp.buttons).to.be.an('array');
      const data = resp.buttons!.flat().map(b => b.callbackData);
      expect(data[0]).to.match(/^menu:launch_prompt:/);
    });
  });

  describe('routeCommand — assets', () => {
    it('lists assets for the active editing plan', async () => {
      sessions.setMode('u1', 'telegram', 'editing');
      sessions.setPlan('u1', 'telegram', 'p1');
      (api.getPlanAssets as sinon.SinonStub).resolves({
        assets: [
          {
            filename: 'stored-mockup.png',
            original_name: 'mockup.png',
            mime_type: 'image/png',
            size_bytes: 2048,
            uploaded_at: '2026-04-05T00:00:00Z',
          },
        ],
      });

      const [resp] = await routeCommand('u1', 'telegram', 'assets');
      expect(resp.text).to.include('Assets for `p1`');
      expect(resp.text).to.include('mockup.png');
      expect(resp.text).to.include('stored-mockup.png');
    });

    it('shows a plan picker when no active plan is being edited', async () => {
      sandbox.stub(api, 'getPlans').resolves(MOCK_PLANS);

      const [resp] = await routeCommand('u1', 'telegram', 'assets');
      expect(resp.buttons).to.be.an('array');
      const data = resp.buttons!.flat().map(b => b.callbackData);
      expect(data[0]).to.match(/^menu:assets:/);
    });

    it('shows "No assets" when plan has no saved assets', async () => {
      sessions.setMode('u1', 'telegram', 'editing');
      sessions.setPlan('u1', 'telegram', 'p1');
      (api.getPlanAssets as sinon.SinonStub).resolves({ assets: [] });
      (api.getPlanEpics as sinon.SinonStub).resolves({ epics: [] });

      const [resp] = await routeCommand('u1', 'telegram', 'assets');
      expect(resp.text).to.include('No assets or epics found');
      expect(resp.text).to.include('p1');
    });

    it('shows error when API fails', async () => {
      sessions.setMode('u1', 'telegram', 'editing');
      sessions.setPlan('u1', 'telegram', 'p1');
      (api.getPlanAssets as sinon.SinonStub).resolves({ error: 'connection refused', assets: [] });

      const [resp] = await routeCommand('u1', 'telegram', 'assets');
      expect(resp.text).to.include('connection refused');
    });

    it('also works during drafting mode with a real plan id', async () => {
      sessions.setMode('u1', 'telegram', 'drafting');
      sessions.setPlan('u1', 'telegram', 'p2');
      (api.getPlanAssets as sinon.SinonStub).resolves({ assets: [] });

      const [resp] = await routeCommand('u1', 'telegram', 'assets');
      expect(resp.text).to.include('Assets for `p2`');
    });

    it('falls back to plan picker when plan is "new" (not yet created)', async () => {
      sessions.setMode('u1', 'telegram', 'drafting');
      sessions.setPlan('u1', 'telegram', 'new');
      sandbox.stub(api, 'getPlans').resolves(MOCK_PLANS);

      const [resp] = await routeCommand('u1', 'telegram', 'assets');
      expect(resp.buttons).to.be.an('array');
    });

    it('shows "No plans" when idle and no plans exist', async () => {
      sandbox.stub(api, 'getPlans').resolves({ plans: [], count: 0 });

      const [resp] = await routeCommand('u1', 'telegram', 'assets');
      expect(resp.text).to.include('No plans');
    });

    it('displays file sizes in human-readable format', async () => {
      sessions.setMode('u1', 'telegram', 'editing');
      sessions.setPlan('u1', 'telegram', 'p1');
      (api.getPlanAssets as sinon.SinonStub).resolves({
        assets: [
          { filename: 'big.psd', original_name: 'design.psd', mime_type: 'image/vnd.adobe.photoshop', size_bytes: 5242880, uploaded_at: '2026-04-05T00:00:00Z' },
          { filename: 'tiny.txt', original_name: 'notes.txt', mime_type: 'text/plain', size_bytes: 42, uploaded_at: '2026-04-05T00:00:00Z' },
        ],
      });

      const [resp] = await routeCommand('u1', 'telegram', 'assets');
      expect(resp.text).to.include('5.0 MB');
      expect(resp.text).to.include('42 B');
    });
  });

  describe('routeCallback — assets', () => {
    it('menu:assets:p1 lists assets for that plan', async () => {
      (api.getPlanAssets as sinon.SinonStub).resolves({
        assets: [
          { filename: 'stored.png', original_name: 'logo.png', mime_type: 'image/png', size_bytes: 1024, uploaded_at: '2026-04-05T00:00:00Z' },
        ],
      });

      const [resp] = await routeCallback('u1', 'telegram', 'menu:assets:p1');
      expect(resp.text).to.include('Assets for `p1`');
      expect(resp.text).to.include('logo.png');
    });

    it('assets for correct plan id are fetched — plan isolation', async () => {
      (api.getPlanAssets as sinon.SinonStub).resolves({ assets: [] });

      await routeCallback('u1', 'telegram', 'menu:assets:p2');
      expect((api.getPlanAssets as sinon.SinonStub).calledWith('p2')).to.be.true;
    });
  });

  // ── Session commands ──────────────────────────────────────────

  describe('routeCommand — cancel', () => {
    it('clears session and returns confirmation', async () => {
      sessions.setPlan('u1', 'telegram', 'p1');

      const [resp] = await routeCommand('u1', 'telegram', 'cancel');
      expect(resp.text).to.include('Session cleared');

      const s = sessions.getSession('u1', 'telegram');
      expect(s.activePlanId).to.be.null;
    });
  });

  // ── Cross-platform ────────────────────────────────────────────

  describe('cross-platform', () => {
    it('same commands work for discord platform', async () => {
      sandbox.stub(api, 'getRooms').resolves(MOCK_ROOMS);

      const [resp] = await routeCommand('u1', 'discord', 'dashboard');
      expect(resp.text).to.include('COMMAND CENTER');
    });

    it('cancel clears discord session, not telegram', async () => {
      sessions.setMode('u1', 'telegram', 'editing');
      sessions.setMode('u1', 'discord', 'drafting');

      await routeCommand('u1', 'discord', 'cancel');

      expect(sessions.getSession('u1', 'discord').mode).to.equal('idle');
      expect(sessions.getSession('u1', 'telegram').mode).to.equal('editing');
    });
  });

  // ── Callback routing ──────────────────────────────────────────

  describe('routeCallback', () => {
    it('menu:main returns main menu', async () => {
      const [resp] = await routeCallback('u1', 'telegram', 'menu:main');
      expect(resp.buttons).to.have.lengthOf(4);
    });

    it('menu:cat:monitoring returns monitoring submenu', async () => {
      const [resp] = await routeCallback('u1', 'telegram', 'menu:cat:monitoring');
      const data = resp.buttons!.flat().map(b => b.callbackData);
      expect(data).to.include('cmd:dashboard');
    });

    it('menu:cat:plans returns plans submenu', async () => {
      const [resp] = await routeCallback('u1', 'telegram', 'menu:cat:plans');
      const data = resp.buttons!.flat().map(b => b.callbackData);
      expect(data).to.include('cmd:draft_prompt');
    });

    it('menu:cat:system returns system submenu', async () => {
      const [resp] = await routeCallback('u1', 'telegram', 'menu:cat:system');
      const data = resp.buttons!.flat().map(b => b.callbackData);
      expect(data).to.include('cmd:health');
    });

    it('cmd:dashboard dispatches to dashboard command', async () => {
      sandbox.stub(api, 'getRooms').resolves({ rooms: [], summary: {} });

      const [resp] = await routeCallback('u1', 'telegram', 'cmd:dashboard');
      expect(resp.text).to.include('COMMAND CENTER');
    });

    it('cmd:draft_prompt returns draft instructions', async () => {
      const [resp] = await routeCallback('u1', 'telegram', 'cmd:draft_prompt');
      expect(resp.text).to.include('/draft');
    });

    it('menu:view:p1 views a plan', async () => {
      sandbox.stub(api, 'getPlan').resolves({ plan_id: 'p1', content: '# My Plan' });

      const [resp] = await routeCallback('u1', 'telegram', 'menu:view:p1');
      expect(resp.text).to.include('My Plan');
    });

    it('menu:edit:p1 sets active plan', async () => {
      sandbox.stub(api, 'askOpenCodeCommand').resolves({
        text: 'Editing plan p1',
        conversation_id: 'ignored',
        actions: [],
      });

      const [resp] = await routeCallback('u1', 'telegram', 'menu:edit:p1');
      expect(resp.text).to.include('Editing plan');
      expect(sessions.getSession('u1', 'telegram').activePlanId).to.equal('p1');
      expect(sessions.getSession('u1', 'telegram').mode).to.equal('editing');
    });

    it('menu:launch_prompt:p1 shows confirmation', async () => {
      const [resp] = await routeCallback('u1', 'telegram', 'menu:launch_prompt:p1');
      expect(resp.text).to.include('Confirm Launch');
      expect(resp.buttons).to.be.an('array');
      const data = resp.buttons!.flat().map(b => b.callbackData);
      expect(data).to.include('menu:launch_confirm:p1');
    });

    it('menu:launch_confirm:p1 launches the plan', async () => {
      sandbox.stub(api, 'getPlan').resolves({ plan_id: 'p1', content: '# Plan\n## Epic: E1' });
      sandbox.stub(api, 'launchPlan').resolves({ status: 'launched' });

      const responses = await routeCallback('u1', 'telegram', 'menu:launch_confirm:p1');
      const hasLaunch = responses.some(r => r.text.includes('Launched'));
      expect(hasLaunch).to.be.true;
    });

    it('menu:launch_cancel returns cancellation', async () => {
      const [resp] = await routeCallback('u1', 'telegram', 'menu:launch_cancel');
      expect(resp.text).to.include('cancelled');
    });

    it('menu:plans returns plans list', async () => {
      sandbox.stub(api, 'getPlans').resolves(MOCK_PLANS);

      const [resp] = await routeCallback('u1', 'telegram', 'menu:plans');
      expect(resp.text).to.include('Auth System');
    });

    it('returns empty for unknown callback', async () => {
      const responses = await routeCallback('u1', 'telegram', 'unknown:data');
      expect(responses).to.deep.equal([]);
    });
  });

  // handleStatefulText tests removed — editing mode eliminated.
  // Plan creation and refinement now goes through askAgent() with
  // create_plan / refine_plan tools.

  // ── Session pendingAttachments ─────────────────────────────────

  describe('session pendingAttachments', () => {
    it('new session has empty pendingAttachments array', () => {
      sessions.clearSession('u1', 'telegram');
      const session = sessions.getSession('u1', 'telegram');
      expect(session.pendingAttachments).to.deep.equal([]);
    });

    it('clearSession resets pendingAttachments', () => {
      const session = sessions.getSession('u1', 'telegram');
      session.pendingAttachments = [
        { data: new Uint8Array([1]), name: 'a.png', mimeType: 'image/png', stagedAt: Date.now() },
      ];
      expect(session.pendingAttachments).to.have.length(1);

      sessions.clearSession('u1', 'telegram');
      const fresh = sessions.getSession('u1', 'telegram');
      expect(fresh.pendingAttachments).to.deep.equal([]);
    });

    it('pendingAttachments are independent per platform', () => {
      const discordSession = sessions.getSession('u1', 'discord');
      const telegramSession = sessions.getSession('u1', 'telegram');

      discordSession.pendingAttachments = [
        { data: new Uint8Array([1]), name: 'd.png', mimeType: 'image/png', stagedAt: Date.now() },
      ];

      expect(discordSession.pendingAttachments).to.have.length(1);
      expect(telegramSession.pendingAttachments).to.have.length(0);
    });
  });

  // ── COMMAND_REGISTRY ──────────────────────────────────────────

  describe('COMMAND_REGISTRY', () => {
    it('exports a non-empty array of command definitions', () => {
      expect(COMMAND_REGISTRY).to.be.an('array');
      expect(COMMAND_REGISTRY.length).to.be.greaterThan(30);
    });

    it('every entry has name and description', () => {
      for (const def of COMMAND_REGISTRY) {
        expect(def.name, `${def.name} missing name`).to.be.a('string').with.length.greaterThan(0);
        expect(def.description, `${def.name} missing description`).to.be.a('string').with.length.greaterThan(0);
      }
    });

    it('has no duplicate command names', () => {
      const names = COMMAND_REGISTRY.map(c => c.name);
      const unique = new Set(names);
      expect(unique.size).to.equal(names.length);
    });

    it('COMMANDS_NO_ARGS excludes commands with args and discordOnly', () => {
      for (const def of COMMANDS_NO_ARGS) {
        expect(def.arg, `${def.name} should not have arg`).to.be.undefined;
        expect(def.discordOnly, `${def.name} should not be discordOnly`).to.not.equal(true);
      }
    });

    it('COMMANDS_WITH_ARGS only contains commands with args', () => {
      for (const def of COMMANDS_WITH_ARGS) {
        expect(def.arg, `${def.name} should have arg`).to.be.a('string');
        expect(def.discordOnly, `${def.name} should not be discordOnly`).to.not.equal(true);
      }
    });

    it('ALL_PLATFORM_COMMANDS excludes discordOnly', () => {
      for (const def of ALL_PLATFORM_COMMANDS) {
        expect(def.discordOnly, `${def.name} should not be discordOnly`).to.not.equal(true);
      }
    });

    it('platform command helpers derive from COMMAND_REGISTRY', () => {
      expect(getCommandsForPlatform('discord').map(c => c.name)).to.deep.equal(COMMAND_REGISTRY.map(c => c.name));
      expect(getCommandsForPlatform('telegram').map(c => c.name)).to.deep.equal(ALL_PLATFORM_COMMANDS.map(c => c.name));
      expect(getCommandsForPlatform('slack').map(c => c.name)).to.deep.equal(ALL_PLATFORM_COMMANDS.map(c => c.name));
      expect(getCommandsWithArgsForPlatform('telegram').map(c => c.name)).to.deep.equal(COMMANDS_WITH_ARGS.map(c => c.name));
      expect(getCommandsWithoutArgsForPlatform('telegram').map(c => c.name)).to.deep.equal(COMMANDS_NO_ARGS.map(c => c.name));
    });

    it('DEFERRED_COMMANDS is a Set of command names', () => {
      expect(DEFERRED_COMMANDS).to.be.instanceOf(Set);
      expect(DEFERRED_COMMANDS.has('health')).to.be.true;
      expect(DEFERRED_COMMANDS.has('menu')).to.be.false;
    });

    it('builds Discord slash commands from COMMAND_REGISTRY', () => {
      const slashCommands = buildDiscordSlashCommands().map(c => c.toJSON());
      expect(slashCommands.map(c => c.name)).to.deep.equal(COMMAND_REGISTRY.map(c => c.name));

      const draft = slashCommands.find(c => c.name === 'draft')!;
      const draftDef = getCommandDef('draft')!;
      expect(draft.description).to.equal(draftDef.description);
      expect(draft.options?.[0].name).to.equal(draftDef.arg);
      expect(draft.options?.[0].description).to.equal(draftDef.argDescription);

      const feedback = slashCommands.find(c => c.name === 'feedback')!;
      expect(feedback.options?.[0].required).to.equal(true);
    });

    it('every routeCommand case has a matching COMMAND_REGISTRY entry', () => {
      const registeredNames = new Set(COMMAND_REGISTRY.map(c => c.name));
      const routerCommands = [
        'menu', 'help', 'dashboard', 'status', 'plans', 'errors',
        'skills', 'new', 'restart', 'cancel', 'setdir', 'draft',
        'edit', 'assets', 'startplan', 'viewplan',
        'feedback', 'preferences', 'subscriptions', 'progress',
        'resume', 'clearplans', 'logs', 'health',
        'skillsearch', 'skillinstall', 'skillremove', 'skillsync',
        'roles', 'triage', 'launchdashboard',
      ];
      for (const cmd of routerCommands) {
        expect(registeredNames.has(cmd), `${cmd} missing from COMMAND_REGISTRY`).to.be.true;
      }
    });
  });

  // ── Tier 1 commands ───────────────────────────────────────────

  describe('routeCommand — resume', () => {
    it('shows plan selection buttons for resumable plans', async () => {
      sandbox.stub(api, 'getPlans').resolves({
        plans: [
          { plan_id: 'p1', title: 'Auth', status: 'failed' },
          { plan_id: 'p2', title: 'Blog', status: 'draft' },
        ],
      });
      const [resp] = await routeCommand('u1', 'telegram', 'resume');
      expect(resp.buttons).to.be.an('array');
      expect(resp.buttons!.length).to.equal(1); // only p1 is resumable
      expect(resp.buttons![0][0].callbackData).to.include('p1');
    });

    it('returns message when no resumable plans', async () => {
      sandbox.stub(api, 'getPlans').resolves({ plans: [{ plan_id: 'p1', status: 'draft' }] });
      const [resp] = await routeCommand('u1', 'telegram', 'resume');
      expect(resp.text).to.include('No plans available to resume');
    });
  });

  describe('routeCallback — resume_confirm', () => {
    it('resumes a plan', async () => {
      sandbox.stub(api, 'getPlan').resolves({ plan_id: 'p1', content: '# Plan' });
      sandbox.stub(api, 'resumePlan').resolves({ status: 'resumed' });
      const responses = await routeCallback('u1', 'telegram', 'menu:resume_confirm:p1');
      expect(responses.some(r => r.text.includes('Resumed'))).to.be.true;
    });

    it('shows error when plan not found', async () => {
      sandbox.stub(api, 'getPlan').resolves({ _error: 'not found' });
      const responses = await routeCallback('u1', 'telegram', 'menu:resume_confirm:p1');
      expect(responses[0].text).to.include('not found');
    });
  });

  describe('routeCommand — clearplans', () => {
    it('calls shell and returns confirmation', async () => {
      sandbox.stub(api, 'shellCommand').resolves({ stdout: 'cleared', returncode: 0 });
      const [resp] = await routeCommand('u1', 'telegram', 'clearplans');
      expect(resp.text).to.include('plans cleared');
    });

    it('handles error', async () => {
      sandbox.stub(api, 'shellCommand').resolves({ _error: 'permission denied' });
      const [resp] = await routeCommand('u1', 'telegram', 'clearplans');
      expect(resp.text).to.include('Failed');
    });
  });

  describe('routeCommand — logs', () => {
    it('shows room selector when no room_id given', async () => {
      sandbox.stub(api, 'getRooms').resolves(MOCK_ROOMS);
      const [resp] = await routeCommand('u1', 'telegram', 'logs', '');
      expect(resp.buttons).to.be.an('array');
      expect(resp.buttons!.length).to.be.greaterThan(0);
    });

    it('shows messages when room_id given', async () => {
      sandbox.stub(api, 'getRoomChannel').resolves({
        messages: [
          { from: 'engineer', type: 'task', body: 'Working on auth' },
          { from: 'qa', type: 'review', body: 'Looks good' },
        ],
      });
      const [resp] = await routeCommand('u1', 'telegram', 'logs', 'room-1');
      expect(resp.text).to.include('room-1');
      expect(resp.text).to.include('Working on auth');
    });

    it('handles empty messages', async () => {
      sandbox.stub(api, 'getRoomChannel').resolves({ messages: [] });
      const [resp] = await routeCommand('u1', 'telegram', 'logs', 'room-1');
      expect(resp.text).to.include('No messages');
    });
  });

  describe('routeCommand — health', () => {
    it('shows system health info', async () => {
      sandbox.stub(api, 'getManagerStatus').resolves({ running: true, pid: 1234 });
      sandbox.stub(api, 'getBotStatus').resolves({ running: true, pid: 5678, available: true });
      sandbox.stub(api, 'getRooms').resolves(MOCK_ROOMS);

      const [resp] = await routeCommand('u1', 'telegram', 'health');
      expect(resp.text).to.include('System Health');
      expect(resp.text).to.include('Running');
      expect(resp.text).to.include('1234');
    });
  });

  // ── Tier 2 commands ───────────────────────────────────────────

  describe('routeCommand — skillsearch', () => {
    it('requires a query argument', async () => {
      const [resp] = await routeCommand('u1', 'telegram', 'skillsearch', '');
      expect(resp.text).to.include('Usage');
    });

    it('returns search results', async () => {
      sandbox.stub(api, 'searchSkillsClawhub').resolves([
        { name: 'Web Search', slug: 'web-search', description: 'Search the web' },
      ]);
      const [resp] = await routeCommand('u1', 'telegram', 'skillsearch', 'web');
      expect(resp.text).to.include('web-search');
      expect(resp.text).to.include('Search the web');
    });

    it('shows message when no results', async () => {
      sandbox.stub(api, 'searchSkillsClawhub').resolves([]);
      const [resp] = await routeCommand('u1', 'telegram', 'skillsearch', 'nonexistent');
      expect(resp.text).to.include('No skills found');
    });
  });

  describe('routeCommand — skillinstall', () => {
    it('requires a slug argument', async () => {
      const [resp] = await routeCommand('u1', 'telegram', 'skillinstall', '');
      expect(resp.text).to.include('Usage');
    });

    it('installs and confirms', async () => {
      sandbox.stub(api, 'installSkillClawhub').resolves({ status: 'installed' });
      const [resp] = await routeCommand('u1', 'telegram', 'skillinstall', 'steipete/web-search');
      expect(resp.text).to.include('installed');
    });

    it('shows error on failure', async () => {
      sandbox.stub(api, 'installSkillClawhub').resolves({ _error: 'not found on ClawHub' });
      const [resp] = await routeCommand('u1', 'telegram', 'skillinstall', 'bad/slug');
      expect(resp.text).to.include('Failed');
    });
  });

  describe('routeCommand — skillremove', () => {
    it('requires a name argument', async () => {
      const [resp] = await routeCommand('u1', 'telegram', 'skillremove', '');
      expect(resp.text).to.include('Usage');
    });

    it('removes and confirms', async () => {
      sandbox.stub(api, 'removeSkill').resolves({ status: 'removed' });
      const [resp] = await routeCommand('u1', 'telegram', 'skillremove', 'web-search');
      expect(resp.text).to.include('removed');
    });
  });

  describe('routeCommand — skillsync', () => {
    it('syncs and returns confirmation', async () => {
      sandbox.stub(api, 'syncSkills').resolves({ message: 'synced 5 skills' });
      const [resp] = await routeCommand('u1', 'telegram', 'skillsync');
      expect(resp.text).to.include('synced');
    });
  });

  describe('routeCommand — roles', () => {
    it('lists roles', async () => {
      sandbox.stub(api, 'getRoles').resolves([
        { name: 'engineer', description: 'Writes code', default_model: 'gpt-4' },
        { name: 'qa', description: 'Reviews code' },
      ]);
      const [resp] = await routeCommand('u1', 'telegram', 'roles');
      expect(resp.text).to.include('engineer');
      expect(resp.text).to.include('qa');
      expect(resp.text).to.include('gpt-4');
    });

    it('shows message when no roles', async () => {
      sandbox.stub(api, 'getRoles').resolves([]);
      const [resp] = await routeCommand('u1', 'telegram', 'roles');
      expect(resp.text).to.include('No roles');
    });
  });

  describe('routeCommand — triage', () => {
    it('shows failed room selector when no room_id given', async () => {
      sandbox.stub(api, 'getRooms').resolves(MOCK_ROOMS);
      const [resp] = await routeCommand('u1', 'telegram', 'triage', '');
      expect(resp.buttons).to.be.an('array');
      expect(resp.buttons![0][0].callbackData).to.include('room-3');
    });

    it('shows "no failed rooms" when all healthy', async () => {
      sandbox.stub(api, 'getRooms').resolves({
        rooms: [{ room_id: 'r1', status: 'passed', message_count: 5 }],
        summary: {},
      });
      const [resp] = await routeCommand('u1', 'telegram', 'triage', '');
      expect(resp.text).to.include('No failed rooms');
    });

    it('triggers triage action when room_id given', async () => {
      sandbox.stub(api, 'roomAction').resolves({ status: 'ok' });
      const [resp] = await routeCommand('u1', 'telegram', 'triage', 'room-3');
      expect(resp.text).to.include('Triage initiated');
      expect(resp.text).to.include('room-3');
    });
  });

  describe('routeCommand — launchdashboard', () => {
    it('shows dashboard URL', async () => {
      sandbox.stub(api, 'getBaseUrl').resolves('http://localhost:3366');
      sandbox.stub(api, 'getBotStatus').resolves({ running: true });
      const [resp] = await routeCommand('u1', 'telegram', 'launchdashboard');
      expect(resp.text).to.include('Dashboard');
      expect(resp.text).to.include('localhost:3366');
    });
  });

  // ── New callback submenu routes ───────────────────────────────

  describe('routeCallback — new submenus', () => {
    it('menu:cat:skills returns skills submenu', async () => {
      const [resp] = await routeCallback('u1', 'telegram', 'menu:cat:skills');
      const data = resp.buttons!.flat().map(b => b.callbackData);
      expect(data).to.include('cmd:skills');
      expect(data).to.include('cmd:roles');
    });

    it('menu:logs:room-1 shows logs for that room', async () => {
      sandbox.stub(api, 'getRoomChannel').resolves({
        messages: [{ from: 'eng', type: 'done', body: 'Complete' }],
      });
      const [resp] = await routeCallback('u1', 'telegram', 'menu:logs:room-1');
      expect(resp.text).to.include('room-1');
      expect(resp.text).to.include('Complete');
    });

    it('menu:triage:room-3 triggers triage', async () => {
      sandbox.stub(api, 'roomAction').resolves({ status: 'ok' });
      const [resp] = await routeCallback('u1', 'telegram', 'menu:triage:room-3');
      expect(resp.text).to.include('Triage initiated');
    });
  });
});
