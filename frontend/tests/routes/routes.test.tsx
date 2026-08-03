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
    15_000 // first dynamic import of a page module can be slow to transform under load
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
