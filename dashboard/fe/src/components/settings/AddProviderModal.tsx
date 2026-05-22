'use client';

import { useState, useEffect, useMemo } from 'react';
import { apiGet, apiPost } from '@/lib/api-client';

interface AvailableProvider {
  id: string;
  name: string;
  logo_url: string;
  model_count: number;
  doc: string;
  env: string[];
  already_configured: boolean;
}

/**
 * Provider IDs that have dedicated configuration cards on the settings page.
 * These are hidden entirely from the "Add Provider" browser to avoid duplicates.
 */
const EXCLUDED_PROVIDER_IDS = new Set([
  'google',
  'openai',
  'anthropic',
  'byteplus',
]);

export interface AddProviderModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Called after the key is saved. Receives the provider id. */
  onProviderAdded: (providerId: string) => void;
}

type Step = 'browse' | 'configure';

export function AddProviderModal({ isOpen, onClose, onProviderAdded }: AddProviderModalProps) {
  const [step, setStep] = useState<Step>('browse');
  const [providers, setProviders] = useState<AvailableProvider[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<AvailableProvider | null>(null);

  // configure step
  const [apiKey, setApiKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch provider list when modal opens
  useEffect(() => {
    if (!isOpen) return;
    setStep('browse');
    setSelected(null);
    setApiKey('');
    setError(null);
    setSearch('');

    setLoading(true);
    apiGet<{ providers: AvailableProvider[] }>('/models/available')
      .then((res) => setProviders(res.providers ?? []))
      .catch(() => setProviders([]))
      .finally(() => setLoading(false));
  }, [isOpen]);

  const filtered = useMemo(() => {
    // Exclude providers that have dedicated cards on the settings page
    let list = providers.filter((p) => !EXCLUDED_PROVIDER_IDS.has(p.id));

    // Text filter
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (p) =>
          p.name.toLowerCase().includes(q) ||
          p.id.toLowerCase().includes(q),
      );
    }

    // Alphabetical sort
    return [...list].sort((a, b) => a.name.localeCompare(b.name));
  }, [providers, search]);

  const handleSelect = (p: AvailableProvider) => {
    setSelected(p);
    setStep('configure');
    setApiKey('');
    setError(null);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selected || !apiKey.trim()) return;

    setSaving(true);
    setError(null);
    try {
      await apiPost(`/settings/vault/providers/${selected.id}`, { value: apiKey.trim() });
      // Reload models so the provider appears in configured list
      await apiPost('/models/reload');
      onProviderAdded(selected.id);
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.6)' }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-xl bg-white border border-slate-200 shadow-2xl overflow-hidden flex flex-col"
        style={{ maxHeight: '80vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Header ──────────────────────────────────────────────── */}
        <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50">
          <div className="flex items-center gap-2">
            {step === 'configure' && (
              <button
                onClick={() => setStep('browse')}
                className="p-1 rounded hover:bg-slate-200 transition-colors"
              >
                <span className="material-symbols-outlined text-sm text-slate-500">arrow_back</span>
              </button>
            )}
            <h2 className="text-sm font-bold text-slate-900 uppercase tracking-wide">
              {step === 'browse' ? 'Add Provider' : `Configure ${selected?.name ?? ''}`}
            </h2>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-slate-200 transition-colors">
            <span className="material-symbols-outlined text-lg text-slate-500">close</span>
          </button>
        </div>

        {/* ── Step 1: Browse ──────────────────────────────────────── */}
        {step === 'browse' && (
          <>
            <div className="px-6 py-3 border-b border-slate-100">
              <div className="relative">
                <span className="material-symbols-outlined absolute left-3 top-2.5 text-sm text-slate-400">search</span>
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search providers..."
                  className="w-full pl-9 pr-3 py-2 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-500"
                  autoFocus
                />
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-3 py-2" style={{ maxHeight: '50vh' }}>
              {loading ? (
                <div className="flex items-center justify-center py-12">
                  <span className="material-symbols-outlined text-xl text-slate-400 animate-spin">progress_activity</span>
                </div>
              ) : filtered.length === 0 ? (
                <div className="text-center py-12 text-xs text-slate-400">No providers found</div>
              ) : (
                <div className="grid grid-cols-1 gap-1">
                  {filtered.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => !p.already_configured && handleSelect(p)}
                        disabled={p.already_configured}
                        className={`w-full text-left px-4 py-3 rounded-lg flex items-center gap-3 transition-colors ${p.already_configured
                          ? 'opacity-40 cursor-not-allowed'
                          : 'hover:bg-blue-50 cursor-pointer'
                          }`}
                      >
                        <img
                          src={p.logo_url}
                          alt=""
                          className="w-6 h-6 flex-shrink-0 rounded"
                          onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                        />
                        <div className="flex-1 min-w-0">
                          <div className="text-xs font-semibold text-slate-900 truncate">{p.name}</div>
                          <div className="text-[10px] text-slate-400">
                            {p.model_count} model{p.model_count !== 1 ? 's' : ''}
                            {p.env.length > 0 && <> &middot; {p.env[0]}</>}
                          </div>
                        </div>
                        {p.already_configured ? (
                          <span className="text-[10px] font-bold text-green-600 flex-shrink-0">ADDED</span>
                        ) : (
                          <span className="material-symbols-outlined text-sm text-slate-300">chevron_right</span>
                        )}
                      </button>
                    ))}
                </div>
              )}
            </div>

            <div className="px-6 py-3 border-t border-slate-100 text-[10px] text-slate-400 text-center">
              {providers.filter((p) => !EXCLUDED_PROVIDER_IDS.has(p.id)).length} available providers &middot; {providers.filter((p) => p.already_configured && !EXCLUDED_PROVIDER_IDS.has(p.id)).length} already configured
            </div>
          </>
        )}

        {/* ── Step 2: Configure ───────────────────────────────────── */}
        {step === 'configure' && selected && (
          <form onSubmit={handleSave} className="flex-1 flex flex-col">
            <div className="px-6 py-5 space-y-5 flex-1">
              {/* Provider info */}
              <div className="flex items-center gap-3 p-3 bg-slate-50 rounded-lg border border-slate-100">
                <img
                  src={selected.logo_url}
                  alt=""
                  className="w-8 h-8 rounded"
                  onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                />
                <div>
                  <div className="text-sm font-bold text-slate-900">{selected.name}</div>
                  <div className="text-[10px] text-slate-400">
                    {selected.model_count} models available
                    {selected.doc && (
                      <> &middot; <a href={selected.doc} target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">Docs</a></>
                    )}
                  </div>
                </div>
              </div>

              {/* Env hint */}
              {selected.env.length > 0 && (
                <div className="flex items-center gap-2 text-[10px] text-slate-500 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
                  <span className="material-symbols-outlined text-xs text-amber-500">info</span>
                  This provider expects <code className="font-mono bg-white px-1 rounded border border-amber-200">{selected.env[0]}</code>
                </div>
              )}

              {/* API key */}
              <div>
                <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500 block mb-1.5">
                  API Key
                </label>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="Paste your API key"
                  className="w-full px-3 py-2.5 rounded-lg text-sm font-mono bg-slate-50 border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500 text-slate-900"
                  autoFocus
                  required
                />
                <p className="text-[9px] text-slate-400 mt-1">
                  Stored securely in vault. Never displayed again.
                </p>
              </div>

              {error && (
                <div className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                  {error}
                </div>
              )}
            </div>

            <div className="px-6 py-4 border-t border-slate-100 flex gap-2">
              <button
                type="submit"
                disabled={saving || !apiKey.trim()}
                className="flex-1 px-4 py-2.5 rounded-lg text-xs font-bold uppercase tracking-wide bg-blue-600 text-white hover:bg-blue-700 transition-colors disabled:opacity-50"
              >
                {saving ? 'Saving...' : 'Add Provider'}
              </button>
              <button
                type="button"
                onClick={() => setStep('browse')}
                className="px-4 py-2.5 rounded-lg text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200 transition-colors"
              >
                Back
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
