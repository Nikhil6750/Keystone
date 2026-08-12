import { describe, it, expect, vi, afterEach } from 'vitest';
import { vscodeApi } from '../services/vscodeApi';
import {
  BackendUnavailableError,
  activateRuntime,
  createAgentConnection,
  createConnectedAgent,
  fetchConnectedAgents,
  fetchDetectedRuntimes,
  startOrchestration,
  subscribeToOrchestrationEvents,
  updateConnectedAgent,
} from './keystoneClient';

/**
 * Transport-level tests for the extension-host proxy client. These prove
 * the client's own classification logic directly (not just through a
 * component that mocks the module away): a real backend answer -- of any
 * shape, including an empty list -- must never surface as
 * `BackendUnavailableError`, and only a genuine transport failure may.
 *
 * See `src/api/backendProxy.ts` (extension host) for why this proxies
 * through `postMessage` instead of calling `fetch`/`EventSource` directly:
 * a VS Code webview's `vscode-webview://<random-uuid>` origin can never
 * satisfy a static backend CORS allowlist, so a direct cross-origin
 * request from here would always be rejected by the browser even when the
 * backend answers 200.
 */

function dispatchHostMessage(data: unknown): void {
  window.dispatchEvent(new MessageEvent('message', { data }));
}

function lastPostedMessage(): Record<string, unknown> {
  const spy = vi.mocked(vscodeApi.postMessage);
  const call = spy.mock.calls[spy.mock.calls.length - 1];
  return call?.[0] as Record<string, unknown>;
}

