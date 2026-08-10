import * as vscode from 'vscode';
import * as path from 'path';
import { Logger } from '../../utils/logger';
import { MessageBridge } from '../../messaging/messageBridge';
import { getWebviewHtml } from '../../webview/getWebviewHtml';
import { BackendProxy } from '../../api/backendProxy';

/**
 * WebviewViewProvider for the Keystone Sidebar View (`keystone.sidebarView`).
 *
 * Loads the same real Keystone React webview bundle the editor-panel
 * surface (`WorkspaceController`) uses -- the prompt-first home
 * experience must work identically in a narrow sidebar and a wide editor
 * panel (Stage 8C.3 UI redesign), not a separate placeholder.
 */
export class SidebarViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = 'keystone.sidebarView';

  public constructor(private readonly extensionUri: vscode.Uri) {}

  public resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    Logger.info('Resolving Keystone Sidebar View');

    const distPath = path.join(this.extensionUri.fsPath, 'webview', 'dist');

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [
        vscode.Uri.file(distPath),
        vscode.Uri.file(path.join(this.extensionUri.fsPath, 'media')),
      ],
    };

    webviewView.webview.html = getWebviewHtml(webviewView.webview, this.extensionUri);

    const backendProxy = new BackendProxy();
    webviewView.onDidDispose(() => backendProxy.dispose());

    webviewView.webview.onDidReceiveMessage((data) => {
      if (backendProxy.handleMessage(data, webviewView.webview)) {
        return;
      }
      MessageBridge.handleWebviewMessage(data, webviewView.webview);
    });

    setTimeout(() => {
      MessageBridge.sendInitMessage(webviewView.webview);
    }, 300);
  }
}
