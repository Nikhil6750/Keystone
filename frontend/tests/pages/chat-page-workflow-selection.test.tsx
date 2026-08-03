/**
 * Regression tests for a Phase 6A.1 browser-testing defect: after a workflow
 * finished executing and the user clicked "Start another workflow" to create
 * a second workflow, clicking Execute on the newly displayed (pending)
 * workflow could still send the POST .../execute request for the *previous*
 * (already succeeded) workflow's id — the backend then correctly rejected it
 * with "workflow '<id>' cannot start execution from status 'succeeded'".
 *
 * These tests drive the exact reported sequence — create workflow A, execute
 * it successfully, "Start another workflow", create workflow B, execute it —
 * and assert the displayed workflow and the id used by the Execute action
 * can never diverge, that stale state never survives "Start another
 * workflow", and that duplicate/late-arriving responses can never overwrite
 * a newer workflow's state.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ChatPage from '@/app/chat/page';
import { ApiClientError } from '@/services/api-client';
import type { AgentAvailabilityRead, WorkflowRead } from '@/types/backend';

vi.mock('@/hooks/use-agents', () => ({
  useAgents: () => ({
    data: {
      items: [
        {
          agent_type: 'demo',
          display_name: 'Demo Agent',
          enabled: true,
          available: true,
          registered: true,
          execution_mode: 'demo',
          reason: 'ok',
          installation_status: 'installed',
          authentication_status: 'authenticated',
          connection_status: 'connected',
          version: null,
          last_checked_at: null,
          capabilities: [],
        } satisfies AgentAvailabilityRead,
      ],
      count: 1,
    },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

vi.mock('@/hooks/use-audit-chain-verification', () => ({
  useAuditChainVerification: () => ({ data: null, loading: true, error: null, refresh: vi.fn() }),
}));

vi.mock('@/hooks/use-workflows', () => ({
  useWorkflows: () => ({ data: { items: [], count: 0 }, loading: false, error: null, refresh: vi.fn() }),
}));

vi.mock('@/hooks/use-backend-health', () => ({
  useBackendHealth: () => ({ data: null, loading: false, error: null, refresh: vi.fn() }),
}));

const createWorkflow = vi.fn();
const executeWorkflow = vi.fn();
const compensateWorkflow = vi.fn();

vi.mock('@/services/workflows', () => ({
  createWorkflow: (...args: unknown[]) => createWorkflow(...args),
  executeWorkflow: (...args: unknown[]) => executeWorkflow(...args),
  compensateWorkflow: (...args: unknown[]) => compensateWorkflow(...args),
  listWorkflows: () => Promise.resolve({ items: [], count: 0 }),
}));

function makeWorkflow(overrides: Partial<WorkflowRead>): WorkflowRead {
  return {
    id: 'wf-default',
    name: 'Workflow',
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

/** Deferred promise helper for controlling exactly when a mocked call resolves. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function createAndOpenWorkflow(user: ReturnType<typeof userEvent.setup>, workflow: WorkflowRead) {
  createWorkflow.mockResolvedValueOnce(workflow);
  await user.click(screen.getByText('Build REST API'));
  await user.click(await screen.findByRole('button', { name: /^Create Workflow$/ }));
  await screen.findByText(workflow.name);
}

describe('ChatPage — workflow selection / execute id consistency', () => {
  beforeEach(() => {
    createWorkflow.mockReset();
    executeWorkflow.mockReset();
    compensateWorkflow.mockReset();
  });

  it('sends the second workflow id after "Start another workflow", never the first', async () => {
    const user = userEvent.setup();
    render(<ChatPage />);

    const workflowA = makeWorkflow({ id: 'workflow-a', name: 'Claude workflow', status: 'pending' });
    await createAndOpenWorkflow(user, workflowA);

    const succeededA = { ...workflowA, status: 'succeeded' as const };
    executeWorkflow.mockResolvedValueOnce(succeededA);
    await user.click(screen.getByRole('button', { name: /^Execute$/ }));
    await waitFor(() => expect(executeWorkflow).toHaveBeenCalledWith('workflow-a', expect.anything()));
    await screen.findByText('Succeeded');

    // "Start another workflow" must clear the previous workflow entirely.
    await user.click(screen.getByRole('button', { name: /Start another workflow/i }));
    expect(screen.queryByText('Claude workflow')).not.toBeInTheDocument();

    const workflowB = makeWorkflow({ id: 'workflow-b', name: 'Antigravity workflow', status: 'pending' });
    await createAndOpenWorkflow(user, workflowB);

    // The panel must display workflow B, not workflow A.
    expect(screen.getByText('Antigravity workflow')).toBeInTheDocument();
    expect(screen.getByText('Pending')).toBeInTheDocument();

    const succeededB = { ...workflowB, status: 'succeeded' as const };
    executeWorkflow.mockResolvedValueOnce(succeededB);
    await user.click(screen.getByRole('button', { name: /^Execute$/ }));

    // The Execute action must target workflow B's id — never workflow A's.
    await waitFor(() => expect(executeWorkflow).toHaveBeenCalledWith('workflow-b', expect.anything()));
    expect(executeWorkflow).toHaveBeenCalledTimes(2);
    expect(executeWorkflow).not.toHaveBeenNthCalledWith(2, 'workflow-a', expect.anything());
  });

  it('never lets a late (in-flight) response for the first workflow overwrite the second workflow once created', async () => {
    const user = userEvent.setup();
    render(<ChatPage />);

    const workflowA = makeWorkflow({ id: 'workflow-a', name: 'Claude workflow', status: 'pending' });
    await createAndOpenWorkflow(user, workflowA);

    // Execute workflow A but never let the request resolve yet.
    const pendingExecuteA = deferred<WorkflowRead>();
    executeWorkflow.mockReturnValueOnce(pendingExecuteA.promise);
    await user.click(screen.getByRole('button', { name: /^Execute$/ }));
    await waitFor(() => expect(executeWorkflow).toHaveBeenCalledWith('workflow-a', expect.anything()));

    // Before workflow A's request resolves, the user starts another workflow
    // and creates workflow B.
    await user.click(screen.getByRole('button', { name: /Start another workflow/i }));
    const workflowB = makeWorkflow({ id: 'workflow-b', name: 'Antigravity workflow', status: 'pending' });
    await createAndOpenWorkflow(user, workflowB);

    // Now workflow A's stale execute response finally arrives.
    pendingExecuteA.resolve({ ...workflowA, status: 'succeeded' });
    await new Promise((r) => setTimeout(r, 0));

    // Workflow B must still be the one displayed — untouched by A's response.
    expect(screen.getByText('Antigravity workflow')).toBeInTheDocument();
    expect(screen.queryByText('Claude workflow')).not.toBeInTheDocument();
    expect(screen.getByText('Pending')).toBeInTheDocument();
  });

  it('clears the previous execution error when starting another workflow', async () => {
    const user = userEvent.setup();
    render(<ChatPage />);

    const workflowA = makeWorkflow({ id: 'workflow-a', name: 'Claude workflow', status: 'pending' });
    await createAndOpenWorkflow(user, workflowA);

    executeWorkflow.mockRejectedValueOnce(
      new ApiClientError(
        "workflow 'workflow-a' cannot start execution from status 'succeeded'",
        'INVALID_WORKFLOW_STATE',
        409
      )
    );
    await user.click(screen.getByRole('button', { name: /^Execute$/ }));
    await screen.findByText(/cannot start execution from status/i);

    await user.click(screen.getByRole('button', { name: /Start another workflow/i }));
    expect(screen.queryByText(/cannot start execution from status/i)).not.toBeInTheDocument();

    const workflowB = makeWorkflow({ id: 'workflow-b', name: 'Antigravity workflow', status: 'pending' });
    await createAndOpenWorkflow(user, workflowB);
    expect(screen.queryByText(/cannot start execution from status/i)).not.toBeInTheDocument();
  });

  it('prevents duplicate execution requests for the same workflow while one is in flight', async () => {
    const user = userEvent.setup();
    render(<ChatPage />);

    const workflow = makeWorkflow({ id: 'workflow-a', name: 'Claude workflow', status: 'pending' });
    await createAndOpenWorkflow(user, workflow);

    const pendingExecute = deferred<WorkflowRead>();
    executeWorkflow.mockReturnValueOnce(pendingExecute.promise);

    const executeButton = screen.getByRole('button', { name: /^Execute$/ });
    await user.click(executeButton);
    await waitFor(() => expect(executeButton).toBeDisabled());

    // Extra clicks while disabled/in-flight must not send additional requests.
    await user.click(executeButton);
    await user.click(executeButton);
    expect(executeWorkflow).toHaveBeenCalledTimes(1);

    pendingExecute.resolve({ ...workflow, status: 'succeeded' });
    await waitFor(() => expect(screen.getByRole('button', { name: /^Execute$/ })).toBeDisabled());
  });

  it('never permits execution when the displayed workflow is not pending', async () => {
    const user = userEvent.setup();
    render(<ChatPage />);

    const workflow = makeWorkflow({ id: 'workflow-a', name: 'Claude workflow', status: 'pending' });
    await createAndOpenWorkflow(user, workflow);

    executeWorkflow.mockResolvedValueOnce({ ...workflow, status: 'succeeded' });
    await user.click(screen.getByRole('button', { name: /^Execute$/ }));
    await screen.findByText('Succeeded');

    // The now-succeeded workflow's Execute button must be disabled, and
    // clicking it (even if somehow re-enabled) must never fire a request.
    const executeButton = screen.getByRole('button', { name: /^Execute$/ });
    expect(executeButton).toBeDisabled();
    executeWorkflow.mockClear();
    await user.click(executeButton);
    expect(executeWorkflow).not.toHaveBeenCalled();
  });
});
