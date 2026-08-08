import React from 'react';
import { AgentCard } from './AgentCard';
import type { AgentItem } from '../../mock/agents';
import { Bot } from 'lucide-react';

interface AgentGridProps {
  agents: AgentItem[];
  selectedAgentId: string | null;
  verifyingAgentIds: Set<string>;
  onSelectAgent: (agentId: string) => void;
  onVerifyAgent: (agentId: string, e: React.MouseEvent) => void;
}

export const AgentGrid: React.FC<AgentGridProps> = ({
  agents,
  selectedAgentId,
  verifyingAgentIds,
  onSelectAgent,
  onVerifyAgent,
}) => {
  if (agents.length === 0) {
    return (
      <div className="agent-empty-state">
        <Bot size={32} className="empty-icon" />
        <p className="empty-title">No matching agents found</p>
        <p className="empty-subtitle">Try adjusting your search filter.</p>
      </div>
    );
  }

  return (
    <div className="agent-grid">
      {agents.map((agent) => (
        <AgentCard
          key={agent.id}
          agent={agent}
          isSelected={selectedAgentId === agent.id}
          isVerifying={verifyingAgentIds.has(agent.id)}
          onSelect={onSelectAgent}
          onVerify={onVerifyAgent}
        />
      ))}
    </div>
  );
};
