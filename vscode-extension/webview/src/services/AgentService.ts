import { AgentApi } from '../api/AgentApi';
import type { AgentItem } from '../api/MockProvider';

export class AgentService {
  public static async listAgents(): Promise<AgentItem[]> {
    return AgentApi.fetchAgents();
  }

  public static async verifyAgent(agentId: string): Promise<AgentItem> {
    return AgentApi.verifyConnection(agentId);
  }
}
