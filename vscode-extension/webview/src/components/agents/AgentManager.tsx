import React from 'react';
import { AgentSearch } from './AgentSearch';
import { AgentGrid } from './AgentGrid';
import { AgentDetails } from './AgentDetails';
import { useAgentManager } from '../../hooks/useAgentManager';

export const AgentManager: React.FC = () => {
  const {
    searchQuery,
    setSearchQuery,
    selectedAgent,
    setSelectedAgentId,
    filteredAgents,
    verifyingAgentIds,
    verifyConnection,
  } = useAgentManager();

  return (
    <div className="agent-manager-container">
      <header className="builder-header">
        <h1 className="builder-title">Agent Manager</h1>
        <p className="builder-subtitle">
          Inspect, configure, and verify connected AI coding agents.
        </p>
      </header>

      <AgentSearch value={searchQuery} onChange={setSearchQuery} />

      <AgentGrid
        agents={filteredAgents}
        selectedAgentId={selectedAgent?.id || null}
        verifyingAgentIds={verifyingAgentIds}
        onSelectAgent={(id) => setSelectedAgentId(id)}
        onVerifyAgent={(id) => verifyConnection(id)}
      />

      <AgentDetails
        agent={selectedAgent}
        isVerifying={selectedAgent ? verifyingAgentIds.has(selectedAgent.id) : false}
        onClose={() => setSelectedAgentId(null)}
        onVerify={(id) => verifyConnection(id)}
      />
    </div>
  );
};
