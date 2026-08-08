import React from 'react';
import { BookOpen, FileText, Tag, Clock, Folder } from 'lucide-react';
import type { KnowledgeDocument } from '../../mock/knowledge';

interface KnowledgeCardProps {
  document: KnowledgeDocument;
  isSelected: boolean;
  onSelect: (docId: string) => void;
}

export const KnowledgeCard: React.FC<KnowledgeCardProps> = ({
  document,
  isSelected,
  onSelect,
}) => {
  return (
    <div
      className={`agent-card knowledge-card ${isSelected ? 'selected' : ''}`}
      onClick={() => onSelect(document.id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onSelect(document.id);
      }}
    >
      {/* 1. Document Icon + Document Title */}
      <div className="knowledge-card-title-row">
        <div className="agent-icon-box">
          <BookOpen size={18} />
        </div>
        <h3 className="agent-card-name">{document.title}</h3>
      </div>

      {/* 2. Source Path */}
      <span className="knowledge-source-label">
        <FileText size={12} /> {document.source}
      </span>

      {/* 3. Category Metadata Pill */}
      <div className="knowledge-category-pill">
        <Folder size={11} />
        <span>{document.metadata.category}</span>
      </div>

      {/* 4. Preview Text */}
      <p className="agent-card-desc">{document.preview}</p>

      {/* 5. Tags */}
      <div className="knowledge-tags-row">
        <Tag size={12} className="tag-icon" />
        <div className="agent-capabilities-list">
          {document.tags.slice(0, 3).map((tag) => (
            <span key={tag} className="capability-tag">
              #{tag}
            </span>
          ))}
          {document.tags.length > 3 && (
            <span className="capability-tag more">
              +{document.tags.length - 3}
            </span>
          )}
        </div>
      </div>

      {/* 6. Last Updated */}
      <div className="knowledge-card-footer">
        <span className="knowledge-timestamp">
          <Clock size={12} /> {document.lastUpdated}
        </span>
      </div>
    </div>
  );
};
