import React from 'react';
import { ExecutionTimeline } from './ExecutionTimeline';
import { ExecutionLog } from './ExecutionLog';
import { CheckCircle, Loader2 } from 'lucide-react';
import type { ExecutionStatus, LogEntry } from '../../mock/execution';

interface ExecutionConsoleProps {
  executionStarted: boolean;
  executionCompleted: boolean;
  stageStatuses: Record<string, ExecutionStatus>;
  logs: LogEntry[];
  progressPercentage: number;
}

export const ExecutionConsole: React.FC<ExecutionConsoleProps> = ({
  executionStarted,
  executionCompleted,
  stageStatuses,
  logs,
  progressPercentage,
}) => {
  if (!executionStarted) return null;

  return (
    <div className="execution-console-container">
      {/* Execution Status Bar / Progress */}
      <div className="execution-console-header">
        <div className="console-title-group">
          <span className="console-title">Execution Console</span>
          <span
            className={`console-status-badge ${
              executionCompleted ? 'completed' : 'running'
            }`}
          >
            {executionCompleted ? (
              <>
                <CheckCircle size={13} />
                <span>Completed</span>
              </>
            ) : (
              <>
                <Loader2 size={13} className="spin-icon" />
                <span>Running ({progressPercentage}%)</span>
              </>
            )}
          </span>
        </div>

        {/* Progress Bar */}
        <div className="progress-bar-track">
          <div
            className="progress-bar-fill"
            style={{ width: `${progressPercentage}%` }}
          />
        </div>
      </div>

      {/* Completion Banner */}
      {executionCompleted && (
        <div className="execution-success-banner" role="status">
          <CheckCircle size={18} />
          <span>Workflow completed successfully.</span>
        </div>
      )}

      {/* Execution Timeline and Live Log split */}
      <div className="execution-console-body">
        <ExecutionTimeline stageStatuses={stageStatuses} />
        <ExecutionLog logs={logs} />
      </div>
    </div>
  );
};
