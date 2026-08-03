import { APP_CONFIG } from '@/lib/constants';
import type { APIErrorCode, APIErrorEnvelope } from '@/types/backend';

const DEFAULT_TIMEOUT_MS = 15_000;

/**
 * A single typed request boundary the browser uses to talk to the Keystone
 * FastAPI backend. Never used for a provider (Claude/Codex/Gemini) request —
 * those only ever happen server-side, on the machine running the backend.
 */
export class ApiClientError extends Error {
  /** The backend's stable error code (see `docs/api-contract.md`), or a
   * client-side synthetic code (`NETWORK_ERROR`, `TIMEOUT`, `PARSE_ERROR`)
   * when the failure never reached a parsed backend error envelope. */
  code: APIErrorCode | 'NETWORK_ERROR' | 'TIMEOUT' | 'PARSE_ERROR';
  details: unknown;
  status: number;

  constructor(
    message: string,
    code: APIErrorCode | 'NETWORK_ERROR' | 'TIMEOUT' | 'PARSE_ERROR',
    status: number,
    details?: unknown
  ) {
    super(message);
    this.name = 'ApiClientError';
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

function isErrorEnvelope(value: unknown): value is APIErrorEnvelope {
  if (typeof value !== 'object' || value === null || !('error' in value)) return false;
  const candidate = (value as { error?: unknown }).error;
  return (
    typeof candidate === 'object' &&
    candidate !== null &&
    'code' in candidate &&
    'message' in candidate
  );
}

function normalizePath(endpoint: string): string {
  return endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
}

export interface RequestOptions extends Omit<RequestInit, 'signal'> {
  /** Caller-supplied abort signal, combined with the internal request timeout. */
  signal?: AbortSignal;
  /** Aborts the request after this many milliseconds. Defaults to 15s. */
  timeoutMs?: number;
}

/**
 * Issue one JSON request against the Keystone backend and return its parsed,
 * typed body. Never retries automatically — retry semantics belong to the
 * backend's own resilience layer, not the browser.
 */
export async function apiRequest<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const { signal, timeoutMs = DEFAULT_TIMEOUT_MS, headers, ...rest } = options;
  const url = `${APP_CONFIG.apiBaseUrl}${normalizePath(endpoint)}`;

  const timeoutController = new AbortController();
  const timeoutId = setTimeout(() => timeoutController.abort(), timeoutMs);

  const combinedSignal = signal
    ? AbortSignal.any([signal, timeoutController.signal])
    : timeoutController.signal;

  const requestHeaders = new Headers(headers);
  if (!requestHeaders.has('Content-Type') && rest.body !== undefined) {
    requestHeaders.set('Content-Type', 'application/json');
  }
  requestHeaders.set('Accept', 'application/json');

  let response: Response;
  try {
    response = await fetch(url, {
      ...rest,
      headers: requestHeaders,
      signal: combinedSignal,
    });
  } catch (cause) {
    if (timeoutController.signal.aborted) {
      throw new ApiClientError('The request to the backend timed out.', 'TIMEOUT', 0);
    }
    if (cause instanceof DOMException && cause.name === 'AbortError') {
      throw cause;
    }
    throw new ApiClientError(
      'Could not reach the Keystone backend. Confirm it is running and reachable at ' +
        `${APP_CONFIG.apiBaseUrl}.`,
      'NETWORK_ERROR',
      0
    );
  } finally {
    clearTimeout(timeoutId);
  }

  // 204/empty bodies (none of the current endpoints return one, but this
  // keeps the client correct if one is added later).
  const rawText = await response.text();
  const parsed: unknown = rawText.length > 0 ? safeJsonParse(rawText) : null;

  if (!response.ok) {
    if (isErrorEnvelope(parsed)) {
      throw new ApiClientError(
        parsed.error.message,
        parsed.error.code,
        response.status,
        parsed.error.details
      );
    }
    throw new ApiClientError(
      response.statusText || `Backend returned HTTP ${response.status}.`,
      'INTERNAL_ERROR',
      response.status
    );
  }

  return parsed as T;
}

function safeJsonParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    throw new ApiClientError('The backend returned a response that was not valid JSON.', 'PARSE_ERROR', 0);
  }
}

/** A safe, user-facing message for any error this client can throw — never a raw stack trace. */
export function describeApiError(error: unknown): string {
  if (error instanceof ApiClientError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return 'An unexpected error occurred.';
}
