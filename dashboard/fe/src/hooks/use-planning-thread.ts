import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import useSWR from 'swr';
import { PlanningThread, PlanningMessage, ImageAttachment } from '@/types';
import { apiPost } from '@/lib/api-client';
import { getApiBaseUrl } from '@/lib/runtime-config';

interface ThreadDetailResponse {
  thread: PlanningThread;
  messages: PlanningMessage[];
}

interface StreamEvent {
  token?: string;
  error?: string;
  done?: boolean;
}

function asError(err: unknown): Error {
  return err instanceof Error ? err : new Error(String(err));
}

export function usePlanningThread(id: string) {
  const { data, error: swrError, mutate, isLoading } = useSWR<ThreadDetailResponse>(
    id ? `/plans/threads/${id}` : null
  );

  const [optimisticMessages, setOptimisticMessages] = useState<PlanningMessage[]>([]);
  const [streamedResponse, setStreamedResponse] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  
  const abortControllerRef = useRef<AbortController | null>(null);

  // Derive final messages from SWR + optimistic additions
  const serverMessages = useMemo(() => data?.messages || [], [data?.messages]);
  const messages = isStreaming || optimisticMessages.length > 0 
    ? [...serverMessages, ...optimisticMessages]
    : serverMessages;

  // Keep a ref so sendMessage always reads the latest server messages
  const serverMessagesRef = useRef(serverMessages);
  useEffect(() => { serverMessagesRef.current = serverMessages; }, [serverMessages]);

  const cancel = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setIsStreaming(false);
    }
  }, []);

  const sendMessage = useCallback(async (content: string, images?: ImageAttachment[]) => {
    if (!id || (!content.trim() && (!images || images.length === 0)) || isStreaming) return;

    setError(null);
    setStreamedResponse('');
    setIsStreaming(true);

    const userMessage: PlanningMessage = {
      id: `temp-${Date.now()}`,
      role: 'user',
      content,
      created_at: new Date().toISOString(),
      images: images && images.length > 0 ? images : undefined,
    };

    // Optimistic UI update — skip if this message already exists in server data
    // (e.g. auto-triggering reply for the initial message saved at thread creation)
    const alreadyExists = serverMessagesRef.current.some(
      (m) => m.role === 'user' && m.content === content
    );
    if (!alreadyExists) {
      setOptimisticMessages([userMessage]);
    }

    abortControllerRef.current = new AbortController();

    const body: Record<string, unknown> = { message: content };
    if (images && images.length > 0) {
      body.images = images.map(img => ({ url: img.url, name: img.name, type: img.type }));
    }

    try {
      const response = await fetch(`${getApiBaseUrl()}/plans/threads/${id}/messages/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify(body),
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error(`API Error: ${response.status}`);
      }

      if (!response.body) {
        throw new Error('No response body');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let fullAssistantMessage = '';
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        
        // Keep the last partial line in the buffer
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.slice(6);
            if (!dataStr.trim() || dataStr === '[DONE]') continue;

            let eventData: StreamEvent;
            try {
              eventData = JSON.parse(dataStr);
            } catch (e) {
              console.error('Error parsing SSE data', e, 'Data:', dataStr);
              continue;
            }

            if (eventData.token) {
              fullAssistantMessage += eventData.token;
              setStreamedResponse(fullAssistantMessage);
            } else if (eventData.error) {
              throw new Error(eventData.error);
            } else if (eventData.done) {
              // Done event
            }
          }
        }
      }

      // Stream completed successfully
      setIsStreaming(false);
      setStreamedResponse('');
      
      // Update local messages with final assistant message
      const assistantMessage: PlanningMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: fullAssistantMessage,
        created_at: new Date().toISOString()
      };
      
      setOptimisticMessages(prev => [...prev, assistantMessage]);
      
      // Revalidate to pick up the updated thread title if any
      mutate().then(() => {
        // Once SWR has re-fetched, clear optimistic messages because SWR has the truth
        setOptimisticMessages([]);
      });

    } catch (err: unknown) {
      const nextError = asError(err);
      if (nextError.name !== 'AbortError') {
        setError(nextError);
      }
      setIsStreaming(false);
      // Remove optimistic message on error? SWR mutate will restore server state
      mutate().then(() => setOptimisticMessages([]));
    }
  }, [id, isStreaming, mutate]);

  const promoteToPlan = useCallback(async (title?: string, workingDir?: string) => {
    try {
      const result = await apiPost<{ plan_id: string; url: string }>(`/plans/threads/${id}/promote`, {
        title,
        working_dir: workingDir
      });
      return result;
    } catch (err: unknown) {
      setError(asError(err));
      throw err;
    }
  }, [id]);

  return {
    thread: data?.thread,
    messages: messages,
    streamedResponse,
    isStreaming,
    error: error || swrError,
    isLoading,
    sendMessage,
    promoteToPlan,
    cancel
  };
}
