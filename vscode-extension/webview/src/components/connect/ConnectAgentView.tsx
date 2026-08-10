import React, { useState } from 'react';
import { ArrowLeft, Cloud, KeyRound, HardDrive, Wrench } from 'lucide-react';
import { InstalledSignInView } from './InstalledSignInView';
import { ApiByokView } from './ApiByokView';
import { LocalRuntimeView } from './LocalRuntimeView';
import { CustomRuntimeView } from './CustomRuntimeView';

export type ConnectCategory = 'installed' | 'api' | 'local' | 'custom';

export interface ConnectAgentViewProps {
  onClose: () => void;
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
 * provider logos or brand-specific chrome on the first screen. Each
 * category opens a generic, honest detail view; none of them can report a
 * successful connection today (see each sub-view's own docstring).
 */
export const ConnectAgentView: React.FC<ConnectAgentViewProps> = ({ onClose }) => {
  const [category, setCategory] = useState<ConnectCategory | null>(null);

  if (category === 'installed') {
    return <InstalledSignInView onBack={() => setCategory(null)} />;
  }
  if (category === 'api') {
    return <ApiByokView onBack={() => setCategory(null)} />;
  }
  if (category === 'local') {
    return <LocalRuntimeView onBack={() => setCategory(null)} />;
  }
  if (category === 'custom') {
    return <CustomRuntimeView onBack={() => setCategory(null)} />;
  }

  return (
    <div className="connect-agent-view">
      <button type="button" className="connect-agent-back-btn" onClick={onClose}>
        <ArrowLeft size={13} />
        Back
      </button>
      <h2 className="connect-agent-heading">Connect Agent</h2>
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
