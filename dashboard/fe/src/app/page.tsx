'use client';

import { useState, useRef, useCallback } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { usePlans } from '@/hooks/use-plans';
import PlanCard from '@/components/dashboard/PlanCard';
import { CommandPrompt, type AttachedTemplate } from '@/components/ui/CommandPrompt';
import { Skeleton } from '@/components/ui/Skeleton';
import { BrandIcon } from '@/components/ui/BrandIcon';
import { ActivityFeed } from '@/components/chat/ActivityFeed';
import { TemplatePicker } from '@/components/dashboard/TemplatePicker';
import { templateCatalog, loadTemplateContent, type TemplateCatalogEntry } from '@/data/template-catalog';
import type { ImageAttachment } from '@/types';


export default function DashboardHomePage() {
  const router = useRouter();
  const { plans, isLoading: plansLoading, deletePlan } = usePlans();

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
        ? `@${templateName}\n\n${userBrief}\n\n---\n\n<template>\n${templateContent}\n</template>`
        : `@${templateName}\n\n---\n\n<template>\n${templateContent}\n</template>`;
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

      const resp = await fetch((process.env.NEXT_PUBLIC_API_BASE_URL || '/api') + '/plans/threads', {
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
    <div className="min-h-[calc(100vh-theme(spacing.16))] flex flex-col items-center animate-in fade-in slide-in-from-bottom-4 duration-700 w-full relative pt-8 px-6 pb-24">
      {/* Top Center Workspace Badge */}
      <div className="flex items-center gap-2 px-4 py-2 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-[var(--radius-full)] shadow-[var(--shadow-card)] mb-12">
        <BrandIcon size={24} />
        <span className="text-sm font-medium text-[var(--color-text-main)]">
          Ostwin Pro
        </span>
        <span className="material-symbols-outlined text-[var(--color-text-muted)] text-sm">expand_more</span>
      </div>

      <div className="w-full max-w-4xl flex flex-col items-center">
        {/* Greeting */}
        <div className="flex flex-col items-center text-center mb-6">
          <BrandIcon size={48} className="mb-4 text-primary" />
          <h1 className="text-[38px] md:text-[46px] lg:text-[54px] leading-tight font-[var(--font-display)] font-bold text-[var(--color-text-main)] tracking-tight">
            What do you want to build?
          </h1>
        </div>

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

        {/* Template Picker */}
        {templateCatalog.length > 0 && (
          <TemplatePicker
            categories={templateCatalog}
            onSelectTemplate={handleSelectTemplate}
            loadingTemplateId={loadingTemplateId}
          />
        )}

        {/* Recent Projects & Activity */}
        <div className="w-full max-w-5xl">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-lg font-bold text-[var(--color-text-main)]">Your recent Plans</h2>
                <Link href="/plans" className="text-sm font-medium text-primary hover:text-[var(--color-primary-hover)] flex items-center gap-1 transition-colors">
                  View All <span className="material-symbols-outlined text-sm">arrow_forward</span>
                </Link>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {plansLoading ? (
                  Array.from({ length: 2 }).map((_, i) => (
                    <div key={i} className="h-[200px]">
                      <Skeleton className="w-full h-full rounded-[var(--radius-xl)]" />
                    </div>
                  ))
                ) : plans && plans.length > 0 ? (
                  plans.slice(0, 2).map(plan => (
                    <PlanCard key={plan.plan_id} plan={plan} onDelete={deletePlan} />
                  ))
                ) : (
                  <div className="col-span-full py-8 text-center bg-[var(--color-surface)] rounded-[var(--radius-xl)] border border-dashed border-[var(--color-border)]">
                    <p className="text-[var(--color-text-muted)]">No recent plans found. Start a new one above!</p>
                  </div>
                )}
              </div>
            </div>

            <div className="h-[400px]">
              <ActivityFeed />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
