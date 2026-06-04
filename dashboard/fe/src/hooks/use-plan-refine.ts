'use client';

import { useState, useCallback, useRef } from 'react';
import { getApiBaseUrl } from '@/lib/runtime-config';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export function usePlanRefine() {
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [isRefining, setIsRefining] = useState(false);
  const [streamedResponse, setStreamedResponse] = useState('');
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const seededRef = useRef(false);

  /** Seed chat history once (idempotent). Skips if history already has messages. */
  const seedHistory = useCallback((messages: ChatMessage[]) => {
    if (seededRef.current) return;
    seededRef.current = true;
    setChatHistory((prev) => (prev.length === 0 ? messages : prev));
  }, []);

  const refine = useCallback(
    async (message: string, planContent: string = '', planId: string = '') => {
      setIsRefining(true);
      setStreamedResponse('');
      setError(null);

      setChatHistory((prev) => [...prev, { role: 'user', content: message }]);

      const historyForApi = chatHistory.slice(-10).map((m) => ({
        role: m.role,
        content: m.content,
      }));

      const abortController = new AbortController();
      abortRef.current = abortController;

      try {
        const BASE_URL = getApiBaseUrl();
        const res = await fetch(`${BASE_URL}/plans/refine/stream`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message,
            plan_content: planContent,
            plan_id: planId,
            chat_history: historyForApi,
          }),
          signal: abortController.signal,
        });

        if (!res.ok) {
          const errorData = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
          throw new Error(errorData.detail || `HTTP ${res.status}`);
        }

        const reader = res.body?.getReader();
        if (!reader) throw new Error('No response body');

        const decoder = new TextDecoder();
        let accumulated = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const text = decoder.decode(value, { stream: true });
          const lines = text.split('\n');

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const jsonStr = line.slice(6).trim();
            if (!jsonStr) continue;

            try {
              const data = JSON.parse(jsonStr);
              if (data.token) {
                accumulated += data.token;
                setStreamedResponse(accumulated);
              }
              if (data.error) {
                setError(data.error);
              }
            } catch {
              // Skip malformed JSON
            }
          }
        }

        if (accumulated) {
          setChatHistory((prev) => [
            ...prev,
            { role: 'assistant', content: accumulated },
          ]);
        }
      } catch (err: unknown) {
        if ((err as Error).name === 'AbortError') return;
        const msg = err instanceof Error ? err.message : 'Unknown error';
        setError(msg);

        try {
          const BASE_URL = getApiBaseUrl();
          const res = await fetch(`${BASE_URL}/plans/refine`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              message,
              plan_content: planContent,
              plan_id: planId,
              chat_history: historyForApi,
            }),
          });

          if (res.ok) {
            const data = await res.json();
            const fullResponse = data.refined_plan || '';
            setStreamedResponse(fullResponse);
            setError(null);
            setChatHistory((prev) => [
              ...prev,
              { role: 'assistant', content: fullResponse },
            ]);
          }
        } catch {
          // Both endpoints failed
        }
      } finally {
        setIsRefining(false);
        abortRef.current = null;
      }
    },
    [chatHistory]
  );

  const cancelRefine = useCallback(() => {
    abortRef.current?.abort();
    setIsRefining(false);
  }, []);

  const clearHistory = useCallback(() => {
    setChatHistory([]);
    setStreamedResponse('');
    setError(null);
  }, []);

  return {
    chatHistory,
    isRefining,
    streamedResponse,
    error,
    refine,
    cancelRefine,
    clearHistory,
    seedHistory,
  };
}
