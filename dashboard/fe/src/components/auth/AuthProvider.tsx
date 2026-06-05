'use client';

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { usePathname } from 'next/navigation';
import { getApiBaseUrl } from '@/lib/runtime-config';

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  apiKey: string | null;
  username: string | null;
  error: string | null;
  login: (key: string) => Promise<boolean>;
  logout: () => void;
}

const AuthContext = createContext<AuthState>({
  isAuthenticated: false,
  isLoading: true,
  apiKey: null,
  username: null,
  error: null,
  login: async () => false,
  logout: () => {},
});

export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isFixtureRoute = pathname.includes('-fixture');
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [username, setUsername] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const doLogin = useCallback(async (key: string): Promise<boolean> => {
    try {
      setError(null);
      const API_BASE = getApiBaseUrl();
      const res = await fetch(`${API_BASE}/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key }),
        credentials: 'include',
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || 'Invalid API key');
        return false;
      }

      const data = await res.json();
      setApiKey(key);
      setUsername(data.username || 'user');
      setIsAuthenticated(true);
      setError(null);
      return true;
    } catch {
      setError('Cannot reach server');
      return false;
    }
  }, []);

  // Check existing cookie on mount
  useEffect(() => {
    async function bootstrap() {
      try {
        if (isFixtureRoute) {
          setIsAuthenticated(true);
          setUsername('qa-fixture');
          setIsLoading(false);
          return;
        }

        const API_BASE = getApiBaseUrl();

        const meRes = await fetch(`${API_BASE}/auth/me`, { credentials: 'include' });
        if (meRes.ok) {
          const me = await meRes.json();
          setIsAuthenticated(true);
          setUsername(me.username || 'user');
          setIsLoading(false);
          return;
        }
      } catch {
        // Backend not reachable — show auth overlay
      }
      setIsLoading(false);
    }
    bootstrap();
  }, [doLogin, isFixtureRoute]);

  const login = useCallback(async (key: string) => {
    return doLogin(key);
  }, [doLogin]);

  const logout = useCallback(async () => {
    try {
      const API_BASE = getApiBaseUrl();
      await fetch(`${API_BASE}/auth/logout`, {
        method: 'POST',
        credentials: 'include',
      });
    } catch { /* ignore */ }
    setIsAuthenticated(false);
    setApiKey(null);
    setUsername(null);
  }, []);

  return (
    <AuthContext.Provider value={{ isAuthenticated, isLoading, apiKey, username, error, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
