import * as vscode from 'vscode';
import * as path from 'path';
import { Logger } from '../utils/logger';
import { MessageBridge } from '../messaging/messageBridge';
import { getWebviewHtml } from './getWebviewHtml';
import { BackendProxy } from '../api/backendProxy';
import { SecretsProxy } from '../api/secretsProxy';

export interface ConfiguredKeystoneWebview {
  /** Disposes every proxy owned by this webview surface. Call from the
   * surface's own `onDidDispose`. */
  dispose(): void;
}

/**
 * Installs the full Keystone webview surface -- HTML, resource roots,
 * message handling, the backend proxy, and the secrets proxy -- onto a
 * webview. Both the sidebar (`SidebarViewProvider`) and the editor-panel
 * (`WorkspaceController`) surfaces call this instead of duplicating the
 * wiring: they must always stay behaviorally identical (Stage 8C.3 Connect
 * Agent's SecretStorage proxy is exactly the kind of surface that would
 * otherwise silently work in one and not the other).
 */
export function configureKeystoneWebview(
  webview: vscode.Webview,
  extensionUri: vscode.Uri,
  secrets: vscode.SecretStorage
): ConfiguredKeystoneWebview {
  const distPath = path.join(extensionUri.fsPath, 'webview', 'dist');

  webview.options = {
    enableScripts: true,
    localResourceRoots: [
      vscode.Uri.file(distPath),
      vscode.Uri.file(path.join(extensionUri.fsPath, 'media')),
    ],
  };

  webview.html = getWebviewHtml(webview, extensionUri);

  const backendProxy = new BackendProxy();
  const secretsProxy = new SecretsProxy(secrets);

  webview.onDidReceiveMessage((data) => {
    if (backendProxy.handleMessage(data, webview)) {
      return;
    }
    if (secretsProxy.handleMessage(data, webview)) {
      return;
    }
    MessageBridge.handleWebviewMessage(data, webview);
  });

  setTimeout(() => {
    MessageBridge.sendInitMessage(webview);
  }, 300);

  return {
    dispose(): void {
      backendProxy.dispose();
      Logger.info('Keystone webview surface disposed');
    },
  };
}
