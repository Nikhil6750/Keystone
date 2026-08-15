/**
 * TypeScript types mirroring the Keystone backend's actual Pydantic schemas
 * (see ../../docs/api-contract.md and backend/app/schemas/*.py). Field names
 * and enum values are copied verbatim from the backend source — never
 * assumed or renamed for display purposes. Presentation-only mapping (labels,
 * colors) lives in `lib/presentation.ts`, not here.
 */

// --- Error envelope (backend/app/schemas/errors.py) ---

export type APIErrorCode =
  | 'WORKFLOW_NOT_FOUND'
  | 'INVALID_WORKFLOW_STATE'
  | 'AGENT_EXECUTOR_NOT_REGISTERED'
  | 'STEP_EXECUTION_FAILED'
  | 'CIRCUIT_BREAKER_OPEN'
  | 'INVALID_COMPENSATION_STATE'
  | 'COMPENSATION_HANDLER_NOT_REGISTERED'
  | 'COMPENSATION_EXECUTION_FAILED'
  | 'COMPENSATION_ALREADY_COMPLETED'
  | 'AUDIT_CHAIN_INVALID'
  | 'AUDIT_EVENT_CONFLICT'
  | 'AGENT_TYPE_UNKNOWN'
  | 'AGENT_VERIFICATION_IN_PROGRESS'
  | 'ORCHESTRATION_EXECUTION_NOT_FOUND'
  | 'ORCHESTRATION_EXECUTION_EXISTS'
  | 'AGENT_CONNECTION_NOT_FOUND'
  | 'CONNECTED_AGENT_NOT_FOUND'
  | 'AGENT_CONNECTION_EXISTS'
  | 'CONNECTED_AGENT_EXISTS'
  | 'AGENT_CONNECTION_HAS_DEPENDENTS'
  | 'INVALID_AGENT_CONNECTION_REFERENCE'
  | 'INVALID_REQUEST'
  | 'INTERNAL_ERROR';

export interface APIErrorDetail {
  code: APIErrorCode;
  message: string;
  details?: unknown;
}

export interface APIErrorEnvelope {
  error: APIErrorDetail;
}

// --- Enums (backend/app/models/enums.py) ---

export type WorkflowStatus =
  'pending' | 'running' | 'succeeded' | 'failed' | 'compensating' | 'compensated' | 'cancelled';

export type StepStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'retrying'
  | 'compensating'
  | 'compensated'
  | 'skipped'
  | 'cancelled';

export type AttemptStatus = 'running' | 'succeeded' | 'failed';

export type CompensationAttemptStatus = 'running' | 'succeeded' | 'failed';

// --- Workflow request schemas (backend/app/schemas/workflow.py) ---

export interface WorkflowStepCreate {
  name: string;
  position: number;
  agent_type: string;
  input_payload?: Record<string, unknown>;
  max_attempts?: number;
  compensation_handler?: string | null;
}

export interface WorkflowCreate {
  name: string;
  description?: string | null;
  input_payload?: Record<string, unknown>;
  steps?: WorkflowStepCreate[];
}

// --- Workflow response schemas ---

export interface StepAttemptRead {
  id: string;
  step_id: string;
  attempt_number: number;
  status: AttemptStatus;
  started_at: string;
  completed_at: string | null;
  output_payload: Record<string, unknown> | null;
  error_type: string | null;
  error_message: string | null;
}

export interface CompensationAttemptRead {
  id: string;
  step_id: string;
  attempt_number: number;
  handler_name: string;
  status: CompensationAttemptStatus;
  started_at: string;
  completed_at: string | null;
  output_payload: Record<string, unknown> | null;
  error_type: string | null;
  error_message: string | null;
}

export interface WorkflowStepRead {
  id: string;
  workflow_id: string;
  name: string;
  position: number;
  agent_type: string;
  status: StepStatus;
  input_payload: Record<string, unknown>;
  output_payload: Record<string, unknown> | null;
  error_message: string | null;
  max_attempts: number;
  attempt_count: number;
  compensation_handler: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  attempts: StepAttemptRead[];
  compensation_attempts: CompensationAttemptRead[];
}

export interface WorkflowRead {
  id: string;
  name: string;
  description: string | null;
  status: WorkflowStatus;
  input_payload: Record<string, unknown>;
  output_payload: Record<string, unknown> | null;
  error_message: string | null;
  compensation_summary: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  version: number;
  steps: WorkflowStepRead[];
}

export interface WorkflowListResponse {
  items: WorkflowRead[];
  count: number;
}

// --- Agent availability / connection (backend/app/schemas/agents.py,
// backend/app/adapters/connection.py) ---

