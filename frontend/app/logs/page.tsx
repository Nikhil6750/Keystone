'use client';

import * as React from 'react';
import { ShieldAlert, ShieldCheck, Terminal } from 'lucide-react';
import { AppLayout } from '@/components/common';
import { InlineError, describeError } from '@/components/common/inline-error';
import { Skeleton, EmptyState } from '@/components/ui';
import { ToneBadge } from '@/components/workflow';
import { useWorkflows } from '@/hooks/use-workflows';
import { useProvenance } from '@/hooks/use-provenance';
import { useAuditChainVerification } from '@/hooks/use-audit-chain-verification';
import { formatTimestamp } from '@/lib/presentation';

export default function LogsPage() {
  const { data: workflowsResponse, loading: workflowsLoading, error: workflowsError } =
    useWorkflows(100);
  const workflows = workflowsResponse?.items ?? [];
  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  const provenance = useProvenance(selectedId);
  const verification = useAuditChainVerification(selectedId);

  return (
    <AppLayout showSidebar={true}>
      <main className="flex flex-1 flex-col space-y-6 overflow-y-auto p-6 md:p-8">
        <div className="space-y-1">
          <span className="text-xs font-bold tracking-wider text-blue-400 uppercase">
            Logs &amp; Provenance
          </span>
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Audit Trail
          </h1>
          <p className="text-sm leading-relaxed text-zinc-400">
            A tamper-evident (not tamper-proof) hash-linked chain of every workflow, step, and
            compensation event. Select a workflow to inspect its ordered event timeline.
          </p>
        </div>

        {workflowsLoading && <Skeleton className="h-10 w-full max-w-md" />}
        {!workflowsLoading && workflowsError && (
          <InlineError message={describeError(workflowsError).body} />
        )}
        {!workflowsLoading && !workflowsError && workflows.length === 0 && (
          <EmptyState
            icon={<Terminal className="h-5 w-5" />}
            title="No workflows yet"
            description="Create and run a workflow to see its audit trail here."
          />
        )}
        {!workflowsLoading && !workflowsError && workflows.length > 0 && (
          <div className="max-w-md space-y-1.5">
            <label htmlFor="logs-workflow-select" className="block text-xs font-medium text-zinc-400">
              Select a workflow
            </label>
            <select
              id="logs-workflow-select"
              value={selectedId ?? ''}
              onChange={(e) => setSelectedId(e.target.value || null)}
              className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white focus:border-blue-500/50 focus:outline-none"
            >
              <option value="" className="bg-[#0B1120]">
                Select a workflow…
              </option>
              {workflows.map((wf) => (
                <option key={wf.id} value={wf.id} className="bg-[#0B1120]">
                  {wf.name} ({wf.status})
                </option>
              ))}
            </select>
          </div>
        )}

        {selectedId && (
          <div className="space-y-4">
            {!verification.loading && verification.data && (
              <div
                className={`flex items-start gap-3 rounded-xl border p-4 ${
                  verification.data.valid
                    ? 'border-emerald-500/30 bg-emerald-950/20'
                    : 'border-rose-500/30 bg-rose-950/20'
                }`}
                role="status"
              >
                {verification.data.valid ? (
                  <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-emerald-400" />
                ) : (
                  <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-rose-400" />
                )}
                <div className="space-y-1 text-xs">
                  <p className={verification.data.valid ? 'text-emerald-300' : 'text-rose-300'}>
                    {verification.data.valid
                      ? 'Tamper-evident audit chain valid'
                      : 'Audit chain invalid'}
                  </p>
                  <p className="text-zinc-400">
                    {verification.data.event_count} event(s) verified.
                    {!verification.data.valid && (
                      <>
                        {' '}
                        First invalid sequence:{' '}
                        <span className="font-semibold text-rose-300">
                          {verification.data.first_invalid_sequence ?? 'unknown'}
                        </span>
                        . Reason: {verification.data.reason ?? 'unspecified'}.
                      </>
                    )}
                  </p>
                  <p className="text-[10px] text-zinc-500">
                    Tamper-evident means alteration can be detected — it is not tamper-proof
                    (there is no external notarization or digital signature).
                  </p>
                </div>
              </div>
            )}

            {provenance.loading && (
              <div className="space-y-2">
                <Skeleton className="h-14 w-full" />
                <Skeleton className="h-14 w-full" />
                <Skeleton className="h-14 w-full" />
              </div>
            )}

            {!provenance.loading && provenance.error && (
              <InlineError message={describeError(provenance.error).body} />
            )}

            {!provenance.loading && provenance.data && (
              <div className="space-y-2">
                <h2 className="text-xs font-bold tracking-wider text-zinc-400 uppercase">
                  Event timeline ({provenance.data.events.length})
                </h2>
                {provenance.data.events.map((event) => (
                  <div
                    key={event.id}
                    className="space-y-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] p-3 text-[11px]"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-semibold text-white">
                        #{event.sequence_number} — {event.event_type}
                      </span>
                      <ToneBadge tone="neutral">{event.actor_type}</ToneBadge>
                    </div>
                    <div className="grid gap-x-3 gap-y-0.5 text-zinc-400 sm:grid-cols-2">
                      <span>
                        Actor: <span className="text-zinc-300">{event.actor_id}</span>
                      </span>
                      <span>
                        Time: <span className="text-zinc-300">{formatTimestamp(event.created_at)}</span>
                      </span>
                      {event.step_id && (
                        <span className="truncate">
                          Step: <span className="text-zinc-300">{event.step_id}</span>
                        </span>
                      )}
                      {event.execution_attempt_id && (
                        <span className="truncate">
                          Execution attempt:{' '}
                          <span className="text-zinc-300">{event.execution_attempt_id}</span>
                        </span>
                      )}
                      {event.compensation_attempt_id && (
                        <span className="truncate">
                          Compensation attempt:{' '}
                          <span className="text-zinc-300">{event.compensation_attempt_id}</span>
                        </span>
                      )}
                    </div>
                    <details className="text-zinc-500">
                      <summary className="cursor-pointer select-none text-[10px] tracking-wider text-zinc-500 uppercase">
                        Payload &amp; hashes
                      </summary>
                      <div className="mt-1 space-y-1">
                        <pre className="overflow-x-auto rounded bg-black/30 p-2 text-[10px] break-words whitespace-pre-wrap">
                          {JSON.stringify(event.payload, null, 2)}
                        </pre>
                        <p className="truncate font-mono text-[10px]">
                          previous_hash: {event.previous_hash}
                        </p>
                        <p className="truncate font-mono text-[10px]">
                          event_hash: {event.event_hash}
                        </p>
                      </div>
                    </details>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </main>
    </AppLayout>
  );
}
