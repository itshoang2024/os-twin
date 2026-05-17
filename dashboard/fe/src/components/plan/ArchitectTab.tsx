'use client';

import React, { useRef, useEffect, useState } from 'react';
import { usePlanContext } from './PlanWorkspace';
import { usePlanningThread } from '@/hooks/use-planning-thread';
import { usePlanRefine } from '@/hooks/use-plan-refine';
import { AgentResponse } from '@/components/chat/AgentResponse';
import { Button } from '@/components/ui/Button';
import type { ImageAttachment } from '@/types';
import { processImages, MAX_IMAGES, type ProcessedImage } from '@/lib/image-utils';
import { extractPlan } from '@/lib/extract-plan';

const IDEA_PROMPTS = [
  'What are the main risks?',
  'Break this into more epics',
  'Suggest acceptance criteria',
  'What dependencies should I consider?',
];

const REFINE_PROMPTS = [
  'Break this into epics',
  'Add acceptance criteria',
  'Add more detail',
  'Simplify the plan',
];

// ── Shared message bubble components ────────────────────────────────

function AssistantAvatar() {
  return (
    <div
      className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-1"
      style={{ background: 'var(--color-primary-muted)' }}
    >
      <span className="material-symbols-outlined text-[16px]" style={{ color: 'var(--color-primary)' }}>
        smart_toy
      </span>
    </div>
  );
}

function UserBubble({ content, images }: { content: string; images?: ImageAttachment[] }) {
  return (
    <div className="flex gap-3 justify-end">
      <div className="inline-block text-left max-w-[85%]">
        {images && images.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-1.5 justify-end">
            {images.map((img, i) => (
              <img
                key={i}
                src={img.url}
                alt={img.name || 'attachment'}
                className="w-20 h-20 object-cover rounded-lg cursor-pointer hover:opacity-80 transition-opacity"
                style={{ border: '1px solid rgba(255,255,255,0.2)' }}
                onClick={() => window.open(img.url, '_blank')}
              />
            ))}
          </div>
        )}
        {content && (
          <div
            className="rounded-2xl px-4 py-2 text-sm text-white"
            style={{ background: 'var(--color-primary)', borderBottomRightRadius: '4px' }}
          >
            {content}
          </div>
        )}
      </div>
    </div>
  );
}

function StreamingBubble({ content }: { content: string }) {
  return (
    <div className="flex gap-3 justify-start">
      <AssistantAvatar />
      <div className="max-w-[85%]">
        <AgentResponse content={content} isStreaming={true} />
      </div>
    </div>
  );
}

function EmptyState({ chips, onChipClick }: { chips: string[]; onChipClick: (c: string) => void }) {
  return (
    <div className="flex flex-col items-center justify-center pt-16 gap-3 text-center">
      <span className="material-symbols-outlined text-4xl" style={{ color: 'var(--color-primary)' }}>
        hub
      </span>
      <p className="text-base font-semibold" style={{ color: 'var(--color-text-main)' }}>
        AI Plan
      </p>
      <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
        Describe your project and I&apos;ll create a structured plan with epics and acceptance criteria.
      </p>
      <div className="grid grid-cols-2 gap-2 mt-2">
        {chips.map((chip) => (
          <button
            key={chip}
            onClick={() => onChipClick(chip)}
            className="text-xs px-3 py-1.5 rounded-full border transition-colors"
            style={{
              borderColor: 'var(--color-border)',
              background: 'var(--color-surface)',
              color: 'var(--color-text-muted)',
            }}
          >
            {chip}
          </button>
        ))}
      </div>
    </div>
  );
}

