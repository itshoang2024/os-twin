import { expect } from 'chai';
import fs from 'fs';
import path from 'path';
import os from 'os';
import { 
  getSession, 
  clearSession, 
  clearChatHistory,
  clearActivePlan,
  clearConversationState,
  setMode, 
  setPlan, 
  setWorkingDir,
  persistAfterMessage,
  flushSessionsSync,
  getStagedImages,
  getStagedFiles,
  type StagedAttachment 
} from '../src/sessions';

const SESSIONS_FILE = path.join(os.homedir(), '.ostwin', 'sessions.json');

describe('sessions', () => {
  beforeEach(() => {
    clearSession('u1', 'telegram');
    clearSession('u1', 'discord');
    clearSession('u2', 'telegram');
  });

  afterEach(() => {
    clearSession('u1', 'telegram');
    clearSession('u1', 'discord');
    clearSession('u2', 'telegram');
  });

  describe('getSession', () => {
    it('creates a new session with default values', () => {
      const s = getSession('u1', 'telegram');
      expect(s.userId).to.equal('u1');
      expect(s.platform).to.equal('telegram');
      expect(s.mode).to.equal('idle');
      expect(s.activePlanId).to.be.null;
      expect(s.chatHistory).to.deep.equal([]);
      expect(s.lastActivity).to.be.a('number');
    });

    it('returns the same session on subsequent calls', () => {
      const s1 = getSession('u1', 'telegram');
      s1.mode = 'editing';
      const s2 = getSession('u1', 'telegram');
      expect(s2.mode).to.equal('editing');
    });

    it('defaults platform to telegram', () => {
      const s = getSession('u1');
      expect(s.platform).to.equal('telegram');
    });

    it('coerces userId to string', () => {
      const s = getSession(123, 'telegram');
      expect(s.userId).to.equal('123');
    });
  });

  describe('platform isolation', () => {
    it('keeps separate sessions per platform', () => {
      setMode('u1', 'telegram', 'editing');
      setMode('u1', 'discord', 'drafting');

      expect(getSession('u1', 'telegram').mode).to.equal('editing');
      expect(getSession('u1', 'discord').mode).to.equal('drafting');
    });

    it('clearing one platform does not affect the other', () => {
      setMode('u1', 'telegram', 'editing');
      setMode('u1', 'discord', 'drafting');

      clearSession('u1', 'telegram');

      expect(getSession('u1', 'telegram').mode).to.equal('idle');
      expect(getSession('u1', 'discord').mode).to.equal('drafting');
    });
  });

  describe('setMode', () => {
    it('changes the session mode', () => {
      setMode('u1', 'telegram', 'editing');
      expect(getSession('u1', 'telegram').mode).to.equal('editing');
    });

    it('updates lastActivity', () => {
      const s = getSession('u1', 'telegram');
      const before = s.lastActivity;
      setMode('u1', 'telegram', 'drafting');
      expect(getSession('u1', 'telegram').lastActivity).to.be.at.least(before);
    });
  });

  describe('setPlan', () => {
    it('sets the active plan ID', () => {
      setPlan('u1', 'telegram', 'plan-abc');
      expect(getSession('u1', 'telegram').activePlanId).to.equal('plan-abc');
    });
  });

  describe('clearActivePlan', () => {
    it('clears plan selection and returns to idle without clearing working_dir', () => {
      setPlan('u1', 'telegram', 'plan-abc');
      setMode('u1', 'telegram', 'editing');
      setWorkingDir('u1', 'telegram', '/tmp/project');

      clearActivePlan('u1', 'telegram');

      const s = getSession('u1', 'telegram');
      expect(s.activePlanId).to.be.null;
      expect(s.mode).to.equal('idle');
      expect(s.workingDir).to.equal('/tmp/project');
    });
  });

  describe('clearConversationState', () => {
    it('clears active plan, mode, chat history, and pending context', () => {
      setPlan('u1', 'telegram', 'plan-abc');
      setMode('u1', 'telegram', 'editing');
      const s = getSession('u1', 'telegram');
      s.chatHistory.push({ role: 'user', content: 'hello' });
      s.pendingContext.push({ command: 'plans', result: 'Plan list', timestamp: Date.now() });

      clearConversationState('u1', 'telegram');

      const fresh = getSession('u1', 'telegram');
      expect(fresh.activePlanId).to.be.null;
      expect(fresh.mode).to.equal('idle');
      expect(fresh.chatHistory).to.deep.equal([]);
      expect(fresh.pendingContext).to.deep.equal([]);
    });
  });

  describe('clearSession', () => {
    it('resets all session fields', () => {
      setMode('u1', 'telegram', 'editing');
      setPlan('u1', 'telegram', 'plan-abc');
      getSession('u1', 'telegram').chatHistory.push({ role: 'user', content: 'hello' });

      clearSession('u1', 'telegram');

      const s = getSession('u1', 'telegram');
      expect(s.mode).to.equal('idle');
      expect(s.activePlanId).to.be.null;
      expect(s.chatHistory).to.deep.equal([]);
    });
  });

  describe('session timeout', () => {
    it('resets session after 30 min of inactivity', () => {
      const s = getSession('u1', 'telegram');
      s.mode = 'editing';
      s.activePlanId = 'plan-old';
      // Simulate 31 minutes ago
      s.lastActivity = Date.now() - (31 * 60 * 1000);

      const fresh = getSession('u1', 'telegram');
      expect(fresh.mode).to.equal('idle');
      expect(fresh.activePlanId).to.be.null;
    });

    it('does not reset if within 30 min', () => {
      const s = getSession('u1', 'telegram');
      s.mode = 'editing';
      s.lastActivity = Date.now() - (29 * 60 * 1000);

      const same = getSession('u1', 'telegram');
      expect(same.mode).to.equal('editing');
    });
  });

  describe('setWorkingDir', () => {
    it('sets the working directory', () => {
      setWorkingDir('u1', 'telegram', '/tmp/my-project');
      expect(getSession('u1', 'telegram').workingDir).to.equal('/tmp/my-project');
    });

    it('updates lastActivity', () => {
      const s = getSession('u1', 'telegram');
      const before = s.lastActivity;
      setWorkingDir('u1', 'telegram', '/tmp/test');
      expect(getSession('u1', 'telegram').lastActivity).to.be.at.least(before);
    });
  });

  describe('getStagedImages', () => {
    it('returns empty array when no attachments', () => {
      clearSession('u1', 'telegram');
      const images = getStagedImages('u1', 'telegram');
      expect(images).to.deep.equal([]);
    });

    it('returns only image attachments as data URIs', () => {
      clearSession('u1', 'telegram');
      const s = getSession('u1', 'telegram');
      
      const imageAttachment: StagedAttachment = {
        data: new Uint8Array([0x89, 0x50, 0x4E, 0x47]),
        name: 'test.png',
        mimeType: 'image/png',
        stagedAt: Date.now(),
      };
      const pdfAttachment: StagedAttachment = {
        data: new Uint8Array([0x25, 0x50, 0x44, 0x46]),
        name: 'doc.pdf',
        mimeType: 'application/pdf',
        stagedAt: Date.now(),
      };
      
      s.pendingAttachments = [imageAttachment, pdfAttachment];
      
      const images = getStagedImages('u1', 'telegram');
      expect(images.length).to.equal(1);
      expect(images[0].name).to.equal('test.png');
      expect(images[0].contentType).to.equal('image/png');
      expect(images[0].url).to.match(/^data:image\/png;base64,/);
    });
  });

  describe('getStagedFiles', () => {
    it('returns empty array when no attachments', () => {
      clearSession('u1', 'telegram');
      const files = getStagedFiles('u1', 'telegram');
      expect(files).to.deep.equal([]);
    });

    it('returns ALL staged files (images + documents + any type)', () => {
      clearSession('u1', 'telegram');
      const s = getSession('u1', 'telegram');

      s.pendingAttachments = [
        { data: new Uint8Array([0x89, 0x50, 0x4E, 0x47]), name: 'test.png', mimeType: 'image/png', stagedAt: Date.now() },
        { data: new Uint8Array([0x25, 0x50, 0x44, 0x46]), name: 'doc.pdf', mimeType: 'application/pdf', stagedAt: Date.now() },
        { data: new Uint8Array([0x50, 0x4B]), name: 'archive.zip', mimeType: 'application/zip', stagedAt: Date.now() },
      ];

      const files = getStagedFiles('u1', 'telegram');
      expect(files.length).to.equal(3);
      expect(files.map(f => f.name)).to.deep.equal(['test.png', 'doc.pdf', 'archive.zip']);
    });

    it('returns metadata without base64 data', () => {
      clearSession('u1', 'telegram');
      const s = getSession('u1', 'telegram');

      s.pendingAttachments = [
        { data: new Uint8Array(1024), name: 'big.bin', mimeType: 'application/octet-stream', stagedAt: Date.now() },
      ];

      const files = getStagedFiles('u1', 'telegram');
      expect(files.length).to.equal(1);
      expect(files[0].name).to.equal('big.bin');
      expect(files[0].contentType).to.equal('application/octet-stream');
      expect(files[0].sizeBytes).to.equal(1024);
      // Should NOT contain a url or data field
      expect((files[0] as any).url).to.be.undefined;
      expect((files[0] as any).data).to.be.undefined;
    });

    it('includes correct sizeBytes for each file', () => {
      clearSession('u1', 'telegram');
      const s = getSession('u1', 'telegram');

      s.pendingAttachments = [
        { data: new Uint8Array(100), name: 'small.png', mimeType: 'image/png', stagedAt: Date.now() },
        { data: new Uint8Array(5000), name: 'medium.jpg', mimeType: 'image/jpeg', stagedAt: Date.now() },
      ];

      const files = getStagedFiles('u1', 'telegram');
      expect(files[0].sizeBytes).to.equal(100);
      expect(files[1].sizeBytes).to.equal(5000);
    });
  });

  describe('persistAfterMessage', () => {
    it('does not throw when called', () => {
      expect(() => persistAfterMessage()).to.not.throw();
    });
  });

  describe('flushSessionsSync', () => {
    it('writes sessions to disk', () => {
      clearSession('u1', 'telegram');
      setMode('u1', 'telegram', 'editing');
      setPlan('u1', 'telegram', 'test-plan');
      
      flushSessionsSync();
      
      expect(fs.existsSync(SESSIONS_FILE)).to.be.true;
      
      const raw = fs.readFileSync(SESSIONS_FILE, 'utf-8');
      const data = JSON.parse(raw);
      expect(data['telegram:u1']).to.exist;
      expect(data['telegram:u1'].mode).to.equal('editing');
      expect(data['telegram:u1'].activePlanId).to.equal('test-plan');
    });

    it('excludes pendingAttachments from persisted session', () => {
      clearSession('u1', 'telegram');
      setMode('u1', 'telegram', 'editing');
      const s = getSession('u1', 'telegram');
      s.pendingAttachments = [{
        data: new Uint8Array([1, 2, 3]),
        name: 'test.bin',
        mimeType: 'application/octet-stream',
        stagedAt: Date.now(),
      }];
      
      flushSessionsSync();
      
      const raw = fs.readFileSync(SESSIONS_FILE, 'utf-8');
      const data = JSON.parse(raw);
      expect(data['telegram:u1']).to.exist;
      expect(data['telegram:u1'].pendingAttachments).to.be.undefined;
    });
  });

  // ── clearChatHistory ──────────────────────────────────────────

  describe('clearChatHistory', () => {
    it('clears only chat history, preserving activePlanId', () => {
      setPlan('u1', 'telegram', 'my-plan');
      const s = getSession('u1', 'telegram');
      s.chatHistory.push({ role: 'user', content: 'hello' });
      s.chatHistory.push({ role: 'assistant', content: 'hi' });

      clearChatHistory('u1', 'telegram');

      const after = getSession('u1', 'telegram');
      expect(after.chatHistory).to.deep.equal([]);
      expect(after.activePlanId).to.equal('my-plan');
    });

    it('does not affect other users', () => {
      const s1 = getSession('u1', 'telegram');
      s1.chatHistory.push({ role: 'user', content: 'msg1' });
      const s2 = getSession('u2', 'telegram');
      s2.chatHistory.push({ role: 'user', content: 'msg2' });

      clearChatHistory('u1', 'telegram');

      expect(getSession('u1', 'telegram').chatHistory).to.have.lengthOf(0);
      expect(getSession('u2', 'telegram').chatHistory).to.have.lengthOf(1);
    });
  });

  // ── Chat history persistence ──────────────────────────────────

  describe('chatHistory persistence', () => {
    it('persists chat history to disk', () => {
      const s = getSession('u1', 'telegram');
      s.chatHistory.push({ role: 'user', content: 'test message' });
      s.chatHistory.push({ role: 'assistant', content: 'test reply' });

      flushSessionsSync();

      const raw = fs.readFileSync(SESSIONS_FILE, 'utf-8');
      const data = JSON.parse(raw);
      expect(data['telegram:u1'].chatHistory).to.have.lengthOf(2);
      expect(data['telegram:u1'].chatHistory[0].role).to.equal('user');
      expect(data['telegram:u1'].chatHistory[1].content).to.equal('test reply');
    });

    it('survives session reload', () => {
      const s = getSession('u1', 'telegram');
      s.chatHistory.push({ role: 'user', content: 'persistent msg' });
      flushSessionsSync();

      // Read raw and verify
      const raw = JSON.parse(fs.readFileSync(SESSIONS_FILE, 'utf-8'));
      expect(raw['telegram:u1'].chatHistory[0].content).to.equal('persistent msg');
    });
  });
});
