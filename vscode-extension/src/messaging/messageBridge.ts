import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { Logger } from '../utils/logger';
import { OrchestrationApiClient } from '../api/orchestrationApiClient';
import type { OrchestrationExecutionCreate } from '../../../shared-contracts/src';

export interface BridgeMessage {
  type: string;
  action?: string;
  message?: string;
  requestId?: string;
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
 * Handles IPC messaging, workspace file tree inspects, and REST/SSE orchestration requests.
 */
export class MessageBridge {
  private static apiClient: OrchestrationApiClient = new OrchestrationApiClient();
  private static activeSubscriptions: Map<string, () => void> = new Map();

  public static getApiClient(): OrchestrationApiClient {
    return this.apiClient;
  }

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
      return;
    }

    if (actionType === 'CREATE_ORCHESTRATION' && webview) {
      this.handleCreateOrchestration(message, webview);
      return;
    }

    if (actionType === 'GET_ORCHESTRATION_STATUS' && webview) {
      this.handleGetOrchestrationStatus(message, webview);
      return;
    }

    if (actionType === 'SUBSCRIBE_EVENTS' && webview) {
      this.handleSubscribeEvents(message, webview);
      return;
    }

    if (actionType === 'UNSUBSCRIBE_EVENTS') {
      this.handleUnsubscribeEvents(message);
      return;
    }

    if (actionType === 'GET_AGENTS' && webview) {
      this.handleGetAgents(message, webview);
      return;
    }

    if (actionType === 'VERIFY_AGENT' && webview) {
      this.handleVerifyAgent(message, webview);
      return;
    }
  }

  private static async handleCreateOrchestration(
    message: BridgeMessage,
    webview: vscode.Webview
  ): Promise<void> {
    const requestId = message.requestId || String(Date.now());
    const payload = message.payload as OrchestrationExecutionCreate;

    try {
      const accepted = await this.apiClient.createOrchestration(payload);
      webview.postMessage({
        type: 'CREATE_ORCHESTRATION_RESPONSE',
        requestId,
        success: true,
        payload: accepted,
      });
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      webview.postMessage({
        type: 'CREATE_ORCHESTRATION_RESPONSE',
        requestId,
        success: false,
        error: errorMessage,
      });
    }
  }

  private static async handleGetOrchestrationStatus(
    message: BridgeMessage,
    webview: vscode.Webview
  ): Promise<void> {
    const requestId = message.requestId || String(Date.now());
    const executionId = (message.payload as { executionId?: string })?.executionId;

    if (!executionId) {
      webview.postMessage({
        type: 'GET_ORCHESTRATION_STATUS_RESPONSE',
        requestId,
        success: false,
        error: 'Missing executionId parameter',
      });
      return;
    }

    try {
      const status = await this.apiClient.getOrchestrationStatus(executionId);
      webview.postMessage({
        type: 'GET_ORCHESTRATION_STATUS_RESPONSE',
        requestId,
        success: true,
        payload: status,
      });
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      webview.postMessage({
        type: 'GET_ORCHESTRATION_STATUS_RESPONSE',
        requestId,
        success: false,
        error: errorMessage,
      });
    }
  }

  private static handleSubscribeEvents(message: BridgeMessage, webview: vscode.Webview): void {
    const executionId = (message.payload as { executionId?: string })?.executionId;
    if (!executionId) return;

    if (this.activeSubscriptions.has(executionId)) {
      this.activeSubscriptions.get(executionId)?.();
      this.activeSubscriptions.delete(executionId);
    }

    const unsubscribe = this.apiClient.subscribeToEvents(
      executionId,
      (event) => {
        webview.postMessage({
          type: 'ORCHESTRATION_EVENT',
          payload: { executionId, event },
        });
      },
      (err) => {
        webview.postMessage({
          type: 'ORCHESTRATION_EVENT_ERROR',
          payload: { executionId, error: err.message },
        });
      },
      () => {
        webview.postMessage({
          type: 'ORCHESTRATION_EVENTS_COMPLETED',
          payload: { executionId },
        });
        this.activeSubscriptions.delete(executionId);
      }
    );

    this.activeSubscriptions.set(executionId, unsubscribe);
  }

  private static handleUnsubscribeEvents(message: BridgeMessage): void {
    const executionId = (message.payload as { executionId?: string })?.executionId;
    if (executionId && this.activeSubscriptions.has(executionId)) {
      this.activeSubscriptions.get(executionId)?.();
      this.activeSubscriptions.delete(executionId);
    }
  }

  private static async handleGetAgents(
    message: BridgeMessage,
    webview: vscode.Webview
  ): Promise<void> {
    const requestId = message.requestId || String(Date.now());
    try {
      const agents = await this.apiClient.getAgents();
      webview.postMessage({
        type: 'GET_AGENTS_RESPONSE',
        requestId,
        success: true,
        payload: agents,
      });
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      webview.postMessage({
        type: 'GET_AGENTS_RESPONSE',
        requestId,
        success: false,
        error: errorMessage,
      });
    }
  }

  private static async handleVerifyAgent(
    message: BridgeMessage,
    webview: vscode.Webview
  ): Promise<void> {
    const requestId = message.requestId || String(Date.now());
    const agentId = (message.payload as { agentId?: string })?.agentId;

    if (!agentId) {
      webview.postMessage({
        type: 'VERIFY_AGENT_RESPONSE',
        requestId,
        success: false,
        error: 'Missing agentId parameter',
      });
      return;
    }

    try {
      const verified = await this.apiClient.verifyAgent(agentId);
      webview.postMessage({
        type: 'VERIFY_AGENT_RESPONSE',
        requestId,
        success: verified,
      });
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      webview.postMessage({
        type: 'VERIFY_AGENT_RESPONSE',
        requestId,
        success: false,
        error: errorMessage,
      });
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
