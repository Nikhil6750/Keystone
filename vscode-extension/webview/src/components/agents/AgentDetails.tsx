import React from 'react';
import { X, ShieldCheck, Loader2, Bot, Cpu, Zap, Globe } from 'lucide-react';
import type { AgentItem } from '../../mock/agents';

const ICON_MAP: Record<string, React.ElementType> = {
  Bot,
  Cpu,
  Zap,
  Globe,
};

interface AgentDetailsProps {
  agent: AgentItem | null;
  isVerifying: boolean;
  onClose: () => void;
  onVerify: (agentId: string) => void;
}

export const AgentDetails: React.FC<AgentDetailsProps> = ({
  agent,
  isVerifying,
  onClose,
  onVerify,
}) => {
  if (!agent) return null;

  const IconComponent = ICON_MAP[agent.iconName] || Bot;
  const isConnected = agent.connectionStatus === 'Connected';

  return (
    <div className="agent-details-overlay" onClick={onClose}>
      <div
        className="agent-details-drawer"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={`Agent details for ${agent.name}`}
      >
        <div className="details-header">
          <div className="details-title-group">
            <div className="agent-icon-box large">
              <IconComponent size={20} />
            </div>
            <div>
              <h2 className="details-agent-name">{agent.name}</h2>
              <span className="details-agent-type">{agent.type}</span>
            </div>
          </div>
          <button
            type="button"
            className="details-close-btn"
            onClick={onClose}
            aria-label="Close details"
          >
            <X size={16} />
          </button>
        </div>

        <div className="details-body">
          <p className="details-desc">{agent.description}</p>

          <div className="details-specs-grid">
            <div className="spec-item">
              <span className="spec-label">Installation</span>
              <span className="spec-value highlight-green">
                {agent.installationStatus}
              </span>
            </div>

            <div className="spec-item">
              <span className="spec-label">Version</span>
              <span className="spec-value">{agent.version}</span>
            </div>

            <div className="spec-item">
              <span className="spec-label">Executable</span>
              <span className="spec-value code">{agent.executable}</span>
            </div>

            <div className="spec-item">
              <span className="spec-label">Authentication</span>
              <span
                className={`spec-value ${
                  agent.authenticationStatus === 'Authenticated'
                    ? 'highlight-green'
                    : 'highlight-amber'
                }`}
              >
                {agent.authenticationStatus}
              </span>
            </div>

            <div className="spec-item">
              <span className="spec-label">Connection</span>
              <span
                className={`spec-value ${
                  isConnected ? 'highlight-green' : 'highlight-red'
                }`}
              >
                {agent.connectionStatus}
              </span>
            </div>

            <div className="spec-item">
              <span className="spec-label">Last Verified</span>
              <span className="spec-value">{agent.lastVerifiedAt}</span>
            </div>
          </div>

          <div className="details-capabilities-section">
            <span className="section-subtitle">Capabilities</span>
            <div className="details-capabilities-tags">
              {agent.capabilities.map((cap) => (
                <span key={cap} className="capability-tag detailed">
                  {cap}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="details-footer">
          <button
            type="button"
            className="btn-verify large"
            disabled={isVerifying}
            onClick={() => onVerify(agent.id)}
          >
            {isVerifying ? (
              <>
                <Loader2 size={16} className="spin-icon" />
                <span>Running connection check...</span>
              </>
            ) : (
              <>
                <ShieldCheck size={16} />
                <span>Verify Connection</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
