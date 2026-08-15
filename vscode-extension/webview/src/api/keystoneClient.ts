import { vscodeApi } from '../services/vscodeApi';
import type {
  AgentConnection,
  AgentConnectionCreateInput,
  ConnectedAgent,
  ConnectedAgentCreateInput,
  ConnectedAgentSummary,
  DetectedRuntime,
  OrchestrationEvent,
  OrchestrationExecutionAccepted,
  OrchestrationExecutionRead,
  RuntimeActivationResult,
} from '../types/keystone';

/**
 * Thrown only for a genuine transport-level failure between the extension
 * host and the real Keystone backend (connection refused, timeout,
 * malformed/unusable response) -- never for a normal HTTP error response,
 * which means the backend *is* reachable and answered. The raw underlying
 * error is kept on `cause` for developer diagnostics only; nothing in this
 * module ever renders `cause` to the user (see `BackendUnavailable.tsx`).
 *
 * All backend calls are proxied through the extension host (see
 * `src/api/backendProxy.ts`) instead of calling `fetch`/`EventSource`
 * directly from this module. A VS Code webview's JS context runs under a
 * `vscode-webview://<random-uuid>` origin that is minted fresh every
 * session, so it can never be added to a static backend CORS allowlist --
 * a direct cross-origin request from here would be rejected by the browser
 * even when the backend answers 200. The extension host is a plain Node.js
 * process, not subject to browser CORS, so it performs the real request
 * and relays only the already-safe, already-typed result back here.
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

const REQUEST_TIMEOUT_MS = 15000;

interface ApiResponseMessage {
  type: 'KEYSTONE_API_RESPONSE';
  requestId: string;
  networkError: boolean;
  ok: boolean;
  status: number;
  body: unknown;
}

interface SseEventMessage {
  type: 'KEYSTONE_SSE_EVENT';
  subscriptionId: string;
  eventType: string;
  data: string;
}

interface SseErrorMessage {
  type: 'KEYSTONE_SSE_ERROR';
  subscriptionId: string;
}

interface SseDoneMessage {
  type: 'KEYSTONE_SSE_DONE';
  subscriptionId: string;
}

type HostMessage = ApiResponseMessage | SseEventMessage | SseErrorMessage | SseDoneMessage;

function isHostMessage(data: unknown): data is HostMessage {
  return (
    typeof data === 'object' &&
    data !== null &&
    typeof (data as { type?: unknown }).type === 'string' &&
    (data as { type: string }).type.startsWith('KEYSTONE_')
  );
}

interface PendingRequest {
  resolve: (response: ApiResponseMessage) => void;
  timeoutHandle: ReturnType<typeof setTimeout>;
}

const pendingRequests = new Map<string, PendingRequest>();

interface SseSubscription {
  onEvent: (event: OrchestrationEvent) => void;
  onError?: (error: unknown) => void;
}

const activeSseSubscriptions = new Map<string, SseSubscription>();

let listenerInstalled = false;

function ensureListener(): void {
  if (listenerInstalled) {
    return;
  }
  listenerInstalled = true;

  window.addEventListener('message', (event: MessageEvent<unknown>) => {
    const data = event.data;
    if (!isHostMessage(data)) {
      return;
    }

    if (data.type === 'KEYSTONE_API_RESPONSE') {
      const pending = pendingRequests.get(data.requestId);
      if (!pending) {
        return;
      }
      pendingRequests.delete(data.requestId);
      clearTimeout(pending.timeoutHandle);
      pending.resolve(data);
      return;
    }

    if (data.type === 'KEYSTONE_SSE_EVENT') {
      const subscription = activeSseSubscriptions.get(data.subscriptionId);
      if (!subscription) {
        return;
      }
      try {
        const parsed = JSON.parse(data.data) as OrchestrationEvent;
        subscription.onEvent(parsed);
      } catch (err) {
        subscription.onError?.(err);
      }
      return;
    }

    if (data.type === 'KEYSTONE_SSE_ERROR') {
      activeSseSubscriptions.get(data.subscriptionId)?.onError?.(
        new Error('Keystone event stream disconnected.')
      );
    }
  });
}

function nextId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/**
 * Sends one request/response API call through the extension host. Resolves
 * with the raw response envelope for any answered request (even a non-2xx
 * one, which is a real backend answer, not an availability problem).
 * Rejects with `BackendUnavailableError` only for a genuine transport
 * failure (relayed `networkError: true`) or for a request that never gets
 * a response at all within `REQUEST_TIMEOUT_MS`.
 */
