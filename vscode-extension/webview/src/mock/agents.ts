import { MockProvider, type AgentItem } from '../api/MockProvider';

export type { AgentItem };

export let INITIAL_AGENTS: AgentItem[] = [];
MockProvider.getAgents().then((agents) => {
  INITIAL_AGENTS = agents;
});
