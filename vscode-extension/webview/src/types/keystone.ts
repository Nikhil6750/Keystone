/**
 * Types mirroring the certified Stage 8C.2 orchestration API and the
 * Stage 8C.3A dynamic connection API. Only safe, documented fields are
 * represented here -- nothing here can carry chain-of-thought, raw
 * provider output, prompts, or secrets, because the backend contracts
 * these mirror never emit them in the first place.
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

/** Mirrors `GET /api/v1/agents` (`AgentAvailabilityRead`) -- installed/
 * configured runtime *adapter* availability, distinct from a user-created
 * Keystone agent *identity* (`ConnectedAgentSummary`). Never conflate the
 * two: this is "is Claude Code installed and authenticated on this
 * machine," not "did the user connect it." */
export interface DetectedRuntime {
  agent_type: string;
  display_name: string;
  enabled: boolean;
  available: boolean;
  registered: boolean;
  execution_mode: string;
  reason: string;
  installation_status: 'unknown' | 'not_installed' | 'installed';
  authentication_status: 'unknown' | 'authenticated' | 'unauthenticated' | 'error';
  connection_status: 'connected' | 'unavailable' | 'disabled' | 'unknown' | 'verification_required' | 'verification_failed';
  version: string | null;
  last_checked_at: string | null;
  capabilities: string[];
}

/** Mirrors `POST /runtime-connections/{runtime_id}/activate`
 * (`AgentConnectionVerifyRead`) -- the deliberate, user-triggered result of
 * clicking "Connect" on a detected runtime. */
export interface RuntimeActivationResult {
  agent_type: string;
  display_name: string;
  enabled: boolean;
  installation_status: DetectedRuntime['installation_status'];
  authentication_status: DetectedRuntime['authentication_status'];
  connection_status: DetectedRuntime['connection_status'];
  registered: boolean;
  execution_mode: string;
  version: string | null;
  last_checked_at: string | null;
  reason: string;
  capabilities: string[];
}

export type ConnectionKind = 'installed_runtime' | 'api' | 'local' | 'custom';
export type AgentConnectionStatus = 'connected' | 'unavailable' | 'disabled' | 'unknown';

/** Mirrors `AgentConnection` (`app.engine.connections.models`) -- an
 * integration connection (a runtime, an API account, a local endpoint, a
 * custom runtime). `metadata` is backend-validated to never carry a
 * secret-bearing key (see `validate_metadata`'s `FORBIDDEN_SECRET_TOKENS`)
 * -- this type only ever holds what the backend itself accepted. */
export interface AgentConnection {
  connection_id: string;
  display_name: string;
  connection_kind: ConnectionKind;
  provider_or_runtime: string;
  status: AgentConnectionStatus;
  metadata: Record<string, string>;
  created_at: string;
  updated_at: string;
}

export interface AgentConnectionCreateInput {
  connection_id: string;
  display_name: string;
  connection_kind: ConnectionKind;
  provider_or_runtime: string;
  status?: AgentConnectionStatus;
  metadata?: Record<string, string>;
}

/** Mirrors `ConnectedAgent` (`app.engine.connections.models`) -- a
 * user-created Keystone agent identity backed by an `AgentConnection`. */
export interface ConnectedAgent {
  agent_id: AgentId;
  display_name: string;
  connection_id: string;
  model_id: string | null;
  capabilities: string[];
  enabled: boolean;
  metadata: Record<string, string>;
  created_at: string;
  updated_at: string;
}

export interface ConnectedAgentCreateInput {
  agent_id: AgentId;
  display_name: string;
  connection_id: string;
  model_id?: string | null;
  capabilities?: string[];
  enabled?: boolean;
  metadata?: Record<string, string>;
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
