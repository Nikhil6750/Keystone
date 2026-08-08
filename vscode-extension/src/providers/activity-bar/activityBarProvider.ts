import * as vscode from 'vscode';
import { Logger } from '../../utils/logger';

/**
 * Manages Activity Bar view container registration logic.
 */
export class ActivityBarProvider {
  public static register(): void {
    Logger.info('Activity Bar container registered (keystone-activitybar)');
  }
}
