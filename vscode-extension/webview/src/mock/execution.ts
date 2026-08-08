import {
  MockProvider,
  type ExecutionStatus,
  type StageDefinition,
  type LogEntry,
} from '../api/MockProvider';

export type { ExecutionStatus, StageDefinition, LogEntry };

export let EXECUTION_STAGES: StageDefinition[] = [];
MockProvider.getExecutionStages().then((stages) => {
  EXECUTION_STAGES = stages;
});
