import type { RequestStatus, RequestStateModel } from './RequestTypes';

export class RequestState implements RequestStateModel {
  public requestId: string;
  public endpoint: string;
  public method: 'GET' | 'POST' | 'PUT' | 'DELETE';
  public status: RequestStatus;
  public startedAt: string;
  public finishedAt?: string;
  public durationMs?: number;
  public error?: string;
  public isCancelled?: boolean;

  private startTimeStamp: number;

  constructor(
    requestId: string,
    endpoint: string,
    method: 'GET' | 'POST' | 'PUT' | 'DELETE' = 'GET'
  ) {
    this.requestId = requestId;
    this.endpoint = endpoint;
    this.method = method;
    this.status = 'idle';
    this.startTimeStamp = Date.now();
    this.startedAt = new Date().toISOString();
  }

  public markLoading(): void {
    this.status = 'loading';
    this.startTimeStamp = Date.now();
    this.startedAt = new Date().toISOString();
  }

  public markSuccess(): void {
    this.status = 'success';
    const now = Date.now();
    this.finishedAt = new Date().toISOString();
    this.durationMs = now - this.startTimeStamp;
  }

  public markError(errorMsg: string): void {
    this.status = 'error';
    const now = Date.now();
    this.finishedAt = new Date().toISOString();
    this.durationMs = now - this.startTimeStamp;
    this.error = errorMsg;
  }

  public cancel(reason = 'Request cancelled by user'): void {
    this.isCancelled = true;
    this.markError(reason);
  }
}