export type InstallationStatus = 'installed' | 'not_installed' | 'unknown';

export type AuthenticationStatus = 'authenticated' | 'unauthenticated' | 'unknown' | 'error';

export type ConnectionStatus =
  'connected' | 'unavailable' | 'verification_failed' | 'verification_required' | 'disabled';

export interface AgentAvailabilityRead {
  agent_type: string;
  display_name: string;
  enabled: boolean;
  available: boolean;
  registered: boolean;
  execution_mode: string;
  reason: string;
  installation_status: InstallationStatus;
  authentication_status: AuthenticationStatus;
  connection_status: ConnectionStatus;
  version: string | null;
  last_checked_at: string | null;
  capabilities: string[];
}

export interface AgentAvailabilityListResponse {
  items: AgentAvailabilityRead[];
  count: number;
}

/** Response for `POST /api/v1/agents/{agent_type}/verify`. Never includes a
 * raw provider response, email address, or any other account-identifying
 * detail — only this sanitized state. */
export interface AgentConnectionVerifyRead {
  agent_type: string;
  display_name: string;
  enabled: boolean;
  installation_status: InstallationStatus;
  authentication_status: AuthenticationStatus;
  connection_status: ConnectionStatus;
  registered: boolean;
  execution_mode: string;
  version: string | null;
  last_checked_at: string | null;
  reason: string;
  capabilities: string[];
}

// --- Circuit breaker (backend/app/schemas/resilience.py) ---

export type CircuitBreakerState = 'closed' | 'open' | 'half_open';

export interface CircuitBreakerRead {
  agent_type: string;
  state: CircuitBreakerState;
  failure_count: number;
  failure_threshold: number;
  recovery_timeout_seconds: number;
  retry_after_seconds: number;
  half_open_probe_in_flight: boolean;
}

export interface CircuitBreakerListResponse {
  items: CircuitBreakerRead[];
  count: number;
}

// --- Audit / provenance (backend/app/schemas/audit.py) ---

export type AuditEventType =
  | 'workflow_created'
  | 'workflow_execution_started'
  | 'workflow_succeeded'
  | 'workflow_failed'
  | 'workflow_compensation_started'
  | 'workflow_compensated'
  | 'workflow_compensation_failed'
  | 'step_execution_started'
  | 'step_succeeded'
  | 'step_failed'
  | 'step_retry_scheduled'
  | 'step_compensation_started'
  | 'step_compensated'
  | 'step_compensation_failed'
  | 'execution_attempt_started'
  | 'execution_attempt_succeeded'
  | 'execution_attempt_failed'
  | 'compensation_attempt_started'
  | 'compensation_attempt_succeeded'
  | 'compensation_attempt_failed'
  | 'circuit_breaker_rejected';

export type ActorType = 'user' | 'system' | 'agent' | 'compensation_handler';

export interface AuditEventRead {
  id: string;
  workflow_id: string;
  step_id: string | null;
  execution_attempt_id: string | null;
  compensation_attempt_id: string | null;
  sequence_number: number;
  event_type: AuditEventType;
  actor_type: ActorType;
  actor_id: string;
  payload: Record<string, unknown>;
  previous_hash: string;
  event_hash: string;
  created_at: string;
}

export interface AuditEventListResponse {
  items: AuditEventRead[];
  count: number;
}

export interface AuditChainVerificationRead {
  workflow_id: string;
  valid: boolean;
  event_count: number;
  first_invalid_sequence: number | null;
  reason: string | null;
}

/** Alias kept for readability at call sites that iterate provenance events. */
export type ProvenanceEventRead = AuditEventRead;

export interface ProvenanceRead {
  workflow_id: string;
  chain_valid: boolean;
  events: ProvenanceEventRead[];
}

// --- Health (backend/app/schemas/health.py) ---

export interface HealthRead {
  status: string;
  service: string;
  version: string;
}

// --- Orchestrations (backend/app/schemas/orchestration.py) ---
// The full Task Graph -> Agent Organization -> Skill Foundry -> execution
// -> recovery -> Quality Factory -> Intelligence Graph pipeline, distinct
// from the basic manual WorkflowCreate/execute flow above.

export type OrchestrationExecutionStatus =
  'accepted' | 'running' | 'completed' | 'failed' | 'cancelled';

export type OrchestrationOutcome =
  | 'verified_success'
  | 'verification_failed'
  | 'runtime_failure'
  | 'no_eligible_route'
  | 'recovery_exhausted'
  | 'human_review_required'
  | 'cancelled';

