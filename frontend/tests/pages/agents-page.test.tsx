import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import AgentsPage from '@/app/agents/page';
import type { AgentAvailabilityRead } from '@/types/backend';

const agents: AgentAvailabilityRead[] = [
  {
    agent_type: 'demo',
    enabled: true,
    available: true,
    registered: true,
    execution_mode: 'demo',
    reason: 'Demo mode enabled',
  },
  {
    agent_type: 'claude_code',
    enabled: false,
    available: false,
    registered: false,
    execution_mode: 'local_cli',
    reason: 'Disabled by configuration',
  },
];

vi.mock('@/hooks/use-agents', () => ({
  useAgents: () => ({
    data: { items: agents, count: agents.length },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

vi.mock('@/hooks/use-circuit-breakers', () => ({
  useCircuitBreakers: () => ({
    data: { items: [], count: 0 },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

vi.mock('@/hooks/use-workflows', () => ({
  useWorkflows: () => ({ data: { items: [], count: 0 }, loading: false, error: null, refresh: vi.fn() }),
}));

vi.mock('@/hooks/use-backend-health', () => ({
  useBackendHealth: () => ({
    data: { status: 'healthy', service: 'keystone-backend', version: '0.1.0' },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

describe('AgentsPage', () => {
  it('renders real agent availability from the backend', () => {
    render(<AgentsPage />);

    expect(screen.getByRole('heading', { name: 'demo' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'claude_code' })).toBeInTheDocument();
  });

  it('clearly marks an unavailable/unregistered agent as not ready', () => {
    render(<AgentsPage />);

    expect(screen.getByText('Disabled')).toBeInTheDocument();
    expect(screen.getByText('Ready to execute')).toBeInTheDocument();
  });

  it('never shows a fake "Register Agent" control', () => {
    render(<AgentsPage />);

    expect(screen.queryByText(/Register Agent/i)).not.toBeInTheDocument();
  });
});
