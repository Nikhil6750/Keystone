'use client';

import * as React from 'react';
import { CheckCircle2, Info, Loader2, Sparkles, XCircle } from 'lucide-react';
import { AppLayout } from '@/components/common';
import { InlineError, describeError } from '@/components/common/inline-error';
import { ToneBadge } from '@/components/workflow';
import { Skeleton, EmptyState } from '@/components/ui';
import { useAgents } from '@/hooks/use-agents';
import { useOrchestrationPolling } from '@/hooks/use-orchestration-polling';
import { createOrchestrationExecution } from '@/services/orchestrations';
import { getQualityRunGates } from '@/services/quality';
import { getAgentReliability } from '@/services/intelligence';
import { canSelectAgentForStep, formatTimestamp } from '@/lib/presentation';
import {
  orchestrationJobStatusLabel,
  orchestrationJobStatusTone,
  orchestrationOutcomeLabel,
  orchestrationOutcomeTone,
  qualityGateStatusLabel,
  qualityGateStatusTone,
  qualityVerdictStatusLabel,
  qualityVerdictStatusTone,
} from '@/lib/presentation';
import type {
  AgentReliabilityRead,
  QualityGateResultRead,
  QualityVerdictStatus,
} from '@/types/backend';

const GOAL_MAX_LENGTH = 4000;

type PipelineStageStatus = 'pending' | 'active' | 'done' | 'error';

function PipelineStage({
  label,
  status,
  detail,
}: {
  label: string;
  status: PipelineStageStatus;
  detail?: string;
}) {
  const icon =
    status === 'done' ? (
      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
    ) : status === 'error' ? (
      <XCircle className="h-3.5 w-3.5 text-rose-400" />
    ) : status === 'active' ? (
      <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-400" />
    ) : (
      <span className="h-3.5 w-3.5 rounded-full border border-white/[0.15]" />
    );
  return (
    <div className="flex items-start gap-2.5">
      {icon}
      <div className="flex-1">
        <p
          className={`text-xs font-medium ${status === 'pending' ? 'text-zinc-500' : 'text-white'}`}
        >
          {label}
        </p>
        {detail && <p className="text-[11px] text-zinc-400">{detail}</p>}
      </div>
    </div>
  );
}

function QualityPanel({ runId }: { runId: string }) {
  const [gates, setGates] = React.useState<QualityGateResultRead[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    const controller = new AbortController();
    getQualityRunGates(runId, { signal: controller.signal })
      .then((result) => setGates(result))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(describeApiErrorSafe(err));
      });
    return () => controller.abort();
  }, [runId]);

  if (error) return <InlineError message={error} />;
  if (gates === null) return <Skeleton className="h-24 w-full" />;
  if (gates.length === 0) {
    return <p className="text-[11px] text-zinc-500">No individual gate results recorded.</p>;
  }

  return (
    <ul className="space-y-1.5">
      {gates.map((gate) => (
        <li
          key={gate.gate_id}
          className="flex items-center justify-between gap-2 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2"
        >
          <div className="min-w-0">
            <p className="truncate text-[11px] font-medium text-zinc-200">{gate.name}</p>
            <p className="text-[10px] text-zinc-500">
              {gate.gate_type} · {gate.required ? 'required' : 'advisory'}
            </p>
          </div>
          <ToneBadge tone={qualityGateStatusTone(gate.status)}>
            {qualityGateStatusLabel(gate.status)}
          </ToneBadge>
        </li>
      ))}
    </ul>
  );
}

function IntelligencePanel({ agentType }: { agentType: string }) {
  const [reliability, setReliability] = React.useState<AgentReliabilityRead | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    const controller = new AbortController();
    getAgentReliability(agentType, { signal: controller.signal })
      .then((result) => setReliability(result))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(describeApiErrorSafe(err));
      });
    return () => controller.abort();
  }, [agentType]);

  if (error) return <InlineError message={error} />;
  if (reliability === null) return <Skeleton className="h-20 w-full" />;

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Executions" value={reliability.observed_executions} />
        <Stat label="Successful" value={reliability.successful_executions} />
        <Stat label="Quality-verified" value={reliability.quality_verified_successes} />
        <Stat label="Recoveries" value={reliability.recovery_count} />
      </div>
      {reliability.sample_size_is_low && (
        <p className="rounded-lg border border-amber-500/20 bg-amber-950/10 p-2 text-[11px] text-amber-300">
          Sample size is small — not enough observed executions yet to treat this as a strong
          reliability signal.
        </p>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-2.5 text-center">
      <p className="text-lg font-bold text-white">{value}</p>
      <p className="text-[10px] text-zinc-500">{label}</p>
    </div>
  );
}

// Local helper so the two small panels above don't need to import
// `describeError` (which is typed for the full `{title, body}` shape used
// at the page level) just to get a plain string.
function describeApiErrorSafe(error: unknown): string {
  return describeError(error).body;
}

