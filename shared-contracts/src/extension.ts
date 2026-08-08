/**
 * Request payload originating from the VS Code extension or CLI.
 */
export interface ExtensionRequest<T = unknown> {
  id: string;
  action: string;
  payload: T;
  timestamp: string;
}

/**
 * Standardized response envelope sent back from the Keystone Orchestration Engine.
 */
export interface EngineResponse<T = unknown> {
  requestId: string;
  success: boolean;
  data?: T;
  error?: {
    code: string;
    message: string;
    details?: unknown;
  };
  timestamp: string;
}
