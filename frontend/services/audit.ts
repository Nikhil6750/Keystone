import { apiRequest } from './api-client';
import type {
  AuditChainVerificationRead,
  AuditEventListResponse,
  ProvenanceRead,
} from '@/types/backend';

export function listAuditEvents(
  workflowId: string,
  params: { limit?: number } = {},
  options?: { signal?: AbortSignal }
): Promise<AuditEventListResponse> {
  const query = params.limit ? `?limit=${encodeURIComponent(String(params.limit))}` : '';
  return apiRequest<AuditEventListResponse>(
    `/api/v1/workflows/${encodeURIComponent(workflowId)}/audit-events${query}`,
    options
  );
}

export function verifyAuditChain(
  workflowId: string,
  options?: { signal?: AbortSignal }
): Promise<AuditChainVerificationRead> {
  return apiRequest<AuditChainVerificationRead>(
    `/api/v1/workflows/${encodeURIComponent(workflowId)}/audit-chain/verify`,
    options
  );
}

export function getProvenance(
  workflowId: string,
  options?: { signal?: AbortSignal }
): Promise<ProvenanceRead> {
  return apiRequest<ProvenanceRead>(
    `/api/v1/workflows/${encodeURIComponent(workflowId)}/provenance`,
    options
  );
}
