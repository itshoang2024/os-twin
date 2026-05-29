'use client';

import { useEffect, useMemo, useState } from 'react';
import type { KnowledgeSettings, MemoryEmbeddingBackend, ModelInfo } from '@/types/settings';
import { ModelSelect } from '@/components/settings/ModelSelect';
import { ModelConfigSample } from './ModelConfigSample';
import { ProviderIcon } from './ProviderIcon';

export interface KnowledgePanelProps {
  knowledge: KnowledgeSettings;
  onUpdate: (value: Partial<KnowledgeSettings>) => void | Promise<void>;
  allModels: ModelInfo[];
}

// ── Backend option definitions (synchronised with MemoryPanel) ──────────────

interface BackendOption {
  value: string;
  label: string;
  description: string;
  requiresKey?: string;
  icon: string;
}

const LLM_BACKENDS: BackendOption[] = [
  { value: 'ollama',    label: 'Ollama (Local)',          description: 'Local Ollama server', icon: 'dns' },
  { value: 'openai-compatible', label: 'OpenAI-Compatible', description: 'Any OpenAI-compatible API server', icon: 'api' },
];

const EMBEDDING_BACKENDS: BackendOption[] = [
  { value: 'ollama',               label: 'Ollama (Local)',             description: 'Local Ollama embedding server', icon: 'dns' },
  { value: 'openai-compatible',    label: 'OpenAI-Compatible',          description: 'Any OpenAI-compatible embedding API', icon: 'api' },
];

// ── Recommended models per backend (synchronised with MemoryPanel) ──────────

const LLM_MODEL_SUGGESTIONS: Record<string, { model: string; label: string }[]> = {
  ollama: [
    { model: 'llama3.2', label: 'Llama 3.2 (recommended)' },
    { model: 'mistral', label: 'Mistral' },
  ],
  'openai-compatible': [
    { model: 'gpt-4', label: 'GPT-4' },
    { model: 'gpt-3.5-turbo', label: 'GPT-3.5 Turbo' },
  ],
};

const EMBEDDING_MODEL_SUGGESTIONS: Record<string, { model: string; label: string }[]> = {
  ollama: [
    { model: 'leoipulsar/harrier-0.6b', label: 'Harrier 0.6B (recommended)' },
    { model: 'embeddinggemma', label: 'Embedding Gemma' },
    { model: 'qwen3-embedding:0.6b', label: 'Qwen3 Embedding 0.6B' },
  ],
  'openai-compatible': [
    { model: 'default', label: 'Model configured on your server' },
  ],
};

// ── Defaults ────────────────────────────────────────────────────────────────

const DEFAULTS: KnowledgeSettings = {
  knowledge_llm_backend: '',
  knowledge_llm_model: '',
  knowledge_embedding_backend: '',
  knowledge_embedding_model: '',
  knowledge_embedding_dimension: 768,
};

// ── Component ───────────────────────────────────────────────────────────────

