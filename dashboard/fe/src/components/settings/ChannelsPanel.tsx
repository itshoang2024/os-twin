'use client';

import { useState } from 'react';
import { useChannels, ChannelStatus, useChannelSetup, ConnectorConfig } from '@/hooks/use-channels';

const NOTIFICATION_EVENTS = [
  {
    id: 'plan.run.started',
    title: 'Plan Started',
    description: 'plan.run.started',
    group: 'Plan',
  },
  {
    id: 'plan.run.completed',
    title: 'Plan Completed',
    description: 'plan.run.completed',
    group: 'Plan',
  },
  {
    id: 'plan.run.failed',
    title: 'Plan Failed',
    description: 'plan.run.failed',
    group: 'Plan',
  },
  {
    id: 'epic.passed',
    title: 'Epic Done',
    description: 'epic.passed',
    group: 'Epic',
  },
  {
    id: 'epic.failed',
    title: 'Epic Failed',
    description: 'epic.failed',
    group: 'Epic',
  },
  {
    id: 'epic.retrying',
    title: 'Epic Retry',
    description: 'epic.retrying',
    group: 'Epic',
  },
  {
    id: 'room.created',
    title: 'Room Created',
    description: 'room.created',
    group: 'Room',
  },
  {
    id: 'room.status.changed',
    title: 'Room Status Changed',
    description: 'room.status.changed',
    group: 'Room',
  },
] as const;

const SUPPORTED_NOTIFICATION_EVENT_IDS = new Set<string>(NOTIFICATION_EVENTS.map(event => event.id));

const LEGACY_NOTIFICATION_EVENT_IDS: Record<string, string> = {
  plan_started: 'plan.run.started',
  plan_completed: 'plan.run.completed',
  plan_failed: 'plan.run.failed',
  epic_passed: 'epic.passed',
  epic_failed: 'epic.failed',
  epic_retry: 'epic.retrying',
  room_created: 'room.created',
  room_status_changed: 'room.status.changed',
};

interface ChannelItem {
  id: string;
  kind?: string;
  user_id?: string;
  channel_id?: string;
  conversation_id?: string;
  title?: string;
  platform?: string;
  created_at?: string;
  updated_at?: string;
  enabled?: boolean;
  registered_events?: string[];
  notification_events?: string[];
}

function supportedNotificationEvents(events: string[] | undefined): string[] {
  const normalized = (events || [])
    .map(event => LEGACY_NOTIFICATION_EVENT_IDS[event] || event)
    .filter(event => SUPPORTED_NOTIFICATION_EVENT_IDS.has(event));
  return Array.from(new Set(normalized));
}

function getChannelItems(config: ConnectorConfig): ChannelItem[] {
  return Array.isArray(config.settings?.channel_items) ? config.settings.channel_items : [];
}

function channelItemLabel(item: ChannelItem): string {
  return item.title || item.conversation_id || item.channel_id || item.user_id || item.id;
}

function channelItemEventCount(item: ChannelItem): number {
  return supportedNotificationEvents(item.registered_events || item.notification_events).length;
}

export function ChannelsPanel() {
  const { channels = [], isLoading, connect, disconnect, test, regeneratePairing, updateSettings } = useChannels();

  return (
    <div>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs font-mono text-primary bg-primary-container px-2 py-0.5 rounded">
          SYSTEM_ADMIN
        </span>
        <span className="text-xs text-on-surface-variant">/ configuration / channels</span>
      </div>
      <div className="flex items-center gap-4 mb-1">
        <h2 className="text-2xl font-extrabold tracking-tight text-on-surface">
          Channel Management
        </h2>
      </div>
      <p className="text-sm text-on-surface-variant mb-6">
        Connect OS Twin to your favorite platforms — Telegram, Discord, Slack, and more.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {isLoading ? (
          [1, 2, 3].map(i => (
            <div key={i} className="h-[400px] rounded-xl border border-border bg-surface animate-pulse" />
          ))
        ) : (
          channels.map(channel => (
            <ChannelCard
              key={channel.platform}
              channel={channel}
              onConnect={(config) => connect(channel.platform, config)}
              onDisconnect={() => disconnect(channel.platform)}
              onTest={() => test(channel.platform)}
              onRegenerate={() => regeneratePairing(channel.platform)}
              onUpdateSettings={(settings) => updateSettings(channel.platform, settings)}
            />
          ))
        )}
      </div>
    </div>
  );
}

