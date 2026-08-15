import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConnectAgentView } from './ConnectAgentView';

describe('ConnectAgentView', () => {
  it('6. renders all four connection categories, with no provider logos/brand names on the first screen', () => {
    render(<ConnectAgentView onClose={vi.fn()} connectedAgents={[]} onAgentsChanged={vi.fn()} />);

    expect(screen.getByRole('button', { name: /installed \/ sign in/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /api \/ byok/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^local$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^custom$/i })).toBeInTheDocument();

    expect(screen.queryByText(/claude/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/openai/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/anthropic/i)).not.toBeInTheDocument();
  });

  it('opening API/BYOK never pre-claims a successful connection, and its credential field is password-masked', async () => {
    const user = userEvent.setup();
    render(<ConnectAgentView onClose={vi.fn()} connectedAgents={[]} onAgentsChanged={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: /api \/ byok/i }));

    // No connected/success state before the form is ever submitted.
    expect(screen.queryByText(/execution adapter not yet available/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/was created/i)).not.toBeInTheDocument();

    const credentialInput = screen.getByLabelText(/api key/i);
    expect(credentialInput).toHaveAttribute('type', 'password');
  });

  it('does not render an agent-management list when there are no connected agents', () => {
    render(<ConnectAgentView onClose={vi.fn()} connectedAgents={[]} onAgentsChanged={vi.fn()} />);
    expect(screen.queryByText(/connected agents/i)).not.toBeInTheDocument();
  });

  it('renders connected agents with enable/disable and remove actions when present', () => {
    render(
      <ConnectAgentView
        onClose={vi.fn()}
        connectedAgents={[
          {
            agent_id: 'claude-work',
            display_name: 'Claude Work',
            connection_id: 'claude-code-local',
            enabled: true,
            capabilities: ['code_generation'],
          },
        ]}
        onAgentsChanged={vi.fn()}
      />
    );

    expect(screen.getByText('Claude Work')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /disable claude work/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /remove claude work/i })).toBeInTheDocument();
  });
});
