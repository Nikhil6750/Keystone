import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useOrchestrationPolling } from '@/hooks/use-orchestration-polling';
import type { OrchestrationExecutionRead } from '@/types/backend';

const getOrchestrationExecution = vi.fn();

vi.mock('@/services/orchestrations', () => ({
  getOrchestrationExecution: (...args: unknown[]) => getOrchestrationExecution(...args),
}));

function execution(
  executionId: string,
  jobStatus: OrchestrationExecutionRead['job_status']
): OrchestrationExecutionRead {
  return {
    execution_id: executionId,
    job_status: jobStatus,
    orchestration_outcome: jobStatus === 'completed' ? 'verified_success' : null,
    workflow_id: null,
    final_workflow_state: null,
    verification_status: null,
    task_count: null,
    selected_agent_types: [],
    attempt_count: null,
    recovery_used: null,
    recovery_action: null,
    learning_event_count: null,
    retrieval_feedback_recorded: null,
    issue_codes: [],
    quality_run_id: null,
    quality_verdict_status: null,
    error_summary: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  getOrchestrationExecution.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useOrchestrationPolling', () => {
  it('aborts the old request and ignores its stale response when the execution ID changes', async () => {
    const oldRequest = deferred<OrchestrationExecutionRead>();
    const newRequest = deferred<OrchestrationExecutionRead>();
    getOrchestrationExecution.mockImplementation((id: string) =>
      id === 'old-id' ? oldRequest.promise : newRequest.promise
    );

    const { result, rerender } = renderHook(
      ({ executionId }) => useOrchestrationPolling(executionId),
      { initialProps: { executionId: 'old-id' } }
    );
    const oldSignal = getOrchestrationExecution.mock.calls[0][1].signal as AbortSignal;

    rerender({ executionId: 'new-id' });
    expect(oldSignal.aborted).toBe(true);

    await act(async () => newRequest.resolve(execution('new-id', 'completed')));
    expect(result.current.data?.execution_id).toBe('new-id');
    expect(result.current.polling).toBe(false);

    await act(async () => oldRequest.resolve(execution('old-id', 'completed')));
    expect(result.current.data?.execution_id).toBe('new-id');
    expect(result.current.error).toBeNull();
  });

  it('aborts the in-flight request when unmounted', () => {
    const request = deferred<OrchestrationExecutionRead>();
    getOrchestrationExecution.mockReturnValue(request.promise);

    const { unmount } = renderHook(() => useOrchestrationPolling('exec-unmount'));
    const signal = getOrchestrationExecution.mock.calls[0][1].signal as AbortSignal;

    unmount();
    expect(signal.aborted).toBe(true);
  });

  it('never overlaps polls and stops permanently on a terminal response', async () => {
    vi.useFakeTimers();
    const first = deferred<OrchestrationExecutionRead>();
    const second = deferred<OrchestrationExecutionRead>();
    getOrchestrationExecution
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    const { result } = renderHook(() => useOrchestrationPolling('exec-sequential'));
    expect(getOrchestrationExecution).toHaveBeenCalledTimes(1);

    act(() => vi.advanceTimersByTime(10_000));
    expect(getOrchestrationExecution).toHaveBeenCalledTimes(1);

    await act(async () => first.resolve(execution('exec-sequential', 'running')));
    expect(result.current.polling).toBe(true);

    act(() => vi.advanceTimersByTime(1_500));
    expect(getOrchestrationExecution).toHaveBeenCalledTimes(2);

    await act(async () => second.resolve(execution('exec-sequential', 'completed')));
    expect(result.current.polling).toBe(false);

    act(() => vi.advanceTimersByTime(10_000));
    expect(getOrchestrationExecution).toHaveBeenCalledTimes(2);
  });

  it('surfaces one polling failure and does not restart', async () => {
    getOrchestrationExecution.mockRejectedValue(new Error('backend unavailable'));

    const { result } = renderHook(() => useOrchestrationPolling('exec-offline'));
    await waitFor(() => expect(result.current.error).toBe('backend unavailable'));
    expect(result.current.polling).toBe(false);

    await new Promise((resolve) => setTimeout(resolve, 1_600));
    expect(getOrchestrationExecution).toHaveBeenCalledTimes(1);
  });
});
