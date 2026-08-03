import { apiRequest } from './api-client';
import type { AgentAvailabilityListResponse, AgentConnectionVerifyRead } from '@/types/backend';

export function listAgents(options?: {
  signal?: AbortSignal;
}): Promise<AgentAvailabilityListResponse> {
  return apiRequest<AgentAvailabilityListResponse>('/api/v1/agents', options);
}

/**
 * Trigger one safe, backend-owned headless verification for `agentType`.
 * Never sends a prompt or any credential — the backend owns the entire
 * verification call. Can reject with `409 AGENT_VERIFICATION_IN_PROGRESS`
 * if a verification for this agent type is already running.
 */
export function verifyAgent(
  agentType: string,
  options?: { signal?: AbortSignal }
): Promise<AgentConnectionVerifyRead> {
  return apiRequest<AgentConnectionVerifyRead>(
    `/api/v1/agents/${encodeURIComponent(agentType)}/verify`,
    {
      ...options,
      method: 'POST',
    }
  );
}
