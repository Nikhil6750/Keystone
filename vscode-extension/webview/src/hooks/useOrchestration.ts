import { useCallback, useRef, useState } from 'react';
import {
  fetchOrchestrationResult,
  startOrchestration,
  subscribeToOrchestrationEvents,
} from '../api/keystoneClient';
import type { OrchestrationEvent, OrchestrationExecutionRead } from '../types/keystone';
import { TERMINAL_EVENT_TYPES } from '../types/keystone';

export type OrchestrationPhase = 'idle' | 'submitting' | 'running' | 'completed' | 'failed';

export interface UseOrchestrationResult {
  phase: OrchestrationPhase;
  events: OrchestrationEvent[];
  result: OrchestrationExecutionRead | null;
  submitError: string | null;
  submit: (goal: string, availableAgentTypes: string[]) => void;
  reset: () => void;
}

/**
 * Drives one orchestration execution end to end: POST -> SSE -> GET result.
 * Never fabricates progress or a result -- every state transition here is
 * caused by a real backend response or event.
 */
export function useOrchestration(): UseOrchestrationResult {
  const [phase, setPhase] = useState<OrchestrationPhase>('idle');
  const [events, setEvents] = useState<OrchestrationEvent[]>([]);
  const [result, setResult] = useState<OrchestrationExecutionRead | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const unsubscribeRef = useRef<(() => void) | null>(null);

  const cleanup = useCallback(() => {
    unsubscribeRef.current?.();
    unsubscribeRef.current = null;
  }, []);

  const reset = useCallback(() => {
    cleanup();
    setPhase('idle');
    setEvents([]);
    setResult(null);
    setSubmitError(null);
  }, [cleanup]);

  const finalizeFromResult = useCallback((executionId: string) => {
    fetchOrchestrationResult(executionId)
      .then((finalResult) => {
        setResult(finalResult);
        setPhase(finalResult.orchestration_outcome === 'verified_success' ? 'completed' : 'failed');
      })
      .catch(() => {
        setPhase('failed');
      });
  }, []);

  const submit = useCallback(
    (goal: string, availableAgentTypes: string[]) => {
      cleanup();
      setEvents([]);
      setResult(null);
      setSubmitError(null);
      setPhase('submitting');

      startOrchestration(goal, availableAgentTypes)
        .then((accepted) => {
          setPhase('running');
          unsubscribeRef.current = subscribeToOrchestrationEvents(accepted.execution_id, {
            onEvent: (event) => {
              setEvents((prev) => [...prev, event]);
              if (TERMINAL_EVENT_TYPES.has(event.event_type)) {
                cleanup();
                finalizeFromResult(accepted.execution_id);
              }
            },
            onError: () => {
              // A stream disconnect does not by itself mean the
              // orchestration failed -- fall back to the real result.
              cleanup();
              finalizeFromResult(accepted.execution_id);
            },
          });
        })
        .catch((err: unknown) => {
          setPhase('idle');
          setSubmitError(err instanceof Error ? err.message : 'Failed to start execution.');
        });
    },
    [cleanup, finalizeFromResult]
  );

  return { phase, events, result, submitError, submit, reset };
}
