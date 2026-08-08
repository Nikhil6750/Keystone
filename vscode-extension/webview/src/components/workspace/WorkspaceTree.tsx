import React from 'react';
import { WorkspaceNode } from './WorkspaceNode';
import type { WorkspaceNodeItem } from '../../hooks/useWorkspaceExplorer';

interface WorkspaceTreeProps {
  nodes: WorkspaceNodeItem[];
  selectedNodeId: string | null;
  expandedNodeIds: Set<string>;
  onSelectNode: (node: WorkspaceNodeItem) => void;
  onToggleExpand: (nodeId: string) => void;
}

export const WorkspaceTree: React.FC<WorkspaceTreeProps> = ({
  nodes,
  selectedNodeId,
  expandedNodeIds,
  onSelectNode,
  onToggleExpand,
}) => {
  return (
    <div className="workspace-tree-container">
      <div className="tree-header">
        <span className="tree-title">Workspace Tree</span>
      </div>
      <div className="tree-body">
        {nodes.map((node) => (
          <WorkspaceNode
            key={node.id}
            node={node}
            level={0}
            selectedNodeId={selectedNodeId}
            expandedNodeIds={expandedNodeIds}
            onSelectNode={onSelectNode}
            onToggleExpand={onToggleExpand}
          />
        ))}
      </div>
    </div>
  );
};
