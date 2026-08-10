import * as vscode from 'vscode';
import { Logger } from '../../utils/logger';
import { ExtensionLifecycle } from '../lifecycle/extensionLifecycle';
import { KeystoneStatusBarItem } from '../../providers/status-bar/statusBarItem';
import { SidebarViewProvider } from '../../providers/sidebar/sidebarViewProvider';
import { ActivityBarProvider } from '../../providers/activity-bar/activityBarProvider';
import { registerOpenWorkspaceCommand } from '../../commands/openWorkspaceCommand';

/**
 * Executes extension activation setup.
 */
export class ExtensionActivator {
  public static activate(context: vscode.ExtensionContext): void {
    Logger.initialize();
    Logger.info('Activating Keystone VS Code Extension (Sprint 1 Foundation)...');

    // Activity Bar
    ActivityBarProvider.register();

    // Sidebar View
    const sidebarProvider = new SidebarViewProvider(context.extensionUri);
    const sidebarDisposable = vscode.window.registerWebviewViewProvider(
      SidebarViewProvider.viewType,
      sidebarProvider
    );
    context.subscriptions.push(sidebarDisposable);
    ExtensionLifecycle.register(sidebarDisposable);

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
