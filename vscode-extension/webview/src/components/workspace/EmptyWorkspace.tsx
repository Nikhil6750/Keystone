import React from 'react';
import { FolderPlus } from 'lucide-react';
import { vscodeApi } from '../../services/vscodeApi';

export const EmptyWorkspace: React.FC = () => {
  const handleSelectFolder = () => {
    vscodeApi.postMessage({ type: 'SELECT_WORKSPACE_FOLDER', action: 'SELECT_WORKSPACE_FOLDER' });
  };

  return (
    <div className="agent-empty-state workspace-empty-state flex flex-col items-center justify-center p-6 text-center">
      <FolderPlus size={40} className="empty-icon text-blue-400 mb-3" />
      <h3 className="empty-title text-base font-semibold text-slate-200 mb-1">Select Project Folder</h3>
      <p className="empty-subtitle text-xs text-slate-400 max-w-xs mb-4">
        Choose a project directory to run Keystone multi-agent execution with live workspace writes.
      </p>
      <button
        onClick={handleSelectFolder}
        className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-medium text-xs rounded-md transition-colors shadow-sm"
      >
        Select Project Folder
      </button>
    </div>
  );
};
