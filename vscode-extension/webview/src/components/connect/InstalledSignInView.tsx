import React from 'react';
import { ArrowLeft } from 'lucide-react';

export interface CategoryDetailViewProps {
  onBack: () => void;
}

/**
 * Installed/subscription runtime connectors (e.g. an installed CLI-based
 * agent, a subscription sign-in flow) are not wired to a real connector
 * API yet. This view never claims a connection succeeded -- there is no
 * "Connect" button that could lie. Core architecture intentionally does
 * not hardcode which runtimes this category will eventually support.
 */
export const InstalledSignInView: React.FC<CategoryDetailViewProps> = ({ onBack }) => {
  return (
    <div className="connect-agent-view">
      <button type="button" className="connect-agent-back-btn" onClick={onBack}>
        <ArrowLeft size={13} />
        Back
      </button>
      <h2 className="connect-agent-heading">Installed / Sign in</h2>
      <div className="connect-category-detail">
        <span className="connect-unavailable-badge">Not yet available</span>
        <p>
          Installed and subscription-based runtime connections are not available in this
          build. When ready, this will let Keystone detect and use runtimes already
          installed or signed in on this machine, without assuming which ones you have.
        </p>
      </div>
    </div>
  );
};
