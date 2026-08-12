import React, { useState } from 'react';
import { Power, Trash2 } from 'lucide-react';
import { deleteConnectedAgent, updateConnectedAgent } from '../../api/keystoneClient';
import type { ConnectedAgentSummary } from '../../types/keystone';

export interface AgentManagementListProps {
  agents: ConnectedAgentSummary[];
  onAgentsChanged: () => void;
}

/**
 * Minimal connected-agent management surface (Stage 8C.3 Connect Agent,
 * Phase 8): name, enabled state, and remove -- reusing the existing
 * `PATCH`/`DELETE /connected-agents/{id}` API. Never shows a secret: this
 * list is built only from `ConnectedAgentSummary` (`agent_id`,
 * `display_name`, `connection_id`, `enabled`, `capabilities`), which the
 * backend never populates with credential data to begin with.
 */
export const AgentManagementList: React.FC<AgentManagementListProps> = ({
  agents,
  onAgentsChanged,
}) => {
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (agents.length === 0) {
    return null;
  }

  const handleToggle = async (agent: ConnectedAgentSummary) => {
    setPendingId(agent.agent_id);
    setError(null);
    try {
      await updateConnectedAgent(agent.agent_id, { enabled: !agent.enabled });
      onAgentsChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to update agent.');
    } finally {
      setPendingId(null);
    }
  };

  const handleRemove = async (agent: ConnectedAgentSummary) => {
    setPendingId(agent.agent_id);
    setError(null);
    try {
      await deleteConnectedAgent(agent.agent_id);
      onAgentsChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to remove agent.');
    } finally {
      setPendingId(null);
    }
  };

  return (
    <div className="agent-management-list">
      <h3 className="agent-management-heading">Connected agents</h3>
      {error && (
        <p className="connect-error-text" role="alert">
          {error}
        </p>
      )}
      <ul className="agent-management-items">
        {agents.map((agent) => (
          <li key={agent.agent_id} className="agent-management-item">
            <span className="agent-management-name">
              {agent.display_name}
              <span className="agent-management-id"> · {agent.connection_id}</span>
            </span>
            <span className="agent-management-actions">
              <button
                type="button"
                className="keystone-icon-btn"
                aria-label={agent.enabled ? `Disable ${agent.display_name}` : `Enable ${agent.display_name}`}
                disabled={pendingId === agent.agent_id}
                onClick={() => void handleToggle(agent)}
                title={agent.enabled ? 'Disable' : 'Enable'}
              >
                <Power size={14} className={agent.enabled ? 'agent-enabled-icon' : 'agent-disabled-icon'} />
              </button>
              <button
                type="button"
                className="keystone-icon-btn"
                aria-label={`Remove ${agent.display_name}`}
                disabled={pendingId === agent.agent_id}
                onClick={() => void handleRemove(agent)}
                title="Remove"
              >
                <Trash2 size={14} />
              </button>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
};
