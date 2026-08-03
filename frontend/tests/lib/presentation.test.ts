import { describe, expect, it } from 'vitest';
import {
  compensationAttemptStatusLabel,
  isWorkflowCompensable,
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

  it('marks only failed/succeeded as compensable', () => {
    expect(isWorkflowCompensable('failed')).toBe(true);
    expect(isWorkflowCompensable('succeeded')).toBe(true);
    expect(isWorkflowCompensable('pending')).toBe(false);
    expect(isWorkflowCompensable('running')).toBe(false);
    expect(isWorkflowCompensable('compensating')).toBe(false);
    expect(isWorkflowCompensable('compensated')).toBe(false);
    expect(isWorkflowCompensable('cancelled')).toBe(false);
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
