import { afterEach, describe, expect, it, vi } from 'vitest';
import { listWorkflows } from '@/services/workflows';

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('listWorkflows', () => {
  it('uses the real {items, count} envelope, never a total/page/limit pagination shape', async () => {
    const body = {
      items: [{ id: 'wf-1', name: 'demo', status: 'pending' }],
      count: 1,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(body));
    vi.stubGlobal('fetch', fetchMock);

    const result = await listWorkflows();

    expect(result).toEqual(body);
    expect(result).not.toHaveProperty('total');
    expect(result).not.toHaveProperty('page');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/workflows'),
      expect.any(Object)
    );
  });
});
