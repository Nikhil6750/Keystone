import React from 'react';
import { WorkflowBuilder } from '../components/workflow/WorkflowBuilder';

export const MainPage: React.FC = () => {
  return (
    <div className="app-container">
      <WorkflowBuilder />
    </div>
  );
};
