import { describe, it, expect, vi, afterEach } from 'vitest';
import { vscodeApi } from '../services/vscodeApi';
import {
  BackendUnavailableError,
  fetchConnectedAgents,
  startOrchestration,
  subscribeToOrchestrationEvents,
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
});
