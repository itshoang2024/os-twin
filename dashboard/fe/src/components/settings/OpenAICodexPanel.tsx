'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, apiGet, apiPost } from '@/lib/api-client';
import type { ProviderSettings } from '@/types/settings';

type CodexOAuthStart = {
  authorization_url: string;
};

type CodexSessionStatus = {
  connected: boolean;
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
  onSettingsChange,
}: {
  provider: ProviderSettings;
  onSettingsChange: (updates: Partial<ProviderSettings>) => void | Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState<boolean | null>(null);
  const popupPollRef = useRef<number | null>(null);

  const stopPopupPoll = useCallback(() => {
    if (popupPollRef.current !== null) {
      window.clearInterval(popupPollRef.current);
      popupPollRef.current = null;
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
    return stopPopupPoll;
  }, [refreshSession, stopPopupPoll]);

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

      void Promise.resolve(
        onSettingsChange({
          enabled: true,
          auth_mode: 'codex_oauth',
          default_model: 'openai/gpt-5.3-codex',
          model_variant: provider.model_variant || 'medium',
        }),
      ).catch((err) => {
        window.alert(err instanceof Error ? err.message : 'Codex login saved, but settings update failed.');
      });
      setConnected(true);
      window.dispatchEvent(new CustomEvent('ostwin:models-updated'));
      refreshSession();
    };

    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [onSettingsChange, provider.model_variant, refreshSession, stopPopupPoll]);

  const login = async () => {
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

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={login}
        disabled={busy}
        className="w-full rounded bg-slate-900 px-4 py-3 text-xs font-bold uppercase text-white hover:bg-slate-800 disabled:cursor-wait disabled:opacity-60"
      >
        {busy ? 'Opening OpenAI' : 'Login with Codex'}
      </button>
      <div className="flex items-center justify-center gap-2 text-[10px] font-bold uppercase tracking-wide text-slate-500">
        <span className={`h-2 w-2 rounded-full ${connected ? 'bg-green-500' : 'bg-slate-300'}`} />
        {connected ? 'Connected' : 'Not connected'}
      </div>
    </div>
  );
}
