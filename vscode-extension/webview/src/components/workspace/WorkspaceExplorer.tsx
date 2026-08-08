import React from 'react';
import { WorkspaceTree } from './WorkspaceTree';
import { WorkspaceDetails } from './WorkspaceDetails';
import { EmptyWorkspace } from './EmptyWorkspace';
import { useWorkspaceExplorer } from '../../hooks/useWorkspaceExplorer';

export const WorkspaceExplorer: React.FC = () => {
  const {
    hasWorkspace,
    tree,
    selectedNode,
    expandedNodeIds,
    selectNode,
    toggleExpand,
  } = useWorkspaceExplorer();

  if (!hasWorkspace || tree.length === 0) {
    return (
      <div className="agent-manager-container">
        <header className="builder-header">
          <h1 className="builder-title">Workspace Explorer</h1>
          <p className="builder-subtitle">
            Browse and inspect workspace files, directories, and specs.
          </p>
        </header>
        <EmptyWorkspace />
      </div>
    );
  }

  return (
    <div className="agent-manager-container">
      <header className="builder-header">
        <h1 className="builder-title">Workspace Explorer</h1>
        <p className="builder-subtitle">
          Browse and inspect workspace files, directories, and specs.
        </p>
      </header>

      <div className="workspace-explorer-layout">
        <WorkspaceTree
          nodes={tree}
          selectedNodeId={selectedNode?.id || null}
          expandedNodeIds={expandedNodeIds}
          onSelectNode={selectNode}
          onToggleExpand={toggleExpand}
        />

        <WorkspaceDetails node={selectedNode} />
      </div>
    </div>
  );
};
