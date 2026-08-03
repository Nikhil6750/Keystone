'use client';

import * as React from 'react';
import { Clock, Play, Undo2 } from 'lucide-react';
import type { WorkflowRead, WorkflowStepRead } from '@/types/backend';
import {
  attemptStatusLabel,
  canCompensateWorkflow,
  compensationAttemptStatusLabel,
  formatTimestamp,
  isWorkflowExecutable,
  stepStatusLabel,
  stepStatusTone,
  workflowStatusLabel,
  workflowStatusTone,
} from '@/lib/presentation';
import { useAuditChainVerification } from '@/hooks/use-audit-chain-verification';
import { ToneBadge } from './tone-badge';
import { CompensateDialog } from './compensate-dialog';

export interface ExecutionPanelProps {
  workflow: WorkflowRead;
  onExecute: () => void;
  onCompensate: () => void;
  executing: boolean;
  compensating: boolean;
}

function StepCard({ step }: { step: WorkflowStepRead }) {
  return (
    <div className="space-y-2 rounded-lg border border-white/[0.08] bg-white/[0.03] p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-white">
          {step.position}. {step.name}
        </span>
        <ToneBadge tone={stepStatusTone(step.status)}>{stepStatusLabel(step.status)}</ToneBadge>
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-zinc-400">
        <span>
          Agent: <span className="text-zinc-300">{step.agent_type}</span>
        </span>
        <span>
          Attempts:{' '}
          <span className="text-zinc-300">
            {step.attempt_count}/{step.max_attempts}
          </span>
        </span>
        <span>
          Started: <span className="text-zinc-300">{formatTimestamp(step.started_at)}</span>
        </span>
        <span>
          Completed: <span className="text-zinc-300">{formatTimestamp(step.completed_at)}</span>
        </span>
        <span>
          Output:{' '}
          <span className="text-zinc-300">
            {step.output_payload ? 'Available' : 'None yet'}
          </span>
        </span>
        <span>
          Compensation handler:{' '}
          <span className="text-zinc-300">{step.compensation_handler ?? 'None'}</span>
        </span>
      </div>
      {step.error_message && (
        <p className="rounded-md border border-rose-900/40 bg-rose-950/20 p-2 text-[11px] text-rose-300">
          {step.error_message}
        </p>
      )}

      {step.attempts.length > 0 && (
        <div className="space-y-1 border-t border-white/[0.06] pt-2">
          <p className="text-[10px] font-semibold tracking-wider text-zinc-500 uppercase">
            Execution attempts
          </p>
          {step.attempts.map((attempt) => (
            <div key={attempt.id} className="flex items-center justify-between text-[11px]">
              <span className="text-zinc-400">Attempt {attempt.attempt_number}</span>
              <span className="text-zinc-300">{attemptStatusLabel(attempt.status)}</span>
            </div>
          ))}
        </div>
      )}

      {step.compensation_attempts.length > 0 && (
        <div className="space-y-1 border-t border-white/[0.06] pt-2">
          <p className="text-[10px] font-semibold tracking-wider text-zinc-500 uppercase">
            Compensation attempts
          </p>
          {step.compensation_attempts.map((attempt) => (
            <div key={attempt.id} className="flex items-center justify-between text-[11px]">
              <span className="text-zinc-400">
                {attempt.handler_name} (#{attempt.attempt_number})
              </span>
              <span className="text-zinc-300">
                {compensationAttemptStatusLabel(attempt.status)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export const ExecutionPanel: React.FC<ExecutionPanelProps> = ({
  workflow,
  onExecute,
  onCompensate,
  executing,
  compensating,
}) => {
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const chainVerification = useAuditChainVerification(workflow.id);
  const sortedSteps = [...workflow.steps].sort((a, b) => a.position - b.position);

  const canExecute = isWorkflowExecutable(workflow.status);
  const canCompensate = canCompensateWorkflow(workflow.status);

  return (
    <div className="space-y-4">
      <div className="space-y-2 border-b border-white/[0.08] pb-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold text-white">{workflow.name}</h2>
          <ToneBadge tone={workflowStatusTone(workflow.status)}>
            {workflowStatusLabel(workflow.status)}
          </ToneBadge>
        </div>
        <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-zinc-400">
          <span>
            Version: <span className="text-zinc-300">{workflow.version}</span>
          </span>
          <span>
            Created: <span className="text-zinc-300">{formatTimestamp(workflow.created_at)}</span>
          </span>
          <span>
            Started: <span className="text-zinc-300">{formatTimestamp(workflow.started_at)}</span>
          </span>
          <span>
            Completed:{' '}
            <span className="text-zinc-300">{formatTimestamp(workflow.completed_at)}</span>
          </span>
        </div>
        {workflow.error_message && (
          <p className="rounded-md border border-rose-900/40 bg-rose-950/20 p-2 text-xs text-rose-300">
            {workflow.error_message}
          </p>
        )}
        {!chainVerification.loading && chainVerification.data && (
          <ToneBadge tone={chainVerification.data.valid ? 'success' : 'error'}>
            {chainVerification.data.valid
              ? 'Tamper-evident audit chain valid'
              : `Audit chain invalid (first bad sequence: ${chainVerification.data.first_invalid_sequence ?? '?'})`}
          </ToneBadge>
        )}
      </div>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={onExecute}
          disabled={!canExecute || executing}
          className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white shadow-sm transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Play className="h-3.5 w-3.5" />
          <span>{executing ? 'Execution request in progress…' : 'Execute'}</span>
        </button>
        {canCompensate && (
          <button
            type="button"
            onClick={() => setConfirmOpen(true)}
            disabled={compensating}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-amber-700/40 bg-amber-950/30 px-3 py-2 text-xs font-medium text-amber-300 transition-colors hover:bg-amber-900/40 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Undo2 className="h-3.5 w-3.5" />
            <span>{compensating ? 'Compensating…' : 'Compensate Workflow'}</span>
          </button>
        )}
      </div>
      <p aria-live="polite" className="sr-only">
        {executing && 'Execution request in progress.'}
        {compensating && 'Compensation request in progress.'}
      </p>

      {workflow.compensation_summary && (
        <div className="space-y-1 rounded-lg border border-amber-900/30 bg-amber-950/10 p-3 text-[11px] text-zinc-300">
          <p className="text-[10px] font-semibold tracking-wider text-amber-400 uppercase">
            Compensation summary
          </p>
          <pre className="overflow-x-auto whitespace-pre-wrap break-words text-[10px] text-zinc-400">
            {JSON.stringify(workflow.compensation_summary, null, 2)}
          </pre>
        </div>
      )}

      <div className="space-y-3">
        <h3 className="text-[10px] font-semibold tracking-wider text-zinc-500 uppercase">
          Steps ({sortedSteps.length})
        </h3>
        {sortedSteps.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed border-white/[0.08] py-6 text-center">
            <Clock className="h-4 w-4 text-zinc-500" />
            <p className="text-xs text-zinc-400">This workflow has no steps.</p>
          </div>
        ) : (
          sortedSteps.map((step) => <StepCard key={step.id} step={step} />)
        )}
      </div>

      {workflow.output_payload && (
        <div className="space-y-1 rounded-lg border border-white/[0.08] bg-white/[0.03] p-3">
          <p className="text-[10px] font-semibold tracking-wider text-zinc-500 uppercase">
            Workflow output
          </p>
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words text-[10px] text-zinc-400">
            {JSON.stringify(workflow.output_payload, null, 2)}
          </pre>
        </div>
      )}

      <CompensateDialog
        open={confirmOpen}
        busy={compensating}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => {
          setConfirmOpen(false);
          onCompensate();
        }}
      />
    </div>
  );
};
