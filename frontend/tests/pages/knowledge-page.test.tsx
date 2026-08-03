import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import KnowledgePage from '@/app/knowledge/page';

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

describe('KnowledgePage', () => {
  it('marks the Knowledge feature as future functionality, not implemented today', () => {
    render(<KnowledgePage />);

    expect(screen.getByText(/Coming in Phase 7/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Evidence-grounded workflow memory and adaptive routing are planned for Phase 7/i)
    ).toBeInTheDocument();
  });

  it('never claims to connect to Supabase, and only mentions a vector database to deny using one', () => {
    render(<KnowledgePage />);

    expect(screen.queryByText(/supabase/i)).not.toBeInTheDocument();
    const disclaimer = screen.getByText(/vector database/i);
    expect(disclaimer).toHaveTextContent(/does not implement/i);
  });
});
