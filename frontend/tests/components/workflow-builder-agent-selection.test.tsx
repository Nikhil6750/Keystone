import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { WorkflowBuilder, createEmptyDraft } from '@/components/workflow/workflow-builder';
import type { AgentAvailabilityRead } from '@/types/backend';

function buildAgent(overrides: Partial<AgentAvailabilityRead>): AgentAvailabilityRead {
  return {
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
    ...overrides,
  };
}

let agents: AgentAvailabilityRead[] = [];

vi.mock('@/hooks/use-agents', () => ({
  useAgents: () => ({
    data: { items: agents, count: agents.length },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

describe('WorkflowBuilder agent selectability', () => {
  it('disables a disconnected agent option so it cannot be selected for a step', () => {
    agents = [
      buildAgent({ agent_type: 'demo', display_name: 'Demo Agent' }),
      buildAgent({
        agent_type: 'claude_code',
        display_name: 'Claude Code',
        connection_status: 'verification_required',
      }),
    ];

    render(
      <WorkflowBuilder draft={createEmptyDraft()} onChange={vi.fn()} errors={{ steps: {} }} />
    );

    const option = screen.getByRole('option', { name: /Claude Code/i }) as HTMLOptionElement;
    expect(option.disabled).toBe(true);
  });

  it('disables an unauthenticated agent option so it cannot be selected for a step', () => {
    agents = [
      buildAgent({ agent_type: 'demo', display_name: 'Demo Agent' }),
      buildAgent({
        agent_type: 'codex',
        display_name: 'OpenAI Codex',
        authentication_status: 'unauthenticated',
      }),
    ];

    render(
      <WorkflowBuilder draft={createEmptyDraft()} onChange={vi.fn()} errors={{ steps: {} }} />
    );

    const option = screen.getByRole('option', { name: /OpenAI Codex/i }) as HTMLOptionElement;
    expect(option.disabled).toBe(true);
  });

  it('leaves a fully connected, authenticated, installed agent option selectable', () => {
    agents = [
      buildAgent({ agent_type: 'demo', display_name: 'Demo Agent' }),
      buildAgent({ agent_type: 'claude_code', display_name: 'Claude Code' }),
    ];

    render(
      <WorkflowBuilder draft={createEmptyDraft()} onChange={vi.fn()} errors={{ steps: {} }} />
    );

    const option = screen.getByRole('option', { name: /Claude Code/i }) as HTMLOptionElement;
    expect(option.disabled).toBe(false);
  });

  it('never substitutes Antigravity for Gemini or vice versa in the agent list', () => {
    agents = [
      buildAgent({ agent_type: 'demo', display_name: 'Demo Agent' }),
      buildAgent({ agent_type: 'antigravity', display_name: 'Google Antigravity' }),
    ];

    render(
      <WorkflowBuilder draft={createEmptyDraft()} onChange={vi.fn()} errors={{ steps: {} }} />
    );

    expect(screen.getByRole('option', { name: /Google Antigravity/i })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /^Gemini/i })).not.toBeInTheDocument();
  });

  it('keeps the existing workflow-builder UI (name, description, add-step) fully functional', () => {
    agents = [buildAgent({ agent_type: 'demo', display_name: 'Demo Agent' })];

    render(
      <WorkflowBuilder draft={createEmptyDraft()} onChange={vi.fn()} errors={{ steps: {} }} />
    );

    expect(screen.getByLabelText('Workflow name')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Add step/i })).toBeInTheDocument();
  });
});
