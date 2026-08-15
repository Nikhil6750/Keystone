import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ExecutionResult } from './ExecutionResult';
import type { OrchestrationExecutionRead } from '../../types/keystone';

function makeResult(overrides: Partial<OrchestrationExecutionRead>): OrchestrationExecutionRead {
  return {
    execution_id: 'exec-1',
    job_status: 'completed',
    orchestration_outcome: 'verified_success',
    workflow_id: 'wf-1',
    final_workflow_state: 'succeeded',
    verification_status: 'passed',
    task_count: 3,
    selected_agent_types: ['qwen-coder'],
    learning_event_count: 3,
    retrieval_feedback_recorded: false,
    issue_codes: [],
    error_summary: null,
    ...overrides,
  };
}

describe('ExecutionResult', () => {
  it('11. shows a Verified terminal state for verified_success', () => {
    render(<ExecutionResult result={makeResult({})} onStartOver={vi.fn()} />);
    expect(screen.getByText('Verified')).toBeInTheDocument();
  });

  it('12. shows a distinct failure terminal state for a non-success outcome', () => {
    render(
      <ExecutionResult
        result={makeResult({
          orchestration_outcome: 'recovery_exhausted',
          verification_status: 'inconclusive',
        })}
        onStartOver={vi.fn()}
      />
    );
    expect(screen.getByText('Unable to reach a verified result')).toBeInTheDocument();
    expect(screen.queryByText('Verified')).not.toBeInTheDocument();
  });

  it('12. shows a generic failure state when no result is available at all', () => {
    render(<ExecutionResult result={null} onStartOver={vi.fn()} />);
    expect(screen.getByText('Execution failed')).toBeInTheDocument();
  });

  it('never renders raw error/exception content', () => {
    render(
      <ExecutionResult
        result={makeResult({
          orchestration_outcome: 'runtime_failure',
          error_summary: 'Traceback (most recent call last): raw stack trace',
        })}
        onStartOver={vi.fn()}
      />
    );
    expect(screen.queryByText(/Traceback/)).not.toBeInTheDocument();
  });
});
