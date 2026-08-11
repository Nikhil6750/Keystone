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
    expect(screen.getByText('OpenAI Codex')).toBeInTheDocument();
    expect(screen.getByText('Not detected')).toBeInTheDocument();
  });

  it('5. an installed+authenticated runtime shows a real Connect action', async () => {
    mockFetchDetectedRuntimes.mockResolvedValue([installedRuntime]);
    render(<InstalledSignInView onBack={vi.fn()} onAgentsChanged={vi.fn()} existingAgents={[]} />);

    expect(await screen.findByText('Installed')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /connect/i })).toBeInTheDocument();
  });

  it('5b. an undetected runtime cannot fake a Connect action -- no button renders for it', async () => {
    mockFetchDetectedRuntimes.mockResolvedValue([missingRuntime]);
    render(<InstalledSignInView onBack={vi.fn()} onAgentsChanged={vi.fn()} existingAgents={[]} />);

    expect(await screen.findByText('Not detected')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /connect/i })).not.toBeInTheDocument();
  });

  it('6/7/9. connecting an installed runtime activates it, creates a connection, then creates the named agent', async () => {
    const user = userEvent.setup();
    mockFetchDetectedRuntimes.mockResolvedValue([installedRuntime]);
    mockActivateRuntime.mockResolvedValue({
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
      reason: 'Verified via a harmless headless prompt',
      capabilities: ['code_generation', 'test_execution'],
    });
    mockCreateAgentConnection.mockResolvedValue({
      connection_id: 'claude_code-local',
      display_name: 'Claude Code (local)',
      connection_kind: 'installed_runtime',
      provider_or_runtime: 'claude_code',
      status: 'connected',
      metadata: {},
      created_at: '',
      updated_at: '',
    });
    mockCreateConnectedAgent.mockResolvedValue({
      agent_id: 'claude-code-work',
      display_name: 'Claude Code agent',
      connection_id: 'claude_code-local',
      model_id: null,
      capabilities: ['code_generation', 'test_execution'],
      enabled: true,
      metadata: {},
      created_at: '',
      updated_at: '',
    });
    const onAgentsChanged = vi.fn();

    render(<InstalledSignInView onBack={vi.fn()} onAgentsChanged={onAgentsChanged} existingAgents={[]} />);

    await user.click(await screen.findByRole('button', { name: /connect/i }));
    expect(mockActivateRuntime).toHaveBeenCalledWith('claude_code');

    // Naming step: an agent_id is pre-filled, capabilities shown are
    // exactly what the runtime reported -- never invented.
    expect(await screen.findByText('Name this agent')).toBeInTheDocument();
    expect(screen.getByText('code generation')).toBeInTheDocument();
    expect(screen.getByText('test execution')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /create agent/i }));

    await waitFor(() => expect(mockCreateConnectedAgent).toHaveBeenCalled());
    const call = mockCreateConnectedAgent.mock.calls[0][0];
    expect(call.connection_id).toBe('claude_code-local');
    expect(call.capabilities).toEqual(['code_generation', 'test_execution']);
    expect(onAgentsChanged).toHaveBeenCalled();
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
    mockActivateRuntime.mockResolvedValue({
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
      reason: 'connected',
      capabilities: ['code_generation'],
    });

    render(<InstalledSignInView onBack={vi.fn()} onAgentsChanged={vi.fn()} existingAgents={[]} />);

    await user.click(await screen.findByRole('button', { name: /connect/i }));
    await screen.findByText('Name this agent');

    // The already-existing connection is reused -- no second
    // createAgentConnection call for the same runtime.
    expect(mockCreateAgentConnection).not.toHaveBeenCalled();
  });
});
