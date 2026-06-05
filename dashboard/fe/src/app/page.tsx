'use client';

import { useState, useRef, useCallback } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { CommandPrompt, type AttachedTemplate } from '@/components/ui/CommandPrompt';
import { BrandIcon } from '@/components/ui/BrandIcon';
import { ActivityFeed } from '@/components/chat/ActivityFeed';
import PlanGrid from '@/components/dashboard/PlanGrid';
import StatsRow from '@/components/dashboard/StatsRow';
import { TemplatePicker } from '@/components/dashboard/TemplatePicker';
import { templateCatalog, loadTemplateContent, type TemplateCatalogEntry } from '@/data/template-catalog';
import { getApiBaseUrl } from '@/lib/runtime-config';
import type { ImageAttachment } from '@/types';

const commandExamples = [
  'Launch a compliance audit plan',
  'Map a customer onboarding workflow',
  'Draft an ecommerce logistics rollout',
];

export default function DashboardHomePage() {
  const router = useRouter();

  const [prompt, setPrompt] = useState('');
  const [isCreatingThread, setIsCreatingThread] = useState(false);
  const [loadingTemplateId, setLoadingTemplateId] = useState<string | null>(null);
  const commandPromptRef = useRef<HTMLTextAreaElement>(null);

  // Template state: stored as metadata, never injected as raw text
  const [attachedTemplate, setAttachedTemplate] = useState<AttachedTemplate | null>(null);
  const templateContentRef = useRef<string | null>(null);

  const handleSubmitPrompt = async (userPrompt: string, images?: ImageAttachment[]) => {
    const templateName = attachedTemplate?.name || null;
    const templateContent = templateContentRef.current;

    // Compose the message sent to the agent:
    // - If template attached: structured format with template context + user brief
    // - If no template: just the user's raw prompt
    let message: string;
    if (templateName && templateContent) {
      const userBrief = userPrompt.trim();
      message = userBrief
        ? `@${templateName}

${userBrief}

---

<template>
${templateContent}
</template>`
        : `@${templateName}

---

<template>
${templateContent}
</template>`;
    } else {
      message = userPrompt;
    }

    if (!message.trim()) return;

    // Title = template name + user context (or just user prompt)
    const title = templateName
      ? userPrompt.trim()
        ? `${templateName} - ${userPrompt.trim().substring(0, 80)}`
        : templateName
      : undefined;

    try {
      setIsCreatingThread(true);
      const body: Record<string, unknown> = { message };
      if (images && images.length > 0) {
        body.images = images.map(img => ({ url: img.url, name: img.name, type: img.type }));
      }
      if (templateName) {
        body.template_name = templateName;
      }
      if (title) {
        body.title = title;
      }

      const resp = await fetch(`${getApiBaseUrl()}/plans/threads`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      });

      if (!resp.ok) throw new Error('Failed to create thread');

      const data = await resp.json();
      setAttachedTemplate(null);
      templateContentRef.current = null;
      router.push(`/ideas/${data.thread_id}`);
    } catch (err) {
      console.error(err);
      alert('Failed to create thread. Please try again.');
    } finally {
      setIsCreatingThread(false);
    }
  };

  // When user clicks a template: load content async, store as metadata (NOT in textarea)
  const handleSelectTemplate = useCallback(async (entry: TemplateCatalogEntry) => {
    setLoadingTemplateId(entry.id);
    try {
      const content = await loadTemplateContent(entry.id);
      if (content) {
        // Store template reference + content separately
        setAttachedTemplate({ id: entry.id, name: entry.name });
        templateContentRef.current = content.promptTemplate;
        // Focus textarea so user can type their additional context
        setTimeout(() => commandPromptRef.current?.focus(), 0);
      }
    } finally {
      setLoadingTemplateId(null);
    }
  }, []);

  const handleRemoveTemplate = useCallback(() => {
    setAttachedTemplate(null);
    templateContentRef.current = null;
  }, []);

  return (
    <div className="min-h-[calc(100vh-theme(spacing.16))] w-full overflow-y-auto custom-scrollbar bg-background">
      <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-10 px-4 pb-24 pt-8 sm:px-6 lg:px-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
        <section className="relative overflow-hidden rounded-[28px] border border-border bg-surface px-5 py-8 shadow-card sm:px-8 lg:px-10">
          <div className="pointer-events-none absolute inset-0 opacity-70">
            <div className="absolute -right-16 -top-24 h-72 w-72 rounded-full bg-primary/10 blur-3xl" />
            <div className="absolute -bottom-28 left-8 h-80 w-80 rounded-full bg-purple/10 blur-3xl" />
            <div className="absolute inset-0 dot-grid-bg opacity-40" />
          </div>

          <div className="relative grid gap-8 xl:grid-cols-[minmax(0,1fr)_360px] xl:items-start">
            <div className="flex min-w-0 flex-col items-center text-center xl:items-start xl:text-left">
              <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-border bg-background/80 px-4 py-2 shadow-card backdrop-blur">
                <BrandIcon size={24} />
                <span className="text-sm font-semibold text-text-main">Ostwin Pro</span>
                <span className="rounded-full bg-success-light px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.18em] text-success-text">
                  Live dashboard
                </span>
              </div>

              <div className="mb-7 max-w-4xl">
                <p className="mb-3 text-xs font-bold uppercase tracking-[0.28em] text-primary">
                  Agentic command center
                </p>
                <h1 className="font-[var(--font-display)] text-[42px] font-black leading-[0.96] tracking-[-0.055em] text-text-main sm:text-[56px] lg:text-[72px]">
                  Build, monitor, and steer every plan from one landing page.
                </h1>
                <p className="mx-auto mt-5 max-w-2xl text-base leading-7 text-text-muted xl:mx-0">
                  Start a new workspace from a prompt, review live operating metrics, and use the filterable plan grid powered by SWR-backed mock APIs.
                </p>
              </div>

              <div className="w-full max-w-4xl">
                <CommandPrompt
                  ref={commandPromptRef}
                  value={prompt}
                  onChange={setPrompt}
                  onSubmit={handleSubmitPrompt}
                  isConversationActive={false}
                  isLoading={isCreatingThread}
                  attachedTemplate={attachedTemplate}
                  onRemoveTemplate={handleRemoveTemplate}
                />

                <div className="mt-4 flex flex-wrap justify-center gap-2 xl:justify-start">
                  {commandExamples.map(example => (
                    <button
                      key={example}
                      type="button"
                      onClick={() => {
                        setPrompt(example);
                        commandPromptRef.current?.focus();
                      }}
                      className="rounded-full border border-border bg-background/80 px-3 py-1.5 text-xs font-semibold text-text-muted transition-all hover:-translate-y-0.5 hover:border-primary hover:text-primary hover:shadow-card"
                    >
                      {example}
                    </button>
                  ))}
                </div>

                {templateCatalog.length > 0 && (
                  <TemplatePicker
                    categories={templateCatalog}
                    onSelectTemplate={handleSelectTemplate}
                    loadingTemplateId={loadingTemplateId}
                  />
                )}
              </div>
            </div>

            <aside className="min-h-[420px] rounded-2xl border border-border bg-background/80 p-3 shadow-card backdrop-blur">
              <div className="mb-3 flex items-center justify-between px-2 pt-1">
                <div>
                  <p className="text-xs font-bold uppercase tracking-[0.2em] text-text-faint">Activity</p>
                  <h2 className="text-sm font-bold text-text-main">Recent orchestration</h2>
                </div>
                <span className="flex h-2.5 w-2.5 rounded-full bg-success animate-pulse" />
              </div>
              <div className="h-[360px]">
                <ActivityFeed />
              </div>
            </aside>
          </div>
        </section>

        <section aria-labelledby="dashboard-metrics-heading" className="space-y-4">
          <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.24em] text-primary">Mock API telemetry</p>
              <h2 id="dashboard-metrics-heading" className="mt-1 text-2xl font-extrabold tracking-tight text-text-main">
                Animated operating metrics
              </h2>
            </div>
            <Link href="/plans" className="inline-flex items-center gap-1 text-sm font-bold text-primary transition-colors hover:text-[var(--color-primary-hover)]">
              View all plans <span className="material-symbols-outlined text-sm">arrow_forward</span>
            </Link>
          </div>
          <StatsRow />
        </section>

        <section aria-labelledby="plan-grid-heading" className="rounded-[24px] border border-border bg-surface p-4 shadow-card sm:p-6">
          <div className="mb-2 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.24em] text-primary">Plan operations</p>
              <h2 id="plan-grid-heading" className="mt-1 text-2xl font-extrabold tracking-tight text-text-main">
                Filterable plan grid
              </h2>
              <p className="mt-1 text-sm text-text-muted">
                Search, sort, filter by domain or status, and jump directly into any active workspace.
              </p>
            </div>
          </div>
          <PlanGrid />
        </section>
      </div>
    </div>
  );
}
