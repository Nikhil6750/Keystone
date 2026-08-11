import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { InstalledSignInView } from './InstalledSignInView';

vi.mock('../../api/keystoneClient', async () => {
  const actual = await vi.importActual<typeof import('../../api/keystoneClient')>(
    '../../api/keystoneClient'
  );
  return {
    ...actual,
    fetchDetectedRuntimes: vi.fn(),
    fetchAgentConnections: vi.fn(),
    activateRuntime: vi.fn(),
    createAgentConnection: vi.fn(),
    createConnectedAgent: vi.fn(),
  };
});

import {
  activateRuntime,
  createAgentConnection,
  createConnectedAgent,
  fetchAgentConnections,
  fetchDetectedRuntimes,
} from '../../api/keystoneClient';

const mockFetchDetectedRuntimes = vi.mocked(fetchDetectedRuntimes);
const mockFetchAgentConnections = vi.mocked(fetchAgentConnections);
const mockActivateRuntime = vi.mocked(activateRuntime);
const mockCreateAgentConnection = vi.mocked(createAgentConnection);
const mockCreateConnectedAgent = vi.mocked(createConnectedAgent);

const installedRuntime = {
  agent_type: 'claude_code',
  display_name: 'Claude Code',
  enabled: false,
  available: false,
  registered: false,
  execution_mode: 'local_cli',
  reason: 'Disabled by configuration',
  installation_status: 'installed' as const,
  authentication_status: 'unknown' as const,
  connection_status: 'unknown' as const,
  version: null,
  last_checked_at: null,
  capabilities: ['code_generation', 'test_execution'],
};

const missingRuntime = {
  ...installedRuntime,
  agent_type: 'codex',
  display_name: 'OpenAI Codex',
  installation_status: 'not_installed' as const,
};

const demoRuntime = {
  ...installedRuntime,
  agent_type: 'demo',
  display_name: 'Demo Agent',
};

function mockSuccessfulConnect(agentType: string, displayName: string) {
  mockActivateRuntime.mockResolvedValue({
    agent_type: agentType,
    display_name: displayName,
    enabled: true,
    installation_status: 'installed',
    authentication_status: 'authenticated',
    connection_status: 'connected',
    registered: true,
    execution_mode: 'local_cli',
    version: '2.1.154',
    last_checked_at: null,
    reason: 'Verified via a harmless headless prompt',
    capabilities: ['code_generation', 'test_execution'],
  });
  mockCreateAgentConnection.mockResolvedValue({
    connection_id: `${agentType}-local`,
    display_name: `${displayName} (local)`,
    connection_kind: 'installed_runtime',
    provider_or_runtime: agentType,
    status: 'connected',
    metadata: {},
    created_at: '',
    updated_at: '',
  });
  mockCreateConnectedAgent.mockResolvedValue({
    agent_id: agentType,
    display_name: displayName,
    connection_id: `${agentType}-local`,
    model_id: null,
    capabilities: ['code_generation', 'test_execution'],
    enabled: true,
    metadata: {},
    created_at: '',
    updated_at: '',
  });
}

