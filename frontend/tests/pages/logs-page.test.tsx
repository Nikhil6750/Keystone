import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LogsPage from '@/app/logs/page';
import type { AuditEventRead } from '@/types/backend';

const workflows = [
  {
    id: 'wf-1',
    name: 'Demo workflow',
    description: null,
    status: 'succeeded' as const,
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
  },
];

const events: AuditEventRead[] = [
  {
    id: 'e1',
    workflow_id: 'wf-1',
    step_id: null,
    execution_attempt_id: null,
    compensation_attempt_id: null,
    sequence_number: 1,
    event_type: 'workflow_created',
    actor_type: 'user',
    actor_id: 'api',
    payload: {},
    previous_hash: '0'.repeat(64),
    event_hash: 'a'.repeat(64),
    created_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'e2',
    workflow_id: 'wf-1',
    step_id: null,
    execution_attempt_id: null,
    compensation_attempt_id: null,
    sequence_number: 2,
    event_type: 'workflow_succeeded',
    actor_type: 'system',
    actor_id: 'workflow_engine',
    payload: {},
    previous_hash: 'a'.repeat(64),
    event_hash: 'b'.repeat(64),
    created_at: '2026-01-01T00:00:05Z',
  },
];

let verification = { workflow_id: 'wf-1', valid: true, event_count: 2, first_invalid_sequence: null as number | null, reason: null as string | null };

vi.mock('@/hooks/use-workflows', () => ({
  useWorkflows: () => ({ data: { items: workflows, count: workflows.length }, loading: false, error: null, refresh: vi.fn() }),
}));

vi.mock('@/hooks/use-provenance', () => ({
  useProvenance: (workflowId: string | null) => ({
    data: workflowId ? { workflow_id: workflowId, chain_valid: verification.valid, events } : null,
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

vi.mock('@/hooks/use-audit-chain-verification', () => ({
  useAuditChainVerification: (workflowId: string | null) => ({
    data: workflowId ? verification : null,
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

describe('LogsPage', () => {
  it('shows the valid audit-chain state', async () => {
    verification = { workflow_id: 'wf-1', valid: true, event_count: 2, first_invalid_sequence: null, reason: null };
    render(<LogsPage />);

    await userEvent.setup().selectOptions(screen.getByLabelText(/Select a workflow/i), 'wf-1');

    expect(screen.getByText(/Tamper-evident audit chain valid/i)).toBeInTheDocument();
  });

  it('shows the invalid audit-chain state with the first invalid sequence', async () => {
    verification = {
      workflow_id: 'wf-1',
      valid: false,
      event_count: 2,
      first_invalid_sequence: 2,
      reason: 'Event hash mismatch',
    };
    render(<LogsPage />);

    await userEvent.setup().selectOptions(screen.getByLabelText(/Select a workflow/i), 'wf-1');

    expect(screen.getByText(/Audit chain invalid/i)).toBeInTheDocument();
    expect(screen.getByText(/First invalid sequence:/)).toHaveTextContent(
      'First invalid sequence: 2'
    );
  });

  it('renders provenance events in sequence order', async () => {
    verification = { workflow_id: 'wf-1', valid: true, event_count: 2, first_invalid_sequence: null, reason: null };
    render(<LogsPage />);

    await userEvent.setup().selectOptions(screen.getByLabelText(/Select a workflow/i), 'wf-1');

    const items = screen.getAllByText(/^#\d/);
    expect(items[0]).toHaveTextContent('#1');
    expect(items[1]).toHaveTextContent('#2');
  });
});
