'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, apiGet, apiPost } from '@/lib/api-client';
import type { ProviderSettings } from '@/types/settings';
import { ProviderIcon } from './ProviderIcon';

type CopilotSessionStatus = {
  connected: boolean;
};

type CopilotOAuthStart = {
  authorization_url: string;
};

type CopilotAuthMethod = 'oauth' | 'device';

type CopilotDeviceStatus = {
  status: 'idle' | 'pending' | 'connected' | 'error' | string;
  connected: boolean;
  verification_url?: string | null;
  user_code?: string | null;
  message?: string | null;
};

function getErrorMessage(err: unknown, fallback: string) {
  if (err instanceof ApiError && err.data && typeof err.data === 'object' && 'detail' in err.data) {
    const detail = (err.data as { detail?: unknown }).detail;
    if (typeof detail === 'string') return detail;
  }
  return err instanceof Error ? err.message : fallback;
}

function writePopupMessage(popup: Window | null, title: string, message: string) {
  if (!popup) return;
  popup.document.open();
  popup.document.write(
    `<!doctype html><title>${title}</title><body style="font-family:system-ui;padding:24px;line-height:1.5"><h2 style="font-size:18px;margin:0 0 12px">${title}</h2><pre style="white-space:pre-wrap;font-family:ui-monospace,monospace;font-size:12px">${message}</pre></body>`,
  );
  popup.document.close();
}

