'use client';

import { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { useSettings } from '@/hooks/use-settings';
import { useConfiguredModels } from '@/hooks/use-configured-models';
import { LiveStatusBadge } from '@/components/settings/LiveStatusBadge';
import { SettingsSidebar } from '@/components/settings/SettingsSidebar';
import { ProviderCard } from '@/components/settings/ProviderCard';
import { BytedanceProviderCard } from '@/components/settings/BytedanceProviderCard';
import { OpenAICodexPanel } from '@/components/settings/OpenAICodexPanel';
import { DynamicProviderCard } from '@/components/settings/DynamicProviderCard';
import { AddProviderModal } from '@/components/settings/AddProviderModal';
import { VaultSecretModal } from '@/components/settings/VaultSecretModal';
import { RuntimePanel } from '@/components/settings/RuntimePanel';
import { MemoryPanel } from '@/components/settings/MemoryPanel';
import { KnowledgePanel } from '@/components/settings/KnowledgePanel';
import { ChannelsPanel } from '@/components/settings/ChannelsPanel';
import { AgentCostsPanel } from '@/components/settings/AgentCostsPanel';
import type { SettingsNamespace, ProviderSettings, ModelInfo, RuntimeSettings } from '@/types/settings';
import { apiGet, apiPost, apiDelete, apiPut } from '@/lib/api-client';

// Providers that have dedicated cards at the top of the settings page.
// These are hidden from the Additional Providers section to avoid duplicates.
const LEGACY_PRIMARY_PROVIDERS = new Set([
  'google',
  'openai',
  'anthropic',
  'byteplus',
]);

// Map internal provider names to registry keys (for legacy fallback)
const PROVIDER_REGISTRY_KEY: Record<string, string> = {
  google:    'Gemini',
  anthropic: 'Claude',
  openai:    'GPT',
  byteplus:  'BytePlus',
};

type SettingsMetricTone = 'blue' | 'green' | 'amber' | 'rose';

const SETTINGS_NAMESPACE_META: Record<SettingsNamespace, { eyebrow: string; title: string; description: string; icon: string }> = {
  providers: {
    eyebrow: 'model provisioning',
    title: 'Global Model Provisioning',
    description: 'Configure model endpoints, credentials, and provider availability for every agent surface.',
    icon: 'memory',
  },
  runtime: {
    eyebrow: 'runtime',
    title: 'Runtime Configuration',
    description: 'Tune manager cadence, room limits, retry budgets, and defaults used when new war-rooms launch.',
    icon: 'settings',
  },
  memory: {
    eyebrow: 'memory',
    title: 'Memory Configuration',
    description: 'Shape retrieval, embedding, and pool behavior for long-lived agent memory.',
    icon: 'storage',
  },
  knowledge: {
    eyebrow: 'knowledge',
    title: 'Knowledge Configuration',
    description: 'Set the models and embedding defaults used by knowledge ingestion and graph work.',
    icon: 'school',
  },
  channels: {
    eyebrow: 'channels',
    title: 'Channel Configuration',
    description: 'Connect notification and communication surfaces for plan and war-room events.',
    icon: 'hub',
  },
  'ai-monitor': {
    eyebrow: 'ai monitor',
    title: 'AI Cost Monitor',
    description: 'Inspect model usage and runtime spend across agent work.',
    icon: 'monitoring',
  },
};

const settingsMetricTones: Record<SettingsMetricTone, { background: string; color: string }> = {
  blue: {
    background: 'oklch(0.94 0.035 250)',
    color: 'oklch(0.38 0.16 252)',
  },
  green: {
    background: 'oklch(0.94 0.045 158)',
    color: 'oklch(0.42 0.13 158)',
  },
  amber: {
    background: 'oklch(0.95 0.052 82)',
    color: 'oklch(0.47 0.12 70)',
  },
  rose: {
    background: 'oklch(0.94 0.035 18)',
    color: 'oklch(0.44 0.14 18)',
  },
};

function formatRuntimeSeconds(value?: number) {
  const seconds = value ?? 0;
  if (seconds >= 3600 && seconds % 3600 === 0) return `${seconds / 3600}h`;
  if (seconds >= 60 && seconds % 60 === 0) return `${seconds / 60}m`;
  return `${seconds}s`;
}

function SettingsMetricCard({
  icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: string;
  label: string;
  value: string;
  detail: string;
  tone: SettingsMetricTone;
}) {
  const colors = settingsMetricTones[tone];

  return (
    <article className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-[0_12px_36px_rgba(15,23,42,0.07)] transition duration-300 hover:-translate-y-1 hover:shadow-[0_18px_48px_rgba(15,23,42,0.1)]">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase text-[var(--color-text-muted)]">{label}</p>
          <p className="mt-3 text-3xl font-black text-[var(--color-text-main)]">{value}</p>
        </div>
        <span className="material-symbols-outlined rounded-full p-2 text-[18px]" style={{ background: colors.background, color: colors.color }}>
          {icon}
        </span>
      </div>
      <p className="mt-5 max-w-[32ch] text-sm leading-6 text-[var(--color-text-muted)]">{detail}</p>
    </article>
  );
}

export default function SettingsPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-center text-on-surface-variant">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mb-4 mx-auto" />
          <p className="text-sm font-body">Loading settings...</p>
        </div>
      </div>
    }>
      <SettingsPageContent />
    </Suspense>
  );
}

