import { ApiClient } from './ApiClient';
import type { AgentItem } from './MockProvider';

export class AgentApi {
  public static async fetchAgents(): Promise<AgentItem[]> {
    const res = await ApiClient.get<AgentItem[]>('/agents');
    return res.data;
  }

  public static async verifyConnection(agentId: string): Promise<AgentItem> {
    const res = await ApiClient.post<AgentItem>(`/agents/${agentId}/verify`);
    return res.data;
  }
}