export interface OrchestrationExecutionCreate {
  goal: string;
  task_type?: string | null;
  request_id?: string | null;
  available_agent_types?: string[];
  knowledge_query?: string | null;
  workspace_root: string;
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
  orchestration_outcome: OrchestrationOutcome | null;
  workflow_id: string | null;
  final_workflow_state: WorkflowStatus | null;
  verification_status: 'passed' | 'failed' | 'inconclusive' | 'requires_human_review' | null;
  task_count: number | null;
  selected_agent_types: string[];
  attempt_count: number | null;
  recovery_used: boolean | null;
  recovery_action: string | null;
  learning_event_count: number | null;
  retrieval_feedback_recorded: boolean | null;
  issue_codes: string[];
  quality_run_id: string | null;
  quality_verdict_status: string | null;
  error_summary: string | null;
  created_at: string;
  updated_at: string;
}

// --- Quality (backend/app/api/routes/quality.py, Stage 9D) ---

export type QualityGateStatus = 'PASSED' | 'FAILED' | 'ERROR' | 'SKIPPED';

export type QualityVerdictStatus = 'ACCEPTED' | 'REJECTED' | 'REPAIR_REQUIRED' | 'ERROR';

export interface QualityEvidenceRead {
  summary: string;
  exit_code: number | null;
  diagnostics: string[];
  artifact_references: string[];
  stdout: string;
  stderr: string;
  metrics: Record<string, unknown>;
}

export interface QualityGateResultRead {
  gate_id: string;
  gate_type: string;
  name: string;
  status: QualityGateStatus;
  required: boolean;
  evidence: QualityEvidenceRead;
  execution_time_ms: number;
  failure_reason: string | null;
  skip_reason: string | null;
  timestamp: string;
}

export interface QualityVerdictRead {
  verdict_id: string;
  status: QualityVerdictStatus;
  passed: boolean;
  total_gates: number;
  passed_gates: number;
  failed_gates: number;
  skipped_gates: number;
  error_gates: number;
  summary_explanation: string;
  created_at: string;
}

export interface QualityRunRead {
  run_id: string;
  execution_id: string;
  workflow_id: string | null;
  task_id: string | null;
  attempt_number: number;
  agent_id: string | null;
  skill_id: string | null;
  skill_version: string | null;
  profile_id: string | null;
  status: string;
  passed: boolean;
  verdict: QualityVerdictRead | null;
  created_at: string;
  completed_at: string | null;
}

// --- Intelligence (backend/app/api/routes/intelligence.py, Stage 9E) ---

export interface IntelligenceNodeRead {
  node_id: string;
  node_type: string;
  canonical_id: string;
  label: string;
  workflow_id: string | null;
  agent_type: string | null;
  task_type: string | null;
  skill_id: string | null;
  skill_version: string | null;
  status: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface IntelligenceEdgeRead {
  edge_id: string;
  edge_type: string;
  source_node_id: string;
  target_node_id: string;
  created_at: string;
}

export interface NodeRelationshipsRead {
  node: IntelligenceNodeRead;
  outgoing: IntelligenceEdgeRead[];
  incoming: IntelligenceEdgeRead[];
}

export interface TaskReliabilityRead {
  task_type: string | null;
  attempt_count: number;
  success_count: number;
  failure_count: number;
  recovery_count: number;
  quality_rejection_count: number;
  success_rate: number | null;
  sample_size_is_low: boolean;
}

export interface AgentReliabilityRead {
  agent_type: string;
  task_type: string | null;
  observed_executions: number;
  successful_executions: number;
  failed_executions: number;
  recovery_count: number;
  quality_verified_successes: number;
  success_rate: number | null;
  sample_size_is_low: boolean;
}

export interface SkillReliabilityRead {
  skill_id: string;
  skill_version: string | null;
  task_type: string | null;
  uses: number;
  successful_uses: number;
  failed_uses: number;
  quality_verified_uses: number;
  success_rate: number | null;
  sample_size_is_low: boolean;
}

export interface QualityGateIntelligenceRead {
  task_type: string | null;
  agent_type: string | null;
  skill_id: string | null;
  total_gate_results: number;
  passed_count: number;
  failed_count: number;
  error_count: number;
  skipped_count: number;
  most_frequent_failed_gate_types: [string, number][];
  sample_size_is_low: boolean;
}

export interface FailureAttributionRead {
  attribution_id: string;
  attempt_node_id: string;
  category: string;
  is_known: boolean;
  explanation: string;
  evidence_ids: string[];
  workflow_id: string | null;
  agent_type: string | null;
  task_type: string | null;
  skill_id: string | null;
  created_at: string;
}
