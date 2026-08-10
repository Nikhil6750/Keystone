/**
 * Types mirroring the certified Stage 8C.2 orchestration API and the
 * (not-yet-merged) Stage 8C.3A dynamic connection API. Only safe,
 * documented fields are represented here -- nothing here can carry
 * chain-of-thought, raw provider output, prompts, or secrets, because the
 * backend contracts these mirror never emit them in the first place.
 */

/** Open string identifier -- never a closed Claude/Codex/Gemini enum. */
export type AgentId = string;

export interface ConnectedAgentSummary {
  agent_id: AgentId;
  display_name: string;
  connection_id: string;
  enabled: boolean;
  capabilities: string[];
}

export type OrchestrationJobStatus =
  | 'accepted'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type OrchestrationOutcome =
  | 'verified_success'
  | 'verification_failed'
  | 'runtime_failure'
  | 'no_eligible_route'
  | 'recovery_exhausted'
  | 'human_review_required'
  | 'cancelled';

export interface OrchestrationExecutionAccepted {
  execution_id: string;
  status: OrchestrationJobStatus;
  events_url: string;
  result_url: string;
}

export interface OrchestrationExecutionRead {
  execution_id: string;
  job_status: OrchestrationJobStatus;
  orchestration_outcome: OrchestrationOutcome | null;
  workflow_id: string | null;
  final_workflow_state: string | null;
  verification_status: string | null;
  task_count: number | null;
  selected_agent_types: string[];
  learning_event_count: number | null;
  retrieval_feedback_recorded: boolean | null;
  issue_codes: string[];
  error_summary: string | null;
}

/** The full safe event taxonomy -- see backend
 * app/engine/orchestration/events.py::OrchestrationEventType. */
export type OrchestrationEventType =
  | 'execution.accepted'
  | 'execution.started'
  | 'knowledge.started'
  | 'knowledge.completed'
  | 'manager.started'
  | 'manager.completed'
  | 'manager.fallback'
  | 'planning.completed'
  | 'routing.started'
  | 'routing.task_selected'
  | 'routing.failed'
  | 'workflow.created'
  | 'workflow.started'
  | 'step.started'
  | 'step.completed'
  | 'step.failed'
  | 'verification.started'
  | 'verification.completed'
  | 'recovery.started'
  | 'recovery.completed'
  | 'recovery.exhausted'
  | 'learning.completed'
  | 'retrieval_feedback.completed'
  | 'execution.completed'
  | 'execution.failed'
  | 'execution.cancelled';

/** Mirrors `OrchestrationEvent` -- bounded, typed, safe fields only. No
 * `payload: any` field exists on the backend event either, by design. */
export interface OrchestrationEvent {
  event_id: string;
  execution_id: string;
  sequence: number;
  event_type: OrchestrationEventType;
  timestamp: string;
  phase: string | null;
  status: string | null;
  workflow_id: string | null;
  task_key: string | null;
  agent_id: string | null;
  attempt_number: number | null;
  verification_status: string | null;
  safe_issue_codes: string[];
  message: string | null;
}

export const TERMINAL_EVENT_TYPES: ReadonlySet<OrchestrationEventType> = new Set([
  'execution.completed',
  'execution.failed',
  'execution.cancelled',
]);
