'use client';

import * as React from 'react';
import { Bot, RefreshCw } from 'lucide-react';
import { AppLayout } from '@/components/common';
import { InlineError, describeError } from '@/components/common/inline-error';
import { Skeleton, EmptyState } from '@/components/ui';
import { ToneBadge } from '@/components/workflow';
import { CircuitBreakerList } from '@/components/resilience/circuit-breaker-list';
import { useAgents } from '@/hooks/use-agents';
import type { AgentAvailabilityRead } from '@/types/backend';

function agentTone(agent: AgentAvailabilityRead): 'success' | 'warning' | 'neutral' {
  if (agent.enabled && agent.registered && agent.available) return 'success';
  if (agent.enabled) return 'warning';
  return 'neutral';
}

export default function AgentsPage() {
  const { data, loading, error, refresh } = useAgents();
  const agents = data?.items ?? [];

  return (
    <AppLayout showSidebar={true}>
      <main className="flex flex-1 flex-col space-y-8 overflow-y-auto p-6 md:p-8">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div className="space-y-1">
            <span className="text-xs font-bold tracking-wider text-blue-400 uppercase">Agents</span>
            <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">AI Agents</h1>
            <p className="text-sm leading-relaxed text-zinc-400">
              The canonical agent types the Keystone backend can execute workflow steps with.
            </p>
          </div>
          <button
            type="button"
            onClick={refresh}
            className="inline-flex shrink-0 items-center gap-1.5 self-start rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-zinc-300 hover:bg-white/[0.08] hover:text-white sm:self-auto"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span>Refresh</span>
          </button>
        </div>

        <p className="rounded-lg border border-white/[0.08] bg-white/[0.03] p-3 text-xs leading-relaxed text-zinc-400">
          Provider CLIs must be installed and logged in locally on the computer running the
          Keystone backend. This page never collects an email, password, one-time code, or API
          key — the browser cannot authenticate a provider on your behalf.
        </p>

        {loading && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Skeleton className="h-40 w-full" />
            <Skeleton className="h-40 w-full" />
            <Skeleton className="h-40 w-full" />
            <Skeleton className="h-40 w-full" />
          </div>
        )}

        {!loading && error && <InlineError message={describeError(error).body} onRetry={refresh} />}

        {!loading && !error && agents.length === 0 && (
          <EmptyState
            icon={<Bot className="h-5 w-5" />}
            title="No agent information available"
            description="The backend returned no agent types."
          />
        )}

        {!loading && !error && agents.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {agents.map((agent) => (
              <div
                key={agent.agent_type}
                className="flex flex-col space-y-3 rounded-xl border border-white/[0.08] bg-white/[0.04] p-4"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600/20 text-blue-400">
                      <Bot className="h-4 w-4" />
                    </div>
                    <h3 className="text-xs font-bold text-white">{agent.agent_type}</h3>
                  </div>
                </div>

                <div className="space-y-2 border-t border-white/[0.06] pt-2 text-[11px]">
                  <div className="flex items-center justify-between">
                    <span className="text-zinc-500">Enabled</span>
                    <ToneBadge tone={agent.enabled ? 'success' : 'neutral'}>
                      {agent.enabled ? 'Yes' : 'No'}
                    </ToneBadge>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-zinc-500">Available</span>
                    <ToneBadge tone={agent.available ? 'success' : 'neutral'}>
                      {agent.available ? 'Yes' : 'No'}
                    </ToneBadge>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-zinc-500">Registered</span>
                    <ToneBadge tone={agent.registered ? 'success' : 'neutral'}>
                      {agent.registered ? 'Yes' : 'No'}
                    </ToneBadge>
                  </div>
                  <div>
                    <span className="block text-zinc-500">Execution mode</span>
                    <span className="font-medium text-zinc-300">{agent.execution_mode}</span>
                  </div>
                  <div>
                    <span className="block text-zinc-500">Reason</span>
                    <span className="font-medium text-zinc-300">{agent.reason}</span>
                  </div>
                </div>
                <ToneBadge tone={agentTone(agent)} className="self-start">
                  {agentTone(agent) === 'success'
                    ? 'Ready to execute'
                    : agentTone(agent) === 'warning'
                      ? 'Enabled but not ready'
                      : 'Disabled'}
                </ToneBadge>
              </div>
            ))}
          </div>
        )}

        <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-4 text-[11px] leading-relaxed text-zinc-500">
          <p>
            <span className="font-semibold text-zinc-400">Available</span> means the configured
            executable is present on the machine running the backend.{' '}
            <span className="font-semibold text-zinc-400">Registered</span> means the adapter is
            registered in the currently running backend process. Neither implies authentication
            has been verified — only an actual execution proves that.
          </p>
        </div>

        <CircuitBreakerList />
      </main>
    </AppLayout>
  );
}
