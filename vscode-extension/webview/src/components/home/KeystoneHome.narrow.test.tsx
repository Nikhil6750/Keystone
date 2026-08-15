import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { KeystoneHome } from './KeystoneHome';

vi.mock('../../api/keystoneClient', async () => {
  const actual = await vi.importActual<typeof import('../../api/keystoneClient')>(
    '../../api/keystoneClient'
  );
  return {
    ...actual,
    fetchConnectedAgents: vi.fn().mockResolvedValue([]),
  };
});

/**
 * 13. Narrow layout: jsdom does not perform real CSS layout, so this
 * cannot assert pixel-level overflow -- it is a structural proxy only
 * (renders cleanly with no hardcoded oversized inline widths, at a
 * simulated narrow viewport). Real responsive behavior is additionally
 * confirmed by the manual visual check documented in the final report.
 */
describe('KeystoneHome narrow layout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the header and prompt composer at a narrow (sidebar-width) viewport with no hardcoded oversized widths', async () => {
    Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 260 });

    render(<KeystoneHome />);

    const composerInput = await screen.findByPlaceholderText(/ask keystone/i);
    expect(composerInput).toBeInTheDocument();
    expect(screen.getAllByText('Keystone').length).toBeGreaterThan(0);

    for (const el of document.querySelectorAll<HTMLElement>('[style]')) {
      const widthStyle = el.style.width;
      if (widthStyle && widthStyle.endsWith('px')) {
        expect(Number.parseFloat(widthStyle)).toBeLessThan(260);
      }
    }
  });
});
