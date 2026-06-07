/**
 * Unit tests for the unified asset staging module.
 *
 * Tests the stage → flush lifecycle that is shared across Discord, Telegram,
 * and the web UI. The staging module is the single source of truth for how
 * attachments are buffered when no planId exists yet and flushed once a plan
 * is created.
 *
 * File under test: bot/src/asset-staging.ts
 */

import { expect } from 'chai';
import sinon from 'sinon';
import api from '../src/api';
import * as sessions from '../src/sessions';
import {
  stageAttachments,
  flushStagedAttachments,
  clearStagedAttachments,
  downloadAttachment,
  getStagedCount,
  getStagedSizeBytes,
  MAX_STAGED_BYTES,
} from '../src/asset-staging';

describe('asset-staging', () => {
  let sandbox: sinon.SinonSandbox;
  const USER = 'user-42';
  const PLATFORM = 'discord';

  beforeEach(() => {
    sandbox = sinon.createSandbox();
    sessions.clearSession(USER, PLATFORM);
  });

  afterEach(() => {
    sandbox.restore();
    sessions.clearSession(USER, PLATFORM);
  });

  // ── downloadAttachment ──────────────────────────────────────────

  describe('downloadAttachment', () => {
    it('downloads a file from a URL into a StagedAttachment', async () => {
      const fakeData = new Uint8Array([0x89, 0x50, 0x4e, 0x47]); // PNG magic
      sandbox.stub(globalThis, 'fetch').resolves({
        ok: true,
        arrayBuffer: async () => fakeData.buffer,
        headers: new Headers({ 'content-type': 'image/png' }),
      } as any);

      const result = await downloadAttachment({
        url: 'https://cdn.discordapp.com/photo.png',
        name: 'photo.png',
        contentType: 'image/png',
      });

      expect(result).to.not.be.null;
      expect(result!.name).to.equal('photo.png');
      expect(result!.mimeType).to.equal('image/png');
      expect(result!.data.byteLength).to.equal(4);
    });

    it('returns null when fetch fails', async () => {
      sandbox.stub(globalThis, 'fetch').rejects(new Error('Network error'));

      const result = await downloadAttachment({
        url: 'https://cdn.discordapp.com/bad.png',
        name: 'bad.png',
      });

      expect(result).to.be.null;
    });

    it('returns null when response is not OK', async () => {
      sandbox.stub(globalThis, 'fetch').resolves({
        ok: false,
        status: 404,
        headers: new Headers(),
      } as any);

      const result = await downloadAttachment({
        url: 'https://cdn.discordapp.com/gone.png',
        name: 'gone.png',
      });

      expect(result).to.be.null;
    });

    it('uses contentType from attachment over response header', async () => {
      sandbox.stub(globalThis, 'fetch').resolves({
        ok: true,
        arrayBuffer: async () => new ArrayBuffer(1),
        headers: new Headers({ 'content-type': 'application/octet-stream' }),
      } as any);

      const result = await downloadAttachment({
        url: 'https://cdn.discordapp.com/file.png',
        name: 'file.png',
        contentType: 'image/png',
      });

      expect(result!.mimeType).to.equal('image/png');
    });

    it('falls back to response content-type when attachment has none', async () => {
      sandbox.stub(globalThis, 'fetch').resolves({
        ok: true,
        arrayBuffer: async () => new ArrayBuffer(1),
        headers: new Headers({ 'content-type': 'image/jpeg' }),
      } as any);

      const result = await downloadAttachment({
        url: 'https://example.com/file',
        name: 'file',
      });

      expect(result!.mimeType).to.equal('image/jpeg');
    });
  });

  // ── stageAttachments ────────────────────────────────────────────

  describe('stageAttachments', () => {
    it('adds downloaded files to session.pendingAttachments', async () => {
      sandbox.stub(globalThis, 'fetch').resolves({
        ok: true,
        arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer,
        headers: new Headers({ 'content-type': 'image/png' }),
      } as any);

      const result = await stageAttachments(USER, PLATFORM, [
        { url: 'https://cdn.discordapp.com/a.png', name: 'a.png', contentType: 'image/png' },
        { url: 'https://cdn.discordapp.com/b.jpg', name: 'b.jpg', contentType: 'image/jpeg' },
      ]);

      expect(result.staged).to.equal(2);
      expect(result.failed).to.equal(0);
      expect(getStagedCount(USER, PLATFORM)).to.equal(2);
    });

    it('accumulates across multiple calls', async () => {
      sandbox.stub(globalThis, 'fetch').resolves({
        ok: true,
        arrayBuffer: async () => new ArrayBuffer(10),
        headers: new Headers({ 'content-type': 'image/png' }),
      } as any);

      await stageAttachments(USER, PLATFORM, [
        { url: 'https://cdn.discordapp.com/a.png', name: 'a.png' },
      ]);
      await stageAttachments(USER, PLATFORM, [
        { url: 'https://cdn.discordapp.com/b.png', name: 'b.png' },
      ]);

      expect(getStagedCount(USER, PLATFORM)).to.equal(2);
    });

    it('reports failures for files that cannot be downloaded', async () => {
      const fetchStub = sandbox.stub(globalThis, 'fetch');
      fetchStub.onFirstCall().resolves({
        ok: true,
        arrayBuffer: async () => new ArrayBuffer(1),
        headers: new Headers({ 'content-type': 'image/png' }),
      } as any);
      fetchStub.onSecondCall().resolves({
        ok: false,
        status: 404,
        headers: new Headers(),
      } as any);

      const result = await stageAttachments(USER, PLATFORM, [
        { url: 'https://cdn.discordapp.com/good.png', name: 'good.png' },
        { url: 'https://cdn.discordapp.com/missing.jpg', name: 'missing.jpg' },
      ]);

      expect(result.staged).to.equal(1);
      expect(result.failed).to.equal(1);
      expect(result.failedNames).to.include('missing.jpg');
      expect(getStagedCount(USER, PLATFORM)).to.equal(1);
    });

    it('preserves epicRef when provided', async () => {
      sandbox.stub(globalThis, 'fetch').resolves({
        ok: true,
        arrayBuffer: async () => new ArrayBuffer(5),
        headers: new Headers({ 'content-type': 'image/png' }),
      } as any);

      await stageAttachments(USER, PLATFORM, [
        { url: 'https://cdn.discordapp.com/a.png', name: 'a.png' },
      ], 'EPIC-003');

      const session = sessions.getSession(USER, PLATFORM);
      expect(session.pendingAttachments![0].epicRef).to.equal('EPIC-003');
    });

    it('rejects when total staged size exceeds MAX_STAGED_BYTES', async () => {
      // Stage a file that's just under the limit
      const bigBuffer = new ArrayBuffer(MAX_STAGED_BYTES - 100);
      sandbox.stub(globalThis, 'fetch').resolves({
        ok: true,
        arrayBuffer: async () => bigBuffer,
        headers: new Headers({ 'content-type': 'video/mp4' }),
      } as any);

      await stageAttachments(USER, PLATFORM, [
        { url: 'https://cdn.discordapp.com/big.mp4', name: 'big.mp4' },
      ]);

      // Now try staging another file that would exceed the limit
      const result = await stageAttachments(USER, PLATFORM, [
        { url: 'https://cdn.discordapp.com/another.mp4', name: 'another.mp4' },
      ]);

      expect(result.rejected).to.be.true;
      expect(getStagedCount(USER, PLATFORM)).to.equal(1); // only the first one
    });
  });

  // ── flushStagedAttachments ──────────────────────────────────────

  describe('flushStagedAttachments', () => {
    it('uploads all staged files to the plan and clears the buffer', async () => {
      // Pre-stage files
      const session = sessions.getSession(USER, PLATFORM);
      session.pendingAttachments = [
        { data: new Uint8Array([1, 2, 3]), name: 'a.png', mimeType: 'image/png', stagedAt: Date.now() },
        { data: new Uint8Array([4, 5, 6]), name: 'b.jpg', mimeType: 'image/jpeg', stagedAt: Date.now() },
      ];

      sandbox.stub(api, 'uploadPlanAssets').resolves({
        assets: [
          { filename: 'stored-a.png', original_name: 'a.png', mime_type: 'image/png', uploaded_at: '2026-01-01' },
          { filename: 'stored-b.jpg', original_name: 'b.jpg', mime_type: 'image/jpeg', uploaded_at: '2026-01-01' },
        ],
      });

      const result = await flushStagedAttachments(USER, PLATFORM, 'plan-xyz');

      expect(result.saved).to.have.length(2);
      expect(result.saved[0].original_name).to.equal('a.png');
      expect(getStagedCount(USER, PLATFORM)).to.equal(0);

      // Verify API was called with the correct planId and files
      const uploadCall = (api.uploadPlanAssets as sinon.SinonStub).firstCall;
      expect(uploadCall.args[0]).to.equal('plan-xyz');
      expect(uploadCall.args[1]).to.have.length(2);
      expect(uploadCall.args[1][0].name).to.equal('a.png');
    });

    it('returns empty when no staged files exist', async () => {
      const result = await flushStagedAttachments(USER, PLATFORM, 'plan-xyz');

      expect(result.saved).to.have.length(0);
      expect(result.failures).to.have.length(0);
    });

    it('preserves epicRef during upload', async () => {
      const session = sessions.getSession(USER, PLATFORM);
      session.pendingAttachments = [
        { data: new Uint8Array([1]), name: 'spec.png', mimeType: 'image/png', stagedAt: Date.now(), epicRef: 'EPIC-002' },
      ];

      sandbox.stub(api, 'uploadPlanAssets').resolves({
        assets: [{ filename: 's.png', original_name: 'spec.png', mime_type: 'image/png', uploaded_at: '2026-01-01' }],
      });

      await flushStagedAttachments(USER, PLATFORM, 'plan-abc');

      const uploadCall = (api.uploadPlanAssets as sinon.SinonStub).firstCall;
      expect(uploadCall.args[2]).to.deep.include({ epicRef: 'EPIC-002' });
    });

    it('handles upload API failure gracefully', async () => {
      const session = sessions.getSession(USER, PLATFORM);
      session.pendingAttachments = [
        { data: new Uint8Array([1]), name: 'a.png', mimeType: 'image/png', stagedAt: Date.now() },
      ];

      sandbox.stub(api, 'uploadPlanAssets').resolves({
        error: 'Disk full',
        assets: [],
      });

      const result = await flushStagedAttachments(USER, PLATFORM, 'plan-xyz');

      expect(result.saved).to.have.length(0);
      expect(result.failures).to.include('Disk full');
      // Buffer should still be cleared even on failure (files were sent)
      expect(getStagedCount(USER, PLATFORM)).to.equal(0);
    });
  });

  // ── clearStagedAttachments ──────────────────────────────────────

  describe('clearStagedAttachments', () => {
    it('removes all staged files from session', () => {
      const session = sessions.getSession(USER, PLATFORM);
      session.pendingAttachments = [
        { data: new Uint8Array([1]), name: 'a.png', mimeType: 'image/png', stagedAt: Date.now() },
      ];

      clearStagedAttachments(USER, PLATFORM);

      expect(getStagedCount(USER, PLATFORM)).to.equal(0);
      expect(session.pendingAttachments).to.have.length(0);
    });

    it('is safe to call when no files are staged', () => {
      clearStagedAttachments(USER, PLATFORM); // should not throw
      expect(getStagedCount(USER, PLATFORM)).to.equal(0);
    });
  });

  // ── getStagedCount / getStagedSizeBytes ─────────────────────────

  describe('getStagedCount & getStagedSizeBytes', () => {
    it('returns 0 for a fresh session', () => {
      expect(getStagedCount(USER, PLATFORM)).to.equal(0);
      expect(getStagedSizeBytes(USER, PLATFORM)).to.equal(0);
    });

    it('returns correct count and size after staging', () => {
      const session = sessions.getSession(USER, PLATFORM);
      session.pendingAttachments = [
        { data: new Uint8Array(100), name: 'a.png', mimeType: 'image/png', stagedAt: Date.now() },
        { data: new Uint8Array(200), name: 'b.jpg', mimeType: 'image/jpeg', stagedAt: Date.now() },
      ];

      expect(getStagedCount(USER, PLATFORM)).to.equal(2);
      expect(getStagedSizeBytes(USER, PLATFORM)).to.equal(300);
    });
  });

  // ── Cross-platform isolation ────────────────────────────────────

  describe('cross-platform isolation', () => {
    it('discord and telegram staging buffers are independent', async () => {
      sandbox.stub(globalThis, 'fetch').resolves({
        ok: true,
        arrayBuffer: async () => new ArrayBuffer(5),
        headers: new Headers({ 'content-type': 'image/png' }),
      } as any);

      await stageAttachments(USER, 'discord', [
        { url: 'https://cdn/d1.png', name: 'd1.png' },
        { url: 'https://cdn/d2.png', name: 'd2.png' },
      ]);
      await stageAttachments(USER, 'telegram', [
        { url: 'https://cdn/t1.png', name: 't1.png' },
      ]);

      expect(getStagedCount(USER, 'discord')).to.equal(2);
      expect(getStagedCount(USER, 'telegram')).to.equal(1);

      clearStagedAttachments(USER, 'discord');

      expect(getStagedCount(USER, 'discord')).to.equal(0);
      expect(getStagedCount(USER, 'telegram')).to.equal(1);
    });
  });

  // ── Session timeout clears staging ──────────────────────────────

  describe('session timeout', () => {
    it('staged files are lost when session expires', async () => {
      const session = sessions.getSession(USER, PLATFORM);
      session.pendingAttachments = [
        { data: new Uint8Array(10), name: 'old.png', mimeType: 'image/png', stagedAt: Date.now() },
      ];

      session.lastActivity = Date.now() - 8 * 24 * 60 * 60 * 1000;

      const freshSession = sessions.getSession(USER, PLATFORM);
      expect(freshSession.pendingAttachments).to.have.length(0);
    });
  });

  // ── Full stage→flush lifecycle ──────────────────────────────────

  describe('full lifecycle', () => {
    it('stage → create plan → flush works end-to-end', async () => {
      // 1. Stage files (no plan yet)
      sandbox.stub(globalThis, 'fetch').resolves({
        ok: true,
        arrayBuffer: async () => new Uint8Array([10, 20, 30]).buffer,
        headers: new Headers({ 'content-type': 'image/png' }),
      } as any);

      const stageResult = await stageAttachments(USER, PLATFORM, [
        { url: 'https://cdn/hero.png', name: 'hero.png', contentType: 'image/png' },
      ]);
      expect(stageResult.staged).to.equal(1);

      // 2. Simulate plan creation (as agent-bridge would do)
      sessions.setMode(USER, PLATFORM, 'editing');
      sessions.setPlan(USER, PLATFORM, 'new-blog-plan');

      // 3. Flush staged files to the new plan
      sandbox.stub(api, 'uploadPlanAssets').resolves({
        assets: [
          { filename: 'stored-hero.png', original_name: 'hero.png', mime_type: 'image/png', uploaded_at: '2026-01-01' },
        ],
      });

      const flushResult = await flushStagedAttachments(USER, PLATFORM, 'new-blog-plan');
      expect(flushResult.saved).to.have.length(1);
      expect(flushResult.saved[0].original_name).to.equal('hero.png');
      expect(getStagedCount(USER, PLATFORM)).to.equal(0);
    });
  });
});
