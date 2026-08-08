import * as vscode from 'vscode';

/**
 * Manages the Keystone Status Bar Item.
 */
export class KeystoneStatusBarItem {
  private item: vscode.StatusBarItem;

  constructor() {
    this.item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    this.item.text = '$(layers) Keystone: Ready';
    this.item.tooltip = 'Keystone AI Agent Orchestrator - Sprint 1 Foundation';
    this.item.command = 'keystone.openWorkspace';
    this.item.show();
  }

  public getDisposable(): vscode.Disposable {
    return this.item;
  }
}
