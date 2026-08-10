import * as vscode from 'vscode';
import * as path from 'path';
import { MessageBridge } from '../messaging/messageBridge';
import { getWebviewHtml } from '../webview/getWebviewHtml';
import { BackendProxy } from '../api/backendProxy';

/**
 * Controller orchestrating the Keystone React Webview Panel.
 */
export class WorkspaceController {
  private static currentPanel: vscode.WebviewPanel | undefined;

  public static createOrShow(extensionUri: vscode.Uri): void {
    const column = vscode.window.activeTextEditor
      ? vscode.window.activeTextEditor.viewColumn
      : undefined;

    if (WorkspaceController.currentPanel) {
      WorkspaceController.currentPanel.reveal(column);
      MessageBridge.sendInitMessage(WorkspaceController.currentPanel.webview);
      return;
    }

    const distPath = path.join(extensionUri.fsPath, 'webview', 'dist');

    const panel = vscode.window.createWebviewPanel(
      'keystoneWorkspace',
      'Keystone Workspace',
      column || vscode.ViewColumn.One,
      {
        enableScripts: true,
        localResourceRoots: [
          vscode.Uri.file(distPath),
          vscode.Uri.file(path.join(extensionUri.fsPath, 'media')),
        ],
        retainContextWhenHidden: true,
      }
    );

    WorkspaceController.currentPanel = panel;
    panel.webview.html = getWebviewHtml(panel.webview, extensionUri);

    const backendProxy = new BackendProxy();

    panel.onDidDispose(() => {
      backendProxy.dispose();
      WorkspaceController.currentPanel = undefined;
    });

    panel.webview.onDidReceiveMessage((msg) => {
      if (backendProxy.handleMessage(msg, panel.webview)) {
        return;
      }
      MessageBridge.handleWebviewMessage(msg, panel.webview);
    });

    // Send init message to webview after short delay for listener setup
    setTimeout(() => {
      if (WorkspaceController.currentPanel) {
        MessageBridge.sendInitMessage(WorkspaceController.currentPanel.webview);
      }
    }, 300);
  }
}
