import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { KeystoneHome } from './KeystoneHome';
import { BackendUnavailableError } from '../../api/keystoneClient';

vi.mock('../../api/keystoneClient', async () => {
  const actual = await vi.importActual<typeof import('../../api/keystoneClient')>(
    '../../api/keystoneClient'
  );
  return {
    ...actual,
    fetchConnectedAgents: vi.fn(),
    startOrchestration: vi.fn(),
    fetchOrchestrationResult: vi.fn(),
    subscribeToOrchestrationEvents: vi.fn(() => () => undefined),
  };
});

import {
  fetchConnectedAgents,
  startOrchestration,
} from '../../api/keystoneClient';

const mockFetchConnectedAgents = vi.mocked(fetchConnectedAgents);
const mockStartOrchestration = vi.mocked(startOrchestration);

describe('KeystoneHome', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('1. shows the Connect Agent welcome state when no agents are connected', async () => {
    mockFetchConnectedAgents.mockResolvedValue([]);
    render(<KeystoneHome />);

    expect(await screen.findByText('Ready to build?')).toBeInTheDocument();
    expect(screen.getByText('Connect your agents to get started.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /connect agent/i })).toBeInTheDocument();
  });

  it('2. shows the prompt-first state once agents are connected', async () => {
    mockFetchConnectedAgents.mockResolvedValue([
      { agent_id: 'qwen-coder', display_name: 'Qwen Coder', connection_id: 'c1', enabled: true, capabilities: [] },
    ]);
    render(<KeystoneHome />);

    expect(await screen.findByText('What do you want to build?')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/ask keystone/i)).toBeInTheDocument();
  });

  it('3. renders arbitrary dynamic agent IDs (never a fixed vendor list)', async () => {
    mockFetchConnectedAgents.mockResolvedValue([
      { agent_id: 'qwen-coder', display_name: 'Qwen Coder', connection_id: 'c1', enabled: true, capabilities: [] },
      { agent_id: 'deepseek-reviewer', display_name: 'DeepSeek Reviewer', connection_id: 'c1', enabled: true, capabilities: [] },
      { agent_id: 'corp-security-reviewer', display_name: 'Corp Reviewer', connection_id: 'c2', enabled: true, capabilities: [] },
    ]);
    render(<KeystoneHome />);

    expect(await screen.findByText('3 agents')).toBeInTheDocument();
  });

  it('4. never renders a fixed Claude/Codex/Gemini agent-selection dropdown by default', async () => {
    mockFetchConnectedAgents.mockResolvedValue([
      { agent_id: 'qwen-coder', display_name: 'Qwen Coder', connection_id: 'c1', enabled: true, capabilities: [] },
    ]);
    render(<KeystoneHome />);
    await screen.findByText('What do you want to build?');

    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.queryByText(/claude/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/codex/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/gemini/i)).not.toBeInTheDocument();
  });

  it('5. clicking Connect Agent opens the connection view', async () => {
    mockFetchConnectedAgents.mockResolvedValue([]);
    const user = userEvent.setup();
    render(<KeystoneHome />);

    await user.click(await screen.findByRole('button', { name: /connect agent/i }));

    expect(screen.getByText('Connect Agent')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /installed \/ sign in/i })).toBeInTheDocument();
  });

  it('9. shows Keystone backend unavailable and never simulates execution when the backend is unreachable', async () => {
    mockFetchConnectedAgents.mockRejectedValue(new BackendUnavailableError(new Error('refused')));
    render(<KeystoneHome />);

    expect(await screen.findByText('Keystone backend unavailable.')).toBeInTheDocument();
    // The prompt composer must not be rendered in this state -- there is
    // nothing to submit a goal to.
    expect(screen.queryByPlaceholderText(/ask keystone/i)).not.toBeInTheDocument();
    expect(mockStartOrchestration).not.toHaveBeenCalled();
  });

  it('submits a goal using every currently connected agent ID, never a hardcoded one', async () => {
    mockFetchConnectedAgents.mockResolvedValue([
      { agent_id: 'qwen-coder', display_name: 'Qwen Coder', connection_id: 'c1', enabled: true, capabilities: [] },
      { agent_id: 'deepseek-reviewer', display_name: 'DeepSeek Reviewer', connection_id: 'c1', enabled: true, capabilities: [] },
    ]);
    mockStartOrchestration.mockResolvedValue({
      execution_id: 'exec-1',
      status: 'accepted',
      events_url: '/events',
      result_url: '/result',
    });
    const user = userEvent.setup();
    render(<KeystoneHome />);

    const input = await screen.findByPlaceholderText(/ask keystone/i);
    await user.type(input, 'Build authentication for this project');
    await user.click(screen.getByRole('button', { name: /send/i }));

    await waitFor(() => {
      expect(mockStartOrchestration).toHaveBeenCalledWith(
        'Build authentication for this project',
        ['qwen-coder', 'deepseek-reviewer']
      );
    });
  });
});
