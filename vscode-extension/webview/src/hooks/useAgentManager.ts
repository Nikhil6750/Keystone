import { useState, useEffect, useMemo, useCallback } from 'react';
import { AgentService } from '../services/AgentService';
import type { AgentItem } from '../api/MockProvider';
import { useAppState } from './useAppState';

export function useAgentManager() {
  const { selectedAgentId, setSelectedAgentId, pushNotification } = useAppState();
  const [agents, setAgents] = useState<AgentItem[]>([]);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [verifyingAgentIds, setVerifyingAgentIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    let isMounted = true;
    AgentService.listAgents().then((items) => {
      if (isMounted) setAgents(items);
    });
    return () => {
      isMounted = false;
    };
  }, []);

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

      AgentService.verifyAgent(agentId).then((updatedAgent) => {
        setAgents((prevAgents) =>
          prevAgents.map((a) => (a.id === agentId ? updatedAgent : a))
        );

        setVerifyingAgentIds((prev) => {
          const next = new Set(prev);
          next.delete(agentId);
          return next;
        });

        pushNotification(
          'success',
          `Connection verified for ${updatedAgent.name}. Status: Connected.`,
          'Verification Success'
        );
      });
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
