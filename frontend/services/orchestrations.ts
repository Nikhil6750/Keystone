import { apiRequest } from './api-client';
import type {
  OrchestrationExecutionAccepted,
  OrchestrationExecutionCreate,
  OrchestrationExecutionRead,
} from '@/types/backend';

/** Starts the full Task Graph -> Agent Organization -> Skill Foundry ->
 * execution -> recovery -> Quality Factory -> Intelligence Graph pipeline.
 * Returns immediately (202 Accepted) with an execution_id -- the caller
 * must poll `getOrchestrationExecution` for the result. */
export function createOrchestrationExecution(
  data: OrchestrationExecutionCreate,
  options?: { signal?: AbortSignal }
): Promise<OrchestrationExecutionAccepted> {
  return apiRequest<OrchestrationExecutionAccepted>('/api/v1/orchestrations', {
    method: 'POST',
    body: JSON.stringify(data),
    signal: options?.signal,
  });
}

export function getOrchestrationExecution(
  executionId: string,
  options?: { signal?: AbortSignal }
): Promise<OrchestrationExecutionRead> {
  return apiRequest<OrchestrationExecutionRead>(
    `/api/v1/orchestrations/${encodeURIComponent(executionId)}`,
    options
  );
}
