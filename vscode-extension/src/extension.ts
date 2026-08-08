import * as vscode from 'vscode';
import { ExtensionActivator } from './core/activation/extensionActivator';
import { ExtensionLifecycle } from './core/lifecycle/extensionLifecycle';

/**
 * VS Code Extension Main Entry Point.
 */
export function activate(context: vscode.ExtensionContext): void {
  ExtensionActivator.activate(context);
}

export function deactivate(): void {
  ExtensionLifecycle.dispose();
}
