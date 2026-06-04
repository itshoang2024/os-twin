'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, apiGet, apiPost } from '@/lib/api-client';
import type { ProviderSettings } from '@/types/settings';
import { ProviderIcon } from './ProviderIcon';

type CodexOAuthStart = {
  authorization_url: string;
};

type CodexSessionStatus = {
  connected: boolean;
};

type CodexAuthMethod = 'browser' | 'device';

type CodexDeviceStatus = {
  status: 'idle' | 'pending' | 'connected' | 'error' | string;
  connected: boolean;
  verification_url?: string | null;
  user_code?: string | null;
  message?: string | null;
};

const CALLBACK_ORIGINS = new Set([
  'http://localhost:1455',
  'http://127.0.0.1:1455',
  'http://[::1]:1455',
]);

function getErrorMessage(err: unknown, fallback: string) {
  if (err instanceof ApiError && err.data && typeof err.data === 'object' && 'detail' in err.data) {
    const detail = (err.data as { detail?: unknown }).detail;
    if (typeof detail === 'string') return detail;
  }
  return err instanceof Error ? err.message : fallback;
}

export function OpenAICodexPanel({
  provider,
  onVaultClick,
  vaultSet,
  onSettingsChange,
}: {
  provider: ProviderSettings;
  onVaultClick: () => void;
  vaultSet: boolean;
  onSettingsChange: (updates: Partial<ProviderSettings>) => void | Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [authMethod, setAuthMethod] = useState<CodexAuthMethod>('browser');
  const [deviceStatus, setDeviceStatus] = useState<CodexDeviceStatus | null>(null);
  const popupPollRef = useRef<number | null>(null);
  const devicePollRef = useRef<number | null>(null);

  const stopPopupPoll = useCallback(() => {
    if (popupPollRef.current !== null) {
      window.clearInterval(popupPollRef.current);
      popupPollRef.current = null;
    }
  }, []);

  const stopDevicePoll = useCallback(() => {
    if (devicePollRef.current !== null) {
      window.clearInterval(devicePollRef.current);
      devicePollRef.current = null;
    }
  }, []);

  const refreshSession = useCallback(async () => {
    try {
      const session = await apiGet<CodexSessionStatus>('/settings/openai/codex/session');
      setConnected(session.connected);
    } catch {
      setConnected(null);
    }
  }, []);

  useEffect(() => {
    refreshSession();
    return () => {
      stopPopupPoll();
      stopDevicePoll();
    };
  }, [refreshSession, stopDevicePoll, stopPopupPoll]);

  const applyConnectedSettings = useCallback(async () => {
    try {
      await Promise.resolve(
        onSettingsChange({
          enabled: true,
          auth_mode: 'codex_oauth',
          default_model: 'openai/gpt-5.3-codex',
          model_variant: provider.model_variant || 'medium',
        }),
      );
    } catch (err) {
      window.alert(err instanceof Error ? err.message : 'Codex login saved, but settings update failed.');
    }
    setConnected(true);
    window.dispatchEvent(new CustomEvent('ostwin:models-updated'));
    refreshSession();
  }, [onSettingsChange, provider.model_variant, refreshSession]);

  const pollDeviceStatus = useCallback(async () => {
    try {
      const status = await apiGet<CodexDeviceStatus>('/settings/openai/codex/device/status');
      setDeviceStatus(status);

      if (status.connected || status.status === 'connected') {
        stopDevicePoll();
        setBusy(false);
        await applyConnectedSettings();
        return;
      }

      if (status.status === 'error') {
        stopDevicePoll();
        setBusy(false);
        window.alert(status.message || 'Codex device login failed.');
      }
    } catch (err) {
      stopDevicePoll();
      setBusy(false);
      window.alert(getErrorMessage(err, 'Failed to check Codex device login.'));
    }
  }, [applyConnectedSettings, stopDevicePoll]);

  const startDevicePolling = useCallback(() => {
    stopDevicePoll();
    devicePollRef.current = window.setInterval(() => {
      void pollDeviceStatus();
    }, 1200);
  }, [pollDeviceStatus, stopDevicePoll]);

  useEffect(() => {
    const handler = (event: MessageEvent) => {
      if (event.data?.type !== 'openai_codex_oauth_result') return;
      if (!CALLBACK_ORIGINS.has(event.origin)) return;
      stopPopupPoll();
      setBusy(false);

      if (event.data.status !== 'success') {
        window.alert(event.data.message || 'Codex login failed.');
        return;
      }

      void applyConnectedSettings();
    };

    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [applyConnectedSettings, stopPopupPoll]);

  const loginBrowser = async () => {
    setBusy(true);
    const popup = window.open('', 'openai_codex_oauth', 'width=620,height=760,scrollbars=yes');

    try {
      if (!popup) {
        throw new Error('Allow popups for this dashboard, then try again.');
      }

      popup.document.write(
        '<!doctype html><title>OpenAI</title><body style="font-family:system-ui;padding:24px">Opening OpenAI...</body>',
      );
      popup.focus();

      stopPopupPoll();
      popupPollRef.current = window.setInterval(() => {
        if (popup.closed) {
          stopPopupPoll();
          setBusy(false);
        }
      }, 700);

      const result = await apiPost<CodexOAuthStart>('/settings/openai/codex/oauth/start');
      popup.location.href = result.authorization_url;
    } catch (err) {
      popup?.close();
      stopPopupPoll();
      setBusy(false);
      window.alert(getErrorMessage(err, 'Failed to open Codex login.'));
    }
  };

  const loginDevice = async () => {
    setBusy(true);
    setDeviceStatus(null);
    const popup = window.open('', 'openai_codex_device', 'width=620,height=760,scrollbars=yes');

    try {
      if (popup) {
        popup.document.write(
          '<!doctype html><title>OpenAI</title><body style="font-family:system-ui;padding:24px">Preparing device login...</body>',
        );
        popup.focus();
      }

      const result = await apiPost<CodexDeviceStatus>('/settings/openai/codex/device/start');
      setDeviceStatus(result);

      if (popup && result.verification_url) {
        popup.location.href = result.verification_url;
      } else if (popup) {
        popup.document.write(
          '<!doctype html><title>OpenAI</title><body style="font-family:system-ui;padding:24px">Waiting for device code...</body>',
        );
      }

      if (result.connected || result.status === 'connected') {
        popup?.close();
        setBusy(false);
        await applyConnectedSettings();
        return;
      }

      if (result.status === 'error') {
        popup?.close();
        throw new Error(result.message || 'Codex device login failed.');
      }

      startDevicePolling();
    } catch (err) {
      popup?.close();
      stopDevicePoll();
      setBusy(false);
      window.alert(getErrorMessage(err, 'Failed to start Codex device login.'));
    }
  };

  const login = async () => {
    if (authMethod === 'device') {
      await loginDevice();
      return;
    }
    await loginBrowser();
  };

  return (
    <div
      aria-label="OpenAI provider credentials"
      className="relative rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
      role="region"
    >
      <div className="absolute left-0 top-6 h-8 w-1 bg-green-600" />

      <div className="mb-4 flex items-center gap-3">
        <ProviderIcon provider="openai" size={20} />
        <h3 className="text-xs font-bold uppercase tracking-widest text-slate-900">openai</h3>
      </div>

      <div className="space-y-4">
        <div>
          <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-widest text-slate-500">
            API Access Key
          </label>
          <button
            type="button"
            onClick={onVaultClick}
            className="flex w-full items-center justify-between rounded border border-slate-200 bg-slate-50 p-2.5 text-left font-mono text-xs transition-colors hover:bg-slate-100"
          >
            <span className="text-slate-400">
              {vaultSet ? '••••••••••••••••••••••••' : 'Click to configure'}
            </span>
            <span className={`material-symbols-outlined text-sm ${vaultSet ? 'text-green-600' : 'text-slate-400'}`}>
              {vaultSet ? 'check_circle' : 'vpn_key'}
            </span>
          </button>
        </div>

        <div>
          <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-widest text-slate-500">
            Login Method
          </label>
          <div
            aria-label="Codex login method"
            className="grid grid-cols-2 overflow-hidden rounded border border-slate-200"
            role="group"
          >
            <button
              type="button"
              aria-pressed={authMethod === 'browser'}
              onClick={() => {
                setAuthMethod('browser');
                setDeviceStatus(null);
              }}
              className={`px-3 py-2 text-xs font-bold uppercase ${
                authMethod === 'browser' ? 'bg-slate-900 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'
              }`}
            >
              Browser
            </button>
            <button
              type="button"
              aria-pressed={authMethod === 'device'}
              onClick={() => setAuthMethod('device')}
              className={`border-l border-slate-200 px-3 py-2 text-xs font-bold uppercase ${
                authMethod === 'device' ? 'bg-slate-900 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'
              }`}
            >
              Device code
            </button>
          </div>
          {authMethod === 'browser' && (
            <div className="mt-2 rounded border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] leading-5 text-slate-700">
              Browser login uses local callback port 1455. Make sure port 1455 is free. If it is busy, use Device code.
            </div>
          )}
          {authMethod === 'device' && (
            <div className="mt-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] leading-5 text-amber-900">
              <div className="font-bold uppercase tracking-wide">Device code access</div>
              <ul className="mt-1 list-disc space-y-1 pl-4">
                <li>If device code is already enabled, continue below.</li>
                <li>If OpenAI blocks login, open ChatGPT account Security Settings.</li>
                <li>Enable Codex device code authorization there.</li>
                <li>Return here and click Login with Codex.</li>
              </ul>
            </div>
          )}
        </div>

        <div className="space-y-2">
          <button
            type="button"
            onClick={login}
            disabled={busy}
            className="w-full rounded bg-slate-900 px-4 py-3 text-xs font-bold uppercase text-white hover:bg-slate-800 disabled:cursor-wait disabled:opacity-60"
          >
            {busy ? (authMethod === 'device' ? 'Waiting for Codex' : 'Opening OpenAI') : 'Login with Codex'}
          </button>
          <div className="flex items-center justify-center gap-2 text-[10px] font-bold uppercase tracking-wide text-slate-500">
            <span className={`h-2 w-2 rounded-full ${connected ? 'bg-green-500' : 'bg-slate-300'}`} />
            {connected ? 'Codex connected' : 'Codex not connected'}
          </div>
        </div>

        {authMethod === 'device' && deviceStatus && (
          <div className="border-t border-slate-100 pt-3 text-xs text-slate-600">
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
                Open OpenAI device login
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
