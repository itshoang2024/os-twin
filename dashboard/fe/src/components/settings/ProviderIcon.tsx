'use client';

/**
 * ProviderIcon — renders the local SVG logo for a known provider,
 * falling back to a Material Symbols icon for unknown providers.
 *
 * Local icons live under /providers/<key>.svg in the public folder.
 */

import { useState } from 'react';

/** Map of backend / provider values → local SVG filenames (without extension). */
const LOCAL_ICON_MAP: Record<string, string> = {
  // Providers
  google:              'google',
  anthropic:           'anthropic',
  openai:              'openai',
  byteplus:            'byteplus',
  // Backends
  gemini:              'google',
  'google-vertex':     'vertex',
  vertex:              'vertex',
  ollama:              'ollama',
  huggingface:         'hf',
  // Explicit overrides for clarity
  hf:                  'hf',
};

/** Material Symbols fallback for providers without a local SVG. */
const MATERIAL_FALLBACK: Record<string, string> = {
  openrouter:  'hub',
  sglang:      'terminal',
};

export interface ProviderIconProps {
  /** The provider or backend key, e.g. 'google', 'ollama', 'vertex'. */
  provider: string;
  /** Pixel size for the icon (width & height). Defaults to 18. */
  size?: number;
  /** Extra CSS classes applied to the root element. */
  className?: string;
}

export function ProviderIcon({ provider, size = 18, className = '' }: ProviderIconProps) {
  const [imgError, setImgError] = useState(false);
  const localKey = LOCAL_ICON_MAP[provider];

  // If we have a local SVG and it hasn't errored, render <img>
  if (localKey && !imgError) {
    return (
      <img
        src={`/providers/${localKey}.svg`}
        alt={provider}
        width={size}
        height={size}
        className={`inline-block flex-shrink-0 ${className}`}
        style={{ width: size, height: size }}
        onError={() => setImgError(true)}
      />
    );
  }

  // Fallback: Material Symbol
  const icon = MATERIAL_FALLBACK[provider] || 'smart_toy';
  return (
    <span
      className={`material-symbols-outlined flex-shrink-0 ${className}`}
      style={{ fontSize: size }}
    >
      {icon}
    </span>
  );
}
