import { MockProvider } from './MockProvider';
import { RequestManager } from '../core/RequestManager';

export interface ApiResponse<T> {
  data: T;
  status: number;
  statusText: string;
}

/**
 * ApiClient handles request dispatching.
 * Routes all requests through RequestManager.
 */
export class ApiClient {
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
