import { apiRequest } from './api-client';
import type { CircuitBreakerListResponse } from '@/types/backend';

export function listCircuitBreakers(options?: {
  signal?: AbortSignal;
}): Promise<CircuitBreakerListResponse> {
  return apiRequest<CircuitBreakerListResponse>('/api/v1/resilience/circuit-breakers', options);
}
