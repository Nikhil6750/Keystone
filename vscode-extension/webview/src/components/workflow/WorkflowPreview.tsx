import React from 'react';
import { WorkflowStage, type StageData } from './WorkflowStage';
import { Brain, Search, Play, ShieldCheck, FileText } from 'lucide-react';

const STAGES: StageData[] = [
  {
    id: 'planner',
    title: 'Planner',
    description: 'Decomposes engineering tasks into structured execution steps.',
    icon: Brain,
  },
  {
    id: 'research',
    title: 'Research',
    description: 'Gathers context, codebase references, and dependency definitions.',
    icon: Search,
  },
  {
    id: 'executor',
    title: 'Executor',
    description: 'Executes task steps through assigned AI coding agents.',
    icon: Play,
  },
  {
    id: 'validator',
    title: 'Validator',
    description: 'Runs test suites, static analysis, and type verification.',
    icon: ShieldCheck,
  },
  {
    id: 'reporter',
    title: 'Reporter',
    description: 'Compiles execution outputs and tamper-evident audit logs.',
    icon: FileText,
  },
];

export const WorkflowPreview: React.FC = () => {
  return (
    <div className="workflow-preview-wrapper">
      <span className="section-title">Workflow Pipeline Preview</span>
      <div className="workflow-stages-list">
        {STAGES.map((stage, index) => (
          <WorkflowStage
            key={stage.id}
            stage={stage}
            isLast={index === STAGES.length - 1}
          />
        ))}
      </div>
    </div>
  );
};
