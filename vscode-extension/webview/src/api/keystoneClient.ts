import { KEYSTONE_API_BASE_URL, KEYSTONE_API_PREFIX } from './config';
import type {
  ConnectedAgentSummary,
  OrchestrationEvent,
  OrchestrationExecutionAccepted,
  OrchestrationExecutionRead,
} from '../types/keystone';

/**
 * Thrown only for a network-level failure (connection refused, DNS
 * failure, CSP rejection) -- never for a normal HTTP error response, which
 * means the backend *is* reachable and answered. The raw underlying error
 * is kept on `cause` for developer diagnostics only; nothing in this
 * module ever renders `cause` to the user (see `BackendUnavailable.tsx`).
 */
export class BackendUnavailableError extends Error {
  constructor(cause?: unknown) {
    super('Keystone backend is unavailable.');
    this.name = 'BackendUnavailableError';
    if (cause !== undefined) {
      this.cause = cause;
    }
  }
}

function apiUrl(path: string): string {
  return `${KEYSTONE_API_BASE_URL}${KEYSTONE_API_PREFIX}${path}`;
}

async function safeFetch(input: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch (err) {
    throw new BackendUnavailableError(err);
  }
}

/**
 * Returns the currently connected, enabled agents. The dynamic-connection
 * API (Stage 8C.3A) is not present on every backend yet -- a `404` is
 * treated as "zero agents" (the server responded; it just doesn't have
 * this route deployed), never as "backend unavailable". Only a genuine
 * network failure (`BackendUnavailableError`) propagates.
 */
export async function fetchConnectedAgents(): Promise<ConnectedAgentSummary[]> {
  const response = await safeFetch(apiUrl('/connected-agents'));
  if (!response.ok) {
    return [];
  }
  const body = (await response.json()) as unknown;
  return Array.isArray(body) ? (body as ConnectedAgentSummary[]) : [];
}

/**
 * Starts one orchestration execution. `availableAgentTypes` is the full
 * set of currently connected agent IDs -- Keystone's Router decides which
 * of them to use; the caller never picks one in advance.
 */
export async function startOrchestration(
  goal: string,
  availableAgentTypes: string[]
): Promise<OrchestrationExecutionAccepted> {
  const response = await safeFetch(apiUrl('/orchestrations'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      goal,
      available_agent_types: availableAgentTypes,
    }),
  });
  if (!response.ok) {
    throw new Error(`Keystone rejected the request (HTTP ${response.status}).`);
  }
  return (await response.json()) as OrchestrationExecutionAccepted;
}

export async function fetchOrchestrationResult(
  executionId: string
): Promise<OrchestrationExecutionRead> {
  const response = await safeFetch(apiUrl(`/orchestrations/${encodeURIComponent(executionId)}`));
  if (!response.ok) {
    throw new Error(`Unable to read the execution result (HTTP ${response.status}).`);
  }
  return (await response.json()) as OrchestrationExecutionRead;
}

export interface OrchestrationEventStreamHandlers {
  onEvent: (event: OrchestrationEvent) => void;
  onError?: (error: unknown) => void;
}

const KNOWN_EVENT_TYPES: OrchestrationEvent['event_type'][] = [
  'execution.accepted',
  'execution.started',
  'knowledge.started',
  'knowledge.completed',
  'manager.started',
  'manager.completed',
  'manager.fallback',
  'planning.completed',
  'routing.started',
  'routing.task_selected',
  'routing.failed',
  'workflow.created',
  'workflow.started',
  'step.started',
  'step.completed',
  'step.failed',
  'verification.started',
  'verification.completed',
  'recovery.started',
  'recovery.completed',
  'recovery.exhausted',
  'learning.completed',
  'retrieval_feedback.completed',
  'execution.completed',
  'execution.failed',
  'execution.cancelled',
];

/**
 * Subscribes to `GET /orchestrations/{id}/events` (Server-Sent Events).
 * Returns an unsubscribe function. Every event is parsed into the bounded,
 * already-safe `OrchestrationEvent` shape before it ever reaches a
 * component -- nothing here forwards a raw SSE payload string.
 */
export function subscribeToOrchestrationEvents(
  executionId: string,
  handlers: OrchestrationEventStreamHandlers
): () => void {
  const url = apiUrl(`/orchestrations/${encodeURIComponent(executionId)}/events`);
  const source = new EventSource(url);

  const listener = (message: MessageEvent<string>): void => {
    try {
      const parsed = JSON.parse(message.data) as OrchestrationEvent;
      handlers.onEvent(parsed);
    } catch (err) {
      handlers.onError?.(err);
    }
  };

  for (const eventType of KNOWN_EVENT_TYPES) {
    source.addEventListener(eventType, listener as EventListener);
  }

  source.onerror = (event): void => {
    handlers.onError?.(event);
  };

  return () => {
    source.close();
  };
}
