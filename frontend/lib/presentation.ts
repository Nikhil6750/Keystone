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
  AgentAvailabilityRead,
  AttemptStatus,
  AuthenticationStatus,
  CircuitBreakerState,
  CompensationAttemptStatus,
  ConnectionStatus,
  InstallationStatus,
  OrchestrationExecutionStatus,
  OrchestrationOutcome,
  QualityGateStatus,
  QualityVerdictStatus,
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

const INSTALLATION_STATUS_LABELS: Record<InstallationStatus, string> = {
  installed: 'Installed',
  not_installed: 'Not installed',
  unknown: 'Unknown',
};

const INSTALLATION_STATUS_TONES: Record<InstallationStatus, SemanticTone> = {
  installed: 'success',
  not_installed: 'neutral',
  unknown: 'neutral',
};

export function installationStatusLabel(status: InstallationStatus): string {
  return INSTALLATION_STATUS_LABELS[status];
}

export function installationStatusTone(status: InstallationStatus): SemanticTone {
  return INSTALLATION_STATUS_TONES[status];
}

const AUTHENTICATION_STATUS_LABELS: Record<AuthenticationStatus, string> = {
  authenticated: 'Authenticated',
  unauthenticated: 'Not authenticated',
  unknown: 'Unknown',
  error: 'Error checking',
};

const AUTHENTICATION_STATUS_TONES: Record<AuthenticationStatus, SemanticTone> = {
  authenticated: 'success',
  unauthenticated: 'warning',
  unknown: 'neutral',
  error: 'error',
};

export function authenticationStatusLabel(status: AuthenticationStatus): string {
  return AUTHENTICATION_STATUS_LABELS[status];
}

export function authenticationStatusTone(status: AuthenticationStatus): SemanticTone {
  return AUTHENTICATION_STATUS_TONES[status];
}

const CONNECTION_STATUS_LABELS: Record<ConnectionStatus, string> = {
  connected: 'Connected',
  unavailable: 'Unavailable',
  verification_failed: 'Verification failed',
  verification_required: 'Verification required',
  disabled: 'Disabled',
};

const CONNECTION_STATUS_TONES: Record<ConnectionStatus, SemanticTone> = {
  connected: 'success',
  unavailable: 'neutral',
  verification_failed: 'error',
  verification_required: 'warning',
  disabled: 'neutral',
};

export function connectionStatusLabel(status: ConnectionStatus): string {
  return CONNECTION_STATUS_LABELS[status];
}

export function connectionStatusTone(status: ConnectionStatus): SemanticTone {
  return CONNECTION_STATUS_TONES[status];
}

/**
 * A workflow step must never be built against an agent that is disabled,
 * uninstalled, unregistered, unauthenticated, or not currently connected —
 * doing so would only fail at execution time. This is the single place that
 * decides step-level selectability so no page duplicates the condition.
 */
export function canSelectAgentForStep(agent: AgentAvailabilityRead): boolean {
  return (
    agent.enabled &&
    agent.registered &&
    agent.installation_status === 'installed' &&
    agent.authentication_status === 'authenticated' &&
    agent.connection_status === 'connected'
  );
}

/** Local, provider-owned login commands — never executed by Keystone, only
 * displayed so the user can run them themselves on the machine running the
 * backend. Keystone never launches a browser login or collects a credential. */
const AGENT_LOCAL_LOGIN_INSTRUCTIONS: Record<string, string> = {
  claude_code: 'Run `claude auth login` in a terminal on the machine running the Keystone backend.',
  codex: 'Run `codex login` in a terminal on the machine running the Keystone backend.',
  antigravity:
    'Run `agy` on the machine running the Keystone backend and complete the official browser sign-in it opens.',
  gemini: "Run the Gemini CLI's own login command on the machine running the Keystone backend.",
};

export function agentLocalLoginInstructions(agentType: string): string | null {
  return AGENT_LOCAL_LOGIN_INSTRUCTIONS[agentType] ?? null;
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

const ORCHESTRATION_JOB_STATUS_LABELS: Record<OrchestrationExecutionStatus, string> = {
  accepted: 'Accepted',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

const ORCHESTRATION_JOB_STATUS_TONES: Record<OrchestrationExecutionStatus, SemanticTone> = {
  accepted: 'neutral',
  running: 'info',
  completed: 'success',
  failed: 'error',
  cancelled: 'neutral',
};

export function orchestrationJobStatusLabel(status: OrchestrationExecutionStatus): string {
  return ORCHESTRATION_JOB_STATUS_LABELS[status];
}

export function orchestrationJobStatusTone(status: OrchestrationExecutionStatus): SemanticTone {
  return ORCHESTRATION_JOB_STATUS_TONES[status];
}

const ORCHESTRATION_OUTCOME_LABELS: Record<OrchestrationOutcome, string> = {
  verified_success: 'Verified success',
  verification_failed: 'Verification failed',
  runtime_failure: 'Runtime failure',
  no_eligible_route: 'No eligible agent',
  recovery_exhausted: 'Recovery exhausted',
  human_review_required: 'Human review required',
  cancelled: 'Cancelled',
};

const ORCHESTRATION_OUTCOME_TONES: Record<OrchestrationOutcome, SemanticTone> = {
  verified_success: 'success',
  verification_failed: 'error',
  runtime_failure: 'error',
  no_eligible_route: 'warning',
  recovery_exhausted: 'error',
  human_review_required: 'warning',
  cancelled: 'neutral',
};

export function orchestrationOutcomeLabel(outcome: OrchestrationOutcome): string {
  return ORCHESTRATION_OUTCOME_LABELS[outcome];
}

export function orchestrationOutcomeTone(outcome: OrchestrationOutcome): SemanticTone {
  return ORCHESTRATION_OUTCOME_TONES[outcome];
}

const QUALITY_GATE_STATUS_LABELS: Record<QualityGateStatus, string> = {
  PASSED: 'Passed',
  FAILED: 'Failed',
  ERROR: 'Error',
  SKIPPED: 'Skipped',
};

const QUALITY_GATE_STATUS_TONES: Record<QualityGateStatus, SemanticTone> = {
  PASSED: 'success',
  FAILED: 'error',
  ERROR: 'error',
  SKIPPED: 'neutral',
};

export function qualityGateStatusLabel(status: QualityGateStatus): string {
  return QUALITY_GATE_STATUS_LABELS[status];
}

export function qualityGateStatusTone(status: QualityGateStatus): SemanticTone {
  return QUALITY_GATE_STATUS_TONES[status];
}

const QUALITY_VERDICT_STATUS_LABELS: Record<QualityVerdictStatus, string> = {
  ACCEPTED: 'Accepted',
  REJECTED: 'Rejected',
  REPAIR_REQUIRED: 'Repair required',
  ERROR: 'Error',
};

const QUALITY_VERDICT_STATUS_TONES: Record<QualityVerdictStatus, SemanticTone> = {
  ACCEPTED: 'success',
  REJECTED: 'error',
  REPAIR_REQUIRED: 'warning',
  ERROR: 'error',
};

export function qualityVerdictStatusLabel(status: QualityVerdictStatus): string {
  return QUALITY_VERDICT_STATUS_LABELS[status];
}

export function qualityVerdictStatusTone(status: QualityVerdictStatus): SemanticTone {
  return QUALITY_VERDICT_STATUS_TONES[status];
}
