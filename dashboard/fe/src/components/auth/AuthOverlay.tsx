"use client";

import React, { useState } from 'react';
import Image from 'next/image';
import { usePathname } from 'next/navigation';
import { useAuth } from './AuthProvider';

function normalizePath(pathname: string | null | undefined): string {
  const rawPath = pathname || (typeof window !== 'undefined' ? window.location.pathname : '');
  return decodeURIComponent(rawPath.split('?')[0] || '').replace(/\/+$/, '');
}

function getBrowserSearch(): string {
  return typeof window !== 'undefined' ? window.location.search : '';
}

export function isOntologyFixturePath(pathname: string | null | undefined): boolean {
  return normalizePath(pathname) === '/knowledge/ontology-fixture';
}

export function isOntologyGraphBuilderFixturePath(pathname: string | null | undefined, search = getBrowserSearch()): boolean {
  const normalized = normalizePath(pathname);
  const isGraphBuilderRoute = /^\/knowledge\/[^/]+\/ontology-graph-builder$/.test(normalized);
  if (!isGraphBuilderRoute) return false;

  const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search);
  return ['basic', 'empty', 'redacted', 'large', 'error'].includes(params.get('fixture') || '');
}

export default function AuthOverlay() {
  const pathname = usePathname();
  const { isAuthenticated, isLoading, error, login } = useAuth();
  const [key, setKey] = useState('');
  const [username, setUsername] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const browserPathname = typeof window !== 'undefined' ? window.location.pathname : '';
  const isOntologyFixtureRoute = isOntologyFixturePath(pathname) || isOntologyFixturePath(browserPathname);
  const isOntologyGraphBuilderFixtureRoute =
    isOntologyGraphBuilderFixturePath(pathname) || isOntologyGraphBuilderFixturePath(browserPathname);

  // Don't render if authenticated/loading, or when QA opens local ontology fixtures.
  // These fixture workbenches are client-local and must stay interactive without
  // requiring a backend auth handshake; all non-fixture routes keep the setup overlay
  // unchanged. Check both usePathname() and window.location because static-export
  // hydration can briefly expose placeholder paths such as /knowledge/_.
  if (isLoading || isAuthenticated || isOntologyFixtureRoute || isOntologyGraphBuilderFixtureRoute) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    await login(key.trim(), username.trim());
    setSubmitting(false);
  };

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-background/80 backdrop-blur-md">
      <div
        className="w-full max-w-sm mx-4 p-8 bg-surface rounded-2xl border border-border shadow-2xl"
        style={{ animation: 'fadeInUp 0.3s ease-out' }}
      >
        {/* Logo / Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-primary/10 mb-4">
            <Image src="/logo.svg" alt="OsTwin" width={28} height={28} />
          </div>
          <h1 className="text-xl font-black text-text-main tracking-tight">
            Os<span style={{ background: 'linear-gradient(135deg, #00ff88, #00c4e0, #00d4ff)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>Twin</span>
          </h1>
          <p className="text-xs text-text-muted mt-1">Finish local setup to continue</p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit}>
          <div className="space-y-4">
            <div>
              <label htmlFor="ostwin-username" className="block text-[10px] font-bold text-text-faint uppercase tracking-widest mb-2">
                Your name
              </label>
              <input
                id="ostwin-username"
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                placeholder="Paul"
                autoComplete="name"
                autoFocus
                className="w-full px-4 py-3 rounded-xl bg-background border border-border text-sm text-text-main placeholder:text-text-faint/50 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary transition-all"
              />
            </div>

            <div>
              <label htmlFor="ostwin-api-key" className="block text-[10px] font-bold text-text-faint uppercase tracking-widest mb-2">
                OSTWIN API Key
              </label>
              <input
                id="ostwin-api-key"
                type="password"
                value={key}
                onChange={e => setKey(e.target.value)}
                placeholder="ostwin_••••••••••••"
                autoComplete="off"
                className="w-full px-4 py-3 rounded-xl bg-background border border-border text-sm text-text-main placeholder:text-text-faint/50 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary transition-all font-mono"
              />
            </div>

            {error && (
              <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-danger-light text-danger-text text-xs font-medium">
                <span className="material-symbols-outlined text-[16px]">error</span>
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={!key.trim() || !username.trim() || submitting}
              className="w-full py-3 rounded-xl bg-primary text-white text-sm font-bold hover:bg-primary-dark transition-all shadow-lg shadow-primary/20 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {submitting ? (
                <>
                  <span className="material-symbols-outlined animate-spin text-[18px]">progress_activity</span>
                  Verifying...
                </>
              ) : (
                <>
                  <span className="material-symbols-outlined text-[18px]">login</span>
                  Save and enter dashboard
                </>
              )}
            </button>
          </div>
        </form>

        {/* Hint */}
        <p className="text-[10px] text-text-faint text-center mt-6 leading-relaxed">
          Your key and name are stored locally in <code className="px-1 py-0.5 rounded bg-surface-alt font-mono text-[9px]">~/.ostwin/.env</code>
        </p>
      </div>

      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes fadeInUp {
          from { opacity: 0; transform: translateY(12px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}} />
    </div>
  );
}
