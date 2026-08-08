import React from 'react';
import { PromptInput } from './PromptInput';
import { SuggestionGrid } from './SuggestionGrid';
import { WorkflowPreview } from './WorkflowPreview';
import { ExecuteButton } from './ExecuteButton';
import { ExecutionConsole } from '../execution/ExecutionConsole';
import { useWorkflowBuilder } from '../../hooks/useWorkflowBuilder';
import { useWorkflowExecution } from '../../hooks/useWorkflowExecution';
import type { Suggestion } from '../../hooks/useWorkflowBuilder';

export const WorkflowBuilder: React.FC = () => {
  const {
    prompt,
    setPrompt,
    selectedTemplate,
    selectSuggestion,
  } = useWorkflowBuilder();

  const {
    executionStarted,
    executionCompleted,
    stageStatuses,
    logs,
    progressPercentage,
    startExecution,
    resetExecution,
  } = useWorkflowExecution();

  const handlePromptChange = (value: string) => {
    if (executionStarted) resetExecution();
    setPrompt(value);
  };

  const handleSelectSuggestion = (suggestion: Suggestion) => {
    if (executionStarted) resetExecution();
    selectSuggestion(suggestion);
  };

  const isExecuting = executionStarted && !executionCompleted;

  return (
    <div className="workflow-builder-container">
      {/* Header */}
      <header className="builder-header">
        <h1 className="builder-title">Workflow Builder</h1>
        <p className="builder-subtitle">
          Describe your engineering task and prepare an orchestration workflow.
        </p>
      </header>

      {/* Main Content */}
      <div className="builder-body">
        <PromptInput value={prompt} onChange={handlePromptChange} />

        <SuggestionGrid
          selectedTemplate={selectedTemplate}
          onSelectSuggestion={handleSelectSuggestion}
        />

        <WorkflowPreview />

        <ExecuteButton onExecute={startExecution} disabled={isExecuting} />

        {/* Execution Console */}
        <ExecutionConsole
          executionStarted={executionStarted}
          executionCompleted={executionCompleted}
          stageStatuses={stageStatuses}
          logs={logs}
          progressPercentage={progressPercentage}
        />
      </div>
    </div>
  );
};
