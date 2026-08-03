import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ExecutionPanel } from '@/components/workflow/execution-panel';
import type { WorkflowRead, WorkflowStepRead } from '@/types/backend';

vi.mock('@/hooks/use-audit-chain-verification', () => ({
  useAuditChainVerification: () => ({ data: null, loading: true, error: null, refresh: vi.fn() }),
}));

function makeStep(overrides: Partial<WorkflowStepRead>): WorkflowStepRead {
  return {
    id: overrides.id ?? 'step-1',
    workflow_id: 'wf-1',
    name: 'step',
    position: 0,
    agent_type: 'demo',
    status: 'pending',
    input_payload: {},
    output_payload: null,
    error_message: null,
    max_attempts: 3,
    attempt_count: 0,
    compensation_handler: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    started_at: null,
    completed_at: null,
    attempts: [],
    compensation_attempts: [],
    ...overrides,
  };
}

function makeWorkflow(overrides: Partial<WorkflowRead>): WorkflowRead {
  return {
    id: 'wf-1',
    name: 'Test workflow',
    description: null,
    status: 'pending',
    input_payload: {},
    output_payload: null,
    error_message: null,
    compensation_summary: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    started_at: null,
    completed_at: null,
    version: 1,
    steps: [],
    ...overrides,
  };
}

describe('ExecutionPanel', () => {
  it('renders steps in position order, driven by the real workflow, never a fixed pipeline', () => {
    const workflow = makeWorkflow({
      steps: [
        makeStep({ id: 's-b', name: 'second-step', position: 1 }),
        makeStep({ id: 's-a', name: 'first-step', position: 0 }),
      ],
    });

    render(
      <ExecutionPanel
        workflow={workflow}
        onExecute={vi.fn()}
        onCompensate={vi.fn()}
        executing={false}
        compensating={false}
      />
    );

    const headings = screen.getAllByText(/^(0|1)\. (first-step|second-step)$/);
    expect(headings[0]).toHaveTextContent('0. first-step');
    expect(headings[1]).toHaveTextContent('1. second-step');
  });

  it('never renders the fixed Planner/Research/Executor/Validator/Reporter pipeline', () => {
    const workflow = makeWorkflow({
      steps: [makeStep({ name: 'real-step', agent_type: 'demo' })],
    });

    render(
      <ExecutionPanel
        workflow={workflow}
        onExecute={vi.fn()}
        onCompensate={vi.fn()}
        executing={false}
        compensating={false}
      />
    );

    for (const fixedStage of ['Planner', 'Research', 'Executor', 'Validator', 'Reporter']) {
      expect(screen.queryByText(fixedStage)).not.toBeInTheDocument();
    }
  });

  it('enables Execute only for a pending workflow', () => {
    const { rerender } = render(
      <ExecutionPanel
        workflow={makeWorkflow({ status: 'pending' })}
        onExecute={vi.fn()}
        onCompensate={vi.fn()}
        executing={false}
        compensating={false}
      />
    );
    expect(screen.getByRole('button', { name: /^Execute$/ })).toBeEnabled();

    rerender(
      <ExecutionPanel
        workflow={makeWorkflow({ status: 'running' })}
        onExecute={vi.fn()}
        onCompensate={vi.fn()}
        executing={false}
        compensating={false}
      />
    );
    expect(screen.getByRole('button', { name: /^Execute$/ })).toBeDisabled();
  });

  it('shows Compensate Workflow only for an eligible (failed/succeeded) workflow', () => {
    const { rerender } = render(
      <ExecutionPanel
        workflow={makeWorkflow({ status: 'pending' })}
        onExecute={vi.fn()}
        onCompensate={vi.fn()}
        executing={false}
        compensating={false}
      />
    );
    expect(screen.queryByRole('button', { name: /Compensate Workflow/ })).not.toBeInTheDocument();

    rerender(
      <ExecutionPanel
        workflow={makeWorkflow({ status: 'failed' })}
        onExecute={vi.fn()}
        onCompensate={vi.fn()}
        executing={false}
        compensating={false}
      />
    );
    expect(screen.getByRole('button', { name: /Compensate Workflow/ })).toBeInTheDocument();
  });

  it('disables Execute while a request is already in progress, preventing duplicate submission', () => {
    render(
      <ExecutionPanel
        workflow={makeWorkflow({ status: 'pending' })}
        onExecute={vi.fn()}
        onCompensate={vi.fn()}
        executing={true}
        compensating={false}
      />
    );

    expect(screen.getByRole('button', { name: /Execution request in progress/ })).toBeDisabled();
  });
});
