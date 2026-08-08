import React from 'react';

export interface StageData {
  id: string;
  title: string;
  description: string;
  icon: React.ElementType;
}

interface WorkflowStageProps {
  stage: StageData;
  isLast: boolean;
}

export const WorkflowStage: React.FC<WorkflowStageProps> = ({ stage, isLast }) => {
  const Icon = stage.icon;

  return (
    <div className="workflow-stage-container">
      <div className="workflow-stage">
        <div className="stage-icon-box">
          <Icon size={18} />
        </div>
        <div className="stage-info">
          <span className="stage-title">{stage.title}</span>
          <span className="stage-desc">{stage.description}</span>
        </div>
        <div className="stage-badge">Waiting</div>
      </div>
      {!isLast && <div className="stage-connector">↓</div>}
    </div>
  );
};
