import * as vscode from 'vscode';
import { Logger } from '../../utils/logger';

/**
 * Manages extension subscriptions and teardown lifecycle.
 */
export class ExtensionLifecycle {
  private static disposables: vscode.Disposable[] = [];

  public static register(disposable: vscode.Disposable): void {
    this.disposables.push(disposable);
  }

  public static dispose(): void {
    Logger.info('Disposing Keystone extension resources...');
    for (const disposable of this.disposables) {
      try {
        disposable.dispose();
      } catch (err) {
        Logger.error('Failed to dispose resource', err);
      }
    }
    this.disposables = [];
    Logger.dispose();
  }
}
