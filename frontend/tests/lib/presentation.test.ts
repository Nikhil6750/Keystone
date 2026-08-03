import { describe, expect, it } from 'vitest';
import {
  canCompensateWorkflow,
  compensationAttemptStatusLabel,
  isWorkflowExecutable,
  workflowStatusLabel,
} from '@/lib/presentation';
import type { WorkflowStatus } from '@/types/backend';

describe('workflowStatusLabel', () => {
  const ALL_STATUSES: WorkflowStatus[] = [
    'pending',
    'running',
    'succeeded',
    'failed',
    'compensating',
    'compensated',
    'cancelled',
  ];

  it('renders every real backend workflow status to a non-empty label without altering the value', () => {
    for (const status of ALL_STATUSES) {
      expect(workflowStatusLabel(status)).toBeTruthy();
    }
  });

  it('never uses UI-only invented values like "Waiting" or "Completed" as the wire value', () => {
    expect(ALL_STATUSES).not.toContain('Waiting');
    expect(ALL_STATUSES).not.toContain('Completed');
  });

  it('marks only failed as compensable — the backend rejects every other status, including succeeded, with 409 INVALID_COMPENSATION_STATE', () => {
    expect(canCompensateWorkflow('failed')).toBe(true);
    expect(canCompensateWorkflow('succeeded')).toBe(false);
    expect(canCompensateWorkflow('pending')).toBe(false);
    expect(canCompensateWorkflow('running')).toBe(false);
    expect(canCompensateWorkflow('compensating')).toBe(false);
    expect(canCompensateWorkflow('compensated')).toBe(false);
    expect(canCompensateWorkflow('cancelled')).toBe(false);
  });

  it('marks only pending as executable', () => {
    expect(isWorkflowExecutable('pending')).toBe(true);
    expect(isWorkflowExecutable('running')).toBe(false);
    expect(isWorkflowExecutable('succeeded')).toBe(false);
  });
});

describe('compensationAttemptStatusLabel', () => {
  it('renders every compensation attempt status', () => {
    expect(compensationAttemptStatusLabel('running')).toBe('Running');
    expect(compensationAttemptStatusLabel('succeeded')).toBe('Succeeded');
    expect(compensationAttemptStatusLabel('failed')).toBe('Failed');
  });
});
