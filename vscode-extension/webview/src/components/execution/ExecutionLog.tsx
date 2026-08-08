import React, { useRef, useEffect } from 'react';
import { Terminal } from 'lucide-react';
import type { LogEntry } from '../../mock/execution';

interface ExecutionLogProps {
  logs: LogEntry[];
}

export const ExecutionLog: React.FC<ExecutionLogProps> = ({ logs }) => {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <div className="execution-log-wrapper">
      <div className="log-header">
        <div className="log-title">
          <Terminal size={14} />
          <span>Live Execution Log</span>
        </div>
        <span className="log-count">{logs.length} entries</span>
      </div>

      <div ref={containerRef} className="log-console-body">
        {logs.length === 0 ? (
          <div className="log-placeholder">Waiting for execution events...</div>
        ) : (
          logs.map((log) => (
            <div key={log.id} className="log-line">
              <span className="log-time">[{log.timestamp}]</span>
              <span className="log-stage-tag">{log.stageTitle}</span>
              <span className="log-message">{log.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
