import { useState, useMemo, useCallback } from 'react';
import { INITIAL_AGENTS, type AgentItem } from '../mock/agents';
import { useAppState } from './useAppState';

export function useAgentManager() {
  const { selectedAgentId, setSelectedAgentId, pushNotification } = useAppState();
  const [agents, setAgents] = useState<AgentItem[]>(INITIAL_AGENTS);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [verifyingAgentIds, setVerifyingAgentIds] = useState<Set<string>>(new Set());

  const selectedAgent = useMemo(
    () => agents.find((a) => a.id === selectedAgentId) || null,
    [agents, selectedAgentId]
  );

  const filteredAgents = useMemo(() => {
    if (!searchQuery.trim()) return agents;
    const query = searchQuery.toLowerCase().trim();
    return agents.filter(
      (agent) =>
        agent.name.toLowerCase().includes(query) ||
        agent.type.toLowerCase().includes(query) ||
        agent.capabilities.some((c) => c.toLowerCase().includes(query))
    );
  }, [agents, searchQuery]);

  const verifyConnection = useCallback(
    (agentId: string) => {
      setVerifyingAgentIds((prev) => new Set(prev).add(agentId));

      setTimeout(() => {
        let updatedAgentName = 'Agent';
        setAgents((prevAgents) =>
          prevAgents.map((agent) => {
            if (agent.id === agentId) {
              updatedAgentName = agent.name;
              const now = new Date();
              const formattedDate = `${now.getFullYear()}-${String(
                now.getMonth() + 1
              ).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${String(
                now.getHours()
              ).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(
                now.getSeconds()
              ).padStart(2, '0')}`;

              return {
                ...agent,
                connectionStatus: 'Connected',
                authenticationStatus: 'Authenticated',
                lastVerifiedAt: formattedDate,
              };
            }
            return agent;
          })
        );

        setVerifyingAgentIds((prev) => {
          const next = new Set(prev);
          next.delete(agentId);
          return next;
        });

        pushNotification(
          'success',
          `Connection verified for ${updatedAgentName}. Status: Connected.`,
          'Verification Success'
        );
      }, 1200);
    },
    [pushNotification]
  );

  return {
    searchQuery,
    setSearchQuery,
    selectedAgent,
    setSelectedAgentId,
    filteredAgents,
    verifyingAgentIds,
    verifyConnection,
  };
}
