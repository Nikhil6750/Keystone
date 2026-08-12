import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ExecutionProgress } from './ExecutionProgress';
import type { OrchestrationEvent } from '../../types/keystone';

function makeEvent(overrides: Partial<OrchestrationEvent>): OrchestrationEvent {
  return {
    event_id: 'evt-1',
    execution_id: 'exec-1',
    sequence: 1,
    event_type: 'execution.started',
    timestamp: new Date().toISOString(),
    phase: null,
    status: null,
    workflow_id: null,
    task_key: null,
    agent_id: null,
    attempt_number: null,
    verification_status: null,
    safe_issue_codes: [],
    message: null,
    ...overrides,
  };
}

describe('ExecutionProgress', () => {
  it('10. maps safe event fields (agent_id, task_key, message) into human-readable progress lines', () => {
    const events: OrchestrationEvent[] = [
      makeEvent({ event_id: 'e1', sequence: 1, event_type: 'execution.started' }),
      makeEvent({
        event_id: 'e2',
        sequence: 2,
        event_type: 'planning.completed',
        message: 'task_count=7',
      }),
      makeEvent({
        event_id: 'e3',
        sequence: 3,
        event_type: 'step.started',
        agent_id: 'qwen-coder',
        task_key: 'implement_change',
      }),
      makeEvent({
        event_id: 'e4',
        sequence: 4,
        event_type: 'step.started',
        agent_id: 'corp-reviewer',
        task_key: 'security_review',
      }),
      makeEvent({ event_id: 'e5', sequence: 5, event_type: 'verification.started' }),
    ];

    render(<ExecutionProgress events={events} />);

    expect(screen.getByText('Understanding goal...')).toBeInTheDocument();
    expect(screen.getByText('Planning 7 tasks...')).toBeInTheDocument();
    expect(screen.getByText(/qwen-coder.*implement_change/)).toBeInTheDocument();
    expect(screen.getByText(/corp-reviewer.*security_review/)).toBeInTheDocument();
    expect(screen.getByText('Verifying...')).toBeInTheDocument();
  });

  it('14. never renders raw event fields outside the curated mapping (no reasoning/CoT/raw-message display path)', () => {
    const events: OrchestrationEvent[] = [
      makeEvent({
        event_id: 'e1',
        event_type: 'manager.completed',
        status: 'True',
        message: 'THIS_SHOULD_NEVER_RENDER_RAW',
      }),
    ];

    render(<ExecutionProgress events={events} />);

    // `manager.completed` is intentionally unmapped (not a visible line) --
    // its raw `status`/`message` fields must never leak into the DOM.
    expect(screen.queryByText(/THIS_SHOULD_NEVER_RENDER_RAW/)).not.toBeInTheDocument();
    expect(screen.queryByText('reasoning_content')).not.toBeInTheDocument();
    expect(screen.queryByText(/chain.?of.?thought/i)).not.toBeInTheDocument();
  });

  it('shows a starting indicator before any events arrive', () => {
    render(<ExecutionProgress events={[]} />);
    expect(screen.getByText('Starting...')).toBeInTheDocument();
  });
});
