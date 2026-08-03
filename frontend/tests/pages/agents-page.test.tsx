import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AgentsPage from '@/app/agents/page';
import type { AgentAvailabilityRead, AgentConnectionVerifyRead } from '@/types/backend';

const refresh = vi.fn();

function buildAgent(overrides: Partial<AgentAvailabilityRead>): AgentAvailabilityRead {
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

let agents: AgentAvailabilityRead[] = [];

vi.mock('@/hooks/use-agents', () => ({
  useAgents: () => ({
    data: { items: agents, count: agents.length },
    loading: false,
    error: null,
    refresh,
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
  useWorkflows: () => ({
    data: { items: [], count: 0 },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

vi.mock('@/hooks/use-backend-health', () => ({
  useBackendHealth: () => ({
    data: { status: 'healthy', service: 'keystone-backend', version: '0.1.0' },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

const verifyAgentMock = vi.fn<(agentType: string) => Promise<AgentConnectionVerifyRead>>();

vi.mock('@/services/agents', () => ({
  verifyAgent: (agentType: string) => verifyAgentMock(agentType),
}));

beforeEach(() => {
  refresh.mockClear();
  verifyAgentMock.mockReset();
});

describe('AgentsPage', () => {
  it('renders real agent availability from the backend, including Claude Code, Codex, and Antigravity', () => {
    agents = [
      buildAgent({ agent_type: 'claude_code', display_name: 'Claude Code' }),
      buildAgent({ agent_type: 'codex', display_name: 'OpenAI Codex' }),
      buildAgent({ agent_type: 'antigravity', display_name: 'Google Antigravity' }),
      buildAgent({ agent_type: 'demo', display_name: 'Demo Agent' }),
    ];

    render(<AgentsPage />);

    expect(screen.getByRole('heading', { name: 'Claude Code' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'OpenAI Codex' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Google Antigravity' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Demo Agent' })).toBeInTheDocument();
  });

  it('accurately shows install/auth/connection state for each provider, not a single boolean', () => {
    agents = [
      buildAgent({
        agent_type: 'claude_code',
        display_name: 'Claude Code',
        installation_status: 'installed',
        authentication_status: 'authenticated',
        connection_status: 'connected',
      }),
      buildAgent({
        agent_type: 'codex',
        display_name: 'OpenAI Codex',
        enabled: false,
        installation_status: 'not_installed',
        authentication_status: 'unknown',
        connection_status: 'disabled',
        reason: 'Disabled by configuration',
      }),
    ];

    render(<AgentsPage />);

    const claudeCard = screen.getByTestId('agent-card-claude_code');
    expect(within(claudeCard).getByText('Installed')).toBeInTheDocument();
    expect(within(claudeCard).getByText('Authenticated')).toBeInTheDocument();
    expect(within(claudeCard).getByText('Connected')).toBeInTheDocument();

    const codexCard = screen.getByTestId('agent-card-codex');
    expect(within(codexCard).getByText('Not installed')).toBeInTheDocument();
    expect(within(codexCard).getByText('Disabled')).toBeInTheDocument();
  });

  it('never shows a fake "Register Agent" control', () => {
    agents = [buildAgent({})];
    render(<AgentsPage />);

    expect(screen.queryByText(/Register Agent/i)).not.toBeInTheDocument();
  });

  it('displays the exact required credential-handling disclosure', () => {
    agents = [buildAgent({})];
    render(<AgentsPage />);

    expect(
      screen.getByText(
        'Keystone uses the provider CLI session already authenticated on the computer running the backend. Credentials never pass through the browser.'
      )
    ).toBeInTheDocument();
  });

  it('never renders an email, password, OTP, or API-key input anywhere on the page', () => {
    agents = [
      buildAgent({ agent_type: 'claude_code', authentication_status: 'unauthenticated' }),
      buildAgent({ agent_type: 'codex', authentication_status: 'unauthenticated' }),
    ];
    render(<AgentsPage />);

    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/one-time code|otp/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/api key/i)).not.toBeInTheDocument();
    expect(document.querySelector('input[type="password"]')).not.toBeInTheDocument();
  });

  it('shows the local claude auth login instruction only when unauthenticated', () => {
    agents = [
      buildAgent({
        agent_type: 'claude_code',
        display_name: 'Claude Code',
        authentication_status: 'unauthenticated',
      }),
    ];
    render(<AgentsPage />);

    expect(screen.getByText(/claude auth login/)).toBeInTheDocument();
  });

  it('shows the local codex login instruction only when unauthenticated', () => {
    agents = [
      buildAgent({
        agent_type: 'codex',
        display_name: 'OpenAI Codex',
        authentication_status: 'unauthenticated',
      }),
    ];
    render(<AgentsPage />);

    expect(screen.getByText(/codex login/)).toBeInTheDocument();
  });

  it('shows the local Antigravity sign-in instruction, never calling it "gemini"', () => {
    agents = [
      buildAgent({
        agent_type: 'antigravity',
        display_name: 'Google Antigravity',
        authentication_status: 'unauthenticated',
      }),
    ];
    render(<AgentsPage />);

    expect(screen.getByText(/Run `agy`/)).toBeInTheDocument();
    expect(screen.queryByText(/gemini/i)).not.toBeInTheDocument();
  });

  it('renders the Antigravity card with its own identity, never mislabeled as Gemini', () => {
    agents = [buildAgent({ agent_type: 'antigravity', display_name: 'Google Antigravity' })];
    render(<AgentsPage />);

    expect(screen.getByRole('heading', { name: 'Google Antigravity' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /gemini/i })).not.toBeInTheDocument();
  });

  it('shows a Gemini placeholder marked "not configured" when the backend returns it, without a full connection card', () => {
    agents = [
      buildAgent({ agent_type: 'demo' }),
      buildAgent({ agent_type: 'gemini', display_name: 'Gemini CLI' }),
    ];
    render(<AgentsPage />);

    expect(screen.getByText(/not configured/i)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Gemini CLI' })).not.toBeInTheDocument();
  });

  it('clicking "Verify Connection" calls the verify endpoint for that agent type', async () => {
    const user = userEvent.setup();
    agents = [buildAgent({ agent_type: 'claude_code', display_name: 'Claude Code' })];
    verifyAgentMock.mockResolvedValue({
      agent_type: 'claude_code',
      display_name: 'Claude Code',
      enabled: true,
      installation_status: 'installed',
      authentication_status: 'authenticated',
      connection_status: 'connected',
      registered: true,
      execution_mode: 'local_cli',
      version: '2.1.154',
      last_checked_at: '2026-08-03T00:00:00Z',
      reason: 'ok',
      capabilities: ['workflow_step_execution'],
    });

    render(<AgentsPage />);
    await user.click(screen.getByRole('button', { name: /verify connection for claude code/i }));

    await waitFor(() => expect(verifyAgentMock).toHaveBeenCalledWith('claude_code'));
  });

  it('prevents a duplicate verification request while one is already in flight', async () => {
    const user = userEvent.setup();
    agents = [buildAgent({ agent_type: 'claude_code', display_name: 'Claude Code' })];
    let resolveVerify: (value: AgentConnectionVerifyRead) => void = () => {};
    verifyAgentMock.mockReturnValue(
      new Promise((resolve) => {
        resolveVerify = resolve;
      })
    );

    render(<AgentsPage />);
    const button = screen.getByRole('button', { name: /verify connection for claude code/i });
    await user.click(button);
    await user.click(button);
    await user.click(button);

    expect(verifyAgentMock).toHaveBeenCalledTimes(1);

    resolveVerify({
      agent_type: 'claude_code',
      display_name: 'Claude Code',
      enabled: true,
      installation_status: 'installed',
      authentication_status: 'authenticated',
      connection_status: 'connected',
      registered: true,
      execution_mode: 'local_cli',
      version: '2.1.154',
      last_checked_at: null,
      reason: 'ok',
      capabilities: ['workflow_step_execution'],
    });
    await waitFor(() => expect(button).not.toBeDisabled());
  });

  it('refreshes the agent list after a verification attempt settles', async () => {
    const user = userEvent.setup();
    agents = [buildAgent({ agent_type: 'claude_code', display_name: 'Claude Code' })];
    verifyAgentMock.mockResolvedValue({
      agent_type: 'claude_code',
      display_name: 'Claude Code',
      enabled: true,
      installation_status: 'installed',
      authentication_status: 'authenticated',
      connection_status: 'connected',
      registered: true,
      execution_mode: 'local_cli',
      version: null,
      last_checked_at: null,
      reason: 'ok',
      capabilities: ['workflow_step_execution'],
    });

    render(<AgentsPage />);
    await user.click(screen.getByRole('button', { name: /verify connection for claude code/i }));

    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it('shows a safe error message, never a raw exception, when verification fails', async () => {
    const user = userEvent.setup();
    agents = [buildAgent({ agent_type: 'claude_code', display_name: 'Claude Code' })];
    verifyAgentMock.mockRejectedValue(new Error('Claude reported a usage-limit failure.'));

    render(<AgentsPage />);
    await user.click(screen.getByRole('button', { name: /verify connection for claude code/i }));

    await waitFor(() =>
      expect(screen.getByText('Claude reported a usage-limit failure.')).toBeInTheDocument()
    );
  });

  it('never claims success before the verify call resolves (no premature success state)', async () => {
    const user = userEvent.setup();
    agents = [
      buildAgent({
        agent_type: 'claude_code',
        display_name: 'Claude Code',
        connection_status: 'verification_required',
      }),
    ];
    verifyAgentMock.mockReturnValue(new Promise(() => {}));

    render(<AgentsPage />);
    await user.click(screen.getByRole('button', { name: /verify connection for claude code/i }));

    const claudeCard = screen.getByTestId('agent-card-claude_code');
    expect(
      within(claudeCard).getByText(/Running a safe headless verification/i)
    ).toBeInTheDocument();
    expect(within(claudeCard).queryByText('Connected')).not.toBeInTheDocument();
  });
});
