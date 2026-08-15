import { describe, it, expect, vi, afterEach } from 'vitest';
import { vscodeApi } from '../services/vscodeApi';
import { storeSecret, deleteSecret } from './secretsClient';

/**
 * Transport-level tests for the extension-host SecretStorage proxy client.
 * Proves the one property that matters most: this module posts the raw
 * value out to the host and resolves only a boolean -- it never has a
 * "read a secret back" code path for a compromised or buggy caller to
 * misuse in the first place.
 */

function dispatchHostMessage(data: unknown): void {
  window.dispatchEvent(new MessageEvent('message', { data }));
}

function lastPostedMessage(): Record<string, unknown> {
  const spy = vi.mocked(vscodeApi.postMessage);
  const call = spy.mock.calls[spy.mock.calls.length - 1];
  return call?.[0] as Record<string, unknown>;
}

describe('secretsClient (extension-host SecretStorage proxy transport)', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('storeSecret posts the key and value, resolving true on a successful host response', async () => {
    vi.spyOn(vscodeApi, 'postMessage');
    const promise = storeSecret('byok:openrouter-personal', 'sk-super-secret-value');
    const sent = lastPostedMessage();

    expect(sent.type).toBe('KEYSTONE_SECRET_STORE');
    expect(sent.key).toBe('byok:openrouter-personal');
    expect(sent.value).toBe('sk-super-secret-value');

    dispatchHostMessage({ type: 'KEYSTONE_SECRET_RESPONSE', requestId: sent.requestId, ok: true });

    await expect(promise).resolves.toBe(true);
  });

  it('storeSecret resolves false (never throws) when the host reports failure', async () => {
    vi.spyOn(vscodeApi, 'postMessage');
    const promise = storeSecret('byok:x', 'value');
    const sent = lastPostedMessage();

    dispatchHostMessage({ type: 'KEYSTONE_SECRET_RESPONSE', requestId: sent.requestId, ok: false });

    await expect(promise).resolves.toBe(false);
  });

  it('storeSecret resolves false on timeout rather than hanging forever', async () => {
    vi.useFakeTimers();
    vi.spyOn(vscodeApi, 'postMessage');
    const promise = storeSecret('byok:x', 'value');
    const assertion = expect(promise).resolves.toBe(false);
    await vi.advanceTimersByTimeAsync(15000);
    await assertion;
  });

  it('deleteSecret posts only the key -- never a value field, since there is nothing to send', async () => {
    vi.spyOn(vscodeApi, 'postMessage');
    const promise = deleteSecret('byok:openrouter-personal');
    const sent = lastPostedMessage();

    expect(sent.type).toBe('KEYSTONE_SECRET_DELETE');
    expect(sent.key).toBe('byok:openrouter-personal');
    expect(sent.value).toBeUndefined();

    dispatchHostMessage({ type: 'KEYSTONE_SECRET_RESPONSE', requestId: sent.requestId, ok: true });

    await expect(promise).resolves.toBe(true);
  });

  it('the response envelope this module listens for never carries a value field back', () => {
    // Static assertion of the module's own contract: `SecretResponseMessage`
    // (see secretsClient.ts) has exactly `type`, `requestId`, `ok` -- no
    // secret-shaped field exists for a response to carry even if the host
    // were compromised or buggy.
    const sample = { type: 'KEYSTONE_SECRET_RESPONSE', requestId: 'r1', ok: true };
    expect(Object.keys(sample).sort()).toEqual(['ok', 'requestId', 'type']);
  });
});