function Composer({
  input,
  setInput,
  onSend,
  onCancel,
  isBusy,
  inputRef,
  placeholder,
  enableImages = false,
  pendingImages,
  onImagesChange,
}: {
  input: string;
  setInput: (v: string) => void;
  onSend: () => void;
  onCancel: () => void;
  isBusy: boolean;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  placeholder?: string;
  enableImages?: boolean;
  pendingImages?: ProcessedImage[];
  onImagesChange?: (imgs: ProcessedImage[]) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const images = pendingImages ?? [];

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  const addImages = async (files: FileList | File[]) => {
    if (!onImagesChange) return;
    const remaining = MAX_IMAGES - images.length;
    if (remaining <= 0) { setImageError(`Maximum ${MAX_IMAGES} images.`); return; }
    const { images: processed, errors } = await processImages(Array.from(files).slice(0, remaining));
    if (errors.length > 0) setImageError(errors.join(' '));
    else setImageError(null);
    if (processed.length > 0) onImagesChange([...images, ...processed]);
  };

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    if (!enableImages) return;
    const items = e.clipboardData?.items;
    if (!items) return;
    const imageFiles: File[] = [];
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith('image/')) {
        const file = items[i].getAsFile();
        if (file) imageFiles.push(file);
      }
    }
    if (imageFiles.length > 0) { e.preventDefault(); addImages(imageFiles); }
  };

  return (
    <div
      className="p-4 border-t shrink-0"
      style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)' }}
    >
      <div className="max-w-5xl mx-auto">
        {/* Image previews */}
        {enableImages && images.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-2">
            {images.map((img, i) => (
              <div key={i} className="relative group">
                <img src={img.url} alt={img.name} className="w-14 h-14 object-cover rounded-lg" style={{ border: '1px solid var(--color-border)' }} />
                <button
                  onClick={() => { onImagesChange?.(images.filter((_, idx) => idx !== i)); setImageError(null); }}
                  className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full flex items-center justify-center text-white text-xs opacity-0 group-hover:opacity-100 transition-opacity"
                  style={{ background: 'var(--color-danger, #ef4444)' }}
                >
                  <span className="material-symbols-outlined" style={{ fontSize: 14 }}>close</span>
                </button>
              </div>
            ))}
          </div>
        )}
        {enableImages && imageError && (
          <div className="text-xs mb-1" style={{ color: 'var(--color-danger, #ef4444)' }}>{imageError}</div>
        )}

        <div className="relative">
          {enableImages && (
            <input ref={fileInputRef} type="file" accept="image/jpeg,image/png,image/gif,image/webp" multiple className="hidden"
              onChange={(e) => { if (e.target.files?.length) { addImages(e.target.files); e.target.value = ''; } }} />
          )}

          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            disabled={isBusy}
            placeholder={placeholder ?? 'Describe your plan or ask for refinement...'}
            className={`w-full resize-none rounded-lg py-3 pr-12 text-sm focus:outline-none ${enableImages ? 'pl-11' : 'px-4'}`}
            style={{
              background: 'var(--color-background)',
              color: 'var(--color-text-main)',
              border: '1px solid var(--color-border)',
              minHeight: '52px',
              maxHeight: '200px',
            }}
            rows={Math.min(5, input.split('\n').length || 1)}
          />

          {enableImages && (
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={isBusy || images.length >= MAX_IMAGES}
              className="absolute left-2 bottom-2 p-1.5 rounded-md transition-colors disabled:opacity-30"
              style={{ color: 'var(--color-text-muted)' }}
              title="Attach images"
            >
              <span className="material-symbols-outlined text-lg">add_photo_alternate</span>
            </button>
          )}

          <div className="absolute right-2 bottom-2">
            {isBusy ? (
              <Button
                variant="secondary"
                size="icon"
                onClick={onCancel}
                className="h-8 w-8 text-red-500 hover:text-red-600 hover:bg-red-50"
              >
                <span className="material-symbols-outlined text-sm">stop_circle</span>
              </Button>
            ) : (
              <Button
                variant="primary"
                size="icon"
                onClick={onSend}
                disabled={!input.trim() && images.length === 0}
                className="h-8 w-8"
              >
                <span
                  className="material-symbols-outlined text-sm"
                  style={{ transform: 'rotate(-45deg)', marginLeft: '2px', marginBottom: '2px' }}
                >
                  send
                </span>
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Thread-based chat (idea → plan) ─────────────────────────────────

function ThreadChat({ threadId }: { threadId: string }) {
  const { thread, messages, streamedResponse, isStreaming, isLoading, sendMessage, cancel } =
    usePlanningThread(threadId);

  const [input, setInput] = useState('');
  const [pendingImages, setPendingImages] = useState<ProcessedImage[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamedResponse]);

  const handleSend = () => {
    const hasText = input.trim().length > 0;
    const hasImages = pendingImages.length > 0;
    if ((!hasText && !hasImages) || isStreaming) return;

    const images: ImageAttachment[] | undefined = hasImages
      ? pendingImages.map(img => ({ url: img.url, name: img.name, type: img.type }))
      : undefined;

    sendMessage(input.trim(), images);
    setInput('');
    setPendingImages([]);
  };

  const handleChipClick = (prompt: string) => {
    setInput(prompt);
    inputRef.current?.focus();
  };

  const showEmpty = messages.length === 0 && !isStreaming;

  return (
    <div className="flex flex-col h-full" style={{ background: 'var(--color-background)' }}>
      {/* Header */}
      <div
        className="flex items-center justify-between px-5 py-3 border-b shrink-0"
        style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)' }}
      >
        <div className="flex items-center gap-3">
          <AssistantAvatar />
          <div>
            <p className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>
              AI Plan
            </p>
            {thread?.title && (
              <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                {thread.title}
              </p>
            )}
          </div>
        </div>
        <span
          className="text-xs px-2 py-0.5 rounded-full"
          style={{ background: 'rgba(139, 92, 246, 0.1)', color: 'var(--color-purple, #8b5cf6)' }}
        >
          From idea
        </span>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
        {isLoading && messages.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2" style={{ borderColor: 'var(--color-primary)' }} />
          </div>
        ) : (
          <div className="max-w-5xl mx-auto space-y-6 pb-4 px-4">
            {showEmpty && <EmptyState chips={IDEA_PROMPTS} onChipClick={handleChipClick} />}

            {messages.map((msg, idx) => {
              const isAssistant = msg.role === 'assistant';
              const prevMsg = idx > 0 ? messages[idx - 1] : null;
              const isGrouped = prevMsg?.role === msg.role;

              if (!isAssistant) return <UserBubble key={msg.id} content={msg.content} images={msg.images} />;

              return (
                <div key={msg.id} className="flex gap-3 justify-start">
                  {!isGrouped ? <AssistantAvatar /> : <div className="w-8 shrink-0" />}
                  <div className="max-w-[85%]">
                    <AgentResponse content={msg.content} />
                  </div>
                </div>
              );
            })}

            {isStreaming && <StreamingBubble content={streamedResponse} />}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      <Composer
        input={input}
        setInput={setInput}
        onSend={handleSend}
        onCancel={cancel}
        isBusy={isStreaming}
        inputRef={inputRef}
        placeholder="Continue the conversation… (Shift+Enter for newline)"
        enableImages
        pendingImages={pendingImages}
        onImagesChange={setPendingImages}
      />
    </div>
  );
}

// ── Plan-refine chat (no thread linked) ─────────────────────────────

function RefineChat() {
  const { planContent, planId, setPlanContent, setActiveTab } = usePlanContext();

  const { chatHistory, isRefining, streamedResponse, error, refine, cancelRefine, clearHistory } =
    usePlanRefine();

  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory.length, streamedResponse]);

  const handleSend = () => {
    const msg = input.trim();
    if (!msg || isRefining) return;
    setInput('');
    refine(msg, planContent, planId);
  };

  const handleChipClick = (prompt: string) => {
    setInput('');
    refine(prompt, planContent, planId);
  };

  const showEmpty = chatHistory.length === 0 && !isRefining;

  const handleApply = (content: string) => {
    setPlanContent(extractPlan(content));
    setActiveTab('editor');
  };

  return (
    <div className="flex flex-col h-full" style={{ background: 'var(--color-background)' }}>
      {/* Header */}
      <div
        className="flex items-center justify-between px-5 py-3 border-b shrink-0"
        style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)' }}
      >
        <div className="flex items-center gap-3">
          <AssistantAvatar />
          <p className="text-sm font-semibold" style={{ color: 'var(--color-text-main)' }}>
            AI Plan
          </p>
        </div>
        {chatHistory.length > 0 && (
          <button
            onClick={clearHistory}
            className="text-xs px-2 py-1 rounded-md transition-colors"
            style={{ color: 'var(--color-text-faint)' }}
            title="Clear chat"
          >
            <span className="material-symbols-outlined text-[16px]">delete_sweep</span>
          </button>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
        <div className="max-w-5xl mx-auto space-y-6 pb-4 px-4">
          {showEmpty && <EmptyState chips={REFINE_PROMPTS} onChipClick={handleChipClick} />}

          {chatHistory.map((msg, i) => {
            if (msg.role === 'user') return <UserBubble key={i} content={msg.content} />;

            const prevMsg = i > 0 ? chatHistory[i - 1] : null;
            const isGrouped = prevMsg?.role === msg.role;

            return (
              <div key={i}>
                <div className="flex gap-3 justify-start">
                  {!isGrouped ? <AssistantAvatar /> : <div className="w-8 shrink-0" />}
                  <div className="max-w-[85%]">
                    <AgentResponse content={msg.content} />
                  </div>
                </div>
                <div className="ml-11 mt-1">
                  <button
                    className="text-xs font-medium flex items-center gap-1 transition-colors"
                    style={{ color: 'var(--color-primary)' }}
                    onClick={() => handleApply(msg.content)}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: 14 }}>edit_note</span>
                    Apply to Editor
                  </button>
                </div>
              </div>
            );
          })}

          {isRefining && <StreamingBubble content={streamedResponse} />}

          {error && (
            <div
              className="rounded-lg px-3 py-2 text-xs flex items-center gap-2"
              style={{ background: 'var(--color-danger-light)', color: 'var(--color-danger-text)' }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: 16 }}>warning</span>
              {error}
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      <Composer
        input={input}
        setInput={setInput}
        onSend={handleSend}
        onCancel={cancelRefine}
        isBusy={isRefining}
        inputRef={inputRef}
      />
    </div>
  );
}

// ── Main export ─────────────────────────────────────────────────────

export default function ArchitectTab() {
  // Always use RefineChat once a plan exists. Plans promoted from
  // brainstorm threads used to render ThreadChat here, but that agent
  // tells users to click a non-existent "Create Plan" button.
  // RefineChat gives the correct "Apply to Editor" behaviour.
  return <RefineChat />;
}
