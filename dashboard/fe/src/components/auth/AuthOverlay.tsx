'use client';

import React, { useState } from 'react';
import { useAuth } from './AuthProvider';

export default function AuthOverlay() {
  const { isAuthenticated, isLoading, error, login } = useAuth();
  const [key, setKey] = useState('');
  const [username, setUsername] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Don't render if authenticated or still loading
  if (isLoading || isAuthenticated) return null;

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
            <img src="/logo.svg" alt="OsTwin" width={28} height={28} />
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
