import type {
  OrchestrationExecutionCreate,
  OrchestrationExecutionAccepted,
  OrchestrationExecutionRead,
  OrchestrationEventRead,
} from '../../../shared-contracts/src';
import { Logger } from '../utils/logger';

export interface OrchestrationApiClientConfig {
  baseUrl?: string;
  fetchFn?: typeof fetch;
}

export interface AgentStatusInfo {
  id: string;
  name: string;
  type: string;
  status: string;
  capabilities: string[];
}

const TERMINAL_EVENT_TYPES = new Set([
  'execution.completed',
  'execution.failed',
  'execution.cancelled',
]);

/**
 * Stage 8C.3a Real HTTP REST & SSE API Client for Keystone Backend Engine.
 *
 * Fully supports provider-neutral, dynamic agent string identifiers,
 * asynchronous 202 orchestration POST creation, status polling, and live
 * SSE event streaming.
 */
export class OrchestrationApiClient {
  private baseUrl: string;
  private fetchFn: typeof fetch;

  constructor(config?: OrchestrationApiClientConfig) {
    const rawUrl = config?.baseUrl || 'http://127.0.0.1:8000';
    this.baseUrl = rawUrl.replace(/\/+$/, '');
    this.fetchFn = config?.fetchFn || globalThis.fetch;
  }

  public setBaseUrl(url: string): void {
    this.baseUrl = url.replace(/\/+$/, '');
  }

  public getBaseUrl(): string {
    return this.baseUrl;
  }

  /**
   * Submits a new orchestration request to `POST /api/v1/orchestrations`.
   * Returns immediately with `202 Accepted` and execution urls.
   */
  public async createOrchestration(
    request: OrchestrationExecutionCreate
  ): Promise<OrchestrationExecutionAccepted> {
    const url = `${this.baseUrl}/api/v1/orchestrations`;
    Logger.info(`[OrchestrationApiClient] Posting execution request to ${url}`);

    const response = await this.fetchFn(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      const errorText = await response.text().catch(() => '');
      Logger.error(`[OrchestrationApiClient] POST failed status=${response.status}: ${errorText}`);
      throw new Error(
        `Failed to start orchestration (${response.status}): ${errorText || response.statusText}`
      );
    }

    const data: OrchestrationExecutionAccepted = await response.json();
    return data;
  }

  /**
   * Retrieves status and result for an execution via `GET /api/v1/orchestrations/{execution_id}`.
   */
  public async getOrchestrationStatus(
    executionId: string
  ): Promise<OrchestrationExecutionRead> {
    const url = `${this.baseUrl}/api/v1/orchestrations/${encodeURIComponent(executionId)}`;
    const response = await this.fetchFn(url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
    });

    if (!response.ok) {
      const errorText = await response.text().catch(() => '');
      throw new Error(
        `Failed to get orchestration status (${response.status}): ${errorText || response.statusText}`
      );
    }

    const data: OrchestrationExecutionRead = await response.json();
    return data;
  }

  /**
   * Lists available agent capabilities and types from backend.
   */
  public async getAgents(): Promise<AgentStatusInfo[]> {
    const url = `${this.baseUrl}/api/v1/agents`;
    try {
      const response = await this.fetchFn(url, {
        method: 'GET',
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) return [];
      return await response.json();
    } catch (err) {
      Logger.warn(`[OrchestrationApiClient] Failed to fetch agents: ${err}`);
      return [];
    }
  }

  /**
   * Triggers verification for a specific agent.
   */
  public async verifyAgent(agentId: string): Promise<boolean> {
    const url = `${this.baseUrl}/api/v1/agents/${encodeURIComponent(agentId)}/verify`;
    try {
      const response = await this.fetchFn(url, {
        method: 'POST',
        headers: { Accept: 'application/json' },
      });
      return response.ok;
    } catch (err) {
      Logger.warn(`[OrchestrationApiClient] Agent verification call failed: ${err}`);
      return false;
    }
  }

  /**
   * Subscribes to live SSE events from `GET /api/v1/orchestrations/{execution_id}/events`.
   * Returns an unsubscribe function to abort the stream listener.
   */
  public subscribeToEvents(
    executionId: string,
    onEvent: (event: OrchestrationEventRead) => void,
    onError?: (err: Error) => void,
    onComplete?: () => void
  ): () => void {
    const url = `${this.baseUrl}/api/v1/orchestrations/${encodeURIComponent(executionId)}/events`;
    const controller = new AbortController();

    (async () => {
      try {
        const response = await this.fetchFn(url, {
          method: 'GET',
          headers: { Accept: 'text/event-stream' },
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`SSE stream failed HTTP ${response.status}`);
        }

        if (!response.body) {
          throw new Error('SSE response body missing');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (!controller.signal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          while (buffer.includes('\n\n')) {
            const index = buffer.indexOf('\n\n');
            const frame = buffer.slice(0, index);
            buffer = buffer.slice(index + 2);

            if (!frame.trim() || frame.startsWith(':')) {
              // Comment or heartbeat
              continue;
            }

            const parsedEvent = this.parseSseFrame(frame);
            if (parsedEvent) {
              onEvent(parsedEvent);
              if (TERMINAL_EVENT_TYPES.has(parsedEvent.event_type)) {
                controller.abort();
                if (onComplete) onComplete();
                return;
              }
            }
          }
        }
        if (onComplete) onComplete();
      } catch (err: unknown) {
        if (controller.signal.aborted) return; // intentional abort
        const error = err instanceof Error ? err : new Error(String(err));
        Logger.error(`[OrchestrationApiClient] SSE stream error: ${error.message}`);
        if (onError) onError(error);
      }
    })();

    return () => {
      controller.abort();
    };
  }

  /**
   * Helper function to parse an SSE text frame into `OrchestrationEventRead`.
   */
  public parseSseFrame(frame: string): OrchestrationEventRead | null {
    let dataStr: string | null = null;

    for (const line of frame.split('\n')) {
      if (line.startsWith('data: ')) {
        dataStr = line.slice(6);
      }
    }

    if (!dataStr) return null;

    try {
      return JSON.parse(dataStr) as OrchestrationEventRead;
    } catch {
      return null;
    }
  }
}
