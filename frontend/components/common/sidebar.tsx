'use client';

import * as React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  MessageSquare,
  GitFork,
  Bot,
  Terminal,
  Settings,
  Plus,
  ChevronsUpDown,
  Sparkles,
} from 'lucide-react';

const NAV_ITEMS = [
  { label: 'Chat', href: '/chat', icon: MessageSquare },
  { label: 'Workflows', href: '/chat', icon: GitFork },
  { label: 'Agents', href: '/chat', icon: Bot },
  { label: 'Logs', href: '/chat', icon: Terminal },
  { label: 'Settings', href: '/chat', icon: Settings },
];

export const Sidebar: React.FC = () => {
  const pathname = usePathname();

  return (
    <aside className="hidden min-h-[calc(100vh-64px)] w-[280px] shrink-0 flex-col justify-between border-r border-white/[0.08] bg-[#0B1120]/80 p-4 md:flex">
      <div className="space-y-6">
        {/* PROJECT SECTION */}
        <div className="space-y-3">
          <span className="text-[11px] font-bold tracking-wider text-zinc-500 uppercase">
            PROJECT
          </span>
          <div className="flex items-center justify-between">
            <span className="text-sm font-bold text-white">Keystone</span>
            <ChevronsUpDown className="h-3.5 w-3.5 cursor-pointer text-zinc-500 hover:text-zinc-300" />
          </div>

          {/* + New Workflow Primary Button */}
          <button
            type="button"
            className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white shadow-sm transition-colors hover:bg-blue-500"
          >
            <Plus className="h-4 w-4" />
            <span>New Workflow</span>
          </button>
        </div>

        {/* NAVIGATION SECTION */}
        <div className="space-y-2">
          <span className="text-[11px] font-bold tracking-wider text-zinc-500 uppercase">
            NAVIGATION
          </span>

          <nav className="space-y-1">
            {NAV_ITEMS.map((item) => {
              const IconComponent = item.icon;
              const isActive =
                pathname === item.href || (item.label === 'Chat' && pathname === '/chat');

              return (
                <Link
                  key={item.label}
                  href={item.href}
                  className={`flex items-center gap-3 rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
                    isActive
                      ? 'border border-blue-500/30 bg-blue-950/40 font-semibold text-white shadow-sm'
                      : 'text-zinc-400 hover:bg-white/[0.04] hover:text-white'
                  }`}
                >
                  <IconComponent
                    className={`h-4 w-4 ${isActive ? 'text-blue-400' : 'text-zinc-400'}`}
                  />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>
        </div>
      </div>

      {/* Bottom Feature Box */}
      <div className="space-y-2 rounded-xl border border-white/[0.08] bg-white/[0.03] p-4">
        <Sparkles className="h-4 w-4 text-blue-400" />
        <p className="text-xs leading-relaxed text-zinc-400">
          Keystone orchestrates multiple AI agents to deliver reliable engineering outcomes.
        </p>
      </div>
    </aside>
  );
};
