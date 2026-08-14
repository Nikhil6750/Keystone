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

    expect(screen.getByText(/Verifying/i)).toBeInTheDocument();
    expect(screen.getByText(/qwen-coder/i)).toBeInTheDocument();
    expect(screen.getByText(/corp-reviewer/i)).toBeInTheDocument();
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
    expect(screen.getByText(/Understanding your goal/i)).toBeInTheDocument();
  });

  it('correctly handles all 7 UI states: queued, waiting, working, rerouted, verifying, completed, failed', () => {
    const events: OrchestrationEvent[] = [
      makeEvent({
        event_id: 'e1',
        sequence: 1,
        event_type: 'routing.task_selected',
        task_key: 'T1',
        agent_id: 'codex',
      }),
      makeEvent({
        event_id: 'e2',
        sequence: 2,
        event_type: 'task.waiting',
        task_key: 'T2',
        agent_id: 'antigravity',
        reason_category: 'dependency',
      }),
      makeEvent({
        event_id: 'e3',
        sequence: 3,
        event_type: 'step.started',
        task_key: 'T3',
        agent_id: 'gemini',
      }),
      makeEvent({
        event_id: 'e4',
        sequence: 4,
        event_type: 'file.activity',
        task_key: 'T3',
        agent_id: 'gemini',
        relative_path: 'server.py',
        activity: 'modified',
      }),
      makeEvent({
        event_id: 'e5',
        sequence: 5,
        event_type: 'recovery.started',
        task_key: 'T4',
        agent_id: 'claude-code',
        new_agent_id: 'antigravity',
        reason_category: 'verification_failure',
      }),
      makeEvent({
        event_id: 'e6',
        sequence: 6,
        event_type: 'verification.started',
        task_key: 'T5',
        agent_id: 'codex',
      }),
      makeEvent({
        event_id: 'e7',
        sequence: 7,
        event_type: 'step.completed',
        task_key: 'T6',
        agent_id: 'codex',
      }),
      makeEvent({
        event_id: 'e8',
        sequence: 8,
        event_type: 'step.failed',
        task_key: 'T7',
        agent_id: 'codex',
      }),
    ];

    render(<ExecutionProgress events={events} />);

    expect(screen.getByText('queued')).toBeInTheDocument();
    expect(screen.getByText('waiting')).toBeInTheDocument();
    expect(screen.getByText('working')).toBeInTheDocument();
    expect(screen.getByText('rerouted')).toBeInTheDocument();
    expect(screen.getByText('verifying')).toBeInTheDocument();
    expect(screen.getByText('completed')).toBeInTheDocument();
    expect(screen.getByText('failed')).toBeInTheDocument();
    expect(screen.getByText('server.py')).toBeInTheDocument();
  });
});
