'use client';

import * as React from 'react';
import Link from 'next/link';
import { Search, Bell, ChevronDown } from 'lucide-react';
import { APP_CONFIG } from '@/lib/constants';
import { ThemeToggle } from './theme-toggle';

export const Header: React.FC = () => {
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

        {/* Notification Bell */}
        <button
          type="button"
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/[0.08] bg-white/[0.04] text-zinc-400 transition-colors hover:bg-white/[0.08] hover:text-white"
          aria-label="Notifications"
        >
          <Bell className="h-4 w-4" />
        </button>

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
