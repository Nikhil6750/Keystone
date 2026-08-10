import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PromptComposer } from './PromptComposer';

describe('PromptComposer', () => {
  it('7. sends the trimmed goal on Enter and clears the input', async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<PromptComposer onSubmit={onSubmit} />);

    const input = screen.getByLabelText('Ask Keystone');
    await user.type(input, '  Build a REST API  ');
    await user.keyboard('{Enter}');

    expect(onSubmit).toHaveBeenCalledWith('Build a REST API');
    expect(input).toHaveValue('');
  });

  it('7. sends the goal via the send button', async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<PromptComposer onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText('Ask Keystone'), 'Refactor the payments module');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    expect(onSubmit).toHaveBeenCalledWith('Refactor the payments module');
  });

  it('7. never submits a blank goal', async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<PromptComposer onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText('Ask Keystone'), '   ');
    await user.keyboard('{Enter}');

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('8. Shift+Enter inserts a newline instead of submitting', async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<PromptComposer onSubmit={onSubmit} />);

    const input = screen.getByLabelText('Ask Keystone');
    await user.type(input, 'line one');
    await user.keyboard('{Shift>}{Enter}{/Shift}');
    await user.type(input, 'line two');

    expect(onSubmit).not.toHaveBeenCalled();
    expect(input).toHaveValue('line one\nline two');
  });

  it('disables the composer when `disabled` is set', () => {
    render(<PromptComposer disabled onSubmit={vi.fn()} />);
    expect(screen.getByLabelText('Ask Keystone')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
  });
});