function SettingsPageContent() {
  const searchParams = useSearchParams();
  const [activeNamespace, setActiveNamespace] = useState<SettingsNamespace>('providers');
  const [vaultModalOpen, setVaultModalOpen] = useState(false);
  const [addProviderOpen, setAddProviderOpen] = useState(false);
  const [vaultScope, setVaultScope] = useState('');
  const [vaultKey, setVaultKey] = useState('');
  const [vaultStatus, setVaultStatus] = useState<Record<string, boolean>>({});
  const [modelRegistry, setModelRegistry] = useState<Record<string, ModelInfo[]>>({});
  const [isReloading, setIsReloading] = useState(false);

  const { settings, isLoading, isError, updateNamespace, updateVault } = useSettings();
  const { configured, providers: configuredProviders, allModels, reload: reloadModels } = useConfiguredModels();

  // Sync ?tab= query param to activeNamespace
  useEffect(() => {
    const tab = searchParams.get('tab');
    const validTabs: SettingsNamespace[] = ['providers', 'runtime', 'memory', 'knowledge', 'channels', 'ai-monitor'];
    if (tab && validTabs.includes(tab as SettingsNamespace)) {
      setActiveNamespace(tab as SettingsNamespace);
    }
  }, [searchParams]);

  // Fetch model registry (backward compat + dynamic)
  useEffect(() => {
    const fetchRegistry = async () => {
      try {
        const data = await apiGet<Record<string, ModelInfo[]>>('/models/registry');
        setModelRegistry(data ?? {});
      } catch {
        setModelRegistry({});
      }
    };
    fetchRegistry();
  }, []);

  useEffect(() => {
    const fetchVaultStatus = async () => {
      try {
        const raw = await apiGet<{ keys?: Record<string, { is_set: boolean }> } & Record<string, { is_set: boolean }>>('/settings/vault/providers');
        const entries = raw.keys ?? raw;
        const status: Record<string, boolean> = {};
        Object.entries(entries).forEach(([key, value]) => {
          if (value && typeof value === 'object' && 'is_set' in value) {
            status[key] = value.is_set;
          }
        });
        setVaultStatus(status);
      } catch {
        setVaultStatus({});
      }
    };
    fetchVaultStatus();
  }, [settings]);

  const handleVaultClick = (provider: string) => {
    setVaultScope('providers');
    setVaultKey(provider);
    setVaultModalOpen(true);
  };

  const handleVaultSubmit = async (secret: string) => {
    await updateVault(vaultScope, vaultKey, secret);
    if (vaultScope === 'providers' && vaultKey === 'openai') {
      await updateProvider('openai', openaiSettings, { enabled: true, auth_mode: 'api_key' });
    }
    const raw = await apiGet<{ keys?: Record<string, { is_set: boolean }> } & Record<string, { is_set: boolean }>>('/settings/vault/providers');
    const entries = raw.keys ?? raw;
    const status: Record<string, boolean> = {};
    Object.entries(entries).forEach(([key, value]) => {
      if (value && typeof value === 'object' && 'is_set' in value) {
        status[key] = value.is_set;
      }
    });
    setVaultStatus(status);
    // Reload models after a key change (provider may now be active)
    reloadModels();
  };

  const handleRemoveProvider = async (providerId: string) => {
    try {
      const isSet = vaultStatus[providerId];

      if (isSet) {
        // First click: remove key
        await apiDelete(`/settings/vault/providers/${providerId}`);
        await apiPost('/models/reload');

        // Refresh vault status
        const raw = await apiGet<{ keys?: Record<string, { is_set: boolean }> } & Record<string, { is_set: boolean }>>('/settings/vault/providers');
        const entries = raw.keys ?? raw;
        const status: Record<string, boolean> = {};
        Object.entries(entries).forEach(([key, value]) => {
          if (value && typeof value === 'object' && 'is_set' in value) {
            status[key] = value.is_set;
          }
        });
        setVaultStatus(status);
        reloadModels();
      } else {
        // Second click (or no key existed): dismiss from UI
        const provSettings = (providers as Record<string, ProviderSettings>)[providerId] || { enabled: false };
        updateProvider(providerId, provSettings, { dismissed: true });

        await apiDelete(`/settings/vault/providers/${providerId}`).catch(() => {});
        await apiPost('/models/reload');
        reloadModels();
      }
    } catch { /* ignore */ }
  };

  const handleProviderAdded = async (providerId: string) => {
    // If the provider was previously dismissed, un-dismiss it
    const provSettings = (providers as Record<string, ProviderSettings>)[providerId];
    if (provSettings?.dismissed) {
      updateProvider(providerId, provSettings, { dismissed: false });
    }

    // Refresh vault status + model catalog
    try {
      const raw = await apiGet<{ keys?: Record<string, { is_set: boolean }> } & Record<string, { is_set: boolean }>>('/settings/vault/providers');
      const entries = raw.keys ?? raw;
      const status: Record<string, boolean> = {};
      Object.entries(entries).forEach(([key, value]) => {
        if (value && typeof value === 'object' && 'is_set' in value) {
          status[key] = value.is_set;
        }
      });
      setVaultStatus(status);
    } catch { /* ignore */ }
    reloadModels();
    // Re-fetch registry
    try {
      const data = await apiGet<Record<string, ModelInfo[]>>('/models/registry');
      setModelRegistry(data ?? {});
    } catch { /* ignore */ }
  };

  // Get model registry entries for a provider
  const getRegistryForProvider = (providerName: string): ModelInfo[] => {
    const key = PROVIDER_REGISTRY_KEY[providerName];
    return key ? (modelRegistry[key] || []) : [];
  };



  // Flat model IDs for backward-compat consumers (RolesPanel)
  const providers = settings?.providers || {};
  const defaultProvider = { enabled: true } as ProviderSettings;
  const googleSettings   = (providers as Record<string, ProviderSettings>).google    ?? defaultProvider;
  const anthropicSettings = (providers as Record<string, ProviderSettings>).anthropic ?? defaultProvider;
  const openaiSettings   = (providers as Record<string, ProviderSettings>).openai    ?? defaultProvider;
  const byteplusSettings = (providers as Record<string, ProviderSettings>).byteplus  ?? defaultProvider;

  const allModelIds = allModels.length > 0
    ? allModels.map((m) => m.id)
    : Object.values(modelRegistry).flat().map((m) => m.id);

  // Dynamic providers: those configured in auth.json but NOT legacy primary, and NOT dismissed
  const dynamicProviderIds = Object.keys(configuredProviders).filter(
    (pid) => !LEGACY_PRIMARY_PROVIDERS.has(pid) && !(providers as Record<string, ProviderSettings>)[pid]?.dismissed,
  );

  const runtime: RuntimeSettings = {
    poll_interval_seconds: 5,
    max_concurrent_rooms: 10,
    max_engineer_retries: 3,
    state_timeout_seconds: 900,
    auto_approve_tools: false,
    dynamic_pipelines: true,
    master_agent_model: '',
    ...(settings?.runtime ?? {}),
  };
  const enabledProviderCount = (Object.values(providers) as Array<ProviderSettings | null | undefined>)
    .filter((provider) => provider?.enabled && !provider.dismissed).length;
  const activeMeta = SETTINGS_NAMESPACE_META[activeNamespace];
  const settingsMetrics = [
    {
      id: 'providers',
      icon: 'api',
      label: 'Enabled providers',
      value: String(enabledProviderCount),
      detail: `${Object.keys(configuredProviders).length} providers discovered, ${allModels.length} models available.`,
      tone: 'blue' as const,
    },
    {
      id: 'timeout',
      icon: 'timer',
      label: 'State timeout',
      value: formatRuntimeSeconds(runtime.state_timeout_seconds),
      detail: 'Default timeout for each new war-room lifecycle state.',
      tone: 'rose' as const,
    },
    {
      id: 'retries',
      icon: 'restart_alt',
      label: 'Room retries',
      value: String(runtime.max_engineer_retries),
      detail: 'Retry budget copied into newly created war-room lifecycles.',
      tone: 'amber' as const,
    },
    {
      id: 'rooms',
      icon: 'meeting_room',
      label: 'Concurrent rooms',
      value: String(runtime.max_concurrent_rooms),
      detail: `Manager loop polls every ${formatRuntimeSeconds(runtime.poll_interval_seconds)}.`,
      tone: 'green' as const,
    },
  ];

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-center text-on-surface-variant">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mb-4 mx-auto" />
          <p className="text-sm font-body">Loading settings...</p>
        </div>
      </div>
    );
  }

  if (isError || !settings) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-center text-error">
          <span className="material-symbols-outlined text-4xl mb-2">error</span>
          <p className="font-medium">Failed to load settings.</p>
          <button
            onClick={() => window.location.reload()}
            className="mt-4 px-4 py-2 bg-error text-on-error rounded hover:bg-error/90 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const updateProvider = (name: string, current: ProviderSettings, updates: Partial<ProviderSettings>) =>
    updateNamespace('providers', { ...providers, [name]: { ...current, ...updates } });

  const handleServiceAccountUpload = async (jsonContent: string) => {
    await updateVault('providers', 'google_service_account', jsonContent);
    try {
      const raw = await apiGet<{ keys?: Record<string, { is_set: boolean }> } & Record<string, { is_set: boolean }>>('/settings/vault/providers');
      const entries = raw.keys ?? raw;
      const status: Record<string, boolean> = {};
      Object.entries(entries).forEach(([key, value]) => {
        if (value && typeof value === 'object' && 'is_set' in value) {
          status[key] = value.is_set;
        }
      });
      setVaultStatus(status);
    } catch { /* ignore */ }
  };

  const renderActivePanel = () => {
    switch (activeNamespace) {
      case 'providers':
        return (
          <div className="space-y-8">
            <section className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-[0_12px_36px_rgba(15,23,42,0.07)] md:p-6">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <p className="text-xs font-bold uppercase text-[var(--color-text-muted)]">Provider portfolio</p>
                  <h2 className="mt-2 text-xl font-black text-[var(--color-text-main)]">Provider Portfolio</h2>
                  <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--color-text-muted)]">
                    Configure and manage LLM endpoints and provider credentials.
                  </p>
                  {configured && (
                    <p className="mt-3 text-xs font-bold text-[var(--color-text-faint)]">
                      {Object.keys(configuredProviders).length} providers configured
                      {' / '}
                      {allModels.length} models available
                      {' / '}
                      Source: models.dev
                    </p>
                  )}
                </div>
              <button
                onClick={async () => {
                  setIsReloading(true);
                  try {
                    await reloadModels();
                  } finally {
                    setIsReloading(false);
                  }
                }}
                disabled={isReloading}
                className="inline-flex items-center justify-center gap-2 rounded-full border border-[var(--color-border)] bg-[var(--color-background)] px-4 py-2 text-xs font-bold uppercase text-[var(--color-text-main)] transition hover:-translate-y-0.5 disabled:opacity-50"
                title="Re-fetch models from models.dev"
              >
                <span className={`material-symbols-outlined text-sm ${isReloading ? 'animate-spin' : ''}`}>
                  {isReloading ? 'progress_activity' : 'refresh'}
                </span>
                {isReloading ? 'Reloading...' : 'Reload Models'}
              </button>
              </div>
            </section>

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
              {/* ── Row 1: Google (8) + Anthropic/OpenAI stack (4) ──── */}

              {/* Google Cloud Provisioning -- primary large card */}
              <div className="lg:col-span-8">
                <ProviderCard
                  name="google"
                  provider={googleSettings}
                  variant="primary"
                  onToggle={(enabled) => updateProvider('google', googleSettings, { enabled })}
                  onModelChange={(model) => updateProvider('google', googleSettings, { default_model: model })}
                  onSettingsChange={(updates) => updateProvider('google', googleSettings, updates)}
                  onVaultClick={() => handleVaultClick('google')}
                  onServiceAccountUpload={handleServiceAccountUpload}
                  vaultSet={vaultStatus['google'] || false}
                  serviceAccountVaultSet={vaultStatus['google_service_account'] || false}
                  modelRegistry={getRegistryForProvider('google')}
                  models={allModelIds}
                />
              </div>

              {/* Anthropic & OpenAI -- stacked compact cards */}
              <div className="lg:col-span-4 space-y-6">
                <ProviderCard
                  name="anthropic"
                  provider={anthropicSettings}
                  variant="compact"
                  onToggle={(enabled) => updateProvider('anthropic', anthropicSettings, { enabled })}
                  onModelChange={(model) => updateProvider('anthropic', anthropicSettings, { default_model: model })}
                  onVaultClick={() => handleVaultClick('anthropic')}
                  vaultSet={vaultStatus['anthropic'] || false}
                  modelRegistry={getRegistryForProvider('anthropic')}
                  models={allModelIds}
                />
                <OpenAICodexPanel
                  provider={openaiSettings}
                  onVaultClick={() => handleVaultClick('openai')}
                  vaultSet={vaultStatus['openai'] || false}
                  onSettingsChange={(updates) => updateProvider('openai', openaiSettings, updates)}
                />
              </div>

              {/* ── Row 2: Bytedance (Ark) -- full-width bento ──────── */}
              <BytedanceProviderCard
                provider={byteplusSettings}
                onSettingsChange={(updates) => updateProvider('byteplus', byteplusSettings, updates)}
                onVaultClick={() => handleVaultClick('byteplus')}
                vaultSet={vaultStatus['byteplus'] || false}
                modelRegistry={getRegistryForProvider('byteplus')}
              />
            </div>

            {/* ── Additional Providers ─────────────────────────────── */}
            <div className="mt-10">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-slate-400 text-lg">extension</span>
                  <h3 className="text-sm font-bold uppercase tracking-widest text-slate-700">
                    Additional Providers
                  </h3>
                  {dynamicProviderIds.length > 0 && (
                    <span className="text-[10px] text-slate-400">{dynamicProviderIds.length} configured</span>
                  )}
                </div>
                <button
                  onClick={() => setAddProviderOpen(true)}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-bold uppercase tracking-wide bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm"
                >
                  <span className="material-symbols-outlined text-sm">add</span>
                  Add Provider
                </button>
              </div>

              {dynamicProviderIds.length === 0 ? (
                <button
                  onClick={() => setAddProviderOpen(true)}
                  className="w-full py-10 border-2 border-dashed border-slate-200 rounded-xl text-center hover:border-blue-300 hover:bg-blue-50/30 transition-colors cursor-pointer group"
                >
                  <span className="material-symbols-outlined text-3xl text-slate-300 group-hover:text-blue-400 mb-2 block">add_circle</span>
                  <p className="text-xs font-semibold text-slate-500 group-hover:text-blue-600">
                    Add your first provider
                  </p>
                  <p className="text-[10px] text-slate-400 mt-1">
                    Browse 100+ providers from models.dev
                  </p>
                </button>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {dynamicProviderIds.map((pid) => {
                    const provider = configuredProviders[pid];
                    if (!provider) return null;
                    const provSettings = (providers as Record<string, ProviderSettings>)[pid] ?? defaultProvider;
                    return (
                      <DynamicProviderCard
                        key={pid}
                        providerId={pid}
                        provider={provider}
                        settings={provSettings}
                        vaultSet={vaultStatus[pid] || false}
                        onVaultClick={() => handleVaultClick(pid)}
                        onToggle={(enabled) => updateProvider(pid, provSettings, { enabled })}
                        onRemove={() => handleRemoveProvider(pid)}
                      />
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        );

      case 'runtime':
        return (
          <div>
            <RuntimePanel
              runtime={runtime}
              allModels={allModels}
              onUpdate={async (value) => {
                // If master_agent_model changed, also update the master agent singleton
                if (value.master_agent_model !== undefined) {
                  try {
                    await apiPut('/settings/master-model', {
                      model: value.master_agent_model,
                    });
                  } catch (e) {
                    console.error('Failed to update master model:', e);
                  }
                }
                updateNamespace('runtime', { ...runtime, ...value });
              }}
            />
          </div>
        );

      case 'memory':
        return (
          <MemoryPanel
            memory={settings.memory || {}}
            onUpdate={(value) => updateNamespace('memory', { ...settings.memory, ...value })}
            allModels={allModels}
          />
        );

      case 'knowledge': {
        const knowledgeDefaults = { knowledge_llm_backend: '', knowledge_llm_model: '', knowledge_embedding_backend: '' as const, knowledge_embedding_model: '', knowledge_embedding_dimension: 768 };
        const knowledgeCurrent = settings.knowledge ?? knowledgeDefaults;
        return (
          <KnowledgePanel
            knowledge={knowledgeCurrent}
            onUpdate={(value) =>
              updateNamespace('knowledge', { ...knowledgeCurrent, ...value })
            }
            allModels={allModels}
          />
        );
      }

      case 'channels':
        return <ChannelsPanel />;

      case 'ai-monitor':
        return <AgentCostsPanel />;

      default:
        return null;
    }
  };

  return (
    <div className="min-h-[calc(100dvh-56px)] overflow-auto bg-[var(--color-background)] px-5 py-6 font-body text-[var(--color-text-main)] md:px-8 lg:px-10">
      <section className="mx-auto flex w-full max-w-7xl flex-col gap-8">
        <header className="grid gap-6 border-b border-[var(--color-border)] pb-6 md:pb-8 lg:grid-cols-[1.1fr_0.9fr]">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-[var(--color-surface)] px-3 py-1.5 text-xs font-bold uppercase text-[var(--color-text-muted)]">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              Settings control room
            </div>
            <h1 className="mt-5 max-w-4xl text-3xl font-black leading-tight text-[var(--color-text-main)] md:text-4xl">
              {activeMeta.title}
            </h1>
            <p className="mt-5 max-w-2xl text-base leading-7 text-[var(--color-text-muted)] md:text-lg">
              {activeMeta.description}
            </p>
          </div>

          <div className="flex flex-col justify-between gap-5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-bold uppercase text-[var(--color-text-faint)]">Configuration plane</p>
                <p className="mt-3 text-2xl font-black text-[var(--color-text-main)]">
                  {activeMeta.eyebrow}
                </p>
              </div>
              <span className="material-symbols-outlined rounded-full bg-[var(--color-primary-muted)] p-2 text-[20px] text-[var(--color-primary)]">
                {activeMeta.icon}
              </span>
            </div>
            <div className="grid gap-2 text-sm text-[var(--color-text-muted)]">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[18px] text-[var(--color-primary)]">verified</span>
                Runtime changes are saved through the dashboard settings API.
              </div>
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[18px] text-[var(--color-primary)]">sync_alt</span>
                New launches read manager defaults from the canonical config.
              </div>
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[18px] text-[var(--color-primary)]">history</span>
                Existing war-rooms keep their current lifecycle values.
              </div>
            </div>
            <div>
              <LiveStatusBadge />
            </div>
          </div>
        </header>

        <div className="grid gap-5 lg:grid-cols-4">
          {settingsMetrics.map((metric) => (
            <SettingsMetricCard key={metric.id} {...metric} />
          ))}
        </div>

        <div className="grid gap-8 lg:grid-cols-[18rem_1fr]">
          <SettingsSidebar
            activeNamespace={activeNamespace}
            onNamespaceChange={setActiveNamespace}
          />

          <main className="min-w-0">
            {renderActivePanel()}
          </main>
        </div>
      </section>

      <VaultSecretModal
        isOpen={vaultModalOpen}
        onClose={() => setVaultModalOpen(false)}
        scope={vaultScope}
        keyName={vaultKey}
        isSet={vaultStatus[vaultKey] || false}
        onSubmit={handleVaultSubmit}
      />

      <AddProviderModal
        isOpen={addProviderOpen}
        onClose={() => setAddProviderOpen(false)}
        onProviderAdded={handleProviderAdded}
      />
    </div>
  );
}
