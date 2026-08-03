'use client';

import * as React from 'react';
import { Bot, RefreshCw, ShieldCheck } from 'lucide-react';
import { AppLayout } from '@/components/common';
import { InlineError, describeError } from '@/components/common/inline-error';
import { Skeleton, EmptyState } from '@/components/ui';
import { ToneBadge } from '@/components/workflow';
import { CircuitBreakerList } from '@/components/resilience/circuit-breaker-list';
import { useAgents } from '@/hooks/use-agents';
import { useVerifyAgent } from '@/hooks/use-verify-agent';
import {
  agentLocalLoginInstructions,
  authenticationStatusLabel,
  authenticationStatusTone,
  connectionStatusLabel,
  connectionStatusTone,
  formatTimestamp,
  installationStatusLabel,
  installationStatusTone,
} from '@/lib/presentation';
import type { AgentAvailabilityRead } from '@/types/backend';

const CREDENTIAL_DISCLOSURE =
  'Keystone uses the provider CLI session already authenticated on the computer running the backend. Credentials never pass through the browser.';

function AgentCard({
  agent,
  verifying,
  verifyError,
  onVerify,
}: {
  agent: AgentAvailabilityRead;
  verifying: boolean;
  verifyError: string | undefined;
  onVerify: () => void;
}) {
  const loginInstructions =
    agent.authentication_status === 'unauthenticated'
      ? agentLocalLoginInstructions(agent.agent_type)
      : null;

  return (
    <div
      data-testid={`agent-card-${agent.agent_type}`}
      className="flex flex-col space-y-3 rounded-xl border border-white/[0.08] bg-white/[0.04] p-4"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600/20 text-blue-400">
            <Bot className="h-4 w-4" />
          </div>
          <h3 className="text-xs font-bold text-white">{agent.display_name}</h3>
        </div>
      </div>

      <div className="space-y-2 border-t border-white/[0.06] pt-2 text-[11px]">
        <div className="flex items-center justify-between">
          <span className="text-zinc-500">Installation</span>
          <ToneBadge tone={installationStatusTone(agent.installation_status)}>
            {installationStatusLabel(agent.installation_status)}
          </ToneBadge>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-zinc-500">Version</span>
          <span className="font-medium text-zinc-300">{agent.version ?? '—'}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-zinc-500">Registered</span>
          <ToneBadge tone={agent.registered ? 'success' : 'neutral'}>
            {agent.registered ? 'Yes' : 'No'}
          </ToneBadge>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-zinc-500">Authentication</span>
          <ToneBadge tone={authenticationStatusTone(agent.authentication_status)}>
            {authenticationStatusLabel(agent.authentication_status)}
          </ToneBadge>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-zinc-500">Connection</span>
          <ToneBadge tone={connectionStatusTone(agent.connection_status)}>
            {connectionStatusLabel(agent.connection_status)}
          </ToneBadge>
        </div>
        <div>
          <span className="block text-zinc-500">Execution mode</span>
          <span className="font-medium text-zinc-300">{agent.execution_mode}</span>
        </div>
        <div>
          <span className="block text-zinc-500">Last verified</span>
          <span className="font-medium text-zinc-300">
            {formatTimestamp(agent.last_checked_at)}
          </span>
        </div>
        <div>
          <span className="block text-zinc-500">Reason</span>
          <span className="font-medium text-zinc-300">{agent.reason}</span>
        </div>
        {agent.capabilities.length > 0 && (
          <div>
            <span className="block text-zinc-500">Capabilities</span>
            <span className="font-medium text-zinc-300">{agent.capabilities.join(', ')}</span>
          </div>
        )}
      </div>

      {loginInstructions && (
        <p className="rounded-lg border border-amber-500/20 bg-amber-950/10 p-2 text-[11px] leading-relaxed text-amber-300">
          {loginInstructions}
        </p>
      )}

      <button
        type="button"
        onClick={onVerify}
        disabled={verifying || !agent.enabled}
        aria-label={`Verify connection for ${agent.display_name}`}
        className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:bg-white/[0.08] hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
      >
        <ShieldCheck className="h-3.5 w-3.5" />
        <span>{verifying ? 'Verifying…' : 'Verify Connection'}</span>
      </button>

      <div aria-live="polite" className="min-h-[1rem] text-[11px]">
        {verifying && <span className="text-zinc-500">Running a safe headless verification…</span>}
        {!verifying && verifyError && <span className="text-rose-400">{verifyError}</span>}
      </div>
    </div>
  );
}

export default function AgentsPage() {
  const { data, loading, error, refresh } = useAgents();
  const { verifying, errors, verify } = useVerifyAgent(refresh);
  const items = data?.items ?? [];

  const agents = items.filter((agent) => agent.agent_type !== 'gemini');
  const geminiPlaceholder = items.find((agent) => agent.agent_type === 'gemini');

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
          {CREDENTIAL_DISCLOSURE}
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
              <AgentCard
                key={agent.agent_type}
                agent={agent}
                verifying={verifying.has(agent.agent_type)}
                verifyError={errors[agent.agent_type]}
                onVerify={() => void verify(agent.agent_type)}
              />
            ))}
          </div>
        )}

        {geminiPlaceholder && (
          <p className="rounded-lg border border-dashed border-white/[0.08] p-3 text-[11px] text-zinc-500">
            <span className="font-semibold text-zinc-400">Gemini CLI</span> is a separate, planned
            integration — not configured in this phase.
          </p>
        )}

        <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-4 text-[11px] leading-relaxed text-zinc-500">
          <p>
            <span className="font-semibold text-zinc-400">Installed</span> means the configured
            executable is present on the machine running the backend.{' '}
            <span className="font-semibold text-zinc-400">Registered</span> means the adapter is
            registered in the currently running backend process.{' '}
            <span className="font-semibold text-zinc-400">Connected</span> means a safe headless
            verification succeeded recently — installation or authentication status alone never
            implies a working connection.
          </p>
        </div>

        <CircuitBreakerList />
      </main>
    </AppLayout>
  );
}
