import { vscodeApi } from '../services/vscodeApi';

/**
 * Webview-side client for the extension-host `SecretsProxy`
 * (`src/api/secretsProxy.ts`). The only two operations that exist are
 * "store" and "delete" -- there is deliberately no "read a secret back"
 * message, so a credential typed into this webview can never round-trip
 * back into React state, a log, or a rendered element after it is stored.
 */

interface SecretResponseMessage {
  type: 'KEYSTONE_SECRET_RESPONSE';
  requestId: string;
  ok: boolean;
}

function isSecretResponseMessage(data: unknown): data is SecretResponseMessage {
  return (
    typeof data === 'object' &&
    data !== null &&
    (data as { type?: unknown }).type === 'KEYSTONE_SECRET_RESPONSE'
  );
}

const REQUEST_TIMEOUT_MS = 10000;
const pending = new Map<string, (ok: boolean) => void>();
let listenerInstalled = false;

function ensureListener(): void {
  if (listenerInstalled) return;
  listenerInstalled = true;
  window.addEventListener('message', (event: MessageEvent<unknown>) => {
    const data = event.data;
    if (!isSecretResponseMessage(data)) return;
    const resolve = pending.get(data.requestId);
    if (!resolve) return;
    pending.delete(data.requestId);
    resolve(data.ok);
  });
}

function nextId(): string {
  return `secret-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** Stores `value` in VS Code `SecretStorage` under `key`. Never resolves
 * with the value itself -- only whether the store succeeded. */
export function storeSecret(key: string, value: string): Promise<boolean> {
  ensureListener();
  const requestId = nextId();
  return new Promise<boolean>((resolve) => {
    const timeoutHandle = setTimeout(() => {
      pending.delete(requestId);
      resolve(false);
    }, REQUEST_TIMEOUT_MS);
    pending.set(requestId, (ok) => {
      clearTimeout(timeoutHandle);
      resolve(ok);
    });
    vscodeApi.postMessage({ type: 'KEYSTONE_SECRET_STORE', requestId, key, value });
  });
}

export function deleteSecret(key: string): Promise<boolean> {
  ensureListener();
  const requestId = nextId();
  return new Promise<boolean>((resolve) => {
    const timeoutHandle = setTimeout(() => {
      pending.delete(requestId);
      resolve(false);
    }, REQUEST_TIMEOUT_MS);
    pending.set(requestId, (ok) => {
      clearTimeout(timeoutHandle);
      resolve(ok);
    });
    vscodeApi.postMessage({ type: 'KEYSTONE_SECRET_DELETE', requestId, key });
  });
}
