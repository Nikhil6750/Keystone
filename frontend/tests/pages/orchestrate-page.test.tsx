import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import OrchestratePage from '@/app/orchestrate/page';
import type { AgentAvailabilityRead, OrchestrationExecutionRead } from '@/types/backend';

const refresh = vi.fn();

function buildAgent(overrides: Partial<AgentAvailabilityRead> = {}): AgentAvailabilityRead {
  return {
    agent_type: 'demo',
    display_name: 'Demo Agent',
    enabled: true,
    available: true,
    registered: true,
    execution_mode: 'demo',
    reason: 'Demo mode enabled',
    installation_status: 'installed',
    authentication_status: 'authenticated',
    connection_status: 'connected',
    version: null,
    last_checked_at: null,
    capabilities: [],
    ...overrides,
  };
}

vi.mock('@/hooks/use-agents', () => ({
  useAgents: () => ({
    data: { items: [buildAgent()], count: 1 },
    loading: false,
    error: null,
    refresh,
  }),
}));

// The sidebar (rendered by AppLayout on every page) fetches recent
// workflows independently of this page's own content -- mocked so the test
// only exercises real network calls this page itself makes.
vi.mock('@/hooks/use-workflows', () => ({
  useWorkflows: () => ({
    data: { items: [], count: 0 },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

const createOrchestrationExecution = vi.fn();
const getOrchestrationExecution = vi.fn();

vi.mock('@/services/orchestrations', () => ({
  createOrchestrationExecution: (...args: unknown[]) => createOrchestrationExecution(...args),
  getOrchestrationExecution: (...args: unknown[]) => getOrchestrationExecution(...args),
}));

vi.mock('@/services/quality', () => ({
  getQualityRunGates: vi.fn().mockResolvedValue([]),
}));

vi.mock('@/services/intelligence', () => ({
  getAgentReliability: vi.fn().mockResolvedValue({
    agent_type: 'demo',
    task_type: null,
    observed_executions: 3,
    successful_executions: 2,
    failed_executions: 1,
    recovery_count: 0,
    quality_verified_successes: 1,
    success_rate: 0.667,
    sample_size_is_low: true,
  }),
}));

function terminalResult(
  overrides: Partial<OrchestrationExecutionRead> = {}
): OrchestrationExecutionRead {
  return {
    execution_id: 'exec-1',
    job_status: 'completed',
    orchestration_outcome: 'verified_success',
    workflow_id: 'wf-1',
    final_workflow_state: 'succeeded',
    verification_status: 'passed',
    task_count: 1,
    selected_agent_types: ['demo'],
    attempt_count: 1,
    recovery_used: false,
    recovery_action: null,
    learning_event_count: 1,
    retrieval_feedback_recorded: false,
    issue_codes: [],
    quality_run_id: 'qrun-1',
    quality_verdict_status: 'ACCEPTED',
    error_summary: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:05Z',
    ...overrides,
  };
}

beforeEach(() => {
  createOrchestrationExecution.mockReset();
  getOrchestrationExecution.mockReset();
});

describe('OrchestratePage', () => {
  it('submits the goal and selected agents, then shows the terminal outcome', async () => {
    const user = userEvent.setup();
    createOrchestrationExecution.mockResolvedValue({
      execution_id: 'exec-1',
      status: 'accepted',
      events_url: '/api/v1/orchestrations/exec-1/events',
      result_url: '/api/v1/orchestrations/exec-1',
    });
    getOrchestrationExecution.mockResolvedValue(terminalResult());

    render(<OrchestratePage />);

    await user.type(screen.getByLabelText('Goal'), 'Implement a REST endpoint with tests');
    await user.type(screen.getByLabelText('Workspace root'), 'C:\\projects\\demo');
    await user.click(screen.getByRole('button', { name: 'Demo Agent' }));
    await user.click(screen.getByRole('button', { name: /run orchestration/i }));

    await waitFor(() => expect(createOrchestrationExecution).toHaveBeenCalledTimes(1));
    expect(createOrchestrationExecution).toHaveBeenCalledWith({
      goal: 'Implement a REST endpoint with tests',
      available_agent_types: ['demo'],
      workspace_root: 'C:\\projects\\demo',
    });

    await waitFor(() => expect(screen.getAllByText('Verified success').length).toBeGreaterThan(0));
    expect(screen.getByText('Completed')).toBeInTheDocument();
  });

  it('disables submission until a goal, workspace, and agent are selected', () => {
    render(<OrchestratePage />);
    expect(screen.getByRole('button', { name: /run orchestration/i })).toBeDisabled();
  });

  it('shows a rejected quality verdict without claiming success', async () => {
    const user = userEvent.setup();
    createOrchestrationExecution.mockResolvedValue({
      execution_id: 'exec-2',
      status: 'accepted',
      events_url: '/api/v1/orchestrations/exec-2/events',
      result_url: '/api/v1/orchestrations/exec-2',
    });
    getOrchestrationExecution.mockResolvedValue(
      terminalResult({
        execution_id: 'exec-2',
        orchestration_outcome: 'verification_failed',
        quality_verdict_status: 'REJECTED',
      })
    );

    render(<OrchestratePage />);
    await user.type(screen.getByLabelText('Goal'), 'Implement a REST endpoint with tests');
    await user.type(screen.getByLabelText('Workspace root'), 'C:\\projects\\demo');
    await user.click(screen.getByRole('button', { name: 'Demo Agent' }));
    await user.click(screen.getByRole('button', { name: /run orchestration/i }));

    await waitFor(() =>
      expect(screen.getAllByText('Verification failed').length).toBeGreaterThan(0)
    );
    expect(screen.queryAllByText('Verified success')).toHaveLength(0);
  });
});
