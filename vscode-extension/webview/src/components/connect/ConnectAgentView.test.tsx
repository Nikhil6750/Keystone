import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConnectAgentView } from './ConnectAgentView';

describe('ConnectAgentView', () => {
  it('6. renders all four connection categories, with no provider logos/brand names on the first screen', () => {
    render(<ConnectAgentView onClose={vi.fn()} />);

    expect(screen.getByRole('button', { name: /installed \/ sign in/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /api \/ byok/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^local$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^custom$/i })).toBeInTheDocument();

    expect(screen.queryByText(/claude/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/openai/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/anthropic/i)).not.toBeInTheDocument();
  });

  it('opens a category detail view without claiming a successful connection', async () => {
    const user = userEvent.setup();
    render(<ConnectAgentView onClose={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: /api \/ byok/i }));

    expect(screen.getByText('Not yet available')).toBeInTheDocument();
    expect(screen.queryByText(/connected/i)).not.toBeInTheDocument();
    // No functional credential input anywhere in this view.
    expect(screen.queryByLabelText(/api key/i)).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/api key/i)).not.toBeInTheDocument();
  });
});
