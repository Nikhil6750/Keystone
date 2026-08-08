import { RequestState } from './RequestState';
import { RequestLogger } from './RequestLogger';
import type { RequestConfig, CancelToken } from './RequestTypes';

export class RequestManager {
  private static requestCounter = 0;
  private static activeRequests = new Map<string, RequestState>();
  private static cancelTokens = new Map<string, CancelToken>();

  public static async execute<T>(
    config: RequestConfig,
    executor: () => Promise<T>
  ): Promise<T> {
    const requestId = this.generateRequestId();
    const state = new RequestState(requestId, config.endpoint, config.method || 'GET');

    this.activeRequests.set(requestId, state);
    state.markLoading();
    RequestLogger.logStarted(state);

    const cancelToken = this.createCancelToken(requestId);

    try {
      if (cancelToken.isCancelled) {
        state.cancel();
        RequestLogger.logCancelled(state);
        throw new Error(`Request [${requestId}] was cancelled prior to execution`);
      }

      const result = await executor();

      if (cancelToken.isCancelled) {
        state.cancel();
        RequestLogger.logCancelled(state);
        throw new Error(`Request [${requestId}] was cancelled during execution`);
      }

      state.markSuccess();
      RequestLogger.logFinished(state);
      return result;
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : String(err);
      state.markError(errorMsg);
      RequestLogger.logFailed(state, err);
      throw err;
    } finally {
      this.activeRequests.delete(requestId);
      this.cancelTokens.delete(requestId);
    }
  }

  public static generateRequestId(): string {
    this.requestCounter += 1;
    return `req-${this.requestCounter}-${Date.now().toString(36)}`;
  }

  public static getRequestState(requestId: string): RequestState | undefined {
    return this.activeRequests.get(requestId);
  }

  public static getActiveRequests(): RequestState[] {
    return Array.from(this.activeRequests.values());
  }

  public static createCancelToken(requestId: string): CancelToken {
    const token: CancelToken = {
      requestId,
      isCancelled: false,
      cancel: (reason) => {
        token.isCancelled = true;
        const state = this.activeRequests.get(requestId);
        if (state) {
          state.cancel(reason);
        }
      },
    };
    this.cancelTokens.set(requestId, token);
    return token;
  }

  public static cancelRequest(requestId: string, reason?: string): boolean {
    const token = this.cancelTokens.get(requestId);
    if (token) {
      token.cancel(reason);
      return true;
    }
    return false;
  }
}