export function KnowledgePanel({ knowledge, onUpdate, allModels }: KnowledgePanelProps) {
  const effective = { ...DEFAULTS, ...knowledge };

  const [draft, setDraft] = useState<KnowledgeSettings>(effective);
  const [hasChanges, setHasChanges] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  // Sync draft if external knowledge settings change (but don't overwrite if user is editing)
  useEffect(() => {
    if (!hasChanges) {
      setDraft({ ...DEFAULTS, ...knowledge });
    }
  }, [knowledge, hasChanges]);

  // Helper to update draft
  const updateDraft = (updates: Partial<KnowledgeSettings>) => {
    setDraft((prev) => ({ ...prev, ...updates }));
    setHasChanges(true);
  };

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await onUpdate(draft);
      setHasChanges(false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'unknown error';
      setOllamaHealth((prev) => ({
        ...prev,
        ['save_error']: { running: false, model_exists: false, pulling: false, progress: `Save failed: ${msg}` },
      }));
    } finally {
      setIsSaving(false);
    }
  };

  // Removes unused variables from the top
  const [llmModelInput, setLlmModelInput] = useState(draft.knowledge_llm_model);
  const [embedModelInput, setEmbedModelInput] = useState(draft.knowledge_embedding_model);

  // OpenAI-compatible specific fields
  const [llmCompatibleUrl, setLlmCompatibleUrl] = useState(draft.knowledge_llm_compatible_url ?? '');
  const [llmCompatibleKey, setLlmCompatibleKey] = useState(draft.knowledge_llm_compatible_key ?? '');
  const [embeddingCompatibleUrl, setEmbeddingCompatibleUrl] = useState(draft.knowledge_embedding_compatible_url ?? '');
  const [embeddingCompatibleKey, setEmbeddingCompatibleKey] = useState(draft.knowledge_embedding_compatible_key ?? '');

  const [ollamaHealth, setOllamaHealth] = useState<Record<string, { running: boolean; model_exists: boolean; pulling: boolean; progress?: string }>>({});
  const [ollamaModels, setOllamaModels] = useState<{ raw_name: string; display_name: string; is_embed: boolean }[]>([]);

  // Fetch all installed Ollama models
  useEffect(() => {
    const fetchModels = async () => {
      try {
        const { apiGet } = await import('@/lib/api-client');
        const data = await apiGet<{ models: { raw_name: string; display_name: string; is_embed: boolean }[] }>('/settings/ollama/models');
        setOllamaModels(data.models || []);
      } catch {
        setOllamaModels([]);
      }
    };

    if (draft.knowledge_llm_backend === 'ollama' || draft.knowledge_embedding_backend === 'ollama') {
      fetchModels();
    }
  }, [draft.knowledge_llm_backend, draft.knowledge_embedding_backend]);

  // Check health when model changes
  useEffect(() => {
    const checkHealth = async (model: string) => {
      if (!model) return;
      try {
        const { apiGet } = await import('@/lib/api-client');
        const data = await apiGet<{ running: boolean; model_exists: boolean }>(`/settings/ollama/health?model=${model}`);
        setOllamaHealth((prev) => ({
          ...prev,
          [model]: { ...prev[model], ...data, pulling: prev[model]?.pulling || false },
        }));
      } catch {
        setOllamaHealth((prev) => ({
          ...prev,
          [model]: { running: false, model_exists: false, pulling: false, progress: 'Could not connect to backend to check Ollama status.' },
        }));
      }
    };

    if (draft.knowledge_llm_backend === 'ollama' && draft.knowledge_llm_model) {
      checkHealth(draft.knowledge_llm_model);
    }
    if (draft.knowledge_embedding_backend === 'ollama' && draft.knowledge_embedding_model) {
      checkHealth(draft.knowledge_embedding_model);
    }
  }, [draft.knowledge_llm_backend, draft.knowledge_llm_model, draft.knowledge_embedding_backend, draft.knowledge_embedding_model]);

  const pullModel = async (model: string) => {
    setOllamaHealth((prev) => ({
      ...prev,
      [model]: { ...prev[model], pulling: true, progress: 'Starting pull...' },
    }));

    try {
      const response = await fetch('/api/settings/ollama/pull', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model }),
      });

      if (!response.body) throw new Error('No body');

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const lines = decoder.decode(value).split('\n').filter(Boolean);
        for (const line of lines) {
          try {
            const data = JSON.parse(line);
            if (data.error) throw new Error(data.error);
            if (data.status) {
              let msg = data.status;
              if (data.total && data.completed) {
                const percent = Math.round((data.completed / data.total) * 100);
                msg += ` (${percent}%)`;
              }
              setOllamaHealth((prev) => ({
                ...prev,
                [model]: { ...prev[model], progress: msg },
              }));
            }
          } catch {
            // parse error
          }
        }
      }

      // Success! Re-check health
      const { apiGet } = await import('@/lib/api-client');
      const data = await apiGet<{ running: boolean; model_exists: boolean }>(`/settings/ollama/health?model=${model}`);
      setOllamaHealth((prev) => ({
        ...prev,
        [model]: { ...data, pulling: false },
      }));

    } catch (e) {
      setOllamaHealth((prev) => ({
        ...prev,
        [model]: { ...prev[model], pulling: false, progress: `Error: ${e}` },
      }));
    }
  };

  const renderOllamaBanner = () => {
    const usesOllamaLlm = draft.knowledge_llm_backend === 'ollama' && draft.knowledge_llm_model;
    const usesOllamaEmbed = draft.knowledge_embedding_backend === 'ollama' && draft.knowledge_embedding_model;

    if (!usesOllamaLlm && !usesOllamaEmbed) return null;

    const llmStatus = usesOllamaLlm && draft.knowledge_llm_model ? ollamaHealth[draft.knowledge_llm_model] : null;
    const embedStatus = usesOllamaEmbed && draft.knowledge_embedding_model ? ollamaHealth[draft.knowledge_embedding_model] : null;

    if ((usesOllamaLlm && !llmStatus) || (usesOllamaEmbed && !embedStatus)) return null;

    const notRunning = (llmStatus && !llmStatus.running) || (embedStatus && !embedStatus.running);
    const pullingLlm = llmStatus?.pulling;
    const pullingEmbed = embedStatus?.pulling;
    const missingLlm = llmStatus?.running && !llmStatus.model_exists && !pullingLlm;
    const missingEmbed = embedStatus?.running && !embedStatus.model_exists && !pullingEmbed;

    if (notRunning) {
      return (
        <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
          <span className="material-symbols-outlined text-red-600 mt-0.5">error</span>
          <div>
            <h4 className="text-sm font-bold text-red-800">Ollama is not running</h4>
            <p className="text-xs text-red-600 mt-1">You have selected Ollama as a backend, but the local Ollama server cannot be reached. Please start the Ollama application.</p>
          </div>
        </div>
      );
    }

    const pullingModels = [];
    if (pullingLlm) pullingModels.push({ model: draft.knowledge_llm_model!, progress: llmStatus.progress });
    if (pullingEmbed && draft.knowledge_embedding_model !== draft.knowledge_llm_model) {
      pullingModels.push({ model: draft.knowledge_embedding_model!, progress: embedStatus.progress });
    }

    if (pullingModels.length > 0) {
      return (
        <div className="mt-4 p-4 bg-blue-50 border border-blue-200 rounded-lg flex flex-col gap-2">
          {pullingModels.map(pm => (
            <div key={pm.model} className="flex items-center gap-3">
              <span className="material-symbols-outlined text-blue-600 animate-spin">progress_activity</span>
              <div className="text-sm text-blue-800 font-medium">
                Downloading {pm.model}... <span className="text-xs font-normal text-blue-600 ml-2">{pm.progress}</span>
              </div>
            </div>
          ))}
        </div>
      );
    }

    const missingModels = [];
    if (missingLlm) missingModels.push(draft.knowledge_llm_model!);
    if (missingEmbed && !missingModels.includes(draft.knowledge_embedding_model!)) missingModels.push(draft.knowledge_embedding_model!);

    if (missingModels.length > 0) {
      return (
        <div className="mt-4 p-4 bg-amber-50 border border-amber-200 rounded-lg flex items-start gap-3">
          <span className="material-symbols-outlined text-amber-600 mt-0.5">warning</span>
          <div className="flex-1">
            <h4 className="text-sm font-bold text-amber-800">Missing Local Models</h4>
            <p className="text-xs text-amber-700 mt-1 mb-3">The following models are required but not found in your local Ollama installation.</p>
            <div className="flex flex-wrap gap-2">
              {missingModels.map(model => (
                <button
                  key={model}
                  onClick={() => pullModel(model)}
                  className="px-3 py-1.5 bg-amber-600 text-white text-xs font-semibold rounded hover:bg-amber-700 transition-colors shadow-sm"
                >
                  Download {model}
                </button>
              ))}
            </div>
          </div>
        </div>
      );
    }

    return null;
  };

  // Keep local inputs in sync if external settings change
  useEffect(() => {
    if (!hasChanges) {
      setLlmModelInput(knowledge.knowledge_llm_model);
      setEmbedModelInput(knowledge.knowledge_embedding_model);
      setLlmCompatibleUrl(knowledge.knowledge_llm_compatible_url ?? '');
      setLlmCompatibleKey(knowledge.knowledge_llm_compatible_key ?? '');
      setEmbeddingCompatibleUrl(knowledge.knowledge_embedding_compatible_url ?? '');
      setEmbeddingCompatibleKey(knowledge.knowledge_embedding_compatible_key ?? '');
    }
  }, [knowledge, hasChanges]);

  // Filter out obvious embedding-only models from chat picker
  const chatModels = useMemo(
    () => allModels.filter((m) => !m.id.toLowerCase().includes('embed')),
    [allModels],
  );

  // Filter to only embedding models for the embedding picker
  const embedModels = useMemo(
    () => allModels.filter((m) => m.id.toLowerCase().includes('embed')),
    [allModels],
  );

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const flashSavedMessage = (_msg: string, _isError = false, _ttl = 1800) => {
  };

  const save = async (patch: Partial<KnowledgeSettings>) => {
    updateDraft(patch);
  };

  // ── LLM handlers ────────────────────────────────────────────────────────

  const handleLlmBackendChange = (backend: string) => {
    const suggestions = LLM_MODEL_SUGGESTIONS[backend] ?? [];
    const model = suggestions[0]?.model ?? '';
    updateDraft({ knowledge_llm_backend: backend, knowledge_llm_model: model });
    setLlmModelInput(model);
  };

  const handleLlmModelSelect = (modelId: string) => {
    updateDraft({ knowledge_llm_model: modelId });
    setLlmModelInput(modelId);
  };

  const commitLlmModelInput = () => {
    if (llmModelInput !== draft.knowledge_llm_model) {
      updateDraft({ knowledge_llm_model: llmModelInput });
    }
  };

  // ── Embedding handlers ──────────────────────────────────────────────────

  const handleEmbedBackendChange = (backend: string) => {
    const suggestions = EMBEDDING_MODEL_SUGGESTIONS[backend] ?? [];
    const model = suggestions[0]?.model ?? '';
    updateDraft({
      knowledge_embedding_backend: backend as MemoryEmbeddingBackend | '',
      knowledge_embedding_model: model,
    });
    setEmbedModelInput(model);
  };

  const handleEmbedModelSelect = (modelId: string) => {
    updateDraft({ knowledge_embedding_model: modelId });
    setEmbedModelInput(modelId);
  };

  const commitEmbedModelInput = () => {
    if (embedModelInput !== draft.knowledge_embedding_model) {
      updateDraft({ knowledge_embedding_model: embedModelInput });
    }
  };

  // ── Render ──────────────────────────────────────────────────────────────

  const inputStyle = {
    background: '#f1f5f9',
    border: '1px solid #e2e8f0',
    color: '#0f172a',
  };

  const llmSuggestions = draft.knowledge_llm_backend ? (LLM_MODEL_SUGGESTIONS[draft.knowledge_llm_backend] ?? []) : [];
  const embedSuggestions = draft.knowledge_embedding_backend ? (EMBEDDING_MODEL_SUGGESTIONS[draft.knowledge_embedding_backend] ?? []) : [];

  return (
    <div className="space-y-8">
      {/* ── Header ──────────────────────────────────────────── */}
      <div>
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs font-mono text-primary bg-primary-container px-2 py-0.5 rounded">
            SYSTEM_ADMIN
          </span>
          <span className="text-xs text-on-surface-variant">/ configuration / knowledge-models</span>
        </div>
        <h2 className="text-2xl font-extrabold tracking-tight text-on-surface mb-1">
          Knowledge Models
        </h2>
        <p className="text-sm text-on-surface-variant">
          Configure the LLM and embedding backends used by the knowledge service for entity
          extraction, query answering, and document indexing. All embeddings are normalised to{' '}
          <code className="font-mono text-[10px] bg-slate-100 px-1 py-0.5 rounded">{effective.knowledge_embedding_dimension || '???'}</code>{' '}
          dimensions (set via <code className="font-mono text-[10px] bg-slate-100 px-1 py-0.5 rounded">OSTWIN_EMBEDDING_DIMENSION</code>).
        </p>

        {renderOllamaBanner()}
      </div>

      {/* ── Section 1: LLM Backend ───────────────────────────── */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <span className="material-symbols-outlined text-blue-600 text-lg">psychology</span>
          <h3 className="text-xs font-bold uppercase tracking-widest text-slate-700">Processing Model</h3>
          <span className="text-[9px] text-slate-400 ml-auto font-mono">knowledge_llm_backend / knowledge_llm_model</span>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* LLM Backend Selector */}
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-wider mb-2 block text-slate-500">
              LLM Backend
            </label>
            <div className="space-y-1.5">
              {LLM_BACKENDS.map((b) => {
                const isActive = draft.knowledge_llm_backend === b.value;
                return (
                  <button
                    key={b.value}
                    type="button"
                    onClick={() => handleLlmBackendChange(b.value)}
                    className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-all ${
                      isActive
                        ? 'bg-blue-50 border-2 border-blue-500 shadow-sm'
                        : 'bg-white border border-slate-200 hover:border-blue-300 hover:bg-blue-50/30 cursor-pointer'
                    }`}
                  >
                    <ProviderIcon provider={b.value} size={16} className={isActive ? '' : 'opacity-50'} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className={`text-xs font-semibold ${isActive ? 'text-blue-700' : 'text-slate-700'}`}>
                          {b.label}
                        </span>
                        {!b.requiresKey && b.value !== '' && (
                          <span className="text-[8px] font-bold uppercase px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">
                            Local
                          </span>
                        )}
                        {b.requiresKey === undefined && b.value === 'openai-compatible' && (
                          <span className="text-[8px] font-bold uppercase px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">Custom</span>
                        )}
                      </div>
                      <p className="text-[9px] text-slate-400 truncate">{b.description}</p>
                    </div>
                    {isActive && (
                      <span className="material-symbols-outlined text-blue-600 text-sm">check_circle</span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* LLM Model Selector */}
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-wider mb-2 block text-slate-500">
              Model
            </label>
            {/* Suggested models for the selected backend */}
            {draft.knowledge_llm_backend && llmSuggestions.length > 0 && (
              <div className="space-y-1 mb-3">
                {llmSuggestions.map((s) => {
                  const isActive = llmModelInput === s.model;
                  return (
                    <button
                      key={s.model}
                      type="button"
                      onClick={() => handleLlmModelSelect(s.model)}
                      className={`w-full text-left px-3 py-2 rounded-lg text-xs transition-all flex items-center justify-between ${
                        isActive
                          ? 'bg-blue-50 border border-blue-400 text-blue-700 font-semibold'
                          : 'bg-white border border-slate-200 text-slate-600 hover:border-blue-300'
                      }`}
                    >
                      <span className="font-mono text-[10px]">{s.label}</span>
                      {isActive && <span className="material-symbols-outlined text-blue-500 text-sm">check</span>}
                    </button>
                  );
                })}
              </div>
            )}
            {/* Custom model input */}
            <div>
              <label className="text-[9px] text-slate-400 mb-1 block">Or enter a custom model ID:</label>
              <input
                type="text"
                value={llmModelInput}
                onChange={(e) => setLlmModelInput(e.target.value)}
                onBlur={commitLlmModelInput}
                onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
                placeholder="e.g. llama3.2"
                className="w-full px-3 py-2 rounded-md text-xs font-mono"
                style={inputStyle}
              />
            </div>

            {/* Installed Ollama Models Dropdown */}
            {draft.knowledge_llm_backend === 'ollama' && ollamaModels.length > 0 && (
              <div className="mt-3">
                <label className="text-[9px] text-slate-500 mb-2 block">
                  Or pick from installed Ollama models:
                </label>
                <select
                  value={draft.knowledge_llm_model || ''}
                  onChange={(e) => {
                    const val = e.target.value;
                    setLlmModelInput(val);
                    updateDraft({ knowledge_llm_model: val });
                  }}
                  className="w-full px-3 py-2 rounded-md text-xs font-mono bg-white border border-slate-200 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
                >
                  <option value="" disabled>— Select installed model —</option>
                  {ollamaModels.filter(m => !m.is_embed).map(m => (
                    <option key={m.raw_name} value={m.display_name}>{m.display_name}</option>
                  ))}
                </select>
              </div>
            )}

            {/* Model picker from configured providers */}
            {draft.knowledge_llm_backend === 'openai-compatible' && chatModels.length > 0 && (
              <div className="mt-3">
                <label className="text-[9px] text-slate-500 mb-2 block">
                  Pick from configured providers:
                </label>
                <ModelSelect
                  value={draft.knowledge_llm_model || ''}
                  onChange={(m) => handleLlmModelSelect(m)}
                  models={chatModels}
                  showTier={true}
                  showContext={true}
                  placeholder="— Select from providers —"
                />
              </div>
            )}

            {/* OpenAI-compatible specific fields */}
            {draft.knowledge_llm_backend === 'openai-compatible' && (
              <div className="mt-4 space-y-3 p-3 bg-slate-50 rounded-lg border border-slate-200">
                <div>
                  <label className="text-[9px] font-semibold text-slate-600 mb-1 block">API Endpoint URL</label>
                  <input
                    type="text"
                    value={llmCompatibleUrl}
                    onChange={(e) => setLlmCompatibleUrl(e.target.value)}
                    onBlur={() => updateDraft({ knowledge_llm_compatible_url: llmCompatibleUrl })}
                    placeholder="http://localhost:8000/v1"
                    className="w-full px-3 py-2 rounded-md text-xs font-mono"
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label className="text-[9px] font-semibold text-slate-600 mb-1 block">API Key (optional)</label>
                  <input
                    type="password"
                    value={llmCompatibleKey}
                    onChange={(e) => setLlmCompatibleKey(e.target.value)}
                    onBlur={() => updateDraft({ knowledge_llm_compatible_key: llmCompatibleKey })}
                    placeholder="sk-..."
                    className="w-full px-3 py-2 rounded-md text-xs font-mono"
                    style={inputStyle}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ── Section 2: Embedding ───────────────────────────── */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <span className="material-symbols-outlined text-purple-600 text-lg">layers</span>
          <h3 className="text-xs font-bold uppercase tracking-widest text-slate-700">Embedding</h3>
          <span className="text-[9px] text-slate-400 ml-auto font-mono">knowledge_embedding_backend / knowledge_embedding_model</span>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Embedding Backend Selector */}
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-wider mb-2 block text-slate-500">
              Embedding Backend
            </label>
            <div className="space-y-1.5">
              {EMBEDDING_BACKENDS.map((b) => {
                const isActive = draft.knowledge_embedding_backend === b.value;
                return (
                  <button
                    key={b.value}
                    type="button"
                    onClick={() => handleEmbedBackendChange(b.value)}
                    className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-all ${
                      isActive
                        ? 'bg-purple-50 border-2 border-purple-500 shadow-sm'
                        : 'bg-white border border-slate-200 hover:border-purple-300 hover:bg-purple-50/30 cursor-pointer'
                    }`}
                  >
                    <ProviderIcon provider={b.value} size={16} className={isActive ? '' : 'opacity-50'} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className={`text-xs font-semibold ${isActive ? 'text-purple-700' : 'text-slate-700'}`}>
                          {b.label}
                        </span>
                        {!b.requiresKey && b.value !== '' && (
                          <span className="text-[8px] font-bold uppercase px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">
                            Local
                          </span>
                        )}
                        {b.requiresKey === undefined && b.value === 'openai-compatible' && (
                          <span className="text-[8px] font-bold uppercase px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">Custom</span>
                        )}
                      </div>
                      <p className="text-[9px] text-slate-400 truncate">{b.description}</p>
                    </div>
                    {isActive && (
                      <span className="material-symbols-outlined text-purple-600 text-sm">check_circle</span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Embedding Model Selector */}
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-wider mb-2 block text-slate-500">
              Model
            </label>
            {/* Suggested models for the selected backend */}
            {draft.knowledge_embedding_backend && embedSuggestions.length > 0 && (
              <div className="space-y-1 mb-3">
                {embedSuggestions.map((s) => {
                  const isActive = embedModelInput === s.model;
                  return (
                    <button
                      key={s.model}
                      type="button"
                      onClick={() => handleEmbedModelSelect(s.model)}
                      className={`w-full text-left px-3 py-2 rounded-lg text-xs transition-all flex items-center justify-between ${
                        isActive
                          ? 'bg-purple-50 border border-purple-400 text-purple-700 font-semibold'
                          : 'bg-white border border-slate-200 text-slate-600 hover:border-purple-300'
                      }`}
                    >
                      <span className="font-mono text-[10px]">{s.label}</span>
                      {isActive && <span className="material-symbols-outlined text-purple-500 text-sm">check</span>}
                    </button>
                  );
                })}
              </div>
            )}
            {/* Custom model input */}
            <div>
              <label className="text-[9px] text-slate-400 mb-1 block">Or enter a custom model ID:</label>
              <input
                type="text"
                value={embedModelInput}
                onChange={(e) => setEmbedModelInput(e.target.value)}
                onBlur={commitEmbedModelInput}
                placeholder="e.g. leoipulsar/harrier-0.6b"
                className="w-full px-3 py-2 rounded-md text-xs font-mono"
                style={inputStyle}
              />
            </div>

            {/* Installed Ollama Models Dropdown */}
            {draft.knowledge_embedding_backend === 'ollama' && ollamaModels.length > 0 && (
              <div className="mt-3">
                <label className="text-[9px] text-slate-500 mb-2 block">
                  Or pick from installed Ollama models:
                </label>
                <select
                  value={draft.knowledge_embedding_model || ''}
                  onChange={(e) => {
                    const val = e.target.value;
                    setEmbedModelInput(val);
                    updateDraft({ knowledge_embedding_model: val });
                  }}
                  className="w-full px-3 py-2 rounded-md text-xs font-mono bg-white border border-slate-200 focus:border-purple-500 focus:ring-1 focus:ring-purple-500 outline-none"
                >
                  <option value="" disabled>— Select installed model —</option>
                  {ollamaModels.filter(m => m.is_embed).map(m => (
                    <option key={m.raw_name} value={m.display_name}>{m.display_name}</option>
                  ))}
                </select>
              </div>
            )}

            {/* Model picker from configured providers (embedding models only) */}
            {draft.knowledge_embedding_backend === 'openai-compatible' && embedModels.length > 0 && (
              <div className="mt-3">
                <label className="text-[9px] text-slate-500 mb-2 block">
                  Pick from configured providers:
                </label>
                <ModelSelect
                  value={draft.knowledge_embedding_model || ''}
                  onChange={(m) => handleEmbedModelSelect(m)}
                  models={embedModels}
                  showTier={true}
                  showContext={false}
                  placeholder="— Select from providers —"
                />
              </div>
            )}

            {/* OpenAI-compatible specific fields */}
            {draft.knowledge_embedding_backend === 'openai-compatible' && (
              <div className="mt-4 space-y-3 p-3 bg-slate-50 rounded-lg border border-slate-200">
                <div>
                  <label className="text-[9px] font-semibold text-slate-600 mb-1 block">API Endpoint URL</label>
                  <input
                    type="text"
                    value={embeddingCompatibleUrl}
                    onChange={(e) => setEmbeddingCompatibleUrl(e.target.value)}
                    onBlur={() => save({ knowledge_embedding_compatible_url: embeddingCompatibleUrl })}
                    placeholder="http://localhost:8000/v1"
                    className="w-full px-3 py-2 rounded-md text-xs font-mono"
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label className="text-[9px] font-semibold text-slate-600 mb-1 block">API Key (optional)</label>
                  <input
                    type="password"
                    value={embeddingCompatibleKey}
                    onChange={(e) => setEmbeddingCompatibleKey(e.target.value)}
                    onBlur={() => save({ knowledge_embedding_compatible_key: embeddingCompatibleKey })}
                    placeholder="sk-..."
                    className="w-full px-3 py-2 rounded-md text-xs font-mono"
                    style={inputStyle}
                  />
                </div>
              </div>
            )}

            <p className="text-[10px] text-slate-400 mt-3">
              All vectors are normalised to <strong>{effective.knowledge_embedding_dimension || '???'} dimensions</strong> (via{' '}
              <code className="font-mono text-[10px] bg-slate-100 px-1 py-0.5 rounded">OSTWIN_EMBEDDING_DIMENSION</code>).
              Changing backend requires a <strong>fresh namespace</strong>.
            </p>
          </div>
        </div>
      </section>

      {/* ── Section 3: Embedding Dimension (read-only) ──────── */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <span className="material-symbols-outlined text-emerald-600 text-lg">straighten</span>
          <h3 className="text-xs font-bold uppercase tracking-widest text-slate-700">
            Embedding Dimension
          </h3>
          <span className="text-[9px] text-slate-400 ml-auto font-mono">OSTWIN_EMBEDDING_DIMENSION</span>
        </div>

        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <p className="text-[10px] text-slate-500 mb-3">
            All embedding backends produce vectors normalised to{' '}
            <strong>{effective.knowledge_embedding_dimension || '???'}</strong> dimensions for
            consistency. This value is controlled by the{' '}
            <code className="font-mono text-[10px] bg-slate-100 px-1 py-0.5 rounded">
              OSTWIN_EMBEDDING_DIMENSION
            </code>{' '}
            environment variable and is read-only in this panel.
          </p>
          <div className="flex items-baseline gap-2">
            <code className="text-2xl font-extrabold font-mono text-slate-900">
              {effective.knowledge_embedding_dimension || '???'}
            </code>
            <span className="text-[10px] text-slate-400">dimensions (from env)</span>
          </div>
        </div>
      </section>

      {/* ── Sample Configuration ──────────────────────────── */}
      <ModelConfigSample
        llmBackend={draft.knowledge_llm_backend}
        llmModel={draft.knowledge_llm_model}
        embeddingBackend={draft.knowledge_embedding_backend}
        embeddingModel={draft.knowledge_embedding_model}
        embeddingDimension={effective.knowledge_embedding_dimension}
        type="knowledge"
      />

      {/* ── Save Settings Button ──────────────────────────── */}
      {hasChanges && (
        <section className="sticky bottom-0 bg-surface-container-low border-t border-slate-200 py-4 mt-8 flex justify-end gap-3 z-10">
          <button
            onClick={() => {
              setDraft({ ...DEFAULTS, ...knowledge });
              setLlmModelInput(knowledge.knowledge_llm_model);
              setEmbedModelInput(knowledge.knowledge_embedding_model);
              setLlmCompatibleUrl(knowledge.knowledge_llm_compatible_url ?? '');
              setLlmCompatibleKey(knowledge.knowledge_llm_compatible_key ?? '');
              setEmbeddingCompatibleUrl(knowledge.knowledge_embedding_compatible_url ?? '');
              setEmbeddingCompatibleKey(knowledge.knowledge_embedding_compatible_key ?? '');
              setHasChanges(false);
            }}
            disabled={isSaving}
            className="px-4 py-2 text-sm font-semibold text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="flex items-center gap-2 px-6 py-2 text-sm font-bold text-white bg-blue-600 hover:bg-blue-700 rounded-lg shadow-sm transition-all disabled:opacity-75"
          >
            {isSaving && <span className="material-symbols-outlined text-sm animate-spin">progress_activity</span>}
            {isSaving ? 'Saving...' : 'Save Knowledge Settings'}
          </button>
        </section>
      )}
    </div>
  );
}

export default KnowledgePanel;
