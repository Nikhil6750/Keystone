import { WorkspaceApi } from '../api/WorkspaceApi';
import type { WorkspaceNodeItem } from '../api/MockProvider';

export class WorkspaceService {
  public static async getWorkspaceTree(): Promise<WorkspaceNodeItem[]> {
    return WorkspaceApi.fetchWorkspaceTree();
  }

  public static getNode(
    tree: WorkspaceNodeItem[],
    id: string | null
  ): WorkspaceNodeItem | null {
    if (!id) return null;
    for (const node of tree) {
      if (node.id === id) return node;
      if (node.children) {
        const found = this.getNode(node.children, id);
        if (found) return found;
      }
    }
    return null;
  }
}
