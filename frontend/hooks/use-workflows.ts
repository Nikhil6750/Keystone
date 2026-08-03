'use client';

import { listWorkflows } from '@/services/workflows';
import { useAsyncResource } from './use-async-resource';

export function useWorkflows(limit?: number) {
  return useAsyncResource((signal) => listWorkflows({ limit }, { signal }), [limit]);
}
