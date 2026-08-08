/**
 * Execution lifecycle status of a workflow or step.
 */
export type WorkflowStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'compensating'
  | 'compensated'
  | 'cancelled';

/**
 * Single executable step inside a workflow.
 */
export interface WorkflowStep {
  id: string;
  name: string;
  agentType: string;
  order: number;
  inputPayload?: Record<string, unknown>;
  outputPayload?: Record<string, unknown>;
  maxAttempts?: number;
  status?: WorkflowStatus;
}

/**
 * Multi-step orchestration workflow representation.
 */
export interface Workflow {
  id: string;
  name: string;
  description?: string;
  status: WorkflowStatus;
  steps: WorkflowStep[];
  createdAt: string;
  updatedAt: string;
  metadata?: Record<string, unknown>;
}

/**
 * State change or execution event emitted during workflow processing.
 */
export interface WorkflowExecutionEvent {
  id: string;
  workflowId: string;
  stepId?: string;
  eventType: string;
  timestamp: string;
  payload?: Record<string, unknown>;
}
