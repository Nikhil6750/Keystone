import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { WorkflowBuilder, createEmptyDraft } from '@/components/workflow/workflow-builder';
import type { AgentAvailabilityListResponse } from '@/types/backend';

/**
 * Regression test for Phase 6A.1's reported "stale /chat agent status" defect.
 *
 * The actual root cause was the backend's connection-cache TTL (60s, fixed to
 * 600s), not stale frontend state — this test locks in the frontend half of
 * that finding: every time a `WorkflowBuilder` mounts (which happens fresh
 * each time `/chat` is navigated to, since it only renders once the user
 * enters "builder" mode), it must call the real `listAgents` service function
 * again rather than reusing a previously-cached response. Mocking
 * `@/services/agents` here (instead of `@/hooks/use-agents`, as the sibling
 * selectability tests do) is what lets this test observe the actual fetch.
 */

const listAgentsMock =
  vi.fn<(options?: { signal?: AbortSignal }) => Promise<AgentAvailabilityListResponse>>();

vi.mock('@/services/agents', () => ({
  listAgents: (options?: { signal?: AbortSignal }) => listAgentsMock(options),
}));

beforeEach(() => {
  listAgentsMock.mockReset();
  listAgentsMock.mockResolvedValue({
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
      },
    ],
    count: 1,
  });
});

describe('WorkflowBuilder refetches agent availability on every mount', () => {
  it('calls listAgents again on a fresh mount, simulating navigating away from /chat and back', async () => {
    const { unmount } = render(
      <WorkflowBuilder draft={createEmptyDraft()} onChange={vi.fn()} errors={{ steps: {} }} />
    );
    await vi.waitFor(() => expect(listAgentsMock).toHaveBeenCalledTimes(1));

    // Simulate leaving /chat (e.g. visiting /agents) and coming back — in the
    // real app this is a full component unmount/remount, since WorkflowBuilder
    // is only rendered while ChatPage's local `mode` state is `'builder'`.
    unmount();
    cleanup();

    render(
      <WorkflowBuilder draft={createEmptyDraft()} onChange={vi.fn()} errors={{ steps: {} }} />
    );
    await vi.waitFor(() => expect(listAgentsMock).toHaveBeenCalledTimes(2));
  });
});
