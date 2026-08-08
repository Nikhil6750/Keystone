import type { ExtensionRequest, EngineResponse } from '../../../shared-contracts/src';

/**
 * Placeholder API contract boundary for communicating with Keystone backend engine.
 */
export class EngineClient {
  public async sendRequest<TPayload, TResult>(
    action: string,
    payload: TPayload
  ): Promise<EngineResponse<TResult>> {
    const request: ExtensionRequest<TPayload> = {
      id: String(Date.now()),
      action,
      payload,
      timestamp: new Date().toISOString(),
    };

    return {
      requestId: request.id,
      success: true,
      timestamp: new Date().toISOString(),
    };
  }
}
