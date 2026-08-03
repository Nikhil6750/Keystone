import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import SettingsPage from '@/app/settings/page';

vi.mock('@/hooks/use-backend-health', () => ({
  useBackendHealth: () => ({
    data: { status: 'healthy', service: 'keystone-backend', version: '0.1.0' },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

vi.mock('@/hooks/use-agents', () => ({
  useAgents: () => ({
    data: { items: [{ agent_type: 'demo', enabled: true, available: true, registered: true, execution_mode: 'demo', reason: 'ok' }], count: 1 },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

vi.mock('@/hooks/use-workflows', () => ({
  useWorkflows: () => ({ data: { items: [], count: 0 }, loading: false, error: null, refresh: vi.fn() }),
}));

describe('SettingsPage', () => {
  it('never displays the old fake email or workspace identifiers', () => {
    render(<SettingsPage />);

    expect(screen.queryByText(/ks@example\.com/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/ks_7f3a2c1e8b9d/i)).not.toBeInTheDocument();
  });

  it('never presents a provider credential form (no password/API key inputs)', () => {
    render(<SettingsPage />);

    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/api key/i)).not.toBeInTheDocument();
    expect(document.querySelector('input[type="password"]')).not.toBeInTheDocument();
  });
});
