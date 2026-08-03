import { apiRequest } from './api-client';
import type { HealthRead } from '@/types/backend';

export function getHealth(options?: { signal?: AbortSignal }): Promise<HealthRead> {
  return apiRequest<HealthRead>('/api/v1/health', options);
}
