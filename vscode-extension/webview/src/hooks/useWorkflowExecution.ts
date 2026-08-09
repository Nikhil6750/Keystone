import { useAppState } from './useAppState';

export function useWorkflowExecution() {
  const {
    executionStarted,
    executionCompleted,
    currentStageId,
    stageStatuses,
    executionLogs: logs,
    progressPercentage,
    startExecution,
    resetExecution,
  } = useAppState();

  return {
    executionStarted,
    executionCompleted,
    currentStageId,
    stageStatuses,
    logs,
    progressPercentage,
    startExecution,
    resetExecution,
  };
}
