import { ApiClient } from './ApiClient';
import type { WorkspaceNodeItem } from './MockProvider';

export class WorkspaceApi {
  public static async fetchWorkspaceTree(): Promise<WorkspaceNodeItem[]> {
    const res = await ApiClient.get<WorkspaceNodeItem[]>('/workspace/tree');
    return res.data;
  }
}
