import * as vscode from 'vscode';
import { MessageBridge } from '../messaging/messageBridge';
import { configureKeystoneWebview, ConfiguredKeystoneWebview } from '../webview/configureKeystoneWebview';

/**
 * Controller orchestrating the Keystone React Webview Panel.
 */
export class WorkspaceController {
  private static currentPanel: vscode.WebviewPanel | undefined;
  private static currentConfigured: ConfiguredKeystoneWebview | undefined;

  public static createOrShow(extensionUri: vscode.Uri, secrets: vscode.SecretStorage): void {
    const column = vscode.window.activeTextEditor
      ? vscode.window.activeTextEditor.viewColumn
      : undefined;

    if (WorkspaceController.currentPanel) {
      WorkspaceController.currentPanel.reveal(column);
      MessageBridge.sendInitMessage(WorkspaceController.currentPanel.webview);
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      'keystoneWorkspace',
      'Keystone Workspace',
      column || vscode.ViewColumn.One,
      { retainContextWhenHidden: true }
    );

    WorkspaceController.currentPanel = panel;
    WorkspaceController.currentConfigured = configureKeystoneWebview(panel.webview, extensionUri, secrets);

    panel.onDidDispose(() => {
      WorkspaceController.currentConfigured?.dispose();
      WorkspaceController.currentConfigured = undefined;
      WorkspaceController.currentPanel = undefined;
    });
  }
}
