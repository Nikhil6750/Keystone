import { describe, expect, it, vi } from 'vitest';

vi.mock('@/hooks/use-workflows', () => ({
  useWorkflows: () => ({ data: { items: [], count: 0 }, loading: false, error: null, refresh: vi.fn() }),
}));
vi.mock('@/hooks/use-provenance', () => ({
  useProvenance: () => ({ data: null, loading: false, error: null, refresh: vi.fn() }),
}));
vi.mock('@/hooks/use-audit-chain-verification', () => ({
  useAuditChainVerification: () => ({ data: null, loading: false, error: null, refresh: vi.fn() }),
}));

describe('/logs route', () => {
  it(
    'exists as a real page module (no longer a dead sidebar link)',
    async () => {
      const logsPageModule = await import('@/app/logs/page');
      expect(logsPageModule.default).toBeTypeOf('function');
    },
    // First dynamic import of a page module transforms the whole module
    // graph on demand. 15s was observed to intermittently time out when the
    // machine is under heavy concurrent load (e.g. a backend pytest run
    // executing at the same time) -- not a regression in the module itself
    // (this same import reliably completes in 3-4s standalone/under normal
    // load). 45s gives real headroom for cold-start transform time under
    // contention without masking a genuine hang.
    45_000
  );
});

describe('/workspace route', () => {
  it('redirects to /chat instead of duplicating the workflow-creation UI', async () => {
    vi.doMock('next/navigation', () => ({
      redirect: vi.fn((path: string) => {
        throw new Error(`NEXT_REDIRECT:${path}`);
      }),
    }));

    const workspacePageModule = await import('@/app/workspace/page');

    expect(() => workspacePageModule.default()).toThrow('NEXT_REDIRECT:/chat');
  });
});
