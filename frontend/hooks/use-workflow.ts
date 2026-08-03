'use client';

import { getWorkflow } from '@/services/workflows';
import { useAsyncResource } from './use-async-resource';

export function useWorkflow(workflowId: string | null) {
  return useAsyncResource(
    (signal) => {
      if (!workflowId) return Promise.resolve(null);
      return getWorkflow(workflowId, { signal });
    },
    [workflowId]
  );
}
