'use client';

import * as React from 'react';
import { describeApiError } from '@/services/api-client';

export interface AsyncResourceState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

/**
 * Shared fetch/loading/error/refresh plumbing for the domain hooks in this
 * directory (`use-workflows`, `use-agents`, ...) so each one stays a thin,
 * focused wrapper instead of duplicating this bookkeeping. Not a general
 * state-management library — just local `useState`/`useEffect`.
 *
 * Guards against setting state after unmount and cancels the in-flight
 * request (via `AbortController`) whenever `deps` changes or the component
 * unmounts, so a slow stale response can never overwrite a newer one.
 */
export function useAsyncResource<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: React.DependencyList
): AsyncResourceState<T> {
  const [data, setData] = React.useState<T | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [refreshToken, setRefreshToken] = React.useState(0);

  React.useEffect(() => {
    const controller = new AbortController();
    let isCurrent = true;

    setLoading(true);
    setError(null);

    fetcher(controller.signal)
      .then((result) => {
        if (!isCurrent) return;
        setData(result);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!isCurrent || controller.signal.aborted) return;
        setError(describeApiError(err));
        setLoading(false);
      });

    return () => {
      isCurrent = false;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, refreshToken]);

  const refresh = React.useCallback(() => setRefreshToken((token) => token + 1), []);

  return { data, loading, error, refresh };
}
