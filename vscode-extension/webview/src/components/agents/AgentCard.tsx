import React from 'react';
import { Bot, Cpu, Zap, Globe, ShieldCheck, Loader2 } from 'lucide-react';
import type { AgentItem } from '../../mock/agents';

const ICON_MAP: Record<string, React.ElementType> = {
  Bot,
  Cpu,
  Zap,
  Globe,
};

interface AgentCardProps {
  agent: AgentItem;
  isSelected: boolean;
  isVerifying: boolean;
  onSelect: (agentId: string) => void;
  onVerify: (agentId: string, e: React.MouseEvent) => void;
}

export const AgentCard: React.FC<AgentCardProps> = ({
  agent,
  isSelected,
  isVerifying,
  onSelect,
  onVerify,
}) => {
  const IconComponent = ICON_MAP[agent.iconName] || Bot;
  const isConnected = agent.connectionStatus === 'Connected';

  return (
    <div
      className={`agent-card ${isSelected ? 'selected' : ''}`}
      onClick={() => onSelect(agent.id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onSelect(agent.id);
      }}
    >
      <div className="agent-card-header">
        <div className="agent-card-title-group">
          <div className="agent-icon-box">
            <IconComponent size={18} />
          </div>
          <div>
            <h3 className="agent-card-name">{agent.name}</h3>
            <span className="agent-card-version">{agent.version}</span>
          </div>
        </div>
        <span
          className={`agent-status-badge ${
            isConnected ? 'status-connected' : 'status-disconnected'
          }`}
        >
          {agent.connectionStatus}
        </span>
      </div>

      <p className="agent-card-desc">{agent.description}</p>

      <div className="agent-meta-row">
        <span className="meta-label">Authentication:</span>
        <span
          className={`auth-badge ${
            agent.authenticationStatus === 'Authenticated'
              ? 'auth-ok'
              : 'auth-warn'
          }`}
        >
          {agent.authenticationStatus}
        </span>
      </div>

      <div className="agent-capabilities-list">
        {agent.capabilities.slice(0, 3).map((cap) => (
          <span key={cap} className="capability-tag">
            {cap}
          </span>
        ))}
        {agent.capabilities.length > 3 && (
          <span className="capability-tag more">
            +{agent.capabilities.length - 3}
          </span>
        )}
      </div>

      <div className="agent-card-footer">
        <button
          type="button"
          className="btn-verify"
          disabled={isVerifying}
          onClick={(e) => {
            e.stopPropagation();
            onVerify(agent.id, e);
          }}
        >
          {isVerifying ? (
            <>
              <Loader2 size={14} className="spin-icon" />
              <span>Verifying...</span>
            </>
          ) : (
            <>
              <ShieldCheck size={14} />
              <span>Verify Connection</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
};
