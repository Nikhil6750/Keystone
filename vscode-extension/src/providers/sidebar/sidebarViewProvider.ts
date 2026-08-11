import * as vscode from 'vscode';
import { Logger } from '../../utils/logger';
import { configureKeystoneWebview } from '../../webview/configureKeystoneWebview';

/**
 * WebviewViewProvider for the Keystone Sidebar View (`keystone.sidebarView`).
 *
 * Loads the same real Keystone React webview bundle the editor-panel
 * surface (`WorkspaceController`) uses -- the prompt-first home
 * experience must work identically in a narrow sidebar and a wide editor
 * panel (Stage 8C.3 UI redesign), not a separate placeholder. Both surfaces
 * share their full setup via `configureKeystoneWebview` for the same reason.
 */
export class SidebarViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = 'keystone.sidebarView';

  public constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly secrets: vscode.SecretStorage
  ) {}

  public resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    Logger.info('Resolving Keystone Sidebar View');

    const configured = configureKeystoneWebview(webviewView.webview, this.extensionUri, this.secrets);
    webviewView.onDidDispose(() => configured.dispose());
  }
}