function ChannelCard({
  channel,
  onConnect,
  onDisconnect,
  onTest,
  onRegenerate,
  onUpdateSettings
}: {
  channel: ChannelStatus;
  onConnect: (config?: { credentials?: Record<string, string>; settings?: Record<string, any> }) => void;
  onDisconnect: () => void;
  onTest: () => void;
  onRegenerate: () => void;
  onUpdateSettings: (settings: Partial<ConnectorConfig>) => void;
}) {
  const [view, setView] = useState<'main' | 'setup' | 'settings'>(
    channel.status === 'not_configured' || channel.status === 'needs_setup' ? 'setup' : 'main'
  );

  const platformIcons: Record<string, string> = {
    telegram: 'send',
    discord: 'forum',
    slack: 'chat_bubble',
  };

  const statusColors: Record<string, string> = {
    connected: 'bg-emerald-500',
    disconnected: 'bg-slate-400',
    connecting: 'bg-amber-500',
    error: 'bg-rose-500',
    needs_setup: 'bg-amber-500',
    not_configured: 'bg-slate-300',
  };

  return (
    <div className="flex flex-col bg-surface border border-border rounded-xl shadow-card overflow-hidden transition-all hover:shadow-card-hover min-h-[420px]">
      {/* Header */}
      <div className="p-5 border-b border-border-light flex items-center justify-between bg-background/50">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-primary/5 flex items-center justify-center text-primary border border-primary/10">
            <span className="material-symbols-outlined text-2xl">{platformIcons[channel.platform] || 'cloud'}</span>
          </div>
          <div>
            <h3 className="font-bold text-text-main capitalize">{channel.platform}</h3>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className={`w-2 h-2 rounded-full ${statusColors[channel.status]}`} />
              <span className="text-[10px] font-bold uppercase tracking-wider text-text-muted">
                {channel.status.replace('_', ' ')}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 p-5 overflow-y-auto">
        {view === 'setup' ? (
          <SetupWizard platform={channel.platform} onComplete={onConnect} />
        ) : view === 'settings' ? (
          <SettingsView
            config={channel.config!}
            onUpdate={onUpdateSettings}
            onRegenerate={onRegenerate}
            onBack={() => setView('main')}
          />
        ) : (
          <ConnectedView
            channel={channel}
            onShowSettings={() => setView('settings')}
            onTest={onTest}
          />
        )}
      </div>

      {/* Footer Actions */}
      <div className="p-4 bg-background/30 border-t border-border-light flex items-center justify-between gap-3">
        {channel.status === 'connected' ? (
          <>
            <button
              onClick={onDisconnect}
              className="px-3 py-1.5 text-[11px] font-bold text-rose-600 hover:bg-rose-50 rounded-lg transition-colors border border-rose-100"
            >
              Disconnect
            </button>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setView(view === 'settings' ? 'main' : 'settings')}
                className={`p-2 transition-colors ${view === 'settings' ? 'text-primary' : 'text-text-muted hover:text-primary'}`}
                title="Settings"
              >
                <span className="material-symbols-outlined text-xl">settings</span>
              </button>
              <button
                onClick={onTest}
                className="p-2 text-text-muted hover:text-emerald-600 transition-colors"
                title="Health Check"
              >
                <span className="material-symbols-outlined text-xl">health_and_safety</span>
              </button>
            </div>
          </>
        ) : (
          <button
            onClick={() => setView(view === 'setup' ? 'main' : 'setup')}
            className="w-full py-2 bg-primary text-white text-xs font-bold rounded-lg hover:brightness-105 active:scale-[0.98] transition-all shadow-lg shadow-primary/20"
          >
            {view === 'setup' ? 'Cancel Setup' : (channel.status === 'not_configured' ? 'Begin Setup' : 'Reconnect')}
          </button>
        )}
      </div>
    </div>
  );
}

function Instructions({ text, className }: { text: string, className?: string }) {
  const parts = text.split(/(\[.*?\]\(.*?\))/g);
  return (
    <div className={className}>
      {parts.map((part, i) => {
        const match = part.match(/\[(.*?)\]\((.*?)\)/);
        if (match) {
          return <a key={i} href={match[2]} target="_blank" rel="noopener noreferrer" className="text-primary underline hover:no-underline">{match[1]}</a>;
        }
        return part;
      })}
    </div>
  );
}