describe('InstalledSignInView', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetchAgentConnections.mockResolvedValue([]);
  });

  it('1/2. renders any arbitrary runtime the backend reports, deriving its status only from backend data', async () => {
    mockFetchDetectedRuntimes.mockResolvedValue([installedRuntime, missingRuntime]);
    render(<InstalledSignInView onBack={vi.fn()} onAgentsChanged={vi.fn()} existingAgents={[]} />);

    // No Claude/Codex-specific component -- both render through the same
    // generic row for whatever the backend reports, driven only by data.
    expect(await screen.findByText('Claude Code')).toBeInTheDocument();
    // Undetected runtimes are collapsed (native <details>, closed by
    // default) rather than shown by default.
    expect(screen.getByText('OpenAI Codex').closest('details')).not.toHaveAttribute('open');
    await userEvent.setup().click(screen.getByText(/other supported connectors/i));
    expect(screen.getByText('OpenAI Codex').closest('details')).toHaveAttribute('open');
  });

  it('4. undetected runtimes do not dominate the screen -- collapsed behind a summary, not a wall of "Not detected"', async () => {
    mockFetchDetectedRuntimes.mockResolvedValue([installedRuntime, missingRuntime]);
    render(<InstalledSignInView onBack={vi.fn()} onAgentsChanged={vi.fn()} existingAgents={[]} />);

    await screen.findByText('Claude Code');
    expect(screen.getByText(/other supported connectors \(1\)/i)).toBeInTheDocument();
    expect(screen.getByText('Not detected').closest('details')).not.toHaveAttribute('open');
  });

  it('5. an installed+authenticated runtime shows a real Connect action', async () => {
    mockFetchDetectedRuntimes.mockResolvedValue([installedRuntime]);
    render(<InstalledSignInView onBack={vi.fn()} onAgentsChanged={vi.fn()} existingAgents={[]} />);

    expect(await screen.findByText('Installed', { exact: true })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /connect/i })).toBeInTheDocument();
  });

  it('5b. an undetected runtime cannot fake a Connect action -- no button renders for it', async () => {
    mockFetchDetectedRuntimes.mockResolvedValue([missingRuntime]);
    render(<InstalledSignInView onBack={vi.fn()} onAgentsChanged={vi.fn()} existingAgents={[]} />);

    await userEvent.setup().click(await screen.findByText(/other supported connectors/i));
    expect(await screen.findByText('Not detected')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /connect/i })).not.toBeInTheDocument();
  });

  it('5c. Demo Agent is hidden from the normal Connect UI', async () => {
    mockFetchDetectedRuntimes.mockResolvedValue([installedRuntime, demoRuntime]);
    render(<InstalledSignInView onBack={vi.fn()} onAgentsChanged={vi.fn()} existingAgents={[]} />);

    await screen.findByText('Claude Code');
    expect(screen.queryByText('Demo Agent')).not.toBeInTheDocument();
  });

  it('1/2/6/7/9. connecting an installed runtime is one click: no naming screen, no user-supplied agent id', async () => {
    const user = userEvent.setup();
    mockFetchDetectedRuntimes.mockResolvedValue([installedRuntime]);
    mockSuccessfulConnect('claude_code', 'Claude Code');
    const onAgentsChanged = vi.fn();

    render(<InstalledSignInView onBack={vi.fn()} onAgentsChanged={onAgentsChanged} existingAgents={[]} />);

    await user.click(await screen.findByRole('button', { name: /connect/i }));
    expect(mockActivateRuntime).toHaveBeenCalledWith('claude_code');

    // No naming screen anywhere in this flow.
    expect(screen.queryByText(/name this agent/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/agent id/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/agent name/i)).not.toBeInTheDocument();

    await waitFor(() => expect(mockCreateConnectedAgent).toHaveBeenCalled());
    const call = mockCreateConnectedAgent.mock.calls[0][0];
    expect(call.connection_id).toBe('claude_code-local');
    // Capabilities come only from the runtime's own reported data.
    expect(call.capabilities).toEqual(['code_generation', 'test_execution']);
    // Deterministic, not user-typed and not a random uuid.
    expect(call.agent_id).toBe('claude-code');
    expect(onAgentsChanged).toHaveBeenCalled();

    expect(await screen.findByText(/connected/i)).toBeInTheDocument();
  });

  it('8. reuses an existing connection for the same runtime instead of creating a duplicate', async () => {
    const user = userEvent.setup();
    mockFetchDetectedRuntimes.mockResolvedValue([installedRuntime]);
    mockFetchAgentConnections.mockResolvedValue([
      {
        connection_id: 'claude_code-local',
        display_name: 'Claude Code (local)',
        connection_kind: 'installed_runtime',
        provider_or_runtime: 'claude_code',
        status: 'connected',
        metadata: {},
        created_at: '',
        updated_at: '',
      },
    ]);
    mockSuccessfulConnect('claude_code', 'Claude Code');

    render(<InstalledSignInView onBack={vi.fn()} onAgentsChanged={vi.fn()} existingAgents={[]} />);

    await user.click(await screen.findByRole('button', { name: /connect/i }));
    await waitFor(() => expect(mockCreateConnectedAgent).toHaveBeenCalled());

    // The already-existing connection is reused -- no second
    // createAgentConnection call for the same runtime.
    expect(mockCreateAgentConnection).not.toHaveBeenCalled();
  });

  it('8b. a taken deterministic id gets a safe suffix -- reconnect never collides or produces a random uuid', async () => {
    const user = userEvent.setup();
    mockFetchDetectedRuntimes.mockResolvedValue([installedRuntime]);
    mockSuccessfulConnect('claude_code', 'Claude Code');

    render(
      <InstalledSignInView
        onBack={vi.fn()}
        onAgentsChanged={vi.fn()}
        existingAgents={[
          {
            agent_id: 'claude-code',
            display_name: 'Claude Code',
            connection_id: 'claude_code-local',
            enabled: true,
            capabilities: [],
          },
        ]}
      />
    );

    await user.click(await screen.findByRole('button', { name: /connect/i }));

    await waitFor(() => expect(mockCreateConnectedAgent).toHaveBeenCalled());
    expect(mockCreateConnectedAgent.mock.calls[0][0].agent_id).toBe('claude-code-2');
  });
});
