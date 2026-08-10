import * as vscode from 'vscode';
import { Logger } from '../utils/logger';

/**
 * The Keystone backend, as confirmed running for this workspace. Bound
 * explicitly to the IPv4 loopback address -- not `localhost`, which can
 * resolve to the IPv6 loopback (`::1`) first on some systems and fail to
 * connect even when the IPv4 server is healthy.
 */
const BACKEND_BASE_URL = 'http://127.0.0.1:8000';
const BACKEND_API_PREFIX = '/api/v1';

const REQUEST_TIMEOUT_MS = 15000;

interface ApiRequestMessage {
  type: 'KEYSTONE_API_REQUEST';
  requestId: string;
  method: 'GET' | 'POST';
  path: string;
  body?: unknown;
}

interface SseSubscribeMessage {
  type: 'KEYSTONE_SSE_SUBSCRIBE';
  subscriptionId: string;
  path: string;
}

interface SseUnsubscribeMessage {
  type: 'KEYSTONE_SSE_UNSUBSCRIBE';
  subscriptionId: string;
}

function isApiRequestMessage(message: unknown): message is ApiRequestMessage {
  return (
    typeof message === 'object' &&
    message !== null &&
    (message as { type?: unknown }).type === 'KEYSTONE_API_REQUEST'
  );
}

function isSseSubscribeMessage(message: unknown): message is SseSubscribeMessage {
  return (
    typeof message === 'object' &&
    message !== null &&
    (message as { type?: unknown }).type === 'KEYSTONE_SSE_SUBSCRIBE'
  );
}

function isSseUnsubscribeMessage(message: unknown): message is SseUnsubscribeMessage {
  return (
    typeof message === 'object' &&
    message !== null &&
    (message as { type?: unknown }).type === 'KEYSTONE_SSE_UNSUBSCRIBE'
  );
}

/**
 * Proxies webview <-> Keystone backend traffic through the extension host.
 *
 * A VS Code webview's JS context runs under a `vscode-webview://<random-
 * uuid>` origin that is minted fresh every session, so it can never be
 * added to a static server-side CORS allowlist -- a direct `fetch`/
 * `EventSource` call from the webview to the backend is rejected by the
 * browser even when the backend answers 200. This extension-host process
 * is plain Node.js, not a browser, so it is not subject to CORS: it makes
 * the real HTTP/SSE call here and relays only the already-safe, already-
 * typed result back to the webview over `postMessage`.
 *
 * One instance is owned per webview surface (sidebar view / editor panel)
 * so in-flight SSE subscriptions are tracked and cleaned up independently.
 */
export class BackendProxy {
  private readonly activeStreams = new Map<string, AbortController>();

  /** Returns true if the message was a backend-proxy message and was handled. */
  public handleMessage(message: unknown, webview: vscode.Webview): boolean {
    if (isApiRequestMessage(message)) {
      void this.handleApiRequest(message, webview);
      return true;
    }
    if (isSseSubscribeMessage(message)) {
      void this.handleSseSubscribe(message, webview);
      return true;
    }
    if (isSseUnsubscribeMessage(message)) {
      this.handleSseUnsubscribe(message);
      return true;
    }
    return false;
  }

  private async handleApiRequest(message: ApiRequestMessage, webview: vscode.Webview): Promise<void> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    try {
      const response = await fetch(`${BACKEND_BASE_URL}${BACKEND_API_PREFIX}${message.path}`, {
        method: message.method,
        headers: message.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
        body: message.body !== undefined ? JSON.stringify(message.body) : undefined,
        signal: controller.signal,
      });

      let body: unknown = null;
      try {
        body = await response.json();
      } catch {
        body = null;
      }

      void webview.postMessage({
        type: 'KEYSTONE_API_RESPONSE',
        requestId: message.requestId,
        networkError: false,
        ok: response.ok,
        status: response.status,
        body,
      });
    } catch (err) {
      Logger.error(`Keystone backend request failed (${message.method} ${message.path})`, err);
      void webview.postMessage({
        type: 'KEYSTONE_API_RESPONSE',
        requestId: message.requestId,
        networkError: true,
        ok: false,
        status: 0,
        body: null,
      });
    } finally {
      clearTimeout(timeout);
    }
  }

  private async handleSseSubscribe(message: SseSubscribeMessage, webview: vscode.Webview): Promise<void> {
    const controller = new AbortController();
    this.activeStreams.set(message.subscriptionId, controller);

    try {
      const response = await fetch(`${BACKEND_BASE_URL}${BACKEND_API_PREFIX}${message.path}`, {
        headers: { Accept: 'text/event-stream' },
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        void webview.postMessage({ type: 'KEYSTONE_SSE_ERROR', subscriptionId: message.subscriptionId });
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let separatorIndex = buffer.indexOf('\n\n');
        while (separatorIndex !== -1) {
          const rawFrame = buffer.slice(0, separatorIndex);
          buffer = buffer.slice(separatorIndex + 2);
          this.dispatchSseFrame(rawFrame, message.subscriptionId, webview);
          separatorIndex = buffer.indexOf('\n\n');
        }
      }

      void webview.postMessage({ type: 'KEYSTONE_SSE_DONE', subscriptionId: message.subscriptionId });
    } catch (err) {
      if (!controller.signal.aborted) {
        Logger.error(`Keystone event stream failed (${message.path})`, err);
        void webview.postMessage({ type: 'KEYSTONE_SSE_ERROR', subscriptionId: message.subscriptionId });
      }
    } finally {
      this.activeStreams.delete(message.subscriptionId);
    }
  }

  private dispatchSseFrame(rawFrame: string, subscriptionId: string, webview: vscode.Webview): void {
    let eventType = 'message';
    const dataLines: string[] = [];

    for (const line of rawFrame.split('\n')) {
      if (line.startsWith('event:')) {
        eventType = line.slice('event:'.length).trim();
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice('data:'.length).trim());
      }
    }

    if (dataLines.length === 0) {
      return;
    }

    void webview.postMessage({
      type: 'KEYSTONE_SSE_EVENT',
      subscriptionId,
      eventType,
      data: dataLines.join('\n'),
    });
  }

  private handleSseUnsubscribe(message: SseUnsubscribeMessage): void {
    this.activeStreams.get(message.subscriptionId)?.abort();
    this.activeStreams.delete(message.subscriptionId);
  }

  /** Aborts every in-flight request/stream owned by this proxy instance. */
  public dispose(): void {
    for (const controller of this.activeStreams.values()) {
      controller.abort();
    }
    this.activeStreams.clear();
  }
}
