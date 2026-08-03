import type { APIErrorCode } from '@/types/backend';

/**
 * Short, human titles for the backend error codes documented in
 * `docs/api-contract.md`. The backend's own `message` field is already a
 * safe, readable sentence (never a stack trace) — this map only adds a
 * consistent title above it, it never replaces or hides that message.
 */
const ERROR_CODE_TITLES: Partial<Record<APIErrorCode | 'NETWORK_ERROR' | 'TIMEOUT' | 'PARSE_ERROR', string>> = {
  WORKFLOW_NOT_FOUND: 'Workflow not found',
  INVALID_WORKFLOW_STATE: 'Workflow is not in a valid state for this action',
  AGENT_EXECUTOR_NOT_REGISTERED: 'Agent not registered',
  CIRCUIT_BREAKER_OPEN: 'Circuit breaker is open',
  INVALID_COMPENSATION_STATE: 'Workflow cannot be compensated right now',
  COMPENSATION_HANDLER_NOT_REGISTERED: 'Compensation handler not registered',
  COMPENSATION_ALREADY_COMPLETED: 'Workflow was already compensated',
  COMPENSATION_EXECUTION_FAILED: 'Compensation failed unexpectedly',
  INVALID_REQUEST: 'Request was rejected',
  INTERNAL_ERROR: 'An unexpected server error occurred',
  NETWORK_ERROR: 'Could not reach the backend',
  TIMEOUT: 'The request timed out',
  PARSE_ERROR: 'The backend response could not be read',
};

export function errorCodeTitle(
  code: APIErrorCode | 'NETWORK_ERROR' | 'TIMEOUT' | 'PARSE_ERROR'
): string {
  return ERROR_CODE_TITLES[code] ?? 'Something went wrong';
}
