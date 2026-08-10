import React from 'react';
import { ArrowLeft } from 'lucide-react';
import type { CategoryDetailViewProps } from './InstalledSignInView';

/**
 * Local runtime connections (a local server, an Ollama-style endpoint, a
 * local custom agent). No provider-specific assumptions are made here or
 * anywhere in the underlying architecture. Never claims a connection
 * succeeded.
 */
export const LocalRuntimeView: React.FC<CategoryDetailViewProps> = ({ onBack }) => {
  return (
    <div className="connect-agent-view">
      <button type="button" className="connect-agent-back-btn" onClick={onBack}>
        <ArrowLeft size={13} />
        Back
      </button>
      <h2 className="connect-agent-heading">Local</h2>
      <div className="connect-category-detail">
        <span className="connect-unavailable-badge">Not yet available</span>
        <p>
          Local runtime connections are not available in this build. This will support a
          locally running model server or a local custom agent, addressed by an endpoint
          you control -- never a fixed, built-in list of local providers.
        </p>
      </div>
    </div>
  );
};
