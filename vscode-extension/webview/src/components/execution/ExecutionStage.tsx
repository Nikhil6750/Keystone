import React from 'react';
import { Brain, Search, Play, ShieldCheck, FileText, Loader2, CheckCircle2 } from 'lucide-react';
import type { ExecutionStatus } from '../../mock/execution';

const ICON_MAP: Record<string, React.ElementType> = {
  Brain,
  Search,
  Play,
  ShieldCheck,
  FileText,
};

interface ExecutionStageProps {
  id: string;
  title: string;
  description: string;
  iconName: string;
  status: ExecutionStatus;
  isLast: boolean;
}

export const ExecutionStage: React.FC<ExecutionStageProps> = ({
  title,
  description,
  iconName,
  status,
  isLast,
}) => {
  const Icon = ICON_MAP[iconName] || Brain;

  return (
    <div className="workflow-stage-container">
      <div className={`workflow-stage execution-stage-item ${status.toLowerCase()}`}>
        <div className={`stage-icon-box ${status.toLowerCase()}`}>
          {status === 'Running' ? (
            <Loader2 size={18} className="spin-icon" />
          ) : status === 'Completed' ? (
            <CheckCircle2 size={18} className="icon-completed" />
          ) : (
            <Icon size={18} />
          )}
        </div>
        <div className="stage-info">
          <span className="stage-title">{title}</span>
          <span className="stage-desc">{description}</span>
        </div>
        <div className={`stage-badge ${status.toLowerCase()}`}>{status}</div>
      </div>
      {!isLast && <div className="stage-connector">↓</div>}
    </div>
  );
};
