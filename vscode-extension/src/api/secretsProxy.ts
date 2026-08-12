import * as vscode from 'vscode';
import { Logger } from '../utils/logger';

/**
 * Proxies webview <-> VS Code `SecretStorage` for Connect Agent's API/BYOK
 * credential entry.
 *
 * A credential typed into the webview must never be written to `agent
 * metadata`, `AgentConnection`/`ConnectedAgent` records, `localStorage`,
 * `workspaceState`, `settings.json`, or any orchestration payload -- see
 * the backend's own `validate_metadata` (`app.engine.connections.models`),
 * which rejects any secret-shaped metadata key at the API boundary as a
 * second, independent enforcement layer. This proxy is the *only* place a
 * BYOK credential is allowed to land: `context.secrets` (backed by the
 * OS keychain / VS Code's own encrypted storage), addressed only by an
 * opaque key the caller supplies (e.g. `byok:<connection_id>`) -- never
 * the secret value itself, which this module also never logs.
 *
 * There is deliberately no "read a secret back to the webview" message:
 * nothing here needs one yet (no BYOK execution adapter exists to consume
 * it -- see `ApiByokView.tsx`), and omitting it entirely is a stronger
 * guarantee than trusting every future caller to keep discipline about
 * never rendering what it reads.
 */

interface SecretStoreMessage {
  type: 'KEYSTONE_SECRET_STORE';
  requestId: string;
  key: string;
  value: string;
}

interface SecretDeleteMessage {
  type: 'KEYSTONE_SECRET_DELETE';
  requestId: string;
  key: string;
}

function isSecretStoreMessage(message: unknown): message is SecretStoreMessage {
  return (
    typeof message === 'object' &&
    message !== null &&
    (message as { type?: unknown }).type === 'KEYSTONE_SECRET_STORE'
  );
}

function isSecretDeleteMessage(message: unknown): message is SecretDeleteMessage {
  return (
    typeof message === 'object' &&
    message !== null &&
    (message as { type?: unknown }).type === 'KEYSTONE_SECRET_DELETE'
  );
}

const _KEY_PATTERN = /^[a-zA-Z0-9_.:-]{1,128}$/;

export class SecretsProxy {
  public constructor(private readonly secrets: vscode.SecretStorage) {}

  /** Returns true if the message was a secrets-proxy message and was handled. */
  public handleMessage(message: unknown, webview: vscode.Webview): boolean {
    if (isSecretStoreMessage(message)) {
      void this.handleStore(message, webview);
      return true;
    }
    if (isSecretDeleteMessage(message)) {
      void this.handleDelete(message, webview);
      return true;
    }
    return false;
  }

  private async handleStore(message: SecretStoreMessage, webview: vscode.Webview): Promise<void> {
    if (!_KEY_PATTERN.test(message.key)) {
      Logger.error(`Rejected secret store request with invalid key shape (length ${message.key.length})`);
      void webview.postMessage({
        type: 'KEYSTONE_SECRET_RESPONSE',
        requestId: message.requestId,
        ok: false,
      });
      return;
    }
    try {
      await this.secrets.store(message.key, message.value);
      Logger.info(`Secret stored under key '${message.key}'`);
      void webview.postMessage({
        type: 'KEYSTONE_SECRET_RESPONSE',
        requestId: message.requestId,
        ok: true,
      });
    } catch (err) {
      Logger.error('Failed to store secret', err);
      void webview.postMessage({
        type: 'KEYSTONE_SECRET_RESPONSE',
        requestId: message.requestId,
        ok: false,
      });
    }
  }

  private async handleDelete(message: SecretDeleteMessage, webview: vscode.Webview): Promise<void> {
    try {
      await this.secrets.delete(message.key);
      Logger.info(`Secret deleted for key '${message.key}'`);
      void webview.postMessage({
        type: 'KEYSTONE_SECRET_RESPONSE',
        requestId: message.requestId,
        ok: true,
      });
    } catch (err) {
      Logger.error('Failed to delete secret', err);
      void webview.postMessage({
        type: 'KEYSTONE_SECRET_RESPONSE',
        requestId: message.requestId,
        ok: false,
      });
    }
  }
}
