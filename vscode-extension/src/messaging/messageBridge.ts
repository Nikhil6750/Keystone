import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { Logger } from '../utils/logger';

export interface BridgeMessage {
  type: string;
  action?: string;
  message?: string;
  payload?: unknown;
}

export interface WorkspaceNodeItem {
  id: string;
  name: string;
  relativePath: string;
  kind: 'file' | 'directory';
  size?: number;
  extension?: string;
  lastModified?: string;
  preview?: string;
  children?: WorkspaceNodeItem[];
}

/**
 * Message bridge between Extension Host and Webview.
 */
export class MessageBridge {
  public static sendInitMessage(webview: vscode.Webview): void {
    const msg: BridgeMessage = {
      type: 'INIT',
      message: 'Extension Ready',
    };
    Logger.info('Sending INIT message over bridge to webview');
    webview.postMessage(msg);
  }

  public static handleWebviewMessage(message: BridgeMessage, webview?: vscode.Webview): void {
    const actionType = message.action || message.type;
    Logger.info(`Received webview message action/type: ${actionType}`);

    if (actionType === 'GET_WORKSPACE_TREE' && webview) {
      this.sendWorkspaceTree(webview);
    }
  }

  public static sendWorkspaceTree(webview: vscode.Webview): void {
    const folders = vscode.workspace.workspaceFolders;

    if (!folders || folders.length === 0) {
      webview.postMessage({
        type: 'WORKSPACE_TREE_RESPONSE',
        payload: {
          hasWorkspace: false,
          workspaceName: null,
          rootNodes: [],
        },
      });
      return;
    }

    const rootFolder = folders[0];
    const rootPath = rootFolder.uri.fsPath;
    const workspaceName = rootFolder.name;

    try {
      const rootNodes = [this.buildDirectoryTree(rootPath, rootPath, 0, 4)];
      webview.postMessage({
        type: 'WORKSPACE_TREE_RESPONSE',
        payload: {
          hasWorkspace: true,
          workspaceName,
          rootNodes,
        },
      });
    } catch (err) {
      Logger.error(`Error reading workspace tree: ${err}`);
      webview.postMessage({
        type: 'WORKSPACE_TREE_RESPONSE',
        payload: {
          hasWorkspace: false,
          workspaceName,
          rootNodes: [],
        },
      });
    }
  }

  private static buildDirectoryTree(
    dirPath: string,
    rootPath: string,
    currentDepth: number,
    maxDepth: number
  ): WorkspaceNodeItem {
    const name = path.basename(dirPath);
    const relPath = path.relative(rootPath, dirPath) || '.';
    const stats = fs.statSync(dirPath);

    const node: WorkspaceNodeItem = {
      id: relPath,
      name: name || rootPath,
      relativePath: relPath,
      kind: 'directory',
      lastModified: stats.mtime.toISOString().replace('T', ' ').substring(0, 19),
      children: [],
    };

    if (currentDepth >= maxDepth) return node;

    const ignoreList = new Set(['.git', 'node_modules', 'dist', '.cache', '.DS_Store', 'out', 'build']);

    try {
      const items = fs.readdirSync(dirPath);
      const children: WorkspaceNodeItem[] = [];

      for (const item of items) {
        if (ignoreList.has(item)) continue;

        const fullPath = path.join(dirPath, item);
        try {
          const itemStats = fs.statSync(fullPath);
          const itemRelPath = path.relative(rootPath, fullPath);

          if (itemStats.isDirectory()) {
            children.push(this.buildDirectoryTree(fullPath, rootPath, currentDepth + 1, maxDepth));
          } else {
            const ext = path.extname(item).toLowerCase();
            let preview: string | undefined;

            const textExts = new Set(['.ts', '.tsx', '.json', '.md', '.py', '.css', '.html', '.txt', '.js', '.yml', '.yaml', '.sh']);
            if (textExts.has(ext) && itemStats.size < 100000) {
              try {
                const content = fs.readFileSync(fullPath, 'utf8');
                preview = content.substring(0, 400);
              } catch {
                // ignore unreadable
              }
            }

            children.push({
              id: itemRelPath,
              name: item,
              relativePath: itemRelPath,
              kind: 'file',
              size: itemStats.size,
              extension: ext || 'file',
              lastModified: itemStats.mtime.toISOString().replace('T', ' ').substring(0, 19),
              preview,
            });
          }
        } catch {
          // skip inaccessible
        }
      }

      // Sort directories first, then files
      children.sort((a, b) => {
        if (a.kind !== b.kind) return a.kind === 'directory' ? -1 : 1;
        return a.name.localeCompare(b.name);
      });

      node.children = children;
    } catch {
      // ignore readdir error
    }

    return node;
  }
}
