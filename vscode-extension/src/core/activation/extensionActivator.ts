import * as vscode from 'vscode';
import { Logger } from '../../utils/logger';
import { ExtensionLifecycle } from '../lifecycle/extensionLifecycle';
import { KeystoneStatusBarItem } from '../../providers/status-bar/statusBarItem';
import { SidebarViewProvider } from '../../providers/sidebar/sidebarViewProvider';
import { ActivityBarProvider } from '../../providers/activity-bar/activityBarProvider';
import { registerOpenWorkspaceCommand } from '../../commands/openWorkspaceCommand';
import { LocalEngineManager } from '../../services/localEngineManager';

/**
 * Executes extension activation setup.
 */
export class ExtensionActivator {
  public static activate(context: vscode.ExtensionContext): void {
    Logger.initialize();
    Logger.info('Activating Keystone VS Code Extension (Sprint 1 Foundation)...');

    // Local engine auto-management (Part 9): checked/started in the
    // background so it never blocks the rest of activation -- the sidebar
    // renders immediately either way, showing "Keystone backend
    // unavailable" with Retry for the few seconds a real start takes, the
    // same honest state as before, just self-healing now instead of
    // requiring a manual `uvicorn` command.
    const engineManager = new LocalEngineManager();
    ExtensionLifecycle.register(engineManager);
    void engineManager.ensureRunning().then((result) => {
      Logger.info(`Local engine ensureRunning() -> ${result}`);
      if (result === 'port_conflict') {
        void vscode.window.showWarningMessage('Port 8000 is already in use by another service.');
      } else if (result === 'failed_to_start') {
        void vscode.window.showWarningMessage(
          'Keystone could not start its local backend engine. Check the "Keystone" output channel for details.'
        );
      }
    });

    // Activity Bar
    ActivityBarProvider.register();

    // Sidebar View
    // `retainContextWhenHidden` keeps the webview's JS context (and its
    // already-fetched state) alive when the user switches to a different
    // activity-bar view and back, instead of tearing the whole React app
    // down and remounting it -- which would otherwise re-issue every
    // initial-load request (e.g. GET /connected-agents) on every visibility
    // toggle, not just once per real session.
    const sidebarProvider = new SidebarViewProvider(context.extensionUri, context.secrets);
    const sidebarDisposable = vscode.window.registerWebviewViewProvider(
      SidebarViewProvider.viewType,
      sidebarProvider,
      { webviewOptions: { retainContextWhenHidden: true } }
    );
    context.subscriptions.push(sidebarDisposable);
    ExtensionLifecycle.register(sidebarDisposable);
    Logger.info(`Sidebar view provider registered (${SidebarViewProvider.viewType})`);

    // Status Bar
    const statusBar = new KeystoneStatusBarItem();
    const statusBarDisposable = statusBar.getDisposable();
    context.subscriptions.push(statusBarDisposable);
    ExtensionLifecycle.register(statusBarDisposable);

    // Command registration
    const openWorkspaceDisposable = registerOpenWorkspaceCommand(context);
    context.subscriptions.push(openWorkspaceDisposable);
    ExtensionLifecycle.register(openWorkspaceDisposable);

    Logger.info('Keystone extension foundation successfully activated.');
  }
}
