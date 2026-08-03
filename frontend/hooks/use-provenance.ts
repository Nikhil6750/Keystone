'use client';

import { getProvenance } from '@/services/audit';
import { useAsyncResource } from './use-async-resource';

export function useProvenance(workflowId: string | null) {
  return useAsyncResource(
    (signal) => {
      if (!workflowId) return Promise.resolve(null);
      return getProvenance(workflowId, { signal });
    },
    [workflowId]
  );
}
