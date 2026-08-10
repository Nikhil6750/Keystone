/**
 * Shared Stage 8C.2/8C.3 Orchestration Contracts.
 */

export type OrchestrationExecutionStatus =
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

export interface OrchestrationExecutionCreate {
  goal: string;
  task_type?: string | null;
  repository?: {
    repository_id: string;
    root_path?: string | null;
    default_branch?: string | null;
  } | null;
  request_id?: string | null;
  knowledge_query?: string | null;
  available_agent_types?: string[];
  available_capabilities?: string[];
}

export interface OrchestrationExecutionAccepted {
  execution_id: string;
  status: OrchestrationExecutionStatus;
  events_url: string;
  result_url: string;
}

export interface OrchestrationExecutionRead {
  execution_id: string;
  job_status: OrchestrationExecutionStatus;
  orchestration_outcome?: OrchestrationOutcome | null;
  workflow_id?: string | null;
  final_workflow_state?: string | null;
  verification_status?: string | null;
  task_count?: number | null;
  selected_agent_types: string[];
  learning_event_count?: number | null;
  retrieval_feedback_recorded?: boolean | null;
  issue_codes: string[];
  error_summary?: string | null;
  created_at: string;
  updated_at: string;
}

export interface OrchestrationEventRead {
  event_id: string;
  execution_id: string;
  sequence: number;
  event_type: OrchestrationEventType;
  timestamp: string;
  phase?: string | null;
  status?: string | null;
  workflow_id?: string | null;
  task_key?: string | null;
  agent_id?: string | null;
  attempt_number?: number | null;
  verification_status?: string | null;
  safe_issue_codes: string[];
  message?: string | null;
}