function SetupWizard({ platform, onComplete }: { platform: string, onComplete: (config: { credentials: Record<string, string> }) => void }) {
  const { setupSteps = [], isLoading } = useChannelSetup(platform);
  const [token, setToken] = useState('');
  const [clientId, setClientId] = useState('');
  const [guildId, setGuildId] = useState('');
  const [appToken, setAppToken] = useState('');
  const [signingSecret, setSigningSecret] = useState('');

  if (isLoading) return <div className="animate-pulse space-y-4"><div className="h-4 bg-slate-200 rounded w-3/4" /><div className="h-20 bg-slate-100 rounded" /></div>;

  const buildCredentials = (): Record<string, string> => {
    if (platform === 'discord') {
      return { token, client_id: clientId, guild_id: guildId };
    }
    if (platform === 'slack') {
      return {
        token,
        app_token: appToken,
        ...(signingSecret ? { signing_secret: signingSecret } : {}),
      };
    }
    return { token };
  };

  const isValid = (): boolean => {
    if (!token) return false;
    if (platform === 'discord' && (!clientId || !guildId)) return false;
    if (platform === 'slack' && !appToken) return false;
    return true;
  };

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        {setupSteps.map((step, i) => (
          <div key={i} className="p-3 bg-background border border-border-light rounded-lg">
            <h4 className="text-xs font-bold text-text-main mb-1 flex items-center gap-2">
              <span className="w-4 h-4 rounded-full bg-primary/10 text-primary text-[10px] flex items-center justify-center">{i+1}</span>
              {step.title}
            </h4>
            <Instructions text={step.description} className="text-[11px] text-text-muted mb-2" />
            <Instructions
              text={step.instructions}
              className="text-[10px] font-mono p-2 bg-slate-50 rounded border border-slate-100 text-slate-600 whitespace-pre-wrap"
            />
          </div>
        ))}
      </div>

      <div className="space-y-3 pt-2">
        <div className="space-y-1">
          <label className="text-[10px] font-bold uppercase tracking-wider text-text-faint">Bot Token</label>
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className="w-full p-2 text-xs bg-background border border-border rounded-lg focus:ring-1 focus:ring-primary outline-none"
            placeholder={platform === 'slack' ? 'xoxb-... (Bot User OAuth Token)' : 'Paste token here...'}
          />
        </div>

        {platform === 'discord' && (
          <>
            <div className="space-y-1">
              <label className="text-[10px] font-bold uppercase tracking-wider text-text-faint">Client ID</label>
              <input
                type="text"
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                className="w-full p-2 text-xs bg-background border border-border rounded-lg focus:ring-1 focus:ring-primary outline-none"
                placeholder="Discord Client ID"
              />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] font-bold uppercase tracking-wider text-text-faint">Server ID</label>
              <input
                type="text"
                value={guildId}
                onChange={(e) => setGuildId(e.target.value)}
                className="w-full p-2 text-xs bg-background border border-border rounded-lg focus:ring-1 focus:ring-primary outline-none"
                placeholder="Discord Server ID (right-click server → Copy ID)"
              />
            </div>
          </>
        )}

        {platform === 'slack' && (
          <>
            <div className="space-y-1">
              <label className="text-[10px] font-bold uppercase tracking-wider text-text-faint">App-Level Token</label>
              <input
                type="password"
                value={appToken}
                onChange={(e) => setAppToken(e.target.value)}
                className="w-full p-2 text-xs bg-background border border-border rounded-lg focus:ring-1 focus:ring-primary outline-none"
                placeholder="xapp-... (Socket Mode token with connections:write)"
              />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] font-bold uppercase tracking-wider text-text-faint">
                Signing Secret <span className="normal-case tracking-normal font-normal text-text-faint/60">(optional)</span>
              </label>
              <input
                type="password"
                value={signingSecret}
                onChange={(e) => setSigningSecret(e.target.value)}
                className="w-full p-2 text-xs bg-background border border-border rounded-lg focus:ring-1 focus:ring-primary outline-none"
                placeholder="Found in Basic Information → App Credentials"
              />
            </div>
          </>
        )}

        <button
          onClick={() => onComplete({ credentials: buildCredentials() })}
          disabled={!isValid()}
          className="w-full py-2.5 bg-emerald-600 disabled:opacity-50 text-white text-[11px] font-black uppercase tracking-widest rounded-xl hover:brightness-105 transition-all shadow-lg shadow-emerald-600/20"
        >
          Finish Setup
        </button>
      </div>
    </div>
  );
}

