import { MockProvider } from './MockProvider';
import { RequestManager } from '../core/RequestManager';
import { vscodeApi } from '../services/vscodeApi';
import type {
  OrchestrationExecutionCreate,
  OrchestrationExecutionAccepted,
  OrchestrationExecutionRead,
  OrchestrationEventRead,
} from '../../../../shared-contracts/src';

export interface ApiResponse<T> {
  data: T;
  status: number;
  statusText: string;
}

type MessageCallback = (event: MessageEvent) => void;

/**
 * ApiClient handles request dispatching over the VS Code IPC MessageBridge
 * when available, falling back cleanly to HTTP fetch / MockProvider for standalone dev.
 */
export class ApiClient {
  private static responseListeners: Map<string, (response: any) => void> = new Map();
  private static eventSubscriptions: Map<string, (evt: OrchestrationEventRead) => void> = new Map();
  private static messageListenerInitialized = false;

  private static initMessageListener(): void {
    if (this.messageListenerInitialized) return;
    this.messageListenerInitialized = true;

    window.addEventListener('message', (event: MessageEvent) => {
      const msg = event.data;
      if (!msg) return;

      if (msg.requestId && this.responseListeners.has(msg.requestId)) {
        const callback = this.responseListeners.get(msg.requestId)!;
        this.responseListeners.delete(msg.requestId);
        callback(msg);
        return;
      }

      if (msg.type === 'ORCHESTRATION_EVENT' && msg.payload) {
        const { executionId, event: orchestrationEvent } = msg.payload;
        if (executionId && this.eventSubscriptions.has(executionId)) {
          this.eventSubscriptions.get(executionId)!(orchestrationEvent);
        }
      }
    });
  }

  public static async postOrchestration(
    request: OrchestrationExecutionCreate
  ): Promise<OrchestrationExecutionAccepted> {
    this.initMessageListener();
    const requestId = `req-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;

    return new Promise<OrchestrationExecutionAccepted>((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.responseListeners.delete(requestId);
        // Fallback simulation if IPC times out (e.g. standalone browser mode)
        resolve({
          execution_id: `exec-sim-${Date.now()}`,
          status: 'accepted',
          events_url: `/api/v1/orchestrations/exec-sim-${Date.now()}/events`,
          result_url: `/api/v1/orchestrations/exec-sim-${Date.now()}`,
        });
      }, 5000);

      this.responseListeners.set(requestId, (msg) => {
        clearTimeout(timeout);
        if (msg.success) {
          resolve(msg.payload as OrchestrationExecutionAccepted);
        } else {
          reject(new Error(msg.error || 'Failed to create orchestration'));
        }
      });

      vscodeApi.postMessage({
        action: 'CREATE_ORCHESTRATION',
        requestId,
        payload: request,
      });
    });
  }

  public static async getOrchestrationStatus(
    executionId: string
  ): Promise<OrchestrationExecutionRead> {
    this.initMessageListener();
    const requestId = `req-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;

    return new Promise<OrchestrationExecutionRead>((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.responseListeners.delete(requestId);
        reject(new Error('IPC request timed out'));
      }, 5000);

      this.responseListeners.set(requestId, (msg) => {
        clearTimeout(timeout);
        if (msg.success) {
          resolve(msg.payload as OrchestrationExecutionRead);
        } else {
          reject(new Error(msg.error || 'Failed to fetch status'));
        }
      });

      vscodeApi.postMessage({
        action: 'GET_ORCHESTRATION_STATUS',
        requestId,
        payload: { executionId },
      });
    });
  }

  public static subscribeOrchestrationEvents(
    executionId: string,
    onEvent: (event: OrchestrationEventRead) => void
  ): () => void {
    this.initMessageListener();
    this.eventSubscriptions.set(executionId, onEvent);

    vscodeApi.postMessage({
      action: 'SUBSCRIBE_EVENTS',
      payload: { executionId },
    });

    return () => {
      this.eventSubscriptions.delete(executionId);
      vscodeApi.postMessage({
        action: 'UNSUBSCRIBE_EVENTS',
        payload: { executionId },
      });
    };
  }

  public static async get<T>(endpoint: string): Promise<ApiResponse<T>> {
    const data = await RequestManager.execute<T>(
      { endpoint, method: 'GET' },
      () => this.routeMockRequest<T>('GET', endpoint)
    );
    return {
      data,
      status: 200,
      statusText: 'OK',
    };
  }

  public static async post<T>(endpoint: string, payload?: unknown): Promise<ApiResponse<T>> {
    const data = await RequestManager.execute<T>(
      { endpoint, method: 'POST', payload },
      () => this.routeMockRequest<T>('POST', endpoint, payload)
    );
    return {
      data,
      status: 200,
      statusText: 'OK',
    };
  }

  private static async routeMockRequest<T>(
    method: 'GET' | 'POST',
    endpoint: string,
    _payload?: unknown
  ): Promise<T> {
    if (endpoint === '/workflow/suggestions') {
      return (await MockProvider.getSuggestions()) as unknown as T;
    }

    if (endpoint === '/workflow/stages') {
      return (await MockProvider.getExecutionStages()) as unknown as T;
    }

    if (endpoint === '/agents') {
      return (await MockProvider.getAgents()) as unknown as T;
    }

    if (endpoint.startsWith('/agents/') && endpoint.endsWith('/verify')) {
      const parts = endpoint.split('/');
      const agentId = parts[2];
      return (await MockProvider.verifyAgent(agentId)) as unknown as T;
    }

    if (endpoint === '/knowledge') {
      return (await MockProvider.getKnowledgeDocuments()) as unknown as T;
    }

    if (endpoint === '/workspace/tree') {
      return (await MockProvider.getWorkspaceTree()) as unknown as T;
    }

    throw new Error(`Unhandled API client endpoint: ${method} ${endpoint}`);
  }
}
