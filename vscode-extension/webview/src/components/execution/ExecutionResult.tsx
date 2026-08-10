import React from 'react';
import { CheckCircle2, XCircle } from 'lucide-react';
import type { OrchestrationExecutionRead, OrchestrationOutcome } from '../../types/keystone';

export interface ExecutionResultProps {
  result: OrchestrationExecutionRead | null;
  onStartOver: () => void;
}

const OUTCOME_LABELS: Record<OrchestrationOutcome, string> = {
  verified_success: 'Verified',
  verification_failed: 'Verification failed',
  runtime_failure: 'Something went wrong',
  no_eligible_route: 'No eligible agent was available',
  recovery_exhausted: 'Unable to reach a verified result',
  human_review_required: 'Needs human review',
  cancelled: 'Cancelled',
};

/**
 * Terminal state display. Only ever shows the safe, already-typed fields
 * on `OrchestrationExecutionRead` -- never a raw exception, stack trace, or
 * provider output (the backend contract this mirrors carries none of
 * those either).
 */
export const ExecutionResult: React.FC<ExecutionResultProps> = ({ result, onStartOver }) => {
  const outcome = result?.orchestration_outcome ?? null;
  const isVerified = outcome === 'verified_success';
  const label = outcome ? OUTCOME_LABELS[outcome] : 'Execution failed';

  return (
    <div className="execution-result-view">
      <span className={`result-badge ${isVerified ? 'verified' : 'failed'}`}>
        {isVerified ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
        {label}
      </span>

      {result && (
        <p className="result-summary">
          {result.task_count !== null && <>{result.task_count} task(s) planned. </>}
          {result.selected_agent_types.length > 0 && (
            <>Routed to {result.selected_agent_types.join(', ')}. </>
          )}
          {result.verification_status && <>Verification: {result.verification_status}.</>}
        </p>
      )}

      {result && (result.learning_event_count !== null || result.retrieval_feedback_recorded !== null) && (
        <div className="result-meta-row">
          {result.learning_event_count !== null && (
            <span className="result-meta-chip">{result.learning_event_count} learning event(s)</span>
          )}
          {result.retrieval_feedback_recorded !== null && (
            <span className="result-meta-chip">
              Retrieval feedback: {result.retrieval_feedback_recorded ? 'recorded' : 'not recorded'}
            </span>
          )}
        </div>
      )}

      <button type="button" className="btn-start-over" onClick={onStartOver}>
        Ask something else
      </button>
    </div>
  );
};
