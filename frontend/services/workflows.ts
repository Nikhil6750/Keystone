import { apiRequest } from './api-client';
import type { WorkflowCreate, WorkflowListResponse, WorkflowRead } from '@/types/backend';

export function createWorkflow(
  data: WorkflowCreate,
  options?: { signal?: AbortSignal }
): Promise<WorkflowRead> {
  return apiRequest<WorkflowRead>('/api/v1/workflows', {
    method: 'POST',
    body: JSON.stringify(data),
    signal: options?.signal,
  });
}

export function listWorkflows(
  params: { limit?: number } = {},
  options?: { signal?: AbortSignal }
): Promise<WorkflowListResponse> {
  const query = params.limit ? `?limit=${encodeURIComponent(String(params.limit))}` : '';
  return apiRequest<WorkflowListResponse>(`/api/v1/workflows${query}`, options);
}

export function getWorkflow(
  workflowId: string,
  options?: { signal?: AbortSignal }
): Promise<WorkflowRead> {
  return apiRequest<WorkflowRead>(`/api/v1/workflows/${encodeURIComponent(workflowId)}`, options);
}

export function executeWorkflow(
  workflowId: string,
  options?: { signal?: AbortSignal }
): Promise<WorkflowRead> {
  return apiRequest<WorkflowRead>(`/api/v1/workflows/${encodeURIComponent(workflowId)}/execute`, {
    method: 'POST',
    signal: options?.signal,
  });
}

export function compensateWorkflow(
  workflowId: string,
  options?: { signal?: AbortSignal }
): Promise<WorkflowRead> {
  return apiRequest<WorkflowRead>(
    `/api/v1/workflows/${encodeURIComponent(workflowId)}/compensate`,
    { method: 'POST', signal: options?.signal }
  );
}