type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE';

function apiRequest(method: HttpMethod, path: string, body?: unknown): Promise<ApiResponseMessage> {
  ensureListener();
  const requestId = nextId();

  return new Promise<ApiResponseMessage>((resolve, reject) => {
    const timeoutHandle = setTimeout(() => {
      pendingRequests.delete(requestId);
      reject(new BackendUnavailableError(new Error('Timed out waiting for the Keystone backend.')));
    }, REQUEST_TIMEOUT_MS);

    pendingRequests.set(requestId, { resolve, timeoutHandle });

    vscodeApi.postMessage({
      type: 'KEYSTONE_API_REQUEST',
      requestId,
      method,
      path,
      body,
    });
  }).then((response) => {
    if (response.networkError) {
      throw new BackendUnavailableError();
    }
    return response;
  });
}

/**
 * Returns the currently connected, enabled agents. The real backend
 * contract (`GET /api/v1/connected-agents`) returns a plain JSON array --
 * `[]` for an empty registry, never a wrapped object -- but this stays
 * defensive against an unexpected shape rather than throwing, since an
 * unusual-but-successful response is still not a backend-availability
 * problem.
 */
export async function fetchConnectedAgents(): Promise<ConnectedAgentSummary[]> {
  const response = await apiRequest('GET', '/connected-agents');
  if (!response.ok) {
    return [];
  }
  const body = response.body;
  return Array.isArray(body) ? (body as ConnectedAgentSummary[]) : [];
}

/**
 * Installed/configured runtime *adapter* availability (`GET /api/v1/
 * agents`) -- never a user-created agent identity (see
 * `fetchConnectedAgents`). Drives the "Installed / Sign in" category's
 * runtime list: what Keystone can detect on this machine, truthfully,
 * before the user has connected anything.
 */
export async function fetchDetectedRuntimes(): Promise<DetectedRuntime[]> {
  const response = await apiRequest('GET', '/agents');
  if (!response.ok) {
    return [];
  }
  const body = response.body as { items?: unknown } | null;
  return body && Array.isArray(body.items) ? (body.items as DetectedRuntime[]) : [];
}

/**
 * Deliberately activates one detected-but-not-yet-enabled installed
 * runtime (Connect Agent -> Installed / Sign in -> Connect). Never
 * fabricates success: the backend only registers the runtime if its
 * executable is genuinely found on PATH, then runs one real verification
 * and returns truthful installation/authentication/connection status.
 */
export async function activateRuntime(runtimeId: string): Promise<RuntimeActivationResult> {
  const response = await apiRequest('POST', `/runtime-connections/${encodeURIComponent(runtimeId)}/activate`);
  if (!response.ok) {
    throw new Error(`Unable to activate '${runtimeId}' (HTTP ${response.status}).`);
  }
  return response.body as RuntimeActivationResult;
}

export async function fetchAgentConnections(): Promise<AgentConnection[]> {
  const response = await apiRequest('GET', '/agent-connections');
  if (!response.ok) {
    return [];
  }
  return Array.isArray(response.body) ? (response.body as AgentConnection[]) : [];
}

/**
 * Registers a new integration connection. `input` is a plain, already-
 * validated metadata payload -- see `AgentConnectionCreateInput`'s own
 * type: there is no field here a caller could put a credential into. A
 * real BYOK credential never reaches this function; it stays in VS Code
 * `SecretStorage` via the extension host (see `secretsClient.ts`).
 */
/**
 * The real backend error message/code (`{error:{code,message}}}`, see
 * `app.schemas.errors.APIErrorEnvelope`) when the response body carries
 * one, so a 400/404/409/422/500 reads as an actual, specific reason
 * (Stage 8C.3 error taxonomy) instead of a bare "HTTP 409" -- falling
 * back to that generic form only when the body doesn't have one.
 */
function backendErrorMessage(response: ApiResponseMessage, fallback: string): string {
  const body = response.body as { error?: { message?: string } } | null;
  return body?.error?.message || fallback;
}

export async function createAgentConnection(input: AgentConnectionCreateInput): Promise<AgentConnection> {
  const response = await apiRequest('POST', '/agent-connections', input);
  if (!response.ok) {
    throw new Error(backendErrorMessage(response, `Unable to create connection (HTTP ${response.status}).`));
  }
  return response.body as AgentConnection;
}

