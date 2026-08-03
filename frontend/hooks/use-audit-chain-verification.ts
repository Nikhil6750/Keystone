'use client';

import { verifyAuditChain } from '@/services/audit';
import { useAsyncResource } from './use-async-resource';

/** Detailed chain-verification result (`first_invalid_sequence`, `reason`) —
 * complements `useProvenance`, which only carries the coarse `chain_valid` flag. */
export function useAuditChainVerification(workflowId: string | null) {
  return useAsyncResource(
    (signal) => {
      if (!workflowId) return Promise.resolve(null);
      return verifyAuditChain(workflowId, { signal });
    },
    [workflowId]
  );
}
