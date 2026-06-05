'use client';

import { useState, useRef, useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { apiGet, apiPatch } from '@/lib/api-client';

interface Notification {
  id: string;
  ts: string;
  type: 'escalation' | 'completion' | 'info' | 'error';
  title: string;
  body: string;
  plan_name?: string;
  epic_ref?: string;
  read: boolean;
}

export default function NotificationBell() {
  const pathname = usePathname();
  const isFixtureRoute = pathname.includes('-fixture');
  const [isOpen, setIsOpen] = useState(false);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const fetchNotifications = async () => {
      try {
        const data = await apiGet<Notification[]>('/notifications');
        setNotifications(data);
      } catch (error) {
        console.debug('Notifications not available:', error);
      }
    };

    if (!isFixtureRoute) fetchNotifications();
  }, [isFixtureRoute]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const unreadCount = notifications.filter((n) => !n.read).length;

  const markAsRead = async (id: string) => {
    const notif = notifications.find(n => n.id === id);
    if (notif && notif.read) return;

    try {
      await apiPatch('/notifications', { id, read: true });
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, read: true } : n))
      );
    } catch (error) {
      console.error('Failed to mark notification as read', error);
    }
  };

  const getIcon = (type: string) => {
    switch (type) {
      case 'escalation':
        return 'warning';
      case 'completion':
        return 'check_circle';
      case 'info':
        return 'info';
      case 'error':
        return 'error';
      default:
        return 'notifications';
    }
  };

  const getIconColor = (type: string) => {
    switch (type) {
      case 'escalation':
        return 'var(--color-warning)';
      case 'completion':
        return 'var(--color-success)';
      case 'info':
        return 'var(--color-primary)';
      case 'error':
        return 'var(--color-danger)';
      default:
        return 'var(--color-text-muted)';
    }
  };

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="relative p-2 rounded-lg transition-colors hover:bg-surface-hover"
        style={{ color: 'var(--color-text-muted)' }}
        aria-label={`${unreadCount} unread notifications`}
        aria-expanded={isOpen}
        aria-haspopup="true"
      >
        <span className="material-symbols-outlined text-xl" aria-hidden="true">notifications</span>
        {unreadCount > 0 && (
          <span
            className="absolute top-1 right-1 w-4 h-4 rounded-full text-[9px] font-bold text-white flex items-center justify-center"
            style={{ background: 'var(--color-danger)' }}
          >
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <div
          className="absolute right-0 mt-2 w-[360px] max-h-[480px] overflow-hidden rounded-xl border border-border shadow-modal bg-surface z-[100] animate-in zoom-in-95 duration-200"
          style={{ 
            borderColor: 'var(--color-border)',
            background: 'var(--color-surface)',
            boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1)'
          }}
        >
          <div className="p-4 border-b flex items-center justify-between" style={{ borderColor: 'var(--color-border)' }}>
            <h3 className="text-sm font-bold" style={{ color: 'var(--color-text-main)' }}>Notifications</h3>
            <span className="text-[10px] font-medium px-1.5 py-0.5 rounded" style={{ background: 'var(--color-background)', color: 'var(--color-text-muted)' }}>
              {unreadCount} Unread
            </span>
          </div>

          <div className="overflow-y-auto max-h-[400px] custom-scrollbar">
            {notifications.length === 0 ? (
              <div className="p-8 text-center text-xs" style={{ color: 'var(--color-text-faint)' }}>
                No notifications yet.
              </div>
            ) : (
              notifications.map((notif) => (
                <div
                  key={notif.id}
                  onClick={() => markAsRead(notif.id)}
                  className={`p-4 border-b last:border-0 cursor-pointer transition-colors hover:bg-surface-hover flex gap-3 ${
                    !notif.read ? 'bg-primary-muted/10' : ''
                  }`}
                  style={{ borderColor: 'var(--color-border)' }}
                >
                  <span
                    className="material-symbols-outlined text-xl shrink-0"
                    style={{ color: getIconColor(notif.type) }}
                  >
                    {getIcon(notif.type)}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-xs font-bold truncate" style={{ color: 'var(--color-text-main)' }}>
                        {notif.title}
                      </p>
                      <span className="text-[10px] whitespace-nowrap" style={{ color: 'var(--color-text-faint)' }}>
                        {new Date(notif.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>
                    <p className="text-[11px] mt-0.5 line-clamp-2" style={{ color: 'var(--color-text-muted)' }}>
                      {notif.body}
                    </p>
                    {notif.plan_name && (
                      <div className="mt-2 flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--color-primary)' }} />
                        <span className="text-[10px] font-medium truncate" style={{ color: 'var(--color-primary)' }}>
                          {notif.plan_name}
                        </span>
                      </div>
                    )}
                  </div>
                  {!notif.read && (
                    <div className="w-2 h-2 rounded-full mt-1.5 shrink-0" style={{ background: 'var(--color-primary)' }} />
                  )}
                </div>
              ))
            )}
          </div>
          <div className="p-2 border-t text-center" style={{ borderColor: 'var(--color-border)' }}>
            <button className="text-[10px] font-bold hover:underline" style={{ color: 'var(--color-primary)' }}>
              View all notifications
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
