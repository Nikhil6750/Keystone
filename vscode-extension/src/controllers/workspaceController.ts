import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { Logger } from '../utils/logger';
import { MessageBridge } from '../messaging/messageBridge';

function getNonce(): string {
  let text = '';
  const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  for (let i = 0; i < 32; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return text;
}

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
    panel.webview.html = WorkspaceController.getWebviewContent(panel.webview, extensionUri);

    panel.onDidDispose(() => {
      WorkspaceController.currentPanel = undefined;
    });

    panel.webview.onDidReceiveMessage((msg) => {
      MessageBridge.handleWebviewMessage(msg, panel.webview);
    });

    // Send init message to webview after short delay for listener setup
    setTimeout(() => {
      if (WorkspaceController.currentPanel) {
        MessageBridge.sendInitMessage(WorkspaceController.currentPanel.webview);
      }
    }, 300);
  }

  private static getWebviewContent(webview: vscode.Webview, extensionUri: vscode.Uri): string {
    const distPath = path.join(extensionUri.fsPath, 'webview', 'dist');
    const indexPath = path.join(distPath, 'index.html');

    if (fs.existsSync(indexPath)) {
      let html = fs.readFileSync(indexPath, 'utf8');
      const nonce = getNonce();

      // Content Security Policy allowing script-src with nonce and webview.cspSource
      const cspMeta = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${webview.cspSource} https: data:; script-src 'nonce-${nonce}' ${webview.cspSource}; style-src ${webview.cspSource} 'unsafe-inline'; font-src ${webview.cspSource};">`;

      if (html.includes('<head>')) {
        html = html.replace('<head>', `<head>\n    ${cspMeta}`);
      } else {
        html = `<head>${cspMeta}</head>` + html;
      }

      // Remove crossorigin attribute from bundle script and link tags
      html = html.replace(/\scrossorigin(=("[^"]*"|'[^']*'|[^>\s]+))?/gi, '');

      // Replace asset relative/absolute paths with webview.asWebviewUri
      html = html.replace(/(src|href)="(\.?\/)?assets\/([^"]+)"/g, (_, attr, _prefix, filename) => {
        const fileUri = vscode.Uri.file(path.join(distPath, 'assets', filename));
        const webviewUri = webview.asWebviewUri(fileUri);
        return `${attr}="${webviewUri}"`;
      });

      // Inject nonce into script tags
      html = html.replace(/<script\b([^>]*)>/gi, (match, p1) => {
        if (p1.includes('nonce=')) return match;
        return `<script nonce="${nonce}"${p1}>`;
      });

      Logger.info('Webview HTML generated successfully with CSP and asWebviewUri assets');
      return html;
    }

    Logger.error('webview/dist/index.html not found, falling back to minimal HTML');
    const nonce = getNonce();
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-${nonce}' ${webview.cspSource}; style-src ${webview.cspSource} 'unsafe-inline';">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Keystone Workspace</title>
  <style>
    body { font-family: var(--vscode-font-family, sans-serif); padding: 20px; color: var(--vscode-foreground); background: var(--vscode-editor-background); }
    .card { border: 1px solid var(--vscode-widget-border, #333); padding: 16px; border-radius: 8px; }
  </style>
</head>
<body>
  <div class="card">
    <h2>Keystone</h2>
    <p>Extension successfully initialized.</p>
    <p><strong>Sprint 1 Foundation Complete.</strong></p>
    <p id="status">Connecting to Extension...</p>
  </div>
  <script nonce="${nonce}">
    window.addEventListener('message', event => {
      const message = event.data;
      if (message.type === 'INIT') {
        document.getElementById('status').innerText = 'Connected to Extension';
      }
    });
  </script>
</body>
</html>`;
  }
}
