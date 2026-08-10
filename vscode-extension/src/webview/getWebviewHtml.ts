import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { Logger } from '../utils/logger';

function getNonce(): string {
  let text = '';
  const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  for (let i = 0; i < 32; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return text;
}

/**
 * Builds the CSP-hardened, asset-URI-rewritten HTML for the real Keystone
 * React webview bundle (`webview/dist/index.html`), shared by every
 * webview surface (sidebar view, editor panel) so they render the exact
 * same app and stay in sync automatically.
 */
export function getWebviewHtml(webview: vscode.Webview, extensionUri: vscode.Uri): string {
  const distPath = path.join(extensionUri.fsPath, 'webview', 'dist');
  const indexPath = path.join(distPath, 'index.html');

  if (!fs.existsSync(indexPath)) {
    Logger.error('webview/dist/index.html not found, falling back to minimal HTML');
    return getFallbackHtml(webview);
  }

  let html = fs.readFileSync(indexPath, 'utf8');
  const nonce = getNonce();

  // No `connect-src` override: the webview never calls the Keystone
  // backend directly (a VS Code webview's random-per-session
  // `vscode-webview://` origin can never satisfy a static backend CORS
  // allowlist). All backend HTTP/SSE traffic is proxied through the
  // extension host via `postMessage` instead (see `src/api/backendProxy.ts`
  // and `webview/src/api/keystoneClient.ts`), so `default-src 'none'`
  // correctly blocks any other network access from inside the webview.
  const cspMeta = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${webview.cspSource} https: data:; script-src 'nonce-${nonce}' ${webview.cspSource}; style-src ${webview.cspSource} 'unsafe-inline'; font-src ${webview.cspSource};">`;

  if (html.includes('<head>')) {
    html = html.replace('<head>', `<head>\n    ${cspMeta}`);
  } else {
    html = `<head>${cspMeta}</head>` + html;
  }

  // Remove crossorigin attribute from bundle script and link tags.
  html = html.replace(/\scrossorigin(=("[^"]*"|'[^']*'|[^>\s]+))?/gi, '');

  // Replace asset relative/absolute paths with webview.asWebviewUri.
  html = html.replace(/(src|href)="(\.?\/)?assets\/([^"]+)"/g, (_match, attr, _prefix, filename) => {
    const fileUri = vscode.Uri.file(path.join(distPath, 'assets', filename));
    const webviewUri = webview.asWebviewUri(fileUri);
    return `${attr}="${webviewUri}"`;
  });

  // Inject nonce into script tags.
  html = html.replace(/<script\b([^>]*)>/gi, (match, p1) => {
    if (p1.includes('nonce=')) return match;
    return `<script nonce="${nonce}"${p1}>`;
  });

  Logger.info('Webview HTML generated successfully with CSP and asWebviewUri assets');
  return html;
}

function getFallbackHtml(webview: vscode.Webview): string {
  const nonce = getNonce();
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-${nonce}' ${webview.cspSource}; style-src ${webview.cspSource} 'unsafe-inline';">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Keystone</title>
  <style>
    body {
      font-family: var(--vscode-font-family, sans-serif);
      padding: 20px;
      color: var(--vscode-foreground);
      background: var(--vscode-editor-background);
    }
  </style>
</head>
<body>
  <p>Keystone webview bundle not found. Run "npm run build" in vscode-extension/.</p>
</body>
</html>`;
}
