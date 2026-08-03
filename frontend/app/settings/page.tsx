'use client';

import * as React from 'react';
import { useTheme } from 'next-themes';
import { Info, Monitor, Moon, Sun } from 'lucide-react';
import { AppLayout } from '@/components/common';
import { InlineError, describeError } from '@/components/common/inline-error';
import { ToneBadge } from '@/components/workflow';
import { useBackendHealth } from '@/hooks/use-backend-health';
import { useAgents } from '@/hooks/use-agents';
import { APP_CONFIG } from '@/lib/constants';

const THEME_OPTIONS = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
] as const;

export default function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);
  const health = useBackendHealth();
  const agents = useAgents();

  React.useEffect(() => setMounted(true), []);

  const demoAgent = agents.data?.items.find((a) => a.agent_type === 'demo');
  const registeredCount = agents.data?.items.filter((a) => a.registered).length ?? 0;

  return (
    <AppLayout showSidebar={true}>
      <main className="flex flex-1 flex-col space-y-6 overflow-y-auto p-6 md:p-8">
        <div className="space-y-1">
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">Settings</h1>
          <p className="text-sm leading-relaxed text-zinc-400">
            This prototype is single-user and local-only — there is no multi-user workspace,
            login, or account system.
          </p>
        </div>

        <div className="space-y-4 rounded-xl border border-white/[0.08] bg-white/[0.04] p-5">
          <div>
            <h3 className="text-xs font-bold text-white">System</h3>
            <p className="text-[11px] text-zinc-400">Frontend and backend status.</p>
          </div>
          <div className="grid gap-4 text-xs sm:grid-cols-2">
            <div className="space-y-1">
              <span className="block text-zinc-500">Frontend version</span>
              <span className="font-medium text-zinc-300">{APP_CONFIG.version}</span>
            </div>
            <div className="space-y-1">
              <span className="block text-zinc-500">Prototype phase</span>
              <span className="font-medium text-zinc-300">{APP_CONFIG.prototypePhase}</span>
            </div>
            <div className="space-y-1">
              <span className="block text-zinc-500">Backend API URL</span>
              <span className="font-mono text-[11px] font-medium text-zinc-300">
                {APP_CONFIG.apiBaseUrl}
              </span>
            </div>
            <div className="space-y-1">
              <span className="block text-zinc-500">Backend health</span>
              {health.loading ? (
                <span className="text-zinc-400">Checking…</span>
              ) : health.error ? (
                <ToneBadge tone="error">Unreachable</ToneBadge>
              ) : (
                <ToneBadge tone="success">{health.data?.status ?? 'unknown'}</ToneBadge>
              )}
            </div>
            <div className="space-y-1">
              <span className="block text-zinc-500">Demo agent</span>
              {agents.loading ? (
                <span className="text-zinc-400">Checking…</span>
              ) : demoAgent?.registered ? (
                <ToneBadge tone="success">Registered</ToneBadge>
              ) : (
                <ToneBadge tone="neutral">Not registered</ToneBadge>
              )}
            </div>
            <div className="space-y-1">
              <span className="block text-zinc-500">Registered agents</span>
              <span className="font-medium text-zinc-300">
                {agents.loading ? '…' : registeredCount}
              </span>
            </div>
          </div>
          {health.error && (
            <InlineError message={describeError(health.error).body} onRetry={health.refresh} />
          )}
        </div>

        <div className="space-y-4 rounded-xl border border-white/[0.08] bg-white/[0.04] p-5">
          <div>
            <h3 className="text-xs font-bold text-white">Appearance</h3>
            <p className="text-[11px] text-zinc-400">Choose a color theme.</p>
          </div>
          <div className="flex gap-2" role="radiogroup" aria-label="Theme">
            {THEME_OPTIONS.map((option) => {
              const Icon = option.icon;
              const isActive = mounted && theme === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  aria-checked={isActive}
                  onClick={() => setTheme(option.value)}
                  className={`flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${
                    isActive
                      ? 'border-blue-500/40 bg-blue-950/40 text-white'
                      : 'border-white/[0.08] bg-white/[0.04] text-zinc-400 hover:text-white'
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  <span>{option.label}</span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex items-start gap-2 rounded-lg border border-white/[0.08] bg-white/[0.03] p-3 text-xs text-zinc-400">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <p>
            Provider CLI credentials (Claude Code, Codex, Gemini) live only on the machine
            running the backend and are never entered, stored, or displayed here. Additional
            configuration surfaces (model parameters, API keys, integrations) are planned but not
            implemented in this prototype.
          </p>
        </div>
      </main>
    </AppLayout>
  );
}
