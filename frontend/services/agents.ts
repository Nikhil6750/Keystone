import { apiRequest } from './api-client';
import type { AgentAvailabilityListResponse } from '@/types/backend';

export function listAgents(options?: { signal?: AbortSignal }): Promise<AgentAvailabilityListResponse> {
  return apiRequest<AgentAvailabilityListResponse>('/api/v1/agents', options);
}