export default function OrchestratePage() {
  const agents = useAgents();
  const [goal, setGoal] = React.useState('');
  const [selectedAgentTypes, setSelectedAgentTypes] = React.useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = React.useState(false);
  const [submitError, setSubmitError] = React.useState<string | null>(null);
  const [executionId, setExecutionId] = React.useState<string | null>(null);

  const { data: execution, error: pollError } = useOrchestrationPolling(executionId);

  const availableAgents = (agents.data?.items ?? []).filter(canSelectAgentForStep);

  const toggleAgent = (agentType: string) => {
    setSelectedAgentTypes((prev) => {
      const next = new Set(prev);
      if (next.has(agentType)) next.delete(agentType);
      else next.add(agentType);
      return next;
    });
  };

  const canSubmit = goal.trim().length > 0 && selectedAgentTypes.size > 0 && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setSubmitError(null);
    setExecutionId(null);
    try {
      const accepted = await createOrchestrationExecution({
        goal: goal.trim(),
        available_agent_types: Array.from(selectedAgentTypes),
      });
      setExecutionId(accepted.execution_id);
    } catch (error) {
      setSubmitError(describeError(error).body);
    } finally {
      setSubmitting(false);
    }
  };

  const startOver = () => {
    setExecutionId(null);
    setGoal('');
    setSubmitError(null);
  };

  const isRunning = execution ? !['completed', 'failed', 'cancelled'].includes(execution.job_status) : false;
  const planningDone = Boolean(execution?.task_count);
  const agentDone = Boolean(execution?.selected_agent_types?.length);
  const executionDone = Boolean(execution?.workflow_id);
  const qualityReached = Boolean(execution?.quality_run_id);
  const terminal = execution ? ['completed', 'failed', 'cancelled'].includes(execution.job_status) : false;

  return (
    <AppLayout showSidebar={true}>
      <main className="flex flex-1 flex-col overflow-y-auto p-6 md:p-8">
        <div className="space-y-2">
          <span className="text-xs font-bold tracking-wider text-blue-400 uppercase">
            Automatic Orchestration
          </span>
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Describe a goal — Keystone plans, selects an agent, executes, and verifies it.
          </h1>
          <p className="flex items-start gap-2 rounded-lg border border-blue-900/30 bg-blue-950/20 p-3 text-xs text-blue-300">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              This runs the full pipeline: task planning, agent selection, execution, recovery if
              needed, Software Quality Factory verification, and Engineering Intelligence
              projection. For a manual, step-by-step workflow instead, use{' '}
              <a href="/chat" className="underline hover:text-blue-200">
                Chat
              </a>
              .
            </span>
          </p>
        </div>

        {!executionId && (
          <div className="mt-8 max-w-2xl space-y-6">
            <div className="space-y-2">
              <label htmlFor="orchestrate-goal" className="block text-xs font-medium text-zinc-400">
                Goal
              </label>
              <textarea
                id="orchestrate-goal"
                value={goal}
                onChange={(e) => setGoal(e.target.value.slice(0, GOAL_MAX_LENGTH))}
                rows={4}
                placeholder="e.g. Implement a REST endpoint that returns the current server time, with tests"
                className="w-full resize-none rounded-xl border border-white/[0.08] bg-white/[0.04] p-4 text-sm text-white placeholder:text-zinc-500 focus:border-blue-500/50 focus:outline-none"
              />
            </div>

            <div className="space-y-2">
              <span className="block text-xs font-medium text-zinc-400">
                Available agents (select at least one)
              </span>
              {agents.loading && <Skeleton className="h-16 w-full" />}
              {!agents.loading && agents.error && (
                <InlineError message={describeError(agents.error).body} onRetry={agents.refresh} />
              )}
              {!agents.loading && !agents.error && availableAgents.length === 0 && (
                <EmptyState
                  icon={<Sparkles className="h-5 w-5" />}
                  title="No connected agents"
                  description="Connect and verify an agent on the Agents page before running an automatic orchestration."
                />
              )}
              {!agents.loading && availableAgents.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {availableAgents.map((agent) => {
                    const active = selectedAgentTypes.has(agent.agent_type);
                    return (
                      <button
                        key={agent.agent_type}
                        type="button"
                        onClick={() => toggleAgent(agent.agent_type)}
                        aria-pressed={active}
                        className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                          active
                            ? 'border-blue-500/40 bg-blue-950/40 text-white'
                            : 'border-white/[0.08] bg-white/[0.04] text-zinc-400 hover:text-white'
                        }`}
                      >
                        {agent.display_name}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {submitError && <InlineError message={submitError} />}

            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={!canSubmit}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white shadow-sm transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Sparkles className="h-3.5 w-3.5" />
              <span>{submitting ? 'Starting…' : 'Run orchestration'}</span>
            </button>
          </div>
        )}

        {executionId && (
          <div className="mt-8 max-w-3xl space-y-5">
            {pollError && <InlineError message={pollError} />}

            <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-5">
              <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
                <h2 className="text-sm font-bold text-white">Execution {executionId.slice(0, 8)}</h2>
                {execution ? (
                  <ToneBadge tone={orchestrationJobStatusTone(execution.job_status)}>
                    {orchestrationJobStatusLabel(execution.job_status)}
                  </ToneBadge>
                ) : (
                  <ToneBadge tone="neutral">Loading…</ToneBadge>
                )}
              </div>

              <div className="space-y-3 py-4">
                <PipelineStage
                  label="Planning (Task Graph)"
                  status={planningDone ? 'done' : isRunning ? 'active' : 'pending'}
                  detail={execution?.task_count ? `${execution.task_count} task(s) compiled` : undefined}
                />
                <PipelineStage
                  label="Agent Organization"
                  status={agentDone ? 'done' : planningDone ? 'active' : 'pending'}
                  detail={
                    execution?.selected_agent_types?.length
                      ? execution.selected_agent_types.join(', ')
                      : undefined
                  }
                />
                <PipelineStage
                  label="Execution"
                  status={executionDone ? 'done' : agentDone ? 'active' : 'pending'}
                  detail={
                    execution?.attempt_count
                      ? `${execution.attempt_count} attempt(s)${execution.recovery_used ? ' · recovery used' : ''}`
                      : undefined
                  }
                />
                <PipelineStage
                  label="Software Quality Factory"
                  status={
                    qualityReached
                      ? execution?.quality_verdict_status === 'ACCEPTED'
                        ? 'done'
                        : 'error'
                      : executionDone
                        ? 'active'
                        : 'pending'
                  }
                  detail={
                    execution?.quality_verdict_status
                      ? qualityVerdictStatusLabel(
                          execution.quality_verdict_status as QualityVerdictStatus
                        )
                      : undefined
                  }
                />
                <PipelineStage
                  label="Outcome"
                  status={
                    !terminal
                      ? 'pending'
                      : execution?.orchestration_outcome === 'verified_success'
                        ? 'done'
                        : 'error'
                  }
                  detail={
                    execution?.orchestration_outcome
                      ? orchestrationOutcomeLabel(execution.orchestration_outcome)
                      : undefined
                  }
                />
              </div>

              {execution && terminal && (
                <div className="space-y-2 border-t border-white/[0.06] pt-3">
                  <ToneBadge tone={orchestrationOutcomeTone(execution.orchestration_outcome ?? 'runtime_failure')}>
                    {execution.orchestration_outcome
                      ? orchestrationOutcomeLabel(execution.orchestration_outcome)
                      : 'Unknown outcome'}
                  </ToneBadge>
                  {execution.error_summary && (
                    <p className="rounded-md border border-rose-900/40 bg-rose-950/20 p-2 text-[11px] text-rose-300">
                      {execution.error_summary}
                    </p>
                  )}
                  {execution.issue_codes.length > 0 && (
                    <p className="text-[11px] text-zinc-500">
                      Issues: {execution.issue_codes.join(', ')}
                    </p>
                  )}
                  <p className="text-[11px] text-zinc-500">
                    Completed: {formatTimestamp(execution.updated_at)}
                  </p>
                </div>
              )}
            </div>

            {execution?.quality_run_id && (
              <div className="space-y-3 rounded-xl border border-white/[0.08] bg-white/[0.03] p-5">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-bold text-white">Quality verdict</h3>
                  {execution.quality_verdict_status && (
                    <ToneBadge
                      tone={qualityVerdictStatusTone(
                        execution.quality_verdict_status as QualityVerdictStatus
                      )}
                    >
                      {qualityVerdictStatusLabel(
                        execution.quality_verdict_status as QualityVerdictStatus
                      )}
                    </ToneBadge>
                  )}
                </div>
                <QualityPanel runId={execution.quality_run_id} />
              </div>
            )}

            {execution?.selected_agent_types?.[0] && terminal && (
              <div className="space-y-3 rounded-xl border border-white/[0.08] bg-white/[0.03] p-5">
                <h3 className="text-xs font-bold text-white">
                  Engineering intelligence — {execution.selected_agent_types[0]}
                </h3>
                <IntelligencePanel agentType={execution.selected_agent_types[0]} />
              </div>
            )}

            <button
              type="button"
              onClick={startOver}
              className="rounded-lg border border-white/[0.08] bg-white/[0.04] px-4 py-2 text-xs text-zinc-300 hover:bg-white/[0.08]"
            >
              Start another orchestration
            </button>
          </div>
        )}
      </main>
    </AppLayout>
  );
}
