import { apiRequest } from './api-client';
import type { QualityGateResultRead, QualityRunRead, QualityVerdictRead } from '@/types/backend';

export function getQualityRun(
  runId: string,
  options?: { signal?: AbortSignal }
): Promise<QualityRunRead> {
  return apiRequest<QualityRunRead>(`/api/v1/quality/runs/${encodeURIComponent(runId)}`, options);
}

export function getQualityRunGates(
  runId: string,
  options?: { signal?: AbortSignal }
): Promise<QualityGateResultRead[]> {
  return apiRequest<QualityGateResultRead[]>(
    `/api/v1/quality/runs/${encodeURIComponent(runId)}/gates`,
    options
  );
}

export function getQualityRunVerdict(
  runId: string,
  options?: { signal?: AbortSignal }
): Promise<QualityVerdictRead> {
  return apiRequest<QualityVerdictRead>(
    `/api/v1/quality/runs/${encodeURIComponent(runId)}/verdict`,
    options
  );
}
