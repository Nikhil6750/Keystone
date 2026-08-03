import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiRequest, ApiClientError } from '@/services/api-client';

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

describe('apiRequest', () => {
  it('parses a successful unwrapped response (no data/success/message wrapper)', async () => {
    const payload = { id: 'wf-1', name: 'demo', status: 'pending' };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(payload)));

    const result = await apiRequest<typeof payload>('/api/v1/workflows/wf-1');

    expect(result).toEqual(payload);
  });

  it('parses the backend {"error": {code, message, details}} envelope on failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          { error: { code: 'WORKFLOW_NOT_FOUND', message: "workflow 'x' not found", details: null } },
          { status: 404 }
        )
      )
    );

    await expect(apiRequest('/api/v1/workflows/x')).rejects.toMatchObject({
      code: 'WORKFLOW_NOT_FOUND',
      message: "workflow 'x' not found",
      status: 404,
    });
  });

  it('maps a network failure (fetch throws) to a NETWORK_ERROR ApiClientError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    await expect(apiRequest('/api/v1/health')).rejects.toBeInstanceOf(ApiClientError);
    await expect(apiRequest('/api/v1/health')).rejects.toMatchObject({ code: 'NETWORK_ERROR' });
  });
});