describe('keystoneClient (extension-host proxy transport)', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('1. HTTP 200 + [] resolves to an empty array, never throws BackendUnavailableError', async () => {
    vi.spyOn(vscodeApi, 'postMessage');
    const promise = fetchConnectedAgents();
    const sent = lastPostedMessage();
    expect(sent.type).toBe('KEYSTONE_API_REQUEST');
    expect(sent.method).toBe('GET');
    expect(sent.path).toBe('/connected-agents');

    dispatchHostMessage({
      type: 'KEYSTONE_API_RESPONSE',
      requestId: sent.requestId,
      networkError: false,
      ok: true,
      status: 200,
      body: [],
    });

    await expect(promise).resolves.toEqual([]);
  });

  it('2. tolerates an unexpected (wrapped) 200 body as an empty list rather than throwing -- real contract is a plain array', async () => {
    vi.spyOn(vscodeApi, 'postMessage');
    const promise = fetchConnectedAgents();
    const sent = lastPostedMessage();

    dispatchHostMessage({
      type: 'KEYSTONE_API_RESPONSE',
      requestId: sent.requestId,
      networkError: false,
      ok: true,
      status: 200,
      body: { agents: [] },
    });

    await expect(promise).resolves.toEqual([]);
  });

  it('3/8. HTTP 200 + one arbitrary agent resolves with that agent (no hardcoded shape assumption)', async () => {
    vi.spyOn(vscodeApi, 'postMessage');
    const promise = fetchConnectedAgents();
    const sent = lastPostedMessage();
    const agent = {
      agent_id: 'corp-security-reviewer',
      display_name: 'Corp Reviewer',
      connection_id: 'c9',
      enabled: true,
      capabilities: [],
    };

    dispatchHostMessage({
      type: 'KEYSTONE_API_RESPONSE',
      requestId: sent.requestId,
      networkError: false,
      ok: true,
      status: 200,
      body: [agent],
    });

    await expect(promise).resolves.toEqual([agent]);
  });

  it('4. a genuine transport failure (relayed networkError) rejects with BackendUnavailableError', async () => {
    vi.spyOn(vscodeApi, 'postMessage');
    const promise = fetchConnectedAgents();
    const sent = lastPostedMessage();

    dispatchHostMessage({
      type: 'KEYSTONE_API_RESPONSE',
      requestId: sent.requestId,
      networkError: true,
      ok: false,
      status: 0,
      body: null,
    });

    await expect(promise).rejects.toBeInstanceOf(BackendUnavailableError);
  });

  it('4b. a request that never receives a response times out as BackendUnavailableError, not a hang', async () => {
    vi.useFakeTimers();
    vi.spyOn(vscodeApi, 'postMessage');
    const promise = fetchConnectedAgents();
    const assertion = expect(promise).rejects.toBeInstanceOf(BackendUnavailableError);
    await vi.advanceTimersByTimeAsync(20000);
    await assertion;
  });

  it('a real (non-network) HTTP error response is not mistaken for backend unavailability', async () => {
    vi.spyOn(vscodeApi, 'postMessage');
    const promise = startOrchestration('do a thing', ['agent-a']);
    const sent = lastPostedMessage();
    expect(sent.method).toBe('POST');
    expect(sent.path).toBe('/orchestrations');
    expect(sent.body).toEqual({ goal: 'do a thing', available_agent_types: ['agent-a'] });

    dispatchHostMessage({
      type: 'KEYSTONE_API_RESPONSE',
      requestId: sent.requestId,
      networkError: false,
      ok: false,
      status: 422,
      body: { detail: 'invalid' },
    });

    await expect(promise).rejects.toThrow(/HTTP 422/);
    await expect(promise).rejects.not.toBeInstanceOf(BackendUnavailableError);
  });

  it('7. subscribing sends exactly one SSE_SUBSCRIBE message; unsubscribing sends exactly one SSE_UNSUBSCRIBE message', () => {
    const spy = vi.spyOn(vscodeApi, 'postMessage');

    const unsubscribe = subscribeToOrchestrationEvents('exec-42', { onEvent: vi.fn() });
    const subscribeCalls = spy.mock.calls.filter(
      ([m]) => (m as { type?: string }).type === 'KEYSTONE_SSE_SUBSCRIBE'
    );
    expect(subscribeCalls).toHaveLength(1);
    expect((subscribeCalls[0][0] as { path: string }).path).toBe('/orchestrations/exec-42/events');

    unsubscribe();
    const unsubscribeCalls = spy.mock.calls.filter(
      ([m]) => (m as { type?: string }).type === 'KEYSTONE_SSE_UNSUBSCRIBE'
    );
    expect(unsubscribeCalls).toHaveLength(1);
  });

  it('delivers a relayed SSE event to the subscriber, parsed from the safe event JSON', () => {
    const spy = vi.spyOn(vscodeApi, 'postMessage');
    const onEvent = vi.fn();
    subscribeToOrchestrationEvents('exec-7', { onEvent });
    const subscribeMessage = spy.mock.calls.find(
      ([m]) => (m as { type?: string }).type === 'KEYSTONE_SSE_SUBSCRIBE'
    )?.[0] as { subscriptionId: string };

    const event = {
      event_id: 'e1',
      execution_id: 'exec-7',
      sequence: 1,
      event_type: 'execution.started',
      timestamp: new Date().toISOString(),
      phase: null,
      status: null,
      workflow_id: null,
      task_key: null,
      agent_id: null,
      attempt_number: null,
      verification_status: null,
      safe_issue_codes: [],
      message: null,
    };

    dispatchHostMessage({
      type: 'KEYSTONE_SSE_EVENT',
      subscriptionId: subscribeMessage.subscriptionId,
      eventType: 'execution.started',
      data: JSON.stringify(event),
    });

    expect(onEvent).toHaveBeenCalledWith(event);
  });

  describe('Stage 8C.3 Connect Agent transport', () => {
    it('fetchDetectedRuntimes reads GET /agents and unwraps the {items,count} envelope', async () => {
      vi.spyOn(vscodeApi, 'postMessage');
      const promise = fetchDetectedRuntimes();
      const sent = lastPostedMessage();
      expect(sent.method).toBe('GET');
      expect(sent.path).toBe('/agents');

      dispatchHostMessage({
        type: 'KEYSTONE_API_RESPONSE',
        requestId: sent.requestId,
        networkError: false,
        ok: true,
        status: 200,
        body: { items: [{ agent_type: 'claude_code', installation_status: 'installed' }], count: 1 },
      });

      await expect(promise).resolves.toEqual([
        { agent_type: 'claude_code', installation_status: 'installed' },
      ]);
    });

    it('fetchDetectedRuntimes tolerates an unusual response shape as an empty list, never throwing', async () => {
      vi.spyOn(vscodeApi, 'postMessage');
      const promise = fetchDetectedRuntimes();
      const sent = lastPostedMessage();

      dispatchHostMessage({
        type: 'KEYSTONE_API_RESPONSE',
        requestId: sent.requestId,
        networkError: false,
        ok: true,
        status: 200,
        body: null,
      });

      await expect(promise).resolves.toEqual([]);
    });

    it('activateRuntime posts to the exact runtime_id path and rejects on a non-OK response', async () => {
      vi.spyOn(vscodeApi, 'postMessage');
      const promise = activateRuntime('claude_code');
      const sent = lastPostedMessage();
      expect(sent.method).toBe('POST');
      expect(sent.path).toBe('/runtime-connections/claude_code/activate');

      dispatchHostMessage({
        type: 'KEYSTONE_API_RESPONSE',
        requestId: sent.requestId,
        networkError: false,
        ok: false,
        status: 404,
        body: { error: { message: 'unknown runtime' } },
      });

      await expect(promise).rejects.toThrow(/HTTP 404/);
    });

    it('createAgentConnection sends the connection payload and returns the created connection', async () => {
      vi.spyOn(vscodeApi, 'postMessage');
      const promise = createAgentConnection({
        connection_id: 'claude-code-local',
        display_name: 'Claude Code (local)',
        connection_kind: 'installed_runtime',
        provider_or_runtime: 'claude_code',
      });
      const sent = lastPostedMessage();
      expect(sent.method).toBe('POST');
      expect(sent.path).toBe('/agent-connections');
      expect(sent.body).toEqual({
        connection_id: 'claude-code-local',
        display_name: 'Claude Code (local)',
        connection_kind: 'installed_runtime',
        provider_or_runtime: 'claude_code',
      });

      const created = { ...(sent.body as object), status: 'connected' };
      dispatchHostMessage({
        type: 'KEYSTONE_API_RESPONSE',
        requestId: sent.requestId,
        networkError: false,
        ok: true,
        status: 201,
        body: created,
      });

      await expect(promise).resolves.toEqual(created);
    });

    it('createAgentConnection surfaces the backend error message on a real (non-network) failure', async () => {
      vi.spyOn(vscodeApi, 'postMessage');
      const promise = createAgentConnection({
        connection_id: 'dup',
        display_name: 'Dup',
        connection_kind: 'custom',
        provider_or_runtime: 'dup',
      });
      const sent = lastPostedMessage();

      dispatchHostMessage({
        type: 'KEYSTONE_API_RESPONSE',
        requestId: sent.requestId,
        networkError: false,
        ok: false,
        status: 409,
        body: { error: { message: "AgentConnection 'dup' is already registered" } },
      });

      await expect(promise).rejects.toThrow(/already registered/);
    });

    it('createConnectedAgent never invents capabilities -- it sends exactly the caller-supplied list', async () => {
      vi.spyOn(vscodeApi, 'postMessage');
      const promise = createConnectedAgent({
        agent_id: 'claude-work',
        display_name: 'Claude Work',
        connection_id: 'claude-code-local',
        capabilities: ['code_generation', 'test_execution'],
      });
      const sent = lastPostedMessage();
      expect(sent.method).toBe('POST');
      expect(sent.path).toBe('/connected-agents');
      expect((sent.body as { capabilities: string[] }).capabilities).toEqual([
        'code_generation',
        'test_execution',
      ]);

      dispatchHostMessage({
        type: 'KEYSTONE_API_RESPONSE',
        requestId: sent.requestId,
        networkError: false,
        ok: true,
        status: 201,
        body: sent.body,
      });

      await expect(promise).resolves.toEqual(sent.body);
    });

    it('updateConnectedAgent issues a real PATCH request, not a POST workaround', async () => {
      vi.spyOn(vscodeApi, 'postMessage');
      const promise = updateConnectedAgent('claude-work', { enabled: false });
      const sent = lastPostedMessage();
      expect(sent.method).toBe('PATCH');
      expect(sent.path).toBe('/connected-agents/claude-work');
      expect(sent.body).toEqual({ enabled: false });

      dispatchHostMessage({
        type: 'KEYSTONE_API_RESPONSE',
        requestId: sent.requestId,
        networkError: false,
        ok: true,
        status: 200,
        body: { agent_id: 'claude-work', enabled: false },
      });

      await expect(promise).resolves.toEqual({ agent_id: 'claude-work', enabled: false });
    });
  });
});
