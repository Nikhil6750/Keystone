import React from 'react';
import { ExecutionStage } from './ExecutionStage';
import { EXECUTION_STAGES, type ExecutionStatus } from '../../mock/execution';

interface ExecutionTimelineProps {
  stageStatuses: Record<string, ExecutionStatus>;
}

export const ExecutionTimeline: React.FC<ExecutionTimelineProps> = ({ stageStatuses }) => {
  return (
    <div className="workflow-preview-wrapper">
      <span className="section-title">Execution Timeline</span>
      <div className="workflow-stages-list">
        {EXECUTION_STAGES.map((stage, index) => (
          <ExecutionStage
            key={stage.id}
            id={stage.id}
            title={stage.title}
            description={stage.description}
            iconName={stage.iconName}
            status={stageStatuses[stage.id] || 'Waiting'}
            isLast={index === EXECUTION_STAGES.length - 1}
          />
        ))}
      </div>
    </div>
  );
};
