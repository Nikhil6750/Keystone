import * as vscode from 'vscode';

/**
 * OutputChannel logger for the Keystone VS Code Extension.
 */
export class Logger {
  private static channel: vscode.OutputChannel | undefined;

  public static initialize(): void {
    if (!this.channel) {
      this.channel = vscode.window.createOutputChannel('Keystone');
    }
  }

  public static info(message: string): void {
    this.initialize();
    this.channel?.appendLine(`[INFO] [${new Date().toISOString()}] ${message}`);
  }

  public static error(message: string, error?: unknown): void {
    this.initialize();
    this.channel?.appendLine(`[ERROR] [${new Date().toISOString()}] ${message}`);
    if (error) {
      this.channel?.appendLine(error instanceof Error ? error.stack || error.message : String(error));
    }
  }

  public static dispose(): void {
    this.channel?.dispose();
    this.channel = undefined;
  }
}
