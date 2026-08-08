import { useState, useCallback, useRef, useEffect } from 'react';
import {
  EXECUTION_STAGES,
  type ExecutionStatus,
  type LogEntry,
} from '../mock/execution';

export function useWorkflowExecution() {
  const [executionStarted, setExecutionStarted] = useState<boolean>(false);
  const [executionCompleted, setExecutionCompleted] = useState<boolean>(false);
  const [currentStageId, setCurrentStageId] = useState<string | null>(null);
  const [stageStatuses, setStageStatuses] = useState<Record<string, ExecutionStatus>>(() => {
    const initial: Record<string, ExecutionStatus> = {};
    for (const stage of EXECUTION_STAGES) {
      initial[stage.id] = 'Waiting';
    }
    return initial;
  });
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [progressPercentage, setProgressPercentage] = useState<number>(0);

  const timeoutsRef = useRef<NodeJS.Timeout[]>([]);

  const clearAllTimeouts = useCallback(() => {
    for (const t of timeoutsRef.current) {
      clearTimeout(t);
    }
    timeoutsRef.current = [];
  }, []);

  useEffect(() => {
    return () => {
      clearAllTimeouts();
    };
  }, [clearAllTimeouts]);

  const resetExecution = useCallback(() => {
    clearAllTimeouts();
    setExecutionStarted(false);
    setExecutionCompleted(false);
    setCurrentStageId(null);
    setProgressPercentage(0);
    setLogs([]);
    const initial: Record<string, ExecutionStatus> = {};
    for (const stage of EXECUTION_STAGES) {
      initial[stage.id] = 'Waiting';
    }
    setStageStatuses(initial);
  }, [clearAllTimeouts]);

  const startExecution = useCallback(() => {
    resetExecution();
    setExecutionStarted(true);

    let cumulativeTime = 0;
    const totalStages = EXECUTION_STAGES.length;

    EXECUTION_STAGES.forEach((stage, index) => {
      const startTime = cumulativeTime;
      cumulativeTime += stage.durationMs;

      // 1. Stage transition to 'Running'
      const startTimeout = setTimeout(() => {
        setCurrentStageId(stage.id);
        setStageStatuses((prev) => ({
          ...prev,
          [stage.id]: 'Running',
        }));
        setProgressPercentage(Math.round((index / totalStages) * 100));
      }, startTime);
      timeoutsRef.current.push(startTimeout);

      // 2. Schedule progressive log entries within stage duration
      const logCount = stage.logs.length;
      stage.logs.forEach((logMsg, logIdx) => {
        const logDelay = startTime + Math.round(((logIdx + 1) / (logCount + 1)) * stage.durationMs);
        const logTimeout = setTimeout(() => {
          const now = new Date();
          const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(
            now.getMinutes()
          ).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;

          setLogs((prevLogs) => [
            ...prevLogs,
            {
              id: `${stage.id}-${logIdx}-${Date.now()}`,
              stageId: stage.id,
              stageTitle: stage.title,
              message: logMsg,
              timestamp: timeStr,
            },
          ]);
        }, logDelay);
        timeoutsRef.current.push(logTimeout);
      });

      // 3. Stage transition to 'Completed'
      const endTimeout = setTimeout(() => {
        setStageStatuses((prev) => ({
          ...prev,
          [stage.id]: 'Completed',
        }));

        if (index === totalStages - 1) {
          setCurrentStageId(null);
          setExecutionCompleted(true);
          setProgressPercentage(100);
        }
      }, cumulativeTime);
      timeoutsRef.current.push(endTimeout);
    });
  }, [resetExecution]);

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
