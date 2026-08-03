'use client';

import { listAuditEvents } from '@/services/audit';
import { useAsyncResource } from './use-async-resource';

export function useAuditEvents(workflowId: string | null, limit?: number) {
  return useAsyncResource(
    (signal) => {
      if (!workflowId) return Promise.resolve(null);
      return listAuditEvents(workflowId, { limit }, { signal });
    },
    [workflowId, limit]
  );
}
