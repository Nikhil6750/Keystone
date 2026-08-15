import React from 'react';
import { Plug } from 'lucide-react';

export interface WelcomeStateProps {
  hasConnectedAgents: boolean;
  onConnectAgent: () => void;
}

/** The centered welcome content: "Ready to build?" (no agents) or
 * "What do you want to build?" (agents connected) -- the prompt composer
 * itself is a sibling, always docked at the bottom (see `KeystoneHome`). */
export const WelcomeState: React.FC<WelcomeStateProps> = ({
  hasConnectedAgents,
  onConnectAgent,
}) => {
  return (
    <div className="keystone-welcome">
      <p className="keystone-welcome-title">Keystone</p>
      {hasConnectedAgents ? (
        <p className="keystone-welcome-subtitle">What do you want to build?</p>
      ) : (
        <>
          <p className="keystone-welcome-subtitle">Ready to build?</p>
          <p className="keystone-welcome-hint">Connect your agents to get started.</p>
          <button type="button" className="btn-connect-agent" onClick={onConnectAgent}>
            <Plug size={14} />
            Connect Agent
          </button>
        </>
      )}
    </div>
  );
};
