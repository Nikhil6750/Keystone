import React from 'react';
import { Settings, History } from 'lucide-react';

export interface KeystoneHeaderProps {
  connectedAgentCount: number;
  onOpenAgentSettings: () => void;
  onOpenHistory?: () => void;
}

/** Minimal header: title, optional history icon, agent count, settings icon.
 * Never shows individual agent cards here -- see `ConnectAgentView`. */
export const KeystoneHeader: React.FC<KeystoneHeaderProps> = ({
  connectedAgentCount,
  onOpenAgentSettings,
  onOpenHistory,
}) => {
  return (
    <header className="keystone-header">
      <p className="keystone-header-title">Keystone</p>
      <div className="keystone-header-actions">
        {onOpenHistory && (
          <button
            type="button"
            className="keystone-icon-btn"
            aria-label="Execution history"
            onClick={onOpenHistory}
          >
            <History size={15} />
          </button>
        )}
        <button
          type="button"
          className="keystone-agent-count"
          onClick={onOpenAgentSettings}
          aria-label={`${connectedAgentCount} connected agent${connectedAgentCount === 1 ? '' : 's'} — manage agents`}
        >
          {connectedAgentCount} agent{connectedAgentCount === 1 ? '' : 's'}
        </button>
        <button
          type="button"
          className="keystone-icon-btn"
          aria-label="Settings"
          onClick={onOpenAgentSettings}
        >
          <Settings size={15} />
        </button>
      </div>
    </header>
  );
};
