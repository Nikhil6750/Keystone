import { useState, useEffect, useCallback, useMemo } from 'react';
import { vscodeApi } from '../services/vscodeApi';
import { useAppState } from './useAppState';

export interface WorkspaceNodeItem {
  id: string;
  name: string;
  relativePath: string;
  kind: 'file' | 'directory';
  size?: number;
  extension?: string;
  lastModified?: string;
  preview?: string;
  children?: WorkspaceNodeItem[];
}

const FALLBACK_TREE: WorkspaceNodeItem[] = [
  {
    id: '.',
    name: 'Keystone',
    relativePath: '.',
    kind: 'directory',
    lastModified: '2026-08-08 12:00:00',
    children: [
      {
        id: 'backend',
        name: 'backend',
        relativePath: 'backend',
        kind: 'directory',
        lastModified: '2026-08-08 11:30:00',
        children: [
          {
            id: 'backend/app',
            name: 'app',
            relativePath: 'backend/app',
            kind: 'directory',
            lastModified: '2026-08-08 11:00:00',
            children: [
              {
                id: 'backend/app/main.py',
                name: 'main.py',
                relativePath: 'backend/app/main.py',
                kind: 'file',
                size: 1420,
                extension: '.py',
                lastModified: '2026-08-08 10:45:00',
                preview:
                  'from fastapi import FastAPI\nfrom app.api import router\n\napp = FastAPI(title="Keystone Orchestrator Engine")\napp.include_router(router)',
              },
              {
                id: 'backend/app/config.py',
                name: 'config.py',
                relativePath: 'backend/app/config.py',
                kind: 'file',
                size: 580,
                extension: '.py',
                lastModified: '2026-08-08 09:30:00',
                preview:
                  'import os\nfrom pydantic_settings import BaseSettings\n\nclass Settings(BaseSettings):\n    DB_URL: str = "sqlite:///./keystone.db"',
              },
            ],
          },
          {
            id: 'backend/pyproject.toml',
            name: 'pyproject.toml',
            relativePath: 'backend/pyproject.toml',
            kind: 'file',
            size: 420,
            extension: '.toml',
            lastModified: '2026-08-07 16:00:00',
            preview:
              '[tool.poetry]\nname = "keystone-backend"\nversion = "0.1.0"\ndescription = "Keystone Orchestration Engine"',
          },
        ],
      },
      {
        id: 'frontend',
        name: 'frontend',
        relativePath: 'frontend',
        kind: 'directory',
        lastModified: '2026-08-08 10:00:00',
        children: [
          {
            id: 'frontend/package.json',
            name: 'package.json',
            relativePath: 'frontend/package.json',
            kind: 'file',
            size: 890,
            extension: '.json',
            lastModified: '2026-08-08 09:15:00',
            preview:
              '{\n  "name": "keystone-web-frontend",\n  "version": "0.1.0",\n  "dependencies": {\n    "react": "^18.3.1"\n  }\n}',
          },
        ],
      },
      {
        id: 'shared-contracts',
        name: 'shared-contracts',
        relativePath: 'shared-contracts',
        kind: 'directory',
        lastModified: '2026-08-08 08:30:00',
        children: [
          {
            id: 'shared-contracts/src',
            name: 'src',
            relativePath: 'shared-contracts/src',
            kind: 'directory',
            lastModified: '2026-08-08 08:00:00',
            children: [
              {
                id: 'shared-contracts/src/index.ts',
                name: 'index.ts',
                relativePath: 'shared-contracts/src/index.ts',
                kind: 'file',
                size: 640,
                extension: '.ts',
                lastModified: '2026-08-08 07:50:00',
                preview:
                  'export * from "./agents";\nexport * from "./workflows";\nexport * from "./knowledge";\nexport * from "./extension";',
              },
            ],
          },
        ],
      },
      {
        id: 'vscode-extension',
        name: 'vscode-extension',
        relativePath: 'vscode-extension',
        kind: 'directory',
        lastModified: '2026-08-08 12:30:00',
        children: [
          {
            id: 'vscode-extension/package.json',
            name: 'package.json',
            relativePath: 'vscode-extension/package.json',
            kind: 'file',
            size: 1650,
            extension: '.json',
            lastModified: '2026-08-08 12:00:00',
            preview:
              '{\n  "name": "keystone-vscode-extension",\n  "displayName": "Keystone AI Orchestrator",\n  "version": "0.1.0"\n}',
          },
        ],
      },
      {
        id: 'README.md',
        name: 'README.md',
        relativePath: 'README.md',
        kind: 'file',
        size: 2850,
        extension: '.md',
        lastModified: '2026-08-08 12:45:00',
        preview:
          '# Keystone — AI Agent Orchestration Platform\n\nKeystone is an enterprise multi-agent developer orchestration workspace.',
      },
    ],
  },
];

function findNodeById(nodes: WorkspaceNodeItem[], id: string | null): WorkspaceNodeItem | null {
  if (!id) return null;
  for (const node of nodes) {
    if (node.id === id) return node;
    if (node.children) {
      const found = findNodeById(node.children, id);
      if (found) return found;
    }
  }
  return null;
}

export function useWorkspaceExplorer() {
  const { selectedWorkspaceNodeId, setSelectedWorkspaceNodeId } = useAppState();
  const [hasWorkspace, setHasWorkspace] = useState<boolean>(true);
  const [workspaceName, setWorkspaceName] = useState<string | null>('Keystone');
  const [tree, setTree] = useState<WorkspaceNodeItem[]>(FALLBACK_TREE);
  const [expandedNodeIds, setExpandedNodeIds] = useState<Set<string>>(
    new Set(['.', 'backend', 'backend/app', 'vscode-extension'])
  );

  const selectedNode = useMemo(
    () => findNodeById(tree, selectedWorkspaceNodeId) || tree[0] || null,
    [tree, selectedWorkspaceNodeId]
  );

  useEffect(() => {
    // Request workspace tree from Extension Host
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
    return () => window.removeEventListener('message', handleWindowMessage);
  }, [selectedWorkspaceNodeId, setSelectedWorkspaceNodeId]);

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
