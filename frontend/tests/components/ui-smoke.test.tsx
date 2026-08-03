import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Button, Card, EmptyState, StatusBadge, Toast } from '@/components/ui';
import { ToneBadge } from '@/components/workflow/tone-badge';

describe('existing UI components continue rendering', () => {
  it('renders Button', () => {
    render(<Button>Click me</Button>);
    expect(screen.getByRole('button', { name: 'Click me' })).toBeInTheDocument();
  });

  it('renders Card', () => {
    render(<Card>Card content</Card>);
    expect(screen.getByText('Card content')).toBeInTheDocument();
  });

  it('renders EmptyState', () => {
    render(<EmptyState title="Nothing here" />);
    expect(screen.getByText('Nothing here')).toBeInTheDocument();
  });

  it('renders StatusBadge', () => {
    render(<StatusBadge>Waiting</StatusBadge>);
    expect(screen.getByText('Waiting')).toBeInTheDocument();
  });

  it('renders Toast', () => {
    render(<Toast message="Saved" variant="success" />);
    expect(screen.getByText('Saved')).toBeInTheDocument();
  });

  it('renders the new ToneBadge component alongside the existing design system', () => {
    render(<ToneBadge tone="success">Ready</ToneBadge>);
    expect(screen.getByText('Ready')).toBeInTheDocument();
  });
});
