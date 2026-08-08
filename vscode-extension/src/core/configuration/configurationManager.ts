import * as vscode from 'vscode';

/**
 * Accessor for Keystone workspace configurations.
 */
export class ConfigurationManager {
  private static readonly CONFIG_SECTION = 'keystone';

  public static get<T>(key: string, defaultValue: T): T {
    const config = vscode.workspace.getConfiguration(this.CONFIG_SECTION);
    return config.get<T>(key, defaultValue);
  }

  public static async set<T>(key: string, value: T, target = vscode.ConfigurationTarget.Global): Promise<void> {
    const config = vscode.workspace.getConfiguration(this.CONFIG_SECTION);
    await config.update(key, value, target);
  }
}
