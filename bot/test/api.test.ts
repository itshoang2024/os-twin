import { expect } from 'chai';
import sinon from 'sinon';
import api from '../src/api';

describe('api', () => {
  let fetchStub: sinon.SinonStub;

  before(() => {
    fetchStub = sinon.stub(global, 'fetch');
  });

  afterEach(() => {
    fetchStub.reset();
  });

  after(() => {
    fetchStub.restore();
  });

  function mockFetch(data: any, status = 200): void {
    fetchStub.resolves({
      ok: status >= 200 && status < 300,
      status,
      headers: { get: (name: string) => name === 'content-type' ? 'application/json' : null },
      json: async () => data,
    });
  }

  function mockFetchError(message: string): void {
    fetchStub.rejects(new Error(message));
  }

  // ── getPlans ──────────────────────────────────────────────────

  describe('getPlans', () => {
    it('returns plans array on success', async () => {
      const plans = [
        { plan_id: 'p1', title: 'Plan One', status: 'draft', epic_count: 2 },
        { plan_id: 'p2', title: 'Plan Two', status: 'launched', epic_count: 5 },
      ];
      mockFetch({ plans, count: 2 });

      const result = await api.getPlans();
      expect(result.plans).to.have.lengthOf(2);
      expect(result.plans[0].plan_id).to.equal('p1');
      expect(result.count).to.equal(2);
    });

    it('returns empty plans on API error', async () => {
      mockFetch({}, 500);

      const result = await api.getPlans();
      expect(result.plans).to.deep.equal([]);
      expect(result.error).to.include('500');
    });

    it('returns empty plans when dashboard is unreachable', async () => {
      mockFetchError('Connection refused');

      const result = await api.getPlans();
      expect(result.plans).to.deep.equal([]);
      expect(result.error).to.include('unreachable');
    });
  });

  // ── getPlan ───────────────────────────────────────────────────

  describe('getPlan', () => {
    it('returns plan data on success', async () => {
      mockFetch({ plan_id: 'p1', content: '# Plan: Test', title: 'Test' });

      const result = await api.getPlan('p1');
      expect(result.plan_id).to.equal('p1');
      expect(result.content).to.include('Plan');
    });

    it('returns _error on 404', async () => {
      mockFetch({}, 404);

      const result = await api.getPlan('missing');
      expect(result._error).to.include('404');
    });
  });

  // ── getPlanEpics ──────────────────────────────────────────────

  describe('getPlanEpics', () => {
    it('returns epics on success', async () => {
      const epics = [
        { room_id: 'room-001', task_ref: 'EPIC-001', title: 'Epic One' },
        { room_id: 'room-002', task_ref: 'EPIC-002', title: 'Epic Two' },
      ];
      mockFetch({ epics, count: 2 });

      const result = await api.getPlanEpics('p1');
      expect(result.epics).to.have.lengthOf(2);
      expect(result.epics[0].task_ref).to.equal('EPIC-001');
      expect(result.count).to.equal(2);
    });

    it('returns empty epics on error', async () => {
      mockFetch({}, 500);
      const result = await api.getPlanEpics('p1');
      expect(result.epics).to.have.lengthOf(0);
      expect(result.error).to.include('500');
    });
  });

  // ── getRooms ──────────────────────────────────────────────────

  describe('getRooms', () => {
    it('returns rooms and summary', async () => {
      const data = {
        rooms: [
          { room_id: 'room-1', status: 'passed', message_count: 10 },
          { room_id: 'room-2', status: 'engineering', message_count: 5 },
        ],
        summary: { total: 2, passed: 1, engineering: 1 },
      };
      mockFetch(data);

      const result = await api.getRooms();
      expect(result.rooms).to.have.lengthOf(2);
      expect(result.summary.total).to.equal(2);
    });

    it('exposes both new (developing/review) and legacy (engineering/qa_review) keys on summary', async () => {
      // The /api/rooms response shape mixes legacy and new keys during the
      // transition. The RoomsSummary type must keep both passthrough so
      // dashboard counts don't lose rooms.
      mockFetch({
        rooms: [],
        summary: {
          total: 6, passed: 1, failed_final: 0, pending: 1,
          developing: 1, review: 1, engineering: 1, qa_review: 1, fixing: 0,
        },
      });

      const result = await api.getRooms();
      expect(result.summary.developing).to.equal(1);
      expect(result.summary.review).to.equal(1);
      expect(result.summary.engineering).to.equal(1);
      expect(result.summary.qa_review).to.equal(1);
    });

    it('returns empty on error', async () => {
      mockFetchError('timeout');

      const result = await api.getRooms();
      expect(result.rooms).to.deep.equal([]);
      expect(result.error).to.be.a('string');
    });
  });

  // ── refinePlan ────────────────────────────────────────────────

  describe('refinePlan', () => {
    it('sends correct request body', async () => {
      mockFetch({ plan: '# Plan', explanation: 'Added epics' });

      await api.refinePlan({
        message: 'Add auth epic',
        planContent: '# Old plan',
        planId: 'p1',
        chatHistory: [{ role: 'user', content: 'hello' }],
      });

      const [url, opts] = fetchStub.firstCall.args;
      expect(url).to.include('/api/plans/refine');
      const body = JSON.parse(opts.body);
      expect(body.message).to.equal('Add auth epic');
      expect(body.plan_content).to.equal('# Old plan');
      expect(body.plan_id).to.equal('p1');
      expect(body.chat_history).to.have.lengthOf(1);
    });
  });

  // ── launchPlan ────────────────────────────────────────────────

  describe('launchPlan', () => {
    it('sends plan content in request body', async () => {
      mockFetch({ status: 'launched', plan_id: 'p1' });

      await api.launchPlan('p1', '# Plan content');

      const [url, opts] = fetchStub.firstCall.args;
      expect(url).to.include('/api/run');
      const body = JSON.parse(opts.body);
      expect(body.plan).to.equal('# Plan content');
      expect(body.plan_id).to.equal('p1');
    });

    it('passes through the runner_pid the dashboard returns', async () => {
      // /api/run now spawns the runner, records its PID, and echoes it
      // back so the bot can show the user a live process handle.
      mockFetch({ status: 'launched', plan_id: 'p1', runner_pid: 4242 });

      const result = await api.launchPlan('p1', '# Plan');
      expect((result as any).runner_pid).to.equal(4242);
      expect((result as any).status).to.equal('launched');
    });
  });

  // ── getSkills ─────────────────────────────────────────────────

  describe('getSkills', () => {
    it('returns skills array', async () => {
      mockFetch([{ name: 'skill1', tags: ['test'] }]);

      const result = await api.getSkills();
      expect(result).to.have.lengthOf(1);
      expect(result[0].name).to.equal('skill1');
    });

    it('returns empty array on error', async () => {
      mockFetchError('fail');

      const result = await api.getSkills();
      expect(result).to.deep.equal([]);
    });
  });

  // ── getStats ──────────────────────────────────────────────────

  describe('getStats', () => {
    it('returns stats object', async () => {
      const stats = {
        total_plans: { value: 3 },
        active_epics: { value: 5 },
        completion_rate: { value: 60.5 },
        escalations_pending: { value: 1 },
      };
      mockFetch(stats);

      const result = await api.getStats();
      expect(result.total_plans!.value).to.equal(3);
      expect(result.completion_rate!.value).to.equal(60.5);
    });
  });

  describe('createPlan', () => {
    it('sends POST to /api/plans/create', async () => {
      mockFetch({ plan_id: 'p1' });
      await api.createPlan({ title: 'T', content: 'C' });
      expect(fetchStub.firstCall.args[0]).to.include('/api/plans/create');
    });
  });

  describe('savePlan', () => {
    it('sends POST to /api/plans/p1/save', async () => {
      mockFetch({ status: 'ok' });
      await api.savePlan('p1', 'content');
      expect(fetchStub.firstCall.args[0]).to.include('/api/plans/p1/save');
    });
  });

  describe('shellCommand', () => {
    it('returns success on 200', async () => {
      mockFetch({ status: 'ok' });
      const result = await api.shellCommand('ls');
      expect(result.status).to.equal('ok');
    });

    it('returns error on failure', async () => {
      mockFetch({}, 500);
      const result = await api.shellCommand('ls');
      expect(result._error).to.exist;
    });
  });

  describe('getRoomChannel', () => {
    it('returns messages array', async () => {
      mockFetch([{ from: 'me', body: 'hi' }]);
      const result = await api.getRoomChannel('r1');
      expect(result).to.have.lengthOf(1);
    });
  });

  describe('semanticSearch', () => {
    it('returns search results', async () => {
      mockFetch([{ room_id: 'r1', body: 'match' }]);
      const result = await api.semanticSearch('query');
      expect(result).to.have.lengthOf(1);
    });
  });

  describe('stopDashboard', () => {
    it('returns success on 200', async () => {
      mockFetch({ status: 'stopping' });
      const result = await api.stopDashboard();
      expect(result.status).to.equal('stopping');
    });

    it('returns error on failure', async () => {
      mockFetch({}, 500);
      const result = await api.stopDashboard();
      expect(result._error).to.exist;
    });
  });

  // ── New Tier 1/2 API functions ─────────────────────────────────

  describe('resumePlan', () => {
    it('sends POST to /api/run with resume flag', async () => {
      mockFetch({ status: 'resumed' });
      await api.resumePlan('p1', '# Plan');
      const [url, opts] = fetchStub.firstCall.args;
      expect(url).to.include('/api/run');
      const body = JSON.parse(opts.body);
      expect(body.plan_id).to.equal('p1');
      expect(body.resume).to.equal(true);
    });
  });

  describe('roomAction', () => {
    it('sends POST with action query param', async () => {
      mockFetch({ status: 'ok' });
      await api.roomAction('room-001', 'resume');
      expect(fetchStub.firstCall.args[0]).to.include('/api/rooms/room-001/action?action=resume');
    });
  });

  describe('getManagerStatus', () => {
    it('returns manager status', async () => {
      mockFetch({ running: true, pid: 1234 });
      const result = await api.getManagerStatus();
      expect(result.running).to.equal(true);
      expect(result.pid).to.equal(1234);
    });
  });

  describe('getBotStatus', () => {
    it('returns bot status', async () => {
      mockFetch({ running: true, pid: 5678, available: true });
      const result = await api.getBotStatus();
      expect(result.running).to.equal(true);
    });
  });

  describe('getConfig', () => {
    it('returns config object', async () => {
      mockFetch({ manager: { poll_interval_seconds: 10 } });
      const result = await api.getConfig();
      expect(result.manager.poll_interval_seconds).to.equal(10);
    });

    it('returns _error on failure', async () => {
      mockFetch({}, 500);
      const result = await api.getConfig();
      expect(result._error).to.exist;
    });
  });

  describe('searchSkillsClawhub', () => {
    it('returns skills array on success', async () => {
      mockFetch([{ slug: 'web-search', name: 'Web Search', description: 'Search the web' }]);
      const result = await api.searchSkillsClawhub('web');
      expect(result).to.have.lengthOf(1);
      expect(result[0].slug).to.equal('web-search');
    });

    it('returns empty array on error', async () => {
      mockFetchError('timeout');
      const result = await api.searchSkillsClawhub('query');
      expect(result).to.deep.equal([]);
    });
  });

  describe('installSkillClawhub', () => {
    it('sends POST to install endpoint', async () => {
      mockFetch({ status: 'installed' });
      const result = await api.installSkillClawhub('steipete/web-search');
      expect(fetchStub.firstCall.args[0]).to.include('/api/skills/clawhub-install');
      expect(result.status).to.equal('installed');
    });
  });

  describe('removeSkill', () => {
    it('sends DELETE with force flag', async () => {
      mockFetch({ status: 'removed' });
      await api.removeSkill('web-search', true);
      const [url, opts] = fetchStub.firstCall.args;
      expect(url).to.include('/api/skills/web-search');
      expect(url).to.include('force=true');
      expect(opts.method).to.equal('DELETE');
    });
  });

  describe('syncSkills', () => {
    it('sends POST to sync endpoint', async () => {
      mockFetch({ message: 'synced 5 skills' });
      const result = await api.syncSkills();
      expect(fetchStub.firstCall.args[0]).to.include('/api/skills/sync');
      expect(result.message).to.include('synced');
    });
  });

  describe('getRoles', () => {
    it('returns roles array on success', async () => {
      mockFetch([{ name: 'engineer', description: 'Writes code' }]);
      const result = await api.getRoles();
      expect(result).to.have.lengthOf(1);
      expect(result[0].name).to.equal('engineer');
    });

    it('returns empty array on error', async () => {
      mockFetchError('fail');
      const result = await api.getRoles();
      expect(result).to.deep.equal([]);
    });
  });
});
