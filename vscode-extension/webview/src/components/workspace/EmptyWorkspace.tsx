import React from 'react';
import { FolderX } from 'lucide-react';

export const EmptyWorkspace: React.FC = () => {
  return (
    <div className="agent-empty-state workspace-empty-state">
      <FolderX size={36} className="empty-icon" />
      <h3 className="empty-title">No workspace opened.</h3>
      <p className="empty-subtitle">
        Open a folder or workspace in VS Code to inspect files and project contracts.
      </p>
    </div>
  );
};
