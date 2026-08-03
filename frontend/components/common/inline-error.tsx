'use client';

import * as React from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { ApiClientError } from '@/services/api-client';
import { errorCodeTitle } from '@/lib/error-messages';

export interface InlineErrorProps {
  message: string;
  onRetry?: () => void;
}

/** A persistent, page-level error — used where a transient toast alone would
 * be insufficient (e.g. the primary content of a page failed to load). */
export const InlineError: React.FC<InlineErrorProps> = ({ message, onRetry }) => {
  return (
    <div
      role="alert"
      className="flex flex-col items-center justify-center space-y-3 rounded-xl border border-rose-900/40 bg-rose-950/10 p-8 text-center"
    >
      <AlertCircle className="h-8 w-8 text-rose-400" />
      <p className="max-w-sm text-sm text-rose-200">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-zinc-300 hover:bg-white/[0.08] hover:text-white"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          <span>Retry</span>
        </button>
      )}
    </div>
  );
};

/** Formats any error this app's hooks/services can produce into a title + safe body. */
export function describeError(error: unknown): { title: string; body: string } {
  if (error instanceof ApiClientError) {
    return { title: errorCodeTitle(error.code), body: error.message };
  }
  if (typeof error === 'string') {
    return { title: 'Something went wrong', body: error };
  }
  return { title: 'Something went wrong', body: 'An unexpected error occurred.' };
}
