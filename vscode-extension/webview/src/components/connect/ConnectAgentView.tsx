import React, { useState } from 'react';
import { ArrowLeft, Cloud, KeyRound, HardDrive, Wrench } from 'lucide-react';
import { InstalledSignInView } from './InstalledSignInView';
import { ApiByokView } from './ApiByokView';
import { LocalRuntimeView } from './LocalRuntimeView';
import { CustomRuntimeView } from './CustomRuntimeView';
import { AgentManagementList } from './AgentManagementList';
import type { ConnectedAgentSummary } from '../../types/keystone';

export type ConnectCategory = 'installed' | 'api' | 'local' | 'custom';

export interface ConnectAgentViewProps {
  onClose: () => void;
  connectedAgents: ConnectedAgentSummary[];
  onAgentsChanged: () => void;
}

const CATEGORIES: { id: ConnectCategory; title: string; description: string; icon: React.ReactNode }[] = [
  {
    id: 'installed',
    title: 'Installed / Sign in',
    description: 'Use an installed or subscription-based runtime already on this machine.',
    icon: <Cloud size={16} />,
  },
  {
    id: 'api',
    title: 'API / BYOK',
    description: 'Bring your own API key for a compatible model provider.',
    icon: <KeyRound size={16} />,
  },
  {
    id: 'local',
    title: 'Local',
    description: 'Connect a locally running model or agent endpoint.',
    icon: <HardDrive size={16} />,
  },
  {
    id: 'custom',
    title: 'Custom',
    description: 'Connect a company or custom-compatible agent runtime.',
    icon: <Wrench size={16} />,
  },
];

/**
 * The secondary "Connect Agent" surface. Category buttons only -- no
 * provider logos or brand-specific chrome on the first screen. "Installed
 * / Sign in" is the one category backed by a real connector (Stage 8C.3);
 * API/BYOK, Local, and Custom create real connection/agent metadata but
 * have no execution adapter yet -- see each sub-view's own docstring.
 */
export const ConnectAgentView: React.FC<ConnectAgentViewProps> = ({
  onClose,
  connectedAgents,
  onAgentsChanged,
}) => {
  const [category, setCategory] = useState<ConnectCategory | null>(null);

  if (category === 'installed') {
    return (
      <InstalledSignInView
        onBack={() => setCategory(null)}
        onAgentsChanged={onAgentsChanged}
        existingAgents={connectedAgents}
      />
    );
  }
  if (category === 'api') {
    return <ApiByokView onBack={() => setCategory(null)} onAgentsChanged={onAgentsChanged} />;
  }
  if (category === 'local') {
    return <LocalRuntimeView onBack={() => setCategory(null)} onAgentsChanged={onAgentsChanged} />;
  }
  if (category === 'custom') {
    return <CustomRuntimeView onBack={() => setCategory(null)} onAgentsChanged={onAgentsChanged} />;
  }

  return (
    <div className="connect-agent-view">
      <button type="button" className="connect-agent-back-btn" onClick={onClose}>
        <ArrowLeft size={13} />
        Back
      </button>
      <h2 className="connect-agent-heading">Connect Agent</h2>
      <AgentManagementList agents={connectedAgents} onAgentsChanged={onAgentsChanged} />
      <div className="connect-category-grid">
        {CATEGORIES.map((c) => (
          <button
            key={c.id}
            type="button"
            className="connect-category-btn"
            onClick={() => setCategory(c.id)}
            aria-label={c.title}
          >
            <span className="connect-category-icon">{c.icon}</span>
            <span className="connect-category-text">
              <span className="connect-category-title">{c.title}</span>
              <span className="connect-category-desc">{c.description}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
};