function SettingsView({ config, onUpdate, onRegenerate, onBack }: { config: ConnectorConfig, onUpdate: (settings: Partial<ConnectorConfig>) => void, onRegenerate: () => void, onBack: () => void }) {
  const [events, setEvents] = useState<string[]>(supportedNotificationEvents(config.notification_preferences?.events));
  const [notificationsEnabled, setNotificationsEnabled] = useState(config.notification_preferences?.enabled ?? true);
  const [channelItems, setChannelItems] = useState<ChannelItem[]>(() => {
    const fallbackEvents = supportedNotificationEvents(config.notification_preferences?.events);
    return getChannelItems(config).map(item => ({
      ...item,
      enabled: item.enabled ?? true,
      registered_events: supportedNotificationEvents(item.registered_events || item.notification_events || fallbackEvents),
    }));
  });
  const [expandedChannelItems, setExpandedChannelItems] = useState<string[]>(() => {
    const items = getChannelItems(config);
    return items[0]?.id ? [items[0].id] : [];
  });

  const toggleEvent = (event: string) => {
    setEvents(prev => prev.includes(event) ? prev.filter(e => e !== event) : [...prev, event]);
  };

  const toggleChannelItem = (itemId: string) => {
    if (!notificationsEnabled) return;
    setChannelItems(prev => prev.map(item => (
      item.id === itemId ? { ...item, enabled: !(item.enabled ?? true) } : item
    )));
  };

  const toggleChannelItemEvent = (itemId: string, event: string) => {
    if (!notificationsEnabled) return;
    setChannelItems(prev => prev.map(item => {
      if (item.id !== itemId) return item;
      const registeredEvents = item.registered_events || [];
      return {
        ...item,
        registered_events: registeredEvents.includes(event)
          ? registeredEvents.filter(e => e !== event)
          : [...registeredEvents, event],
      };
    }));
  };

  const toggleChannelItemExpanded = (itemId: string) => {
    setExpandedChannelItems(prev => (
      prev.includes(itemId) ? prev.filter(id => id !== itemId) : [...prev, itemId]
    ));
  };

  const handleSave = () => {
    onUpdate({
      notification_preferences: {
        events: channelItems.length > 0 ? [] : events,
        enabled: notificationsEnabled
      },
      settings: {
        channel_items: channelItems,
      },
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between mb-4">
        <button onClick={onBack} className="flex items-center gap-1 text-[11px] font-bold text-text-muted hover:text-text-main">
          <span className="material-symbols-outlined text-lg">arrow_back</span>
          Back
        </button>
        <button onClick={handleSave} className="text-[11px] font-black text-primary uppercase tracking-wider">Save Changes</button>
      </div>

      <div className="space-y-4">
        <div>
          <label className="text-[10px] font-bold uppercase tracking-widest text-text-faint mb-2 block">Notifications</label>
          <div className="flex items-center justify-between p-2 bg-background border border-border-light rounded-lg">
            <span className="text-xs font-bold text-text-muted">Enabled</span>
            <input
              type="checkbox"
              checked={notificationsEnabled}
              onChange={(e) => setNotificationsEnabled(e.target.checked)}
              className="w-4 h-4 accent-primary"
            />
          </div>
        </div>

        <div className="space-y-2">
          <div className="mb-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-text-faint block">Event Triggers</label>
            <p className="text-[10px] text-text-faint mt-1">
              {channelItems.length > 0
                ? 'Choose registered events for each paired channel target.'
                : 'Leave all unchecked to receive every supported plan, epic, and room event.'}
            </p>
          </div>
          {channelItems.length > 0 ? (
            <div className="space-y-3">
              {channelItems.map(item => (
                <div key={item.id} className={`bg-background border border-border-light rounded-lg overflow-hidden ${notificationsEnabled ? '' : 'opacity-60'}`}>
                  <div className="flex items-center gap-3 p-3">
                    <button
                      type="button"
                      onClick={() => toggleChannelItemExpanded(item.id)}
                      className="flex min-w-0 flex-1 items-center gap-2 text-left"
                      aria-expanded={expandedChannelItems.includes(item.id)}
                    >
                      <span className="material-symbols-outlined text-lg text-text-muted transition-transform">
                        {expandedChannelItems.includes(item.id) ? 'expand_less' : 'expand_more'}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[11px] font-bold text-text-main truncate">{channelItemLabel(item)}</span>
                        <span className="block text-[10px] font-mono text-text-faint truncate">{item.conversation_id || item.id}</span>
                      </span>
                      <span className="shrink-0 rounded-full border border-border-light bg-slate-50 px-2 py-0.5 text-[9px] font-bold text-text-faint">
                        {channelItemEventCount(item)} events
                      </span>
                    </button>
                    <label className="flex shrink-0 items-center gap-1.5 text-[10px] font-bold text-text-faint cursor-pointer">
                      On
                      <input
                        type="checkbox"
                        checked={notificationsEnabled && (item.enabled ?? true)}
                        disabled={!notificationsEnabled}
                        onChange={() => toggleChannelItem(item.id)}
                        className="w-4 h-4 accent-primary"
                      />
                    </label>
                  </div>
                  {expandedChannelItems.includes(item.id) && (
                    <div className="grid grid-cols-1 gap-1.5 border-t border-border-light p-3 pt-2">
                      {NOTIFICATION_EVENTS.map(event => (
                        <label key={event.id} className="flex items-center justify-between gap-2 py-1.5 px-2 rounded hover:bg-slate-50 cursor-pointer">
                          <span className="min-w-0">
                            <span className="text-[10px] font-bold text-text-main">{event.title}</span>
                            <span className="ml-2 text-[9px] font-mono text-text-faint">{event.description}</span>
                          </span>
                          <input
                            type="checkbox"
                            checked={(item.registered_events || []).includes(event.id)}
                            disabled={!notificationsEnabled || item.enabled === false}
                            onChange={() => toggleChannelItemEvent(item.id, event.id)}
                            className="w-4 h-4 accent-primary"
                          />
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            NOTIFICATION_EVENTS.map(event => (
              <label key={event.id} className="flex items-center justify-between p-2 hover:bg-background border border-transparent hover:border-border-light rounded-lg cursor-pointer transition-all gap-3">
                <span className="min-w-0">
                  <span className="flex items-center gap-2">
                    <span className="text-[11px] font-bold text-text-main">{event.title}</span>
                    <span className="text-[9px] font-mono text-text-faint bg-slate-50 border border-border-light rounded px-1.5 py-0.5">{event.group}</span>
                  </span>
                  <span className="block text-[10px] font-mono text-text-faint truncate">{event.description}</span>
                </span>
                <input
                  type="checkbox"
                  checked={events.includes(event.id)}
                  onChange={() => toggleEvent(event.id)}
                  className="w-4 h-4 accent-primary"
                />
              </label>
            ))
          )}
        </div>

        <div>
          <label className="text-[10px] font-bold uppercase tracking-widest text-text-faint mb-2 block">Access Control</label>
          <div className="space-y-3">
            <div className="p-3 bg-background border border-border-light rounded-lg">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-bold text-text-muted">Pairing Code</span>
                <button onClick={onRegenerate} className="text-[10px] text-primary font-bold hover:underline">Regenerate</button>
              </div>
              <div className="text-lg font-mono font-bold tracking-widest text-center py-2 bg-slate-50 rounded border border-slate-100">
                {config.pairing_code || '—'}
              </div>
            </div>

          </div>
        </div>
      </div>
    </div>
  );
}

function ConnectedView({ channel, onShowSettings, onTest: _onTest }: { channel: ChannelStatus, onShowSettings: () => void, onTest: () => void }) {
  const channelItems = channel.config ? getChannelItems(channel.config) : [];
  const eventCount = channelItems.length > 0
    ? channelItems.reduce((total, item) => total + supportedNotificationEvents(item.registered_events || item.notification_events).length, 0)
    : channel.config?.notification_preferences?.events?.length || 0;

  return (
    <div className="flex flex-col items-center justify-center h-full py-6 text-center">
      <div className="w-16 h-16 rounded-full bg-emerald-50 text-emerald-500 flex items-center justify-center mb-4 border border-emerald-100">
        <span className="material-symbols-outlined text-4xl">check_circle</span>
      </div>
      <h4 className="text-sm font-bold text-text-main mb-1">Connector Active</h4>
      <p className="text-xs text-text-muted mb-6">Receiving commands and sending notifications.</p>

      <div className="grid grid-cols-2 gap-3 w-full">
        <div className="p-3 bg-background border border-border-light rounded-lg">
          <div className="text-[10px] font-bold text-text-faint uppercase mb-1">Users</div>
          <div className="text-sm font-black text-text-main">{channelItems.length || channel.config?.authorized_users?.length || 0}</div>
        </div>
        <div className="p-3 bg-background border border-border-light rounded-lg">
          <div className="text-[10px] font-bold text-text-faint uppercase mb-1">Events</div>
          <div className="text-sm font-black text-text-main">{eventCount}</div>
        </div>
      </div>

      <button
        onClick={onShowSettings}
        className="mt-6 text-xs font-bold text-primary hover:underline flex items-center gap-1"
      >
        <span className="material-symbols-outlined text-lg">tune</span>
        Configure Preferences
      </button>
    </div>
  );
}
