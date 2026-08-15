import { apiRequest } from './api-client';
import type {
  AgentReliabilityRead,
  FailureAttributionRead,
  NodeRelationshipsRead,
  QualityGateIntelligenceRead,
  SkillReliabilityRead,
  TaskReliabilityRead,
} from '@/types/backend';

export function getNodeRelationships(
  nodeId: string,
  options?: { signal?: AbortSignal }
): Promise<NodeRelationshipsRead> {
  return apiRequest<NodeRelationshipsRead>(
    `/api/v1/intelligence/nodes/${encodeURIComponent(nodeId)}/relationships`,
    options
  );
}

export function getTaskReliability(
  params: { task_type?: string } = {},
  options?: { signal?: AbortSignal }
): Promise<TaskReliabilityRead> {
  const query = params.task_type ? `?task_type=${encodeURIComponent(params.task_type)}` : '';
  return apiRequest<TaskReliabilityRead>(`/api/v1/intelligence/tasks/reliability${query}`, options);
}

export function getAgentReliability(
  agentType: string,
  options?: { signal?: AbortSignal }
): Promise<AgentReliabilityRead> {
  return apiRequest<AgentReliabilityRead>(
    `/api/v1/intelligence/agents/${encodeURIComponent(agentType)}/reliability`,
    options
  );
}

export function getSkillReliability(
  skillId: string,
  options?: { signal?: AbortSignal }
): Promise<SkillReliabilityRead> {
  return apiRequest<SkillReliabilityRead>(
    `/api/v1/intelligence/skills/${encodeURIComponent(skillId)}/reliability`,
    options
  );
}

export function getQualityGateIntelligence(
  options?: { signal?: AbortSignal }
): Promise<QualityGateIntelligenceRead> {
  return apiRequest<QualityGateIntelligenceRead>('/api/v1/intelligence/quality/gates', options);
}

export function getFailureHistory(
  params: { agent_type?: string; task_type?: string; limit?: number } = {},
  options?: { signal?: AbortSignal }
): Promise<FailureAttributionRead[]> {
  const search = new URLSearchParams();
  if (params.agent_type) search.set('agent_type', params.agent_type);
  if (params.task_type) search.set('task_type', params.task_type);
  if (params.limit) search.set('limit', String(params.limit));
  const query = search.toString() ? `?${search.toString()}` : '';
  return apiRequest<FailureAttributionRead[]>(`/api/v1/intelligence/failures${query}`, options);
}
