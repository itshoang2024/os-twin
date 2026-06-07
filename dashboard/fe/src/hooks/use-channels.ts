import useSWR from 'swr';
import { apiPost, apiPut } from '@/lib/api-client';

export interface ConnectorConfig {
  platform: string;
  enabled: boolean;
  credentials: Record<string, string>;
  settings: Record<string, any>;
  authorized_users: string[];
  pairing_code: string;
  notification_preferences: {
    events: string[];
    enabled: boolean;
  };
}

export interface ChannelStatus {
  platform: string;
  status: 'connected' | 'disconnected' | 'connecting' | 'error' | 'needs_setup' | 'not_configured';
  config?: ConnectorConfig;
  health?: Record<string, string | number | boolean | null>;
}

export interface SetupStep {
  title: string;
  description: string;
  instructions: string;
}

export function useChannels() {
  const { data, error, mutate, isLoading } = useSWR<ChannelStatus[]>('/channels');

  const connect = async (platform: string, config?: { credentials?: Record<string, string>; settings?: Record<string, any> }) => {
    await apiPost(`/channels/${platform}/connect`, config);
    mutate();
  };

  const disconnect = async (platform: string) => {
    await apiPost(`/channels/${platform}/disconnect`);
    mutate();
  };

  const test = async (platform: string) => {
    return await apiPost<{ status: string; message: string }>(`/channels/${platform}/test`);
  };

  const updateSettings = async (platform: string, settings: Partial<ConnectorConfig>) => {
    await apiPut(`/channels/${platform}/settings`, settings);
    mutate();
  };

  const regeneratePairing = async (platform: string) => {
    await apiPost(`/channels/${platform}/pairing/regenerate`);
    mutate();
  };

  return {
    channels: data,
    isLoading,
    isError: error,
    connect,
    disconnect,
    test,
    updateSettings,
    regeneratePairing,
    refresh: mutate,
  };
}

export function useChannelSetup(platform: string | null) {
  const { data, error, isLoading } = useSWR<SetupStep[]>(platform ? `/channels/${platform}/setup` : null);

  return {
    setupSteps: data,
    isLoading,
    isError: error,
  };
}
