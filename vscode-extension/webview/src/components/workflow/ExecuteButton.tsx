import React from 'react';
import { Play } from 'lucide-react';

interface ExecuteButtonProps {
  onExecute: () => void;
  disabled?: boolean;
}

export const ExecuteButton: React.FC<ExecuteButtonProps> = ({ onExecute, disabled }) => {
  return (
    <div className="execute-button-wrapper">
      <button
        type="button"
        className="btn-execute"
        onClick={onExecute}
        disabled={disabled}
      >
        <Play size={16} />
        <span>Execute Workflow</span>
      </button>
    </div>
  );
};