export async function deleteAgentConnection(connectionId: string): Promise<void> {
  const response = await apiRequest('DELETE', `/agent-connections/${encodeURIComponent(connectionId)}`);
  if (!response.ok) {
    throw new Error(
      backendErrorMessage(response, `Unable to delete connection '${connectionId}' (HTTP ${response.status}).`)
    );
  }
}

/** Registers a new Keystone agent identity backed by an existing
 * connection. Capabilities must come from the caller's own already-
 * truthful source (e.g. a `DetectedRuntime.capabilities` list) -- this
 * function never invents or defaults a capability list. */
export async function createConnectedAgent(input: ConnectedAgentCreateInput): Promise<ConnectedAgent> {
  const response = await apiRequest('POST', '/connected-agents', input);
  if (!response.ok) {
    throw new Error(backendErrorMessage(response, `Unable to create agent (HTTP ${response.status}).`));
  }
  return response.body as ConnectedAgent;
}

export async function updateConnectedAgent(
  agentId: string,
  updates: { enabled?: boolean; display_name?: string }
): Promise<ConnectedAgent> {
  const response = await apiRequest(
    'PATCH',
    `/connected-agents/${encodeURIComponent(agentId)}`,
    updates
  );
  if (!response.ok) {
    throw new Error(
      backendErrorMessage(response, `Unable to update agent '${agentId}' (HTTP ${response.status}).`)
    );
  }
  return response.body as ConnectedAgent;
}

export async function deleteConnectedAgent(agentId: string): Promise<void> {
  const response = await apiRequest('DELETE', `/connected-agents/${encodeURIComponent(agentId)}`);
  if (!response.ok) {
    throw new Error(
      backendErrorMessage(response, `Unable to remove agent '${agentId}' (HTTP ${response.status}).`)
    );
  }
}

/**
 * Starts one orchestration execution. `availableAgentTypes` is the full
 * set of currently connected agent IDs -- Keystone's Router decides which
 * of them to use; the caller never picks one in advance. `workspace_root`
 * is never set here -- the extension host (`backendProxy.ts`) injects the
 * real currently-open VS Code workspace folder itself, since the webview
 * has no access to that API and must never guess or derive one from
 * `goal`.
 */
export async function startOrchestration(
  goal: string,
  availableAgentTypes: string[]
): Promise<OrchestrationExecutionAccepted> {
  const response = await apiRequest('POST', '/orchestrations', {
    goal,
    available_agent_types: availableAgentTypes,
  });
  if (!response.ok) {
    throw new Error(backendErrorMessage(response, `Keystone rejected the request (HTTP ${response.status}).`));
  }
  return response.body as OrchestrationExecutionAccepted;
}

export async function fetchOrchestrationResult(
  executionId: string
): Promise<OrchestrationExecutionRead> {
  const response = await apiRequest('GET', `/orchestrations/${encodeURIComponent(executionId)}`);
  if (!response.ok) {
    throw new Error(
      backendErrorMessage(response, `Unable to read the execution result (HTTP ${response.status}).`)
    );
  }
  return response.body as OrchestrationExecutionRead;
}

export interface OrchestrationEventStreamHandlers {
  onEvent: (event: OrchestrationEvent) => void;
  onError?: (error: unknown) => void;
}

/**
 * Subscribes to `GET /orchestrations/{id}/events` (Server-Sent Events),
 * relayed through the extension host. Returns an unsubscribe function.
 * Every event is parsed into the bounded, already-safe `OrchestrationEvent`
 * shape before it ever reaches a component -- nothing here forwards a raw
 * payload beyond what the backend's own SSE `data:` field already
 * contained.
 */
export function subscribeToOrchestrationEvents(
  executionId: string,
  handlers: OrchestrationEventStreamHandlers
): () => void {
  ensureListener();
  const subscriptionId = nextId();
  activeSseSubscriptions.set(subscriptionId, handlers);

  vscodeApi.postMessage({
    type: 'KEYSTONE_SSE_SUBSCRIBE',
    subscriptionId,
    path: `/orchestrations/${encodeURIComponent(executionId)}/events`,
  });

  return () => {
    activeSseSubscriptions.delete(subscriptionId);
    vscodeApi.postMessage({ type: 'KEYSTONE_SSE_UNSUBSCRIBE', subscriptionId });
  };
}
