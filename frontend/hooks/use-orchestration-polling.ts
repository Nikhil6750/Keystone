'use client';

import * as React from 'react';
import { getOrchestrationExecution } from '@/services/orchestrations';
import { describeApiError } from '@/services/api-client';
import type { OrchestrationExecutionRead } from '@/types/backend';

const POLL_INTERVAL_MS = 1500;
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled']);

export interface UseOrchestrationPollingState {
  data: OrchestrationExecutionRead | null;
  error: string | null;
  polling: boolean;
}

/**
 * Polls `GET /api/v1/orchestrations/{executionId}` until the job reaches a
 * terminal status. Polling (not SSE) is intentional for this prototype
 * surface -- simpler and equally correct for a single-viewer detail page;
 * the backend's SSE stream remains available for any future consumer that
 * needs push updates.
 */
export function useOrchestrationPolling(executionId: string | null): UseOrchestrationPollingState {
  const [data, setData] = React.useState<OrchestrationExecutionRead | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [polling, setPolling] = React.useState(false);

  React.useEffect(() => {
    setData(null);
    setError(null);
    if (!executionId) {
      setPolling(false);
      return;
    }

    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    const controller = new AbortController();
    setPolling(true);

    const tick = async () => {
      try {
        const result = await getOrchestrationExecution(executionId, { signal: controller.signal });
        if (cancelled) return;
        setData(result);
        if (TERMINAL_STATUSES.has(result.job_status)) {
          setPolling(false);
          return;
        }
        timeoutId = setTimeout(() => void tick(), POLL_INTERVAL_MS);
      } catch (err) {
        if (cancelled || controller.signal.aborted) return;
        setError(describeApiError(err));
        setPolling(false);
      }
    };

    void tick();

    return () => {
      cancelled = true;
      controller.abort();
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, [executionId]);

  return { data, error, polling };
}
