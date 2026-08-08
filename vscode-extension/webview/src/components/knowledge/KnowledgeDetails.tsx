import React from 'react';
import { X, BookOpen, FileText, Tag, Clock, User, ShieldCheck } from 'lucide-react';
import type { KnowledgeDocument } from '../../mock/knowledge';

interface KnowledgeDetailsProps {
  document: KnowledgeDocument | null;
  onClose: () => void;
}

export const KnowledgeDetails: React.FC<KnowledgeDetailsProps> = ({
  document,
  onClose,
}) => {
  if (!document) return null;

  return (
    <div className="agent-details-overlay" onClick={onClose}>
      <div
        className="agent-details-drawer"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={`Knowledge Document details for ${document.title}`}
      >
        <div className="details-header">
          <div className="details-title-group">
            <div className="agent-icon-box large">
              <BookOpen size={20} />
            </div>
            <div>
              <h2 className="details-agent-name">{document.title}</h2>
              <span className="knowledge-source-label">
                <FileText size={13} /> {document.source}
              </span>
            </div>
          </div>
          <button
            type="button"
            className="details-close-btn"
            onClick={onClose}
            aria-label="Close details"
          >
            <X size={16} />
          </button>
        </div>

        <div className="details-body">
          <div className="knowledge-preview-box">
            <span className="spec-label">Document Overview</span>
            <p className="details-desc text-preview">{document.preview}</p>
          </div>

          <div className="details-specs-grid">
            <div className="spec-item">
              <span className="spec-label">Category</span>
              <span className="spec-value">{document.metadata.category}</span>
            </div>

            <div className="spec-item">
              <span className="spec-label">Author</span>
              <span className="spec-value">
                <User size={12} className="inline-icon" /> {document.metadata.author}
              </span>
            </div>

            {document.metadata.version && (
              <div className="spec-item">
                <span className="spec-label">Version</span>
                <span className="spec-value">{document.metadata.version}</span>
              </div>
            )}

            {document.metadata.status && (
              <div className="spec-item">
                <span className="spec-label">Status</span>
                <span className="spec-value highlight-green">
                  <ShieldCheck size={12} className="inline-icon" /> {document.metadata.status}
                </span>
              </div>
            )}

            <div className="spec-item">
              <span className="spec-label">Word Count</span>
              <span className="spec-value">{document.metadata.wordCount} words</span>
            </div>

            <div className="spec-item">
              <span className="spec-label">Last Updated</span>
              <span className="spec-value">
                <Clock size={12} className="inline-icon" /> {document.lastUpdated}
              </span>
            </div>

            {document.metadata.checksum && (
              <div className="spec-item full-width">
                <span className="spec-label">SHA-256 Checksum</span>
                <span className="spec-value code">{document.metadata.checksum}</span>
              </div>
            )}
          </div>

          <div className="details-capabilities-section">
            <span className="section-subtitle">Tags</span>
            <div className="details-capabilities-tags">
              {document.tags.map((tag) => (
                <span key={tag} className="capability-tag detailed">
                  <Tag size={12} /> #{tag}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="details-footer">
          <button
            type="button"
            className="btn-verify large secondary"
            onClick={onClose}
          >
            Close Document
          </button>
        </div>
      </div>
    </div>
  );
};
