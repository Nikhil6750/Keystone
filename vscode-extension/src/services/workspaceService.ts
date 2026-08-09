import { Logger } from '../utils/logger';

/**
 * Service encapsulating Keystone extension workspace foundation state.
 */
export class WorkspaceService {
  private isInitialized = false;

  public initialize(): void {
    if (this.isInitialized) return;
    this.isInitialized = true;
    Logger.info('WorkspaceService initialized');
  }

  public getStatus(): string {
    return 'Sprint 1 Foundation Complete';
  }
}
