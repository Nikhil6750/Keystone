import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CircuitBreakerList } from '@/components/resilience/circuit-breaker-list';
import type { CircuitBreakerRead } from '@/types/backend';

let breakers: CircuitBreakerRead[] = [];

vi.mock('@/hooks/use-circuit-breakers', () => ({
  useCircuitBreakers: () => ({
    data: { items: breakers, count: breakers.length },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

describe('CircuitBreakerList', () => {
  it('renders a closed breaker state', () => {
    breakers = [
      {
        agent_type: 'demo',
        state: 'closed',
        failure_count: 0,
        failure_threshold: 3,
        recovery_timeout_seconds: 30,
        retry_after_seconds: 0,
        half_open_probe_in_flight: false,
      },
    ];

    render(<CircuitBreakerList />);

    expect(screen.getByText('Closed')).toBeInTheDocument();
  });

  it('renders an open breaker state with failure count and threshold', () => {
    breakers = [
      {
        agent_type: 'claude_code',
        state: 'open',
        failure_count: 3,
        failure_threshold: 3,
        recovery_timeout_seconds: 30,
        retry_after_seconds: 12.5,
        half_open_probe_in_flight: false,
      },
    ];

    render(<CircuitBreakerList />);

    expect(screen.getByText('Open')).toBeInTheDocument();
    expect(screen.getByText(/Failures:/)).toHaveTextContent('Failures: 3/3');
  });
});
