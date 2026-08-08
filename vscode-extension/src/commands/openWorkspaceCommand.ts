import * as vscode from 'vscode';
import { WorkspaceController } from '../controllers/workspaceController';
import { Logger } from '../utils/logger';

/**
 * Registers the "Keystone: Open Workspace" command.
 */
export function registerOpenWorkspaceCommand(context: vscode.ExtensionContext): vscode.Disposable {
  return vscode.commands.registerCommand('keystone.openWorkspace', () => {
    Logger.info('Executing command: keystone.openWorkspace');
    WorkspaceController.createOrShow(context.extensionUri);
  });
}
