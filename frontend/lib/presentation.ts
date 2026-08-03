/**
 * Backend enum value -> human-readable display label mapping.
 *
 * The API values themselves (`pending`, `succeeded`, `half_open`, ...) are
 * never changed for visual convenience — only this module's *display*
 * strings differ from the wire values. Every mapping below is total (covers
 * every backend enum member) so a new backend status can never silently
 * fall through to `undefined`.
 */

import type {
  AttemptStatus,
  CircuitBreakerState,
  CompensationAttemptStatus,
  StepStatus,
  WorkflowStatus,
} from '@/types/backend';

export type SemanticTone = 'neutral' | 'info' | 'success' | 'warning' | 'error';

const WORKFLOW_STATUS_LABELS: Record<WorkflowStatus, string> = {
  pending: 'Pending',
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
  compensating: 'Compensating',
  compensated: 'Compensated',
  cancelled: 'Cancelled',
};

const WORKFLOW_STATUS_TONES: Record<WorkflowStatus, SemanticTone> = {
  pending: 'neutral',
  running: 'info',
  succeeded: 'success',
  failed: 'error',
  compensating: 'warning',
  compensated: 'warning',
  cancelled: 'neutral',
};

export function workflowStatusLabel(status: WorkflowStatus): string {
  return WORKFLOW_STATUS_LABELS[status];
}

export function workflowStatusTone(status: WorkflowStatus): SemanticTone {
  return WORKFLOW_STATUS_TONES[status];
}

const STEP_STATUS_LABELS: Record<StepStatus, string> = {
  pending: 'Pending',
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
  retrying: 'Retrying',
  compensating: 'Compensating',
  compensated: 'Compensated',
  skipped: 'Skipped',
  cancelled: 'Cancelled',
};

const STEP_STATUS_TONES: Record<StepStatus, SemanticTone> = {
  pending: 'neutral',
  running: 'info',
  succeeded: 'success',
  failed: 'error',
  retrying: 'warning',
  compensating: 'warning',
  compensated: 'warning',
  skipped: 'neutral',
  cancelled: 'neutral',
};

export function stepStatusLabel(status: StepStatus): string {
  return STEP_STATUS_LABELS[status];
}

export function stepStatusTone(status: StepStatus): SemanticTone {
  return STEP_STATUS_TONES[status];
}

const ATTEMPT_STATUS_LABELS: Record<AttemptStatus, string> = {
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
};

export function attemptStatusLabel(status: AttemptStatus): string {
  return ATTEMPT_STATUS_LABELS[status];
}

const COMPENSATION_ATTEMPT_STATUS_LABELS: Record<CompensationAttemptStatus, string> = {
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
};

export function compensationAttemptStatusLabel(status: CompensationAttemptStatus): string {
  return COMPENSATION_ATTEMPT_STATUS_LABELS[status];
}

const CIRCUIT_BREAKER_STATE_LABELS: Record<CircuitBreakerState, string> = {
  closed: 'Closed',
  open: 'Open',
  half_open: 'Half-Open',
};

const CIRCUIT_BREAKER_STATE_TONES: Record<CircuitBreakerState, SemanticTone> = {
  closed: 'success',
  open: 'error',
  half_open: 'warning',
};

export function circuitBreakerStateLabel(state: CircuitBreakerState): string {
  return CIRCUIT_BREAKER_STATE_LABELS[state];
}

export function circuitBreakerStateTone(state: CircuitBreakerState): SemanticTone {
  return CIRCUIT_BREAKER_STATE_TONES[state];
}

/**
 * Only a `FAILED` workflow may be manually compensated — the backend rejects
 * every other status, including `succeeded`, with `409 INVALID_COMPENSATION_STATE`
 * (see `backend/app/engine/compensation.py`'s `compensate_workflow`, which checks
 * `status is not WorkflowStatus.FAILED`, and `docs/api-contract.md`). This is the
 * single place that decides compensation eligibility in the frontend — no other
 * component or page duplicates this condition.
 */
export function canCompensateWorkflow(status: WorkflowStatus): boolean {
  return status === 'failed';
}

/** Only a `PENDING` workflow may begin execution. */
export function isWorkflowExecutable(status: WorkflowStatus): boolean {
  return status === 'pending';
}

export function formatTimestamp(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}
