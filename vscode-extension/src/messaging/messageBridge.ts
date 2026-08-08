import * as vscode from 'vscode';
import { Logger } from '../utils/logger';

export interface BridgeMessage {
  type: string;
  message?: string;
  payload?: unknown;
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

  public static handleWebviewMessage(message: BridgeMessage): void {
    Logger.info(`Received webview message of type: ${message.type}`);
  }
}
