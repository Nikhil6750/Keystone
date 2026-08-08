import { useState, useEffect, useCallback, useMemo } from 'react';
import { vscodeApi } from '../services/vscodeApi';
import { WorkspaceService } from '../services/WorkspaceService';
import type { WorkspaceNodeItem } from '../api/MockProvider';
import { useAppState } from './useAppState';

export function useWorkspaceExplorer() {
  const { selectedWorkspaceNodeId, setSelectedWorkspaceNodeId } = useAppState();
  const [hasWorkspace, setHasWorkspace] = useState<boolean>(true);
  const [workspaceName, setWorkspaceName] = useState<string | null>('Keystone');
  const [tree, setTree] = useState<WorkspaceNodeItem[]>([]);
  const [expandedNodeIds, setExpandedNodeIds] = useState<Set<string>>(
    new Set(['.', 'backend', 'backend/app', 'vscode-extension'])
  );

  useEffect(() => {
    let isMounted = true;
    WorkspaceService.getWorkspaceTree().then((nodes) => {
      if (isMounted) setTree(nodes);
    });

    // Request live workspace tree from Extension Host if available
    vscodeApi.postMessage({ action: 'GET_WORKSPACE_TREE' });

    const handleWindowMessage = (event: MessageEvent) => {
      const msg = event.data;
      if (msg && msg.type === 'WORKSPACE_TREE_RESPONSE' && msg.payload) {
        const { hasWorkspace: hw, workspaceName: name, rootNodes } = msg.payload;
        setHasWorkspace(hw);
        setWorkspaceName(name);

        if (hw && rootNodes && rootNodes.length > 0) {
          setTree(rootNodes);
          if (!selectedWorkspaceNodeId) {
            setSelectedWorkspaceNodeId(rootNodes[0].id);
          }
          setExpandedNodeIds((prev) => {
            const next = new Set(prev);
            next.add(rootNodes[0].id);
            return next;
          });
        }
      }
    };

    window.addEventListener('message', handleWindowMessage);
    return () => {
      isMounted = false;
      window.removeEventListener('message', handleWindowMessage);
    };
  }, [selectedWorkspaceNodeId, setSelectedWorkspaceNodeId]);

  const selectedNode = useMemo(
    () => WorkspaceService.getNode(tree, selectedWorkspaceNodeId) || tree[0] || null,
    [tree, selectedWorkspaceNodeId]
  );

  const selectNode = useCallback(
    (node: WorkspaceNodeItem) => {
      setSelectedWorkspaceNodeId(node.id);
    },
    [setSelectedWorkspaceNodeId]
  );

  const toggleExpand = useCallback((nodeId: string) => {
    setExpandedNodeIds((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  }, []);

  return {
    hasWorkspace,
    workspaceName,
    tree,
    selectedNode,
    expandedNodeIds,
    selectNode,
    toggleExpand,
  };
}
