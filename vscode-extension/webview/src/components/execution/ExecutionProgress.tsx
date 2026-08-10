import React from 'react';
import { Loader2, ArrowRight, AlertCircle } from 'lucide-react';
import type { OrchestrationEvent } from '../../types/keystone';
import { mapEventToProgressLine } from '../../utils/progressMapping';

export interface ExecutionProgressProps {
  events: OrchestrationEvent[];
}

/**
 * Renders curated, human-readable progress lines only -- never a raw event
 * log. See `mapEventToProgressLine` for the exact, bounded mapping; any
 * event type not explicitly handled there is silently omitted here, never
 * dumped as JSON.
 */
export const ExecutionProgress: React.FC<ExecutionProgressProps> = ({ events }) => {
  const lines = events
    .map(mapEventToProgressLine)
    .filter((line): line is NonNullable<ReturnType<typeof mapEventToProgressLine>> => line !== null);

  return (
    <div className="execution-progress-view" role="status" aria-live="polite">
      <div className="execution-progress-list">
        {lines.length === 0 ? (
          <div className="progress-line">
            <Loader2 size={14} className="progress-line-icon spin-icon" />
            Starting...
          </div>
        ) : (
          lines.map((line) => (
            <div key={line.id} className={`progress-line ${line.kind}`}>
              <span className="progress-line-icon">
                {line.kind === 'error' ? <AlertCircle size={14} /> : <ArrowRight size={13} />}
              </span>
              {line.text}
            </div>
          ))
        )}
      </div>
    </div>
  );
};
