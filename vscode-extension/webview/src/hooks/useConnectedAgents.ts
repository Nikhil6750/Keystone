import { useCallback, useEffect, useState } from 'react';
import { BackendUnavailableError, fetchConnectedAgents } from '../api/keystoneClient';
import type { ConnectedAgentSummary } from '../types/keystone';

export type BackendAvailability = 'checking' | 'available' | 'unavailable';

export interface UseConnectedAgentsResult {
  agents: ConnectedAgentSummary[];
  availability: BackendAvailability;
  refetch: () => void;
}

/**
 * Fetches the currently connected, enabled agents. Never simulates a
 * connection: `availability` is `'unavailable'` only for a genuine network
 * failure (see `BackendUnavailableError`); an empty/absent agent list is
 * always represented as zero agents, not as an error.
 */
export function useConnectedAgents(): UseConnectedAgentsResult {
  const [agents, setAgents] = useState<ConnectedAgentSummary[]>([]);
  const [availability, setAvailability] = useState<BackendAvailability>('checking');
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setAvailability('checking');

    fetchConnectedAgents()
      .then((result) => {
        if (cancelled) return;
        setAgents(result.filter((agent) => agent.enabled));
        setAvailability('available');
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof BackendUnavailableError) {
          setAgents([]);
          setAvailability('unavailable');
        } else {
          setAgents([]);
          setAvailability('available');
        }
      });

    return () => {
      cancelled = true;
    };
  }, [refreshToken]);

  const refetch = useCallback(() => setRefreshToken((token) => token + 1), []);

  return { agents, availability, refetch };
}
