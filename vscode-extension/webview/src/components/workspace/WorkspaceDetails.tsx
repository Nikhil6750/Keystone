import React from 'react';
import { Folder, FileText, Clock, HardDrive, Hash, AlignLeft } from 'lucide-react';
import type { WorkspaceNodeItem } from '../../api/MockProvider';

interface WorkspaceDetailsProps {
  node: WorkspaceNodeItem | null;
}

export const WorkspaceDetails: React.FC<WorkspaceDetailsProps> = ({ node }) => {
  if (!node) {
    return (
      <div className="workspace-details-container empty">
        <p className="details-placeholder">Select a file or folder to view details.</p>
      </div>
    );
  }

  const isDirectory = node.kind === 'directory';

  const formatSize = (bytes?: number) => {
    if (bytes === undefined) return 'N/A';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

  return (
    <div className="workspace-details-container">
      <div className="details-card-header">
        <div className="agent-icon-box large">
          {isDirectory ? <Folder size={20} /> : <FileText size={20} />}
        </div>
        <div className="details-header-meta">
          <h2 className="details-agent-name">{node.name}</h2>
          <span className="knowledge-source-label">{node.relativePath}</span>
        </div>
      </div>

      <div className="details-specs-grid">
        <div className="spec-item">
          <span className="spec-label">Kind</span>
          <span className="spec-value">{isDirectory ? 'Directory' : 'File'}</span>
        </div>

        <div className="spec-item">
          <span className="spec-label">Relative Path</span>
          <span className="spec-value code">{node.relativePath}</span>
        </div>

        {isDirectory ? (
          <div className="spec-item">
            <span className="spec-label">Children</span>
            <span className="spec-value">
              <Hash size={12} className="inline-icon" />
              {node.children ? node.children.length : 0} items
            </span>
          </div>
        ) : (
          <>
            <div className="spec-item">
              <span className="spec-label">Extension</span>
              <span className="spec-value code">{node.extension || 'none'}</span>
            </div>

            <div className="spec-item">
              <span className="spec-label">Size</span>
              <span className="spec-value">
                <HardDrive size={12} className="inline-icon" />
                {formatSize(node.size)}
              </span>
            </div>
          </>
        )}

        {node.lastModified && (
          <div className="spec-item full-width">
            <span className="spec-label">Last Modified</span>
            <span className="spec-value">
              <Clock size={12} className="inline-icon" />
              {node.lastModified}
            </span>
          </div>
        )}
      </div>

      {!isDirectory && node.preview && (
        <div className="workspace-preview-section">
          <div className="preview-section-header">
            <AlignLeft size={14} />
            <span className="spec-label">Read-Only Preview</span>
          </div>
          <pre className="workspace-preview-code">
            <code>{node.preview}</code>
          </pre>
        </div>
      )}
    </div>
  );
};
