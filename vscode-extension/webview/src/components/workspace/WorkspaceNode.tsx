import React from 'react';
import {
  ChevronRight,
  ChevronDown,
  Folder,
  FolderOpen,
  FileText,
  Code,
  FileJson,
} from 'lucide-react';
import type { WorkspaceNodeItem } from '../../hooks/useWorkspaceExplorer';

interface WorkspaceNodeProps {
  node: WorkspaceNodeItem;
  level?: number;
  selectedNodeId: string | null;
  expandedNodeIds: Set<string>;
  onSelectNode: (node: WorkspaceNodeItem) => void;
  onToggleExpand: (nodeId: string) => void;
}

export const WorkspaceNode: React.FC<WorkspaceNodeProps> = ({
  node,
  level = 0,
  selectedNodeId,
  expandedNodeIds,
  onSelectNode,
  onToggleExpand,
}) => {
  const isDirectory = node.kind === 'directory';
  const isExpanded = expandedNodeIds.has(node.id);
  const isSelected = selectedNodeId === node.id;

  const getFileIcon = (ext?: string) => {
    if (!ext) return FileText;
    const lower = ext.toLowerCase();
    if (['.ts', '.tsx', '.js', '.jsx', '.py', '.css', '.html'].includes(lower)) return Code;
    if (['.json', '.toml', '.yaml', '.yml'].includes(lower)) return FileJson;
    return FileText;
  };

  const FileIconComponent = getFileIcon(node.extension);

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onSelectNode(node);
    if (isDirectory) {
      onToggleExpand(node.id);
    }
  };

  return (
    <div className="tree-node-wrapper">
      <div
        className={`tree-node-row ${isSelected ? 'selected' : ''}`}
        style={{ paddingLeft: `${level * 16 + 8}px` }}
        onClick={handleClick}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') handleClick(e as unknown as React.MouseEvent);
        }}
      >
        {isDirectory ? (
          <span className="caret-box">
            {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </span>
        ) : (
          <span className="caret-spacer" />
        )}

        <span className="node-icon-box">
          {isDirectory ? (
            isExpanded ? (
              <FolderOpen size={15} className="folder-icon" />
            ) : (
              <Folder size={15} className="folder-icon" />
            )
          ) : (
            <FileIconComponent size={14} className="file-icon" />
          )}
        </span>

        <span className="node-name">{node.name}</span>
      </div>

      {isDirectory && isExpanded && node.children && node.children.length > 0 && (
        <div className="tree-node-children">
          {node.children.map((child) => (
            <WorkspaceNode
              key={child.id}
              node={child}
              level={level + 1}
              selectedNodeId={selectedNodeId}
              expandedNodeIds={expandedNodeIds}
              onSelectNode={onSelectNode}
              onToggleExpand={onToggleExpand}
            />
          ))}
        </div>
      )}
    </div>
  );
};
