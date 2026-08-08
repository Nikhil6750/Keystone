import type { RequestState } from './RequestState';

export class RequestLogger {
  public static logStarted(state: RequestState): void {
    console.info(
      `[RequestPipeline] START [${state.requestId}] ${state.method} ${state.endpoint} at ${state.startedAt}`
    );
  }

  public static logFinished(state: RequestState): void {
    console.log(
      `[RequestPipeline] SUCCESS [${state.requestId}] ${state.method} ${state.endpoint} (${state.durationMs}ms)`
    );
  }

  public static logFailed(state: RequestState, error: unknown): void {
    console.error(
      `[RequestPipeline] FAILED [${state.requestId}] ${state.method} ${state.endpoint} (${state.durationMs}ms):`,
      error
    );
  }

  public static logCancelled(state: RequestState): void {
    console.warn(
      `[RequestPipeline] CANCELLED [${state.requestId}] ${state.method} ${state.endpoint}`
    );
  }
}
