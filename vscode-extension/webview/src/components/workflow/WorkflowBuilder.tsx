import React from 'react';
import { PromptInput } from './PromptInput';
import { SuggestionGrid } from './SuggestionGrid';
import { WorkflowPreview } from './WorkflowPreview';
import { ExecuteButton } from './ExecuteButton';
import { useWorkflowBuilder } from '../../hooks/useWorkflowBuilder';
import { AlertCircle, X } from 'lucide-react';

export const WorkflowBuilder: React.FC = () => {
  const {
    prompt,
    setPrompt,
    selectedTemplate,
    selectSuggestion,
    handleExecute,
    toastMessage,
    dismissToast,
  } = useWorkflowBuilder();

  return (
    <div className="workflow-builder-container">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="toast-notification" role="alert">
          <div className="toast-content">
            <AlertCircle size={16} className="toast-icon" />
            <span>{toastMessage}</span>
          </div>
          <button
            type="button"
            className="toast-close"
            onClick={dismissToast}
            aria-label="Dismiss toast"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Header */}
      <header className="builder-header">
        <h1 className="builder-title">Workflow Builder</h1>
        <p className="builder-subtitle">
          Describe your engineering task and prepare an orchestration workflow.
        </p>
      </header>

      {/* Main Content */}
      <div className="builder-body">
        <PromptInput value={prompt} onChange={setPrompt} />

        <SuggestionGrid
          selectedTemplate={selectedTemplate}
          onSelectSuggestion={selectSuggestion}
        />

        <WorkflowPreview />

        <ExecuteButton onExecute={handleExecute} />
      </div>
    </div>
  );
};