export function GitHubCopilotPanel({
  provider,
  onSettingsChange,
}: {
  provider: ProviderSettings;
  onSettingsChange: (updates: Partial<ProviderSettings>) => void | Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [authMethod, setAuthMethod] = useState<CopilotAuthMethod>('oauth');
  const [deviceStatus, setDeviceStatus] = useState<CopilotDeviceStatus | null>(null);
  const pollRef = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const refreshSession = useCallback(async () => {
    try {
      const session = await apiGet<CopilotSessionStatus>('/settings/github/copilot/session');
      setConnected(session.connected);
    } catch {
      setConnected(null);
    }
  }, []);

  useEffect(() => {
    refreshSession();
    return () => stopPolling();
  }, [refreshSession, stopPolling]);

  const applyConnectedSettings = useCallback(async () => {
    await Promise.resolve(
      onSettingsChange({
        enabled: true,
        auth_mode: 'copilot_oauth',
        default_model: provider.default_model || 'github-copilot/gpt-5.2',
      }),
    );
    setConnected(true);
    window.dispatchEvent(new CustomEvent('ostwin:models-updated'));
    refreshSession();
  }, [onSettingsChange, provider.default_model, refreshSession]);

  useEffect(() => {
    const handler = (event: MessageEvent) => {
      if (event.data?.type !== 'github_copilot_oauth_result') return;
      stopPolling();
      setBusy(false);

      if (event.data.status !== 'success') {
        setDeviceStatus({
          status: 'error',
          connected: false,
          message: event.data.message || 'GitHub Copilot login failed.',
        });
        return;
      }

      void applyConnectedSettings();
    };

    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [applyConnectedSettings, stopPolling]);

  const pollStatus = useCallback(async () => {
    try {
      const status = await apiGet<CopilotDeviceStatus>('/settings/github/copilot/device/status');
      setDeviceStatus(status);

      if (status.connected || status.status === 'connected') {
        stopPolling();
        setBusy(false);
        await applyConnectedSettings();
        return;
      }

      if (status.status === 'error') {
        stopPolling();
        setBusy(false);
      }
    } catch (err) {
      stopPolling();
      setBusy(false);
      window.alert(getErrorMessage(err, 'Failed to check GitHub Copilot login.'));
    }
  }, [applyConnectedSettings, stopPolling]);

  const loginOAuth = async () => {
    setBusy(true);
    setDeviceStatus(null);
    const popup = window.open('', 'github_copilot_oauth', 'width=620,height=760,scrollbars=yes');

    try {
      if (popup) {
        popup.document.write(
          '<!doctype html><title>GitHub Copilot</title><body style="font-family:system-ui;padding:24px">Preparing GitHub login...</body>',
        );
        popup.focus();
      }

      const result = await apiPost<CopilotOAuthStart>('/settings/github/oauth/start');
      if (popup) {
        popup.location.href = result.authorization_url;
      }
    } catch (err) {
      writePopupMessage(popup, 'GitHub Copilot Login Failed', getErrorMessage(err, 'Failed to start GitHub Copilot login.'));
      setDeviceStatus({
        status: 'error',
        connected: false,
        message: getErrorMessage(err, 'Failed to start GitHub Copilot login.'),
      });
      stopPolling();
      setBusy(false);
    }
  };

  const loginDevice = async () => {
    setBusy(true);
    setDeviceStatus(null);
    const popup = window.open('', 'github_copilot_device', 'width=620,height=760,scrollbars=yes');

    try {
      if (popup) {
        popup.document.write(
          '<!doctype html><title>GitHub Copilot</title><body style="font-family:system-ui;padding:24px">Preparing GitHub device login...</body>',
        );
        popup.focus();
      }

      const result = await apiPost<CopilotDeviceStatus>('/settings/github/copilot/device/start');
      setDeviceStatus(result);

      if (popup && result.verification_url) {
        popup.location.href = result.verification_url;
      } else {
        writePopupMessage(
          popup,
          'GitHub Copilot Login',
          result.message || 'Waiting for GitHub device code. The dashboard will update when OpenCode returns it.',
        );
      }

      if (result.connected || result.status === 'connected') {
        popup?.close();
        setBusy(false);
        await applyConnectedSettings();
        return;
      }

      if (result.status === 'error') {
        writePopupMessage(popup, 'GitHub Copilot Login Failed', result.message || 'GitHub Copilot login failed.');
        throw new Error(result.message || 'GitHub Copilot login failed.');
      }

      stopPolling();
      pollRef.current = window.setInterval(() => {
        void pollStatus();
      }, 1200);
    } catch (err) {
      writePopupMessage(popup, 'GitHub Copilot Login Failed', getErrorMessage(err, 'Failed to start GitHub Copilot login.'));
      stopPolling();
      setBusy(false);
      window.alert(getErrorMessage(err, 'Failed to start GitHub Copilot login.'));
    }
  };

  const login = async () => {
    if (authMethod === 'device') {
      await loginDevice();
      return;
    }
    await loginOAuth();
  };

  return (
    <div
      aria-label="GitHub Copilot provider credentials"
      className="relative rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
      role="region"
    >
      <div className="absolute left-0 top-6 h-8 w-1 bg-slate-900" />

      <div className="mb-5 flex items-center gap-3">
        <ProviderIcon provider="github-copilot" size={22} />
        <h3 className="text-xs font-bold uppercase tracking-widest text-slate-900">github copilot</h3>
      </div>

      <div className="space-y-3">
        <div>
          <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-widest text-slate-500">
            Login Method
          </label>
          <div
            aria-label="GitHub Copilot login method"
            className="grid grid-cols-2 overflow-hidden rounded border border-slate-200"
            role="group"
          >
            <button
              type="button"
              aria-pressed={authMethod === 'oauth'}
              onClick={() => {
                setAuthMethod('oauth');
                setDeviceStatus(null);
              }}
              className={`px-3 py-2 text-xs font-bold uppercase ${
                authMethod === 'oauth' ? 'bg-slate-900 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'
              }`}
            >
              Browser OAuth
            </button>
            <button
              type="button"
              aria-pressed={authMethod === 'device'}
              onClick={() => {
                setAuthMethod('device');
                setDeviceStatus(null);
              }}
              className={`border-l border-slate-200 px-3 py-2 text-xs font-bold uppercase ${
                authMethod === 'device' ? 'bg-slate-900 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'
              }`}
            >
              Device Code
            </button>
          </div>
        </div>

        <button
          type="button"
          onClick={login}
          disabled={busy}
          className="w-full rounded bg-slate-900 px-4 py-3 text-xs font-bold uppercase text-white hover:bg-slate-800 disabled:cursor-wait disabled:opacity-60"
        >
          {busy ? 'Waiting for GitHub' : 'Login with GitHub Copilot'}
        </button>

        <div className="flex items-center justify-center gap-2 text-[10px] font-bold uppercase tracking-wide text-slate-500">
          <span className={`h-2 w-2 rounded-full ${connected ? 'bg-green-500' : 'bg-slate-300'}`} />
          {connected ? 'Copilot connected' : 'Copilot not connected'}
        </div>

        {deviceStatus && (
          <div
            className={`border-t border-slate-100 pt-3 text-xs ${
              deviceStatus.status === 'error' ? 'text-red-700' : 'text-slate-600'
            }`}
          >
            {deviceStatus.user_code && (
              <div className="mb-2 flex items-center justify-between gap-3">
                <span className="font-bold uppercase tracking-wide text-slate-500">Device code</span>
                <span className="font-mono text-sm font-bold text-slate-900">{deviceStatus.user_code}</span>
              </div>
            )}
            {deviceStatus.verification_url && (
              <a
                href={deviceStatus.verification_url}
                target="_blank"
                rel="noreferrer"
                className="font-bold text-slate-900 underline underline-offset-2"
              >
                Open GitHub device login
              </a>
            )}
            <div className="mt-2 text-[11px] uppercase tracking-wide text-slate-500">
              {deviceStatus.message || deviceStatus.status}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
