'use client';

import * as React from 'react';
import { GitFork, RefreshCw, X } from 'lucide-react';
import { AppLayout } from '@/components/common';
import { InlineError, describeError } from '@/components/common/inline-error';
import { Skeleton, EmptyState } from '@/components/ui';
import { ExecutionPanel, ToneBadge } from '@/components/workflow';
import { useWorkflows } from '@/hooks/use-workflows';
import { executeWorkflow, compensateWorkflow } from '@/services/workflows';
import { formatTimestamp, workflowStatusLabel, workflowStatusTone } from '@/lib/presentation';
import type { WorkflowRead } from '@/types/backend';

export default function WorkflowsPage() {
  const { data, loading, error, refresh } = useWorkflows(100);
  const [selected, setSelected] = React.useState<WorkflowRead | null>(null);
  const [executing, setExecuting] = React.useState(false);
  const [compensating, setCompensating] = React.useState(false);
  const [actionError, setActionError] = React.useState<string | null>(null);

  const workflows = data?.items ?? [];

  const applyUpdate = (updated: WorkflowRead) => {
    setSelected(updated);
    refresh();
  };

  const handleExecute = async () => {
    if (!selected) return;
    setExecuting(true);
    setActionError(null);
    try {
      applyUpdate(await executeWorkflow(selected.id));
    } catch (err) {
      setActionError(describeError(err).body);
    } finally {
      setExecuting(false);
    }
  };

  const handleCompensate = async () => {
    if (!selected) return;
    setCompensating(true);
    setActionError(null);
    try {
      applyUpdate(await compensateWorkflow(selected.id));
    } catch (err) {
      setActionError(describeError(err).body);
    } finally {
      setCompensating(false);
    }
  };

  return (
    <AppLayout showSidebar={true}>
      <main className="flex flex-1 flex-col space-y-6 overflow-y-auto p-6 md:p-8">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div className="space-y-1">
            <span className="text-xs font-bold tracking-wider text-blue-400 uppercase">
              Workflows
            </span>
            <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">Workflows</h1>
            <p className="text-sm leading-relaxed text-zinc-400">
              Real workflows persisted by the Keystone backend. Create new ones from{' '}
              <span className="font-medium text-zinc-300">New Workflow</span>.
            </p>
          </div>
          <button
            type="button"
            onClick={refresh}
            className="inline-flex items-center gap-1.5 self-start rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-zinc-300 hover:bg-white/[0.08] hover:text-white sm:self-auto"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span>Refresh</span>
          </button>
        </div>

        {loading && (
          <div className="space-y-3">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        )}

        {!loading && error && <InlineError message={describeError(error).body} onRetry={refresh} />}

        {!loading && !error && workflows.length === 0 && (
          <EmptyState
            icon={<GitFork className="h-5 w-5" />}
            title="No workflows yet"
            description="Create your first workflow from New Workflow in the sidebar."
          />
        )}

        {!loading && !error && workflows.length > 0 && (
          <div className="overflow-hidden rounded-xl border border-white/[0.08] bg-white/[0.04]">
            <div className="grid grid-cols-6 gap-4 border-b border-white/[0.08] bg-white/[0.02] px-6 py-3.5 text-xs font-semibold text-zinc-400">
              <div className="col-span-2">Name</div>
              <div>Status</div>
              <div>Steps</div>
              <div>Created</div>
              <div>Version</div>
            </div>
            <div className="divide-y divide-white/[0.04] text-xs">
              {workflows.map((wf) => (
                <button
                  key={wf.id}
                  type="button"
                  onClick={() => setSelected(wf)}
                  className="grid w-full grid-cols-6 items-center gap-4 px-6 py-3.5 text-left text-zinc-300 hover:bg-white/[0.02]"
                >
                  <div className="col-span-2 truncate font-semibold text-white">{wf.name}</div>
                  <div>
                    <ToneBadge tone={workflowStatusTone(wf.status)}>
                      {workflowStatusLabel(wf.status)}
                    </ToneBadge>
                  </div>
                  <div>{wf.steps.length}</div>
                  <div className="text-zinc-500">{formatTimestamp(wf.created_at)}</div>
                  <div>{wf.version}</div>
                </button>
              ))}
            </div>
          </div>
        )}
      </main>

      {selected && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-end bg-black/60 backdrop-blur-sm"
          role="presentation"
          onClick={() => setSelected(null)}
        >
          <div
            className="h-full w-full max-w-lg overflow-y-auto border-l border-white/[0.08] bg-[#0B1120] p-6 shadow-2xl"
            role="dialog"
            aria-modal="true"
            aria-label={`Workflow details for ${selected.name}`}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex justify-end">
              <button
                type="button"
                onClick={() => setSelected(null)}
                aria-label="Close workflow details"
                className="text-zinc-400 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            {actionError && (
              <div className="mb-4">
                <InlineError message={actionError} />
              </div>
            )}
            <ExecutionPanel
              workflow={selected}
              onExecute={handleExecute}
              onCompensate={handleCompensate}
              executing={executing}
              compensating={compensating}
            />
          </div>
        </div>
      )}
    </AppLayout>
  );
}
