'use client';

import * as React from 'react';
import { verifyAgent } from '@/services/agents';
import { describeApiError } from '@/services/api-client';
import type { AgentConnectionVerifyRead } from '@/types/backend';

export interface VerifyAgentState {
  /** Agent types with a verification request currently in flight. */
  verifying: Set<string>;
  /** The most recent safe error message per agent type, if the last attempt failed. */
  errors: Record<string, string | undefined>;
  /** Runs one verification for `agentType`. A no-op while that same agent
   * type already has a verification in flight, preventing duplicate clicks
   * from firing overlapping requests. */
  verify: (agentType: string) => Promise<AgentConnectionVerifyRead | null>;
}

/**
 * Mutation-style hook for `POST /api/v1/agents/{agent_type}/verify` — kept
 * separate from `useAgents` (a read-only `useAsyncResource` wrapper) since
 * this one triggers a side effect rather than just fetching.
 */
export function useVerifyAgent(onSettled?: () => void): VerifyAgentState {
  const [verifying, setVerifying] = React.useState<Set<string>>(new Set());
  const [errors, setErrors] = React.useState<Record<string, string | undefined>>({});
  // Mirrors `verifying` synchronously so two rapid clicks (before React
  // re-renders with the updated state) can never both pass the guard below.
  const inFlightRef = React.useRef<Set<string>>(new Set());

  const verify = React.useCallback(
    async (agentType: string): Promise<AgentConnectionVerifyRead | null> => {
      if (inFlightRef.current.has(agentType)) return null;
      inFlightRef.current.add(agentType);

      setVerifying((prev) => new Set(prev).add(agentType));
      setErrors((prev) => ({ ...prev, [agentType]: undefined }));

      try {
        const result = await verifyAgent(agentType);
        return result;
      } catch (err) {
        setErrors((prev) => ({ ...prev, [agentType]: describeApiError(err) }));
        return null;
      } finally {
        inFlightRef.current.delete(agentType);
        setVerifying((prev) => {
          const next = new Set(prev);
          next.delete(agentType);
          return next;
        });
        onSettled?.();
      }
    },
    [onSettled]
  );

  return { verifying, errors, verify };
}
