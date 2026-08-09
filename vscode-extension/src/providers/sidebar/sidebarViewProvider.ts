import * as vscode from 'vscode';
import { Logger } from '../../utils/logger';

/**
 * WebviewViewProvider for the Keystone Sidebar View (`keystone.sidebarView`).
 */
export class SidebarViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = 'keystone.sidebarView';

  public resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    Logger.info('Resolving Keystone Sidebar View');

    webviewView.webview.options = {
      enableScripts: true,
    };

    webviewView.webview.html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <style>
    body { font-family: var(--vscode-font-family, sans-serif); padding: 12px; color: var(--vscode-foreground); }
    h3 { margin-top: 0; color: var(--vscode-textLink-foreground); }
    button {
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
      border: none;
      padding: 6px 12px;
      border-radius: 4px;
      cursor: pointer;
      width: 100%;
    }
    button:hover {
      background: var(--vscode-button-hoverBackground);
    }
  </style>
</head>
<body>
  <h3>Keystone Explorer</h3>
  <p>Sprint 1 Foundation Active</p>
  <button onclick="openWorkspace()">Open Workspace</button>

  <script>
    const vscode = acquireVsCodeApi();
    function openWorkspace() {
      vscode.postMessage({ type: 'OPEN_WORKSPACE' });
    }
  </script>
</body>
</html>`;

    webviewView.webview.onDidReceiveMessage((data) => {
      if (data.type === 'OPEN_WORKSPACE') {
        vscode.commands.executeCommand('keystone.openWorkspace');
      }
    });
  }
}
