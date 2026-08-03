'use client';

import * as React from 'react';
import { RefreshCw } from 'lucide-react';
import { useCircuitBreakers } from '@/hooks/use-circuit-breakers';
import { circuitBreakerStateLabel, circuitBreakerStateTone } from '@/lib/presentation';
import { ToneBadge } from '@/components/workflow/tone-badge';
import { Skeleton } from '@/components/ui';
import { InlineError, describeError } from '@/components/common/inline-error';

export const CircuitBreakerList: React.FC = () => {
  const { data, loading, error, refresh } = useCircuitBreakers();

  return (
    <div className="space-y-3 rounded-xl border border-white/[0.08] bg-white/[0.03] p-5">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-xs font-bold text-white">Circuit Breakers</h3>
          <p className="text-[11px] text-zinc-400">
            A breaker is created lazily the first time its agent type is used. There is no reset
            endpoint — a restart of the backend process is the only reset in this prototype.
          </p>
        </div>
        <button
          type="button"
          onClick={refresh}
          className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-zinc-300 hover:bg-white/[0.08] hover:text-white"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          <span>Refresh</span>
        </button>
      </div>

      {loading && (
        <div className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      )}

      {!loading && error && (
        <InlineError message={describeError(error).body} onRetry={refresh} />
      )}

      {!loading && !error && data && data.items.length === 0 && (
        <p className="rounded-lg border border-dashed border-white/[0.08] p-4 text-center text-xs text-zinc-500">
          No circuit breakers created yet — none of the registered agents have been called.
        </p>
      )}

      {!loading && !error && data && data.items.length > 0 && (
        <div className="space-y-2">
          {data.items.map((breaker) => (
            <div
              key={breaker.agent_type}
              className="grid grid-cols-2 gap-2 rounded-lg border border-white/[0.08] bg-white/[0.02] p-3 text-[11px] sm:grid-cols-4"
            >
              <div className="col-span-2 flex items-center justify-between sm:col-span-1">
                <span className="font-semibold text-white">{breaker.agent_type}</span>
                <ToneBadge tone={circuitBreakerStateTone(breaker.state)}>
                  {circuitBreakerStateLabel(breaker.state)}
                </ToneBadge>
              </div>
              <span className="text-zinc-400">
                Failures: <span className="text-zinc-300">{breaker.failure_count}</span>/
                {breaker.failure_threshold}
              </span>
              <span className="text-zinc-400">
                Recovery: <span className="text-zinc-300">{breaker.recovery_timeout_seconds}s</span>
              </span>
              <span className="text-zinc-400">
                Retry after:{' '}
                <span className="text-zinc-300">{breaker.retry_after_seconds.toFixed(1)}s</span>
                {breaker.half_open_probe_in_flight && (
                  <span className="ml-1 text-amber-400">(probe in flight)</span>
                )}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
