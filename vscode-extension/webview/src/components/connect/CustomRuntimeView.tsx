import React from 'react';
import { ArrowLeft } from 'lucide-react';
import type { CategoryDetailViewProps } from './InstalledSignInView';

/**
 * Custom/company runtime connections (an internal engine, a custom
 * compatible endpoint). Never claims a connection succeeded.
 */
export const CustomRuntimeView: React.FC<CategoryDetailViewProps> = ({ onBack }) => {
  return (
    <div className="connect-agent-view">
      <button type="button" className="connect-agent-back-btn" onClick={onBack}>
        <ArrowLeft size={13} />
        Back
      </button>
      <h2 className="connect-agent-heading">Custom</h2>
      <div className="connect-category-detail">
        <span className="connect-unavailable-badge">Not yet available</span>
        <p>
          Custom runtime connections are not available in this build. This will support a
          company-internal agent or a custom compatible endpoint, identified only by an
          open string ID and endpoint -- never a built-in vendor list.
        </p>
      </div>
    </div>
  );
};
