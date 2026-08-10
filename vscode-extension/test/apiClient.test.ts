import assert from 'assert';
import { OrchestrationApiClient } from '../src/api/orchestrationApiClient';
import type { OrchestrationExecutionCreate } from '../../shared-contracts/src';

describe('OrchestrationApiClient Unit Tests', () => {
  it('initializes with default base URL', () => {
    const client = new OrchestrationApiClient();
    assert.strictEqual(client.getBaseUrl(), 'http://127.0.0.1:8000');
  });

  it('normalizes custom base URL without trailing slash', () => {
    const client = new OrchestrationApiClient({ baseUrl: 'http://localhost:8000///' });
    assert.strictEqual(client.getBaseUrl(), 'http://localhost:8000');
  });

  it('parses SSE event frames correctly', () => {
    const client = new OrchestrationApiClient();
    const frame = `id: 1\nevent: execution.accepted\ndata: {"event_id":"e1","execution_id":"exec-101","sequence":1,"event_type":"execution.accepted","timestamp":"2026-08-10T14:00:00Z","safe_issue_codes":[]}`;

    const parsed = client.parseSseFrame(frame);
    assert.notStrictEqual(parsed, null);
    assert.strictEqual(parsed?.execution_id, 'exec-101');
    assert.strictEqual(parsed?.sequence, 1);
    assert.strictEqual(parsed?.event_type, 'execution.accepted');
  });

  it('returns null for invalid SSE frames without data', () => {
    const client = new OrchestrationApiClient();
    const frame = `: heartbeat comment line`;
    const parsed = client.parseSseFrame(frame);
    assert.strictEqual(parsed, null);
  });

  it('submits createOrchestration request via custom fetch', async () => {
    const mockAccepted = {
      execution_id: 'exec-test-123',
      status: 'accepted' as const,
      events_url: '/api/v1/orchestrations/exec-test-123/events',
      result_url: '/api/v1/orchestrations/exec-test-123',
    };

    const mockFetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const urlStr = typeof input === 'string' ? input : input.toString();
      assert.strictEqual(urlStr, 'http://127.0.0.1:8000/api/v1/orchestrations');
      assert.strictEqual(init?.method, 'POST');
      const bodyStr = init?.body as string;
      const parsedBody = JSON.parse(bodyStr);
      assert.strictEqual(parsedBody.goal, 'Implement dynamic agent connections');

      return new Response(JSON.stringify(mockAccepted), {
        status: 202,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    const client = new OrchestrationApiClient({ fetchFn: mockFetch });
    const req: OrchestrationExecutionCreate = {
      goal: 'Implement dynamic agent connections',
      available_agent_types: ['openrouter-qwen-coder', 'company-security-agent'],
    };

    const result = await client.createOrchestration(req);
    assert.strictEqual(result.execution_id, 'exec-test-123');
    assert.strictEqual(result.status, 'accepted');
  });

  it('handles 404 response on status lookup cleanly', async () => {
    const mockFetch = async (): Promise<Response> => {
      return new Response(JSON.stringify({ error: 'not found' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    const client = new OrchestrationApiClient({ fetchFn: mockFetch });
    await assert.rejects(
      async () => {
        await client.getOrchestrationStatus('missing-id');
      },
      (err: Error) => {
        return err.message.includes('404');
      }
    );
  });
});
