export type RequestStatus = 'idle' | 'loading' | 'success' | 'error';

export interface RequestStateModel {
  requestId: string;
  endpoint: string;
  method: 'GET' | 'POST' | 'PUT' | 'DELETE';
  status: RequestStatus;
  startedAt: string;
  finishedAt?: string;
  durationMs?: number;
  error?: string;
  isCancelled?: boolean;
}

export interface RequestConfig {
  endpoint: string;
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  payload?: unknown;
  headers?: Record<string, string>;
}

export interface CancelToken {
  requestId: string;
  isCancelled: boolean;
  cancel: (reason?: string) => void;
}
