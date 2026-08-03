'use client';

import * as React from 'react';
import Link from 'next/link';
import { Search, Bell, ChevronDown, Check, Trash2, X } from 'lucide-react';
import { APP_CONFIG } from '@/lib/constants';
import { INITIAL_NOTIFICATIONS } from '@/lib/mock';
import { NotificationItem } from '@/types';
import { ThemeToggle } from './theme-toggle';

export const Header: React.FC = () => {
  const [notifications, setNotifications] =
    React.useState<NotificationItem[]>(INITIAL_NOTIFICATIONS);
  const [isOpen, setIsOpen] = React.useState(false);

  const unreadCount = notifications.filter((n) => !n.read).length;

  const handleMarkAllRead = () => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  };

  const handleClearAll = () => {
    setNotifications([]);
  };

  return (
    <header className="sticky top-0 z-50 flex h-16 w-full items-center justify-between border-b border-white/[0.08] bg-[#0B1120]/90 px-6 backdrop-blur-md transition-all">
      {/* Left Logo Section */}
      <div className="flex items-center gap-3">
        <Link href="/" className="flex items-center gap-3 transition-opacity hover:opacity-90">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 text-sm font-bold text-white shadow-sm">
            K
          </div>
          <span className="text-base font-bold tracking-tight text-white">{APP_CONFIG.name}</span>
        </Link>
      </div>

      {/* Center Search Input Placeholder */}
      <div className="hidden w-72 items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs text-zinc-400 transition-colors focus-within:border-white/20 md:flex lg:w-96">
        <Search className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
        <input
          type="text"
          placeholder="Search anything..."
          className="w-full bg-transparent text-xs text-white placeholder:text-zinc-500 focus:outline-none"
          readOnly
        />
        <kbd className="hidden items-center rounded border border-white/10 bg-white/5 px-1.5 text-[10px] font-medium text-zinc-400 sm:inline-flex">
          ⌘ K
        </kbd>
      </div>

      {/* Right Header Controls */}
      <div className="flex items-center gap-3">
        {/* Backend Connected Status Badge */}
        <div className="hidden items-center gap-2 rounded-full border border-white/[0.08] bg-white/[0.04] px-3 py-1 text-xs font-medium text-zinc-300 sm:flex">
          <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
          <span>Backend: Connected</span>
        </div>

        {/* Theme Toggle Button */}
        <ThemeToggle />

        {/* Notification Bell Dropdown */}
        <div className="relative">
          <button
            type="button"
            onClick={() => setIsOpen((prev) => !prev)}
            className="relative flex h-8 w-8 items-center justify-center rounded-lg border border-white/[0.08] bg-white/[0.04] text-zinc-400 transition-colors hover:bg-white/[0.08] hover:text-white"
            aria-label="Notifications"
          >
            <Bell className="h-4 w-4" />
            {unreadCount > 0 && (
              <span className="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-blue-600 text-[9px] font-bold text-white">
                {unreadCount}
              </span>
            )}
          </button>

          {/* Notifications Dropdown Panel */}
          {isOpen && (
            <div className="absolute top-11 right-0 z-50 w-80 space-y-3 rounded-xl border border-white/[0.08] bg-[#0B1120] p-4 shadow-2xl backdrop-blur-md">
              <div className="flex items-center justify-between border-b border-white/[0.08] pb-2">
                <div className="flex items-center gap-2">
                  <h4 className="text-xs font-bold text-white">Notifications</h4>
                  {unreadCount > 0 && (
                    <span className="rounded bg-blue-600/30 px-1.5 py-0.5 text-[10px] font-semibold text-blue-400">
                      {unreadCount} new
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => setIsOpen(false)}
                  className="text-zinc-500 hover:text-white"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>

              {/* Notification Items List */}
              <div className="max-h-64 space-y-2 overflow-y-auto text-xs">
                {notifications.length === 0 ? (
                  <p className="py-4 text-center text-xs text-zinc-500">No notifications.</p>
                ) : (
                  notifications.map((n) => (
                    <div
                      key={n.id}
                      className={`space-y-1 rounded-lg border p-2.5 transition-colors ${
                        n.read
                          ? 'border-white/[0.04] bg-white/[0.02] text-zinc-400'
                          : 'border-blue-500/20 bg-blue-950/20 font-medium text-white'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold">{n.title}</span>
                        <span className="text-[10px] text-zinc-500">{n.timestamp}</span>
                      </div>
                      <p className="text-[11px] text-zinc-400">{n.description}</p>
                    </div>
                  ))
                )}
              </div>

              {notifications.length > 0 && (
                <div className="flex items-center justify-between border-t border-white/[0.08] pt-2.5 text-[11px]">
                  <button
                    type="button"
                    onClick={handleMarkAllRead}
                    className="flex items-center gap-1 text-blue-400 hover:text-blue-300"
                  >
                    <Check className="h-3 w-3" />
                    <span>Mark all read</span>
                  </button>
                  <button
                    type="button"
                    onClick={handleClearAll}
                    className="flex items-center gap-1 text-zinc-500 hover:text-zinc-300"
                  >
                    <Trash2 className="h-3 w-3" />
                    <span>Clear all</span>
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* User Profile Dropdown */}
        <div className="flex cursor-pointer items-center gap-1.5 pl-1">
          <div className="flex h-7 w-7 items-center justify-center rounded-full border border-white/10 bg-zinc-800 text-xs font-semibold text-white">
            KS
          </div>
          <ChevronDown className="h-3.5 w-3.5 text-zinc-400" />
        </div>
      </div>
    </header>
  );
};
